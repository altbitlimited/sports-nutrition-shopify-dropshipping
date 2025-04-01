# core/tasks/enrich_products_barcode_lookup.py

import sys
import time
import random
import requests
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


def fetch_product_data_from_barcodelookup(barcode, retries=3, delay=2):
    if ENABLE_BARCODELOOKUP_CACHE:
        cached = barcode_cache.get(barcode)
        if cached:
            print(f"[CACHE HIT] Barcode {barcode} — using cached barcode lookup data.")
            logger.log(event="barcode_lookup_cache_hit", level="info", data={"barcode": barcode})
            return cached

    if USE_DUMMY_DATA:
        print(f"[DUMMY] Using dummy data for barcode: {barcode}")
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
            print(f"🔍 Fetching data for barcode: {barcode} (Attempt {attempt + 1})")
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
                        print(f"[CACHE SAVE] Cached barcode {barcode} lookup data.")
                    return data
                else:
                    print(f"[404] No product found for barcode: {barcode}")
                    return None
            else:
                logger.log(event="barcode_lookup_api_error", level="error", data={
                    "barcode": barcode,
                    "status_code": response.status_code,
                    "response": response.text
                })
                return None
        except Exception as e:
            attempt += 1
            print(f"[ERROR] Barcode {barcode}: {str(e)} — retrying...")
            logger.log(event="barcode_lookup_error", level="error", data={
                "barcode": barcode,
                "error": str(e),
                "attempt": attempt
            })
            time.sleep(delay * (2 ** attempt) + random.uniform(0, 1))

    return None


def enrich_product(barcode):
    print(f"🔄 Enriching product {barcode}")
    product = Product(barcode)

    if product.product and product.product.get("barcode_lookup_status") == "pending":
        product_data = fetch_product_data_from_barcodelookup(barcode)

        if product_data:
            product.update_product(barcode_lookup_data=product_data, barcode_lookup_status="success")
            print(f"✅ Enriched barcode {barcode}")
        else:
            product.update_product(barcode_lookup_status="failed")
            print(f"❌ Failed to enrich barcode {barcode}")
            logger.log(event="barcode_lookup_failed", level="error", data={
                "barcode": barcode,
                "message": "No product data returned from barcode lookup"
            })
    else:
        print(f"⚠️ Skipping barcode {barcode} — already enriched or not pending.")


def enrich_products(batch_size=500):
    print("🔍 Starting barcode enrichment task...")

    products = Products()
    barcodes_to_enrich = [
        p["barcode"]
        for p in mongo.db.products.find({
            "barcode_lookup_status": "pending"
        })
    ]

    print(f"🧺 Found {len(barcodes_to_enrich)} barcodes to enrich.")

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(enrich_product, barcode): barcode
            for barcode in barcodes_to_enrich[:batch_size]
        }
        for future in as_completed(futures):
            future.result()

    logger.log(event="barcode_lookup_task_complete", level="info", data={
        "enriched": len(barcodes_to_enrich[:batch_size])
    })

    print("✅ Barcode enrichment task complete.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "enrich_products_barcode_lookup":
        enrich_products()
    else:
        print("No valid command provided.")
