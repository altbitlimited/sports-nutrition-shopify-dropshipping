import sys
import os
import time
import mimetypes
import requests
import tempfile
from PIL import Image
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.MongoManager import MongoManager
from core.product import Product
from core.products import Products
from core.Logger import AppLogger
from core.config import (
    USE_DUMMY_DATA,
    BUNNY_ACCESS_KEY,
    BUNNY_STORAGE_ZONE_NAME,
    BUNNY_REGION
)

mongo = MongoManager()
logger = AppLogger(mongo)

BUNNY_UPLOAD_URL = f"https://{BUNNY_REGION}.storage.bunnycdn.com/{BUNNY_STORAGE_ZONE_NAME}/sn/product_images"
HEADERS = {"AccessKey": BUNNY_ACCESS_KEY}
MAX_UPLOAD_RETRIES = 3


def is_valid_image(response):
    content_type = response.headers.get("Content-Type", "")
    return response.status_code == 200 and content_type.startswith("image/")


def is_valid_image_pillow(file_name):
    try:
        with Image.open(file_name) as img:
            img.verify()
            return True
    except (IOError, SyntaxError):
        return False


def upload_to_bunny(barcode, image_url, index):
    try:
        response = requests.get(image_url, timeout=10)
        if not is_valid_image(response):
            logger.log("invalid_image_response", level="warning", data={
                "barcode": barcode, "url": image_url,
                "message": "\u26a0\ufe0f Invalid image headers"
            })
            return None

        filename = f"{barcode}_{index}.jpg"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            tmp_file.write(response.content)
            tmp_file.flush()
            temp_file_path = tmp_file.name

        if not is_valid_image_pillow(temp_file_path):
            logger.log("pillow_image_invalid", level="warning", data={
                "barcode": barcode, "url": image_url,
                "message": "\u26a0\ufe0f Failed Pillow validation"
            })
            os.remove(temp_file_path)
            return None

        for attempt in range(MAX_UPLOAD_RETRIES):
            try:
                with open(temp_file_path, "rb") as f:
                    upload_path = f"{BUNNY_UPLOAD_URL}/{barcode}/{filename}"
                    upload_response = requests.put(
                        upload_path,
                        headers=HEADERS,
                        data=f.read()
                    )

                if upload_response.status_code == 201:
                    os.remove(temp_file_path)
                    return upload_path.replace(
                        f"https://ny.storage.bunnycdn.com/{BUNNY_STORAGE_ZONE_NAME}",
                        f"https://{BUNNY_STORAGE_ZONE_NAME}.b-cdn.net"
                    )
                else:
                    logger.log("bunny_upload_failed", level="warning", data={
                        "barcode": barcode,
                        "status": upload_response.status_code,
                        "attempt": attempt + 1
                    })

            except Exception as e:
                logger.log("upload_exception", level="error", data={
                    "barcode": barcode,
                    "error": str(e),
                    "attempt": attempt + 1
                })

            time.sleep(2 ** attempt + random.uniform(0, 1))

        os.remove(temp_file_path)
        return None

    except Exception as e:
        logger.log("upload_exception", level="error", data={
            "barcode": barcode,
            "error": str(e),
            "message": "\u274c Exception while uploading image"
        })
        return None


def enrich_product_images(barcode, task_id=None, stats=None):
    logger.log("image_enrichment_start", level="info", task_id=task_id, data={
        "barcode": barcode,
        "message": "\ud83d\uddbc\ufe0f Starting image enrichment"
    })
    product = Product(barcode)

    if not product.product or \
       product.product.get("images_status") != "pending" or \
       product.product.get("barcode_lookup_status") != "success":
        logger.log("image_enrichment_skipped", level="warning", task_id=task_id, data={
            "barcode": barcode,
            "message": "\u26a0\ufe0f Skipping image enrichment — not ready"
        })
        return

    images = product.product.get("barcode_lookup_data", {}).get("images", [])
    if not images:
        logger.log("image_enrichment_no_images", level="info", task_id=task_id, data={
            "barcode": barcode,
            "message": "\u2139\ufe0f No images found, marking as success"
        })
        product.update_product(images_status="success")
        if stats:
            stats["success"] += 1
        return

    cdn_urls = []
    for i, image_url in enumerate(images):
        if USE_DUMMY_DATA:
            cdn_urls.append(f"https://dummy.b-cdn.net/sn/product_images/{barcode}/{barcode}_{i}.jpg")
        else:
            uploaded_url = upload_to_bunny(barcode, image_url, i)
            if uploaded_url:
                cdn_urls.append(uploaded_url)

    product.update_product(
        image_urls=cdn_urls if cdn_urls else None,
        images_status="success"
    )

    if stats:
        stats["success"] += 1
        if not cdn_urls:
            stats["no_images"] += 1

    logger.log("image_enrichment_complete", level="success", task_id=task_id, data={
        "barcode": barcode,
        "cdn_images": len(cdn_urls),
        "message": f"\u2705 Completed image enrichment — {len(cdn_urls)} image(s) uploaded"
    })


def enrich_images(batch_size=50):
    task_id = logger.log_task_start("enrich_products_images")
    start_time = time.time()

    barcodes = [p["barcode"] for p in mongo.db.products.find({
        "barcode_lookup_status": "success",
        "images_status": {"$in": [None, "pending"]}
    })]

    logger.log("image_enrichment_found", level="info", task_id=task_id, data={
        "count": len(barcodes),
        "message": f"\ud83d\udd0d Found {len(barcodes)} products to enrich"
    })

    stats = {
        "success": 0,
        "failed": 0,
        "no_images": 0
    }

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(enrich_product_images, b, task_id, stats): b for b in barcodes[:batch_size]}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.log("image_enrichment_batch_error", level="error", task_id=task_id, data={
                    "error": str(e),
                    "message": "\u274c Error during threaded enrichment"
                })
                stats["failed"] += 1

    duration = time.time() - start_time

    logger.log_task_end(
        task_id=task_id,
        event="enrich_products_images",
        success=stats["success"],
        failed=stats["failed"],
        duration=duration,
        cache_hits=0
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "enrich_products_images":
        enrich_images()
    else:
        logger.log("invalid_command", level="warning", data={"message": "No valid command provided"})
