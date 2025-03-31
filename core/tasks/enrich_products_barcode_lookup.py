# core/tasks/enrich_products_barcode_lookup.py

import sys
import time
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.MongoManager import MongoManager
from core.product import Product
from core.products import Products  # Corrected import statement (lowercase 'products')
from core.Logger import AppLogger
from core.config import BARCODELOOKUP_API_KEY, USE_DUMMY_DATA  # Import from config

mongo = MongoManager()
logger = AppLogger(mongo)

# BarcodeLookup API URL
BARCODELOOKUP_API_URL = 'https://api.barcodelookup.com/v3/products'

# Rate limiting constants
MAX_REQUESTS_PER_MINUTE = 40  # 40 requests per minute to stay under the limit
REQUEST_INTERVAL = 60 / MAX_REQUESTS_PER_MINUTE  # Time to wait between requests (every ~0.67 seconds)

def fetch_product_data_from_barcodelookup(barcode, retries=3, delay=2):
    """
    Fetch product data from BarcodeLookup API for a given barcode.
    Implements retry logic with exponential backoff.
    Rate limiting is handled to respect the API's limits.
    If USE_DUMMY_DATA is set to True, return dummy data instead of real API data.
    """
    if USE_DUMMY_DATA:
        print(f"Using dummy data for barcode: {barcode}")
        # Return dummy data for testing
        return {
            "barcode_number": barcode,
            "barcode_formats": f"UPC-A {barcode}, EAN-13 {int(barcode) + 100000000000}",
            "mpn": "TROP-GH0008",
            "model": "",
            "asin": "",
            "title": "Ghost Whey Protein 26 Servings, Milk Chocolate",
            "category": "Food, Beverages & Tobacco",
            "manufacturer": "Ghost",
            "brand": "Ghost",
            "contributors": [],
            "age_group": "",
            "ingredients": "",
            "nutrition_facts": "",
            "energy_efficiency_class": "",
            "color": "",
            "gender": "unisex",
            "material": "",
            "pattern": "",
            "format": "",
            "multipack": "",
            "size": "2 lbs.",
            "length": "",
            "width": "",
            "height": "",
            "weight": "368 g",
            "release_date": "",
            "description": "Versatile and Delicious AF: GHOST WHEY protein combines a premium, fully disclosed whey protein blend, a few digestive enzymes, and out-of-this-world flavors.",
            "features": [],
            "images": [
                "https://images.barcodelookup.com/1033/10337665-1.jpg"
            ],
            "last_update": "2025-01-16 10:05:46",
            "stores": [
                {
                    "name": "LuckyVitamin.com",
                    "country": "US",
                    "currency": "USD",
                    "currency_symbol": "$",
                    "price": "36.09",
                    "sale_price": "",
                    "link": "https://www.luckyvitamin.com/p-1686825-ghost-100-whey-protein-milk-chocolate-924-grams",
                    "last_update": "2021-06-22 04:03:40"
                }
            ],
            "reviews": []
        }

    # Otherwise, make the real API call
    attempt = 0
    while attempt < retries:
        try:
            print(f"Attempting to fetch data for barcode: {barcode} (Attempt {attempt + 1}/{retries})")
            response = requests.get(BARCODELOOKUP_API_URL, params={
                'barcode': barcode,
                'key': BARCODELOOKUP_API_KEY  # Using the API key from config
            })

            # Log the full response for debugging
            # logger.log(event="api_response", level="debug", data={
            #     "barcode": barcode,
            #     "response_status_code": response.status_code,
            #     "response_text": response.text  # Log the response body
            # })

            if response.status_code == 200:
                print(f"Successfully fetched data for barcode: {barcode}")
                product_data = response.json()
                if product_data.get('products'):
                    return product_data['products'][0]  # Return the first product data
                else:
                    print(f"No product found for barcode: {barcode}")
                    return None  # No product found for barcode
            else:
                # Log the error response
                logger.log(event="enrich_products_barcode_lookup_error", level="error", data={
                    "barcode": barcode,
                    "error": f"API error: {response.status_code}, {response.text}",
                })
                print(f"API error for barcode {barcode}: {response.status_code}, {response.text}")
                return None  # In case of other errors like 404 or 500

        except Exception as e:
            attempt += 1
            print(f"Error occurred while fetching barcode {barcode}: {str(e)}. Retrying...")
            logger.log(event="enrich_products_barcode_lookup_error", level="error", data={
                "barcode": barcode,
                "error": str(e),
                "attempt": attempt
            })
            # Exponential backoff with randomization to avoid thundering herd problem
            time.sleep(delay * (2 ** attempt) + random.uniform(0, 1))  # Exponential backoff
            # Implement rate-limiting to avoid hitting API rate limits
            if attempt % MAX_REQUESTS_PER_MINUTE == 0:
                print(f"⏳ Sleeping for {REQUEST_INTERVAL} seconds to respect rate limits.")
                time.sleep(REQUEST_INTERVAL)
    return None  # If all attempts fail


