# core/tasks/enrich_products_images.py

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
            print(f"Invalid image headers: {image_url}")
            return None

        filename = f"{barcode}_{index}.jpg"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            tmp_file.write(response.content)
            tmp_file.flush()
            temp_file_path = tmp_file.name

        if not is_valid_image_pillow(temp_file_path):
            print(f"Image failed Pillow validation: {image_url}")
            os.remove(temp_file_path)
            return None

        with open(temp_file_path, "rb") as f:
            upload_path = f"{BUNNY_UPLOAD_URL}/{barcode}/{filename}"
            upload_response = requests.put(
                upload_path,
                headers=HEADERS,
                data=f.read()
            )

        os.remove(temp_file_path)

        if upload_response.status_code == 201:
            return upload_path.replace(f"https://ny.storage.bunnycdn.com/{BUNNY_STORAGE_ZONE_NAME}", f"https://{BUNNY_STORAGE_ZONE_NAME}.b-cdn.net")
        else:
            print(f"Upload failed for {filename}: {upload_response.status_code}")
            return None

    except Exception as e:
        print(f"Error uploading image {image_url}: {e}")
        return None

def enrich_product_images(barcode):
    print(f"🖼️ Enriching images for barcode: {barcode}")
    product = Product(barcode)

    if not product.product or \
       product.product.get("images_status") != "pending" or \
       product.product.get("barcode_lookup_status") != "success":
        print(f"⚠️ Skipping barcode {barcode} — not ready for image enrichment.")
        return

    images = product.product.get("barcode_lookup_data", {}).get("images", [])
    if not images:
        print(f"❌ No images found for barcode {barcode}.")
        product.update_product(images_status="success")  # Mark as success even with no images
        return

    cdn_urls = []
    for i, image_url in enumerate(images):
        if USE_DUMMY_DATA:
            cdn_urls.append(f"https://dummy.b-cdn.net/sn/product_images/{barcode}/{barcode}_{i}.jpg")
        else:
            uploaded_url = upload_to_bunny(barcode, image_url, i)
            if uploaded_url:
                cdn_urls.append(uploaded_url)

    # Always mark as success — even if no valid images
    product.update_product(
        image_urls=cdn_urls if cdn_urls else None,
        images_status="success"
    )

    if cdn_urls:
        print(f"✅ Enriched {barcode} with {len(cdn_urls)} images.")
    else:
        print(f"⚠️ No valid images were uploaded for {barcode}, but marked as success.")

def enrich_images(batch_size=50):
    print("🔍 Starting product image enrichment...")

    barcodes = [p["barcode"] for p in mongo.db.products.find({
        "barcode_lookup_status": "success",
        "images_status": {"$in": [None, "pending"]}
    })]

    print(f"📦 Found {len(barcodes)} products to enrich.")

    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(enrich_product_images, b): b for b in barcodes[:batch_size]}
        for future in as_completed(futures):
            future.result()

    logger.log(
        event="enrich_products_images_task_complete",
        store=None,
        level="info",
        data={"message": f"Completed image enrichment for {min(len(barcodes), batch_size)} products."}
    )

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "enrich_products_images":
        enrich_images()
    else:
        print("No valid command provided.")