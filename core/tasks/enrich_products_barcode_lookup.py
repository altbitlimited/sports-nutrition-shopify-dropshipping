# core/tasks/enrich_products_barcode_lookup.py

import sys
import time
import random
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.MongoManager import MongoManager
from core.product import Product
from core.products import Products
from core.Logger import AppLogger
from core.config import BARCODELOOKUP_API_KEY, USE_DUMMY_DATA, ENABLE_BARCODELOOKUP_CACHE
from core.cache import Cache

mongo = MongoManager()
logger = AppLogger(mongo)
barcode_cache = Cache(mongo.barcode_lookup_cache)

BARCODELOOKUP_API_URL = 'https://api.barcodelookup.com/v3/products'
MAX_REQUESTS_PER_MINUTE = 40
REQUEST_INTERVAL = 60 / MAX_REQUESTS_PER_MINUTE

# Shared rate limiter across threads
rate_limit_lock = threading.Lock()

# Exponential backoff settings
MAX_RETRIES = 3
INITIAL_BACKOFF_DELAY = 1  # seconds

def fetch_product_data_from_barcodelookup(barcode, retries=MAX_RETRIES, delay=INITIAL_BACKOFF_DELAY, stats=None):
    if ENABLE_BARCODELOOKUP_CACHE:
        cached = barcode_cache.get(barcode)
        if cached:
            logger.log("barcode_lookup_cache_hit", level="info", data={"barcode": barcode})
            if stats:
                stats["cache_hits"] += 1
            return cached

    if USE_DUMMY_DATA:
        logger.log("barcode_lookup_dummy", level="info", data={"barcode": barcode})
        return {
            "barcode_number": barcode,
            "title": "Ghost Whey Protein 26 Servings, Milk Chocolate",
            "brand": "Ghost",
            "description": "Premium whey protein with unbeatable flavor.",
            "ingredients": "Whey protein isolate, cocoa, natural flavors.",
            "weight": "900g",
            "images": [
                "https://images.barcodelookup.com/1033/10337665-1.jpg"
            ]
        }

    attempt = 0
    while attempt < retries:
        try:
            logger.log("barcode_lookup_attempt", level="debug", data={
                "barcode": barcode,
                "attempt": attempt + 1,
                "message": f"🔍 Fetching data for barcode: {barcode} (Attempt {attempt + 1})"
            })

            with rate_limit_lock:
                response = requests.get(BARCODELOOKUP_API_URL, params={
                    'barcode': barcode,
                    'key': BARCODELOOKUP_API_KEY
                })

            if response.status_code == 200:
                product_data = response.json()
                if product_data.get('products'):
                    data = product_data['products'][0]
                    if ENABLE_BARCODELOOKUP_CACHE:
                        barcode_cache.set(barcode, data)
                        logger.log("barcode_lookup_cached", level="debug", data={
                            "barcode": barcode,
                            "message": f"📦 Cached barcode {barcode} lookup data."
                        })
                    return data
                else:
                    logger.log("barcode_lookup_not_found", level="debug", data={
                        "barcode": barcode,
                        "message": f"🛑 No product found for barcode: {barcode}"
                    })
                    return None
            else:
                logger.log("barcode_lookup_api_error", level="error", data={
                    "barcode": barcode,
                    "status_code": response.status_code,
                    "response": response.text
                })
                return None

        except Exception as e:
            attempt += 1
            logger.log("barcode_lookup_error", level="error", data={
                "barcode": barcode,
                "error": str(e),
                "attempt": attempt
            })
            time.sleep(delay * (2 ** attempt) + random.uniform(0, 1))

    return None

def enrich_product(barcode, stats=None, task_id=None):
    logger.log("barcode_lookup_enriching", level="debug", data={
        "barcode": barcode,
        "message": f"🔄 Enriching product {barcode}"
    })

    product = Product(barcode)

    if product.product and product.product.get("barcode_lookup_status") == "pending":
        product_data = fetch_product_data_from_barcodelookup(barcode, stats=stats)

        if product_data:
            product.update_product(barcode_lookup_data=product_data, barcode_lookup_status="success")
            logger.log("barcode_lookup_enriched", level="debug", data={
                "barcode": barcode,
                "message": f"✅ Enriched barcode {barcode}"
            })
            if stats:
                stats["success"] += 1
        else:
            product.update_product(barcode_lookup_status="failed")
            logger.log("barcode_lookup_failed", level="error", task_id=task_id, data={
                "barcode": barcode,
                "message": "No product data returned from barcode lookup"
            })
            if stats:
                stats["failed"] += 1
    else:
        logger.log("barcode_lookup_skipped", level="debug", data={
            "barcode": barcode,
            "message": f"⚠️ Skipping barcode {barcode} — already enriched or not pending."
        })

def enrich_products(batch_size=500):
    task_id = logger.log_task_start("enrich_products_barcode_lookup")
    start_time = time.time()

    barcodes_to_enrich = [
        p["barcode"]
        for p in mongo.db.products.find({
            "barcode_lookup_status": "pending"
        })
    ]

    logger.log("barcode_lookup_found", level="info", task_id=task_id, data={
        "barcodes_to_enrich": len(barcodes_to_enrich),
        "message": f"🧺 Found {len(barcodes_to_enrich)} barcodes to enrich"
    })

    stats = {
        "success": 0,
        "failed": 0,
        "cache_hits": 0
    }

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(enrich_product, barcode, stats, task_id): barcode
            for barcode in barcodes_to_enrich[:batch_size]
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.log("barcode_lookup_thread_error", level="error", task_id=task_id, data={
                    "error": str(e)
                })
                stats["failed"] += 1

    duration = time.time() - start_time
    logger.log_task_end(
        task_id=task_id,
        event="enrich_products_barcode_lookup",
        success=stats["success"],
        failed=stats["failed"],
        duration=duration,
        cache_hits=stats["cache_hits"]
    )

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "enrich_products_barcode_lookup":
        enrich_products()
    else:
        logger.log("invalid_command", level="warning", data={"message": "⚠️ No valid command provided"})