def enrich_product(barcode):
    """
    Enrich a single product from the BarcodeLookup API if barcode_lookup_data is null.
    """
    print(f"🔄 Enriching product with barcode: {barcode}")

    # Create a Product instance to interact with the product
    product = Product(barcode)

    # If the product is pending enrichment
    if product.product and product.product.get("barcode_lookup_status") == "pending":
        print(f"📦 Enriching product {barcode}...")

        # Fetch data from BarcodeLookup API (or dummy data if in testing mode)
        product_data = fetch_product_data_from_barcodelookup(barcode)

        # If data is fetched, update the product in the database
        if product_data:
            print(f"Data fetched successfully for barcode {barcode}. Updating product...")
            product.update_product(barcode_lookup_data=product_data, barcode_lookup_status="success")

            # Log success
            # logger.log(
            #     event="enrich_products_barcode_lookup_product_enriched",
            #     store=None,
            #     level="info",
            #     data={
            #         "barcode": barcode,
            #         "status": "success",
            #         "message": "Product enriched from BarcodeLookup",
            #         "product_data": product_data
            #     }
            # )
        else:
            print(f"Failed to fetch data for barcode {barcode}. Marking as failed.")
            # If no data is found, mark the status as failed
            product.update_product(barcode_lookup_status="failed")

            # Log failure
            logger.log(
                event="enrich_products_barcode_lookup_product_enrichment_failed",
                store=None,
                level="error",
                data={
                    "barcode": barcode,
                    "status": "failed",
                    "message": "Product enrichment failed from BarcodeLookup"
                }
            )
    else:
        print(f"⚠️ Product {barcode} already enriched or doesn't exist.")


def enrich_products(batch_size=500):
    """
    Enrich all products with null barcode_lookup_data in batches.
    """
    print("🔍 Starting barcode lookup enrichment...")

    # Instantiate Products class for bulk operations
    products = Products()

    # Loop through the products collection in batches
    all_products = mongo.db.products.find({"barcode_lookup_status": "pending"})
    barcodes_to_enrich = [product["barcode"] for product in all_products]

    print(f"📦 Found {len(barcodes_to_enrich)} products to enrich.")

    # Process the barcodes in batches using threads
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(enrich_product, barcode): barcode
            for barcode in barcodes_to_enrich[:batch_size]
        }

        for future in as_completed(futures):
            future.result()  # Ensure exceptions are raised here if any

    print("✅ Enrichment completed.")

    # Log completion
    logger.log(
        event="enrich_products_barcode_lookup_task_complete",
        store=None,
        level="info",
        data={
            "message": f"Completed enriching {len(barcodes_to_enrich[:batch_size])} products."
        }
    )


# Entry point for cron or manual run
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "enrich_products_barcode_lookup":
        enrich_products()
    else:
        print("No valid command provided.")
