# core/barcode_lookup.py

import requests
from core.Logger import AppLogger
from core.MongoManager import MongoManager
import time
import random

# Initialize logger
logger = AppLogger(MongoManager())

def fetch_product_data_from_barcodelookup(barcode, api_key, retries=3, delay=2):
    """
    Fetch product details from the BarcodeLookup API.
    Retries the request with exponential backoff if it fails.
    """
    url = f"https://api.barcodelookup.com/v3/products?barcode={barcode}&key={api_key}"

    attempt = 0
    while attempt < retries:
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise HTTPError for bad responses
            data = response.json()

            # Check if the response contains product information
            if data.get("products"):
                return data["products"][0]  # Return the first product in the list
            else:
                logger.log(event="barcode_lookup_no_product", level="warning", data={
                    "barcode": barcode,
                    "message": f"No product found for barcode {barcode}."
                })
                return None
        except requests.exceptions.RequestException as e:
            attempt += 1
            logger.log(event="barcode_lookup_error", level="error", data={
                "barcode": barcode,
                "error": str(e),
                "attempt": attempt
            })
            # Exponential backoff with randomization to avoid thundering herd problem
            time.sleep(delay * (2 ** attempt) + random.uniform(0, 1))  # Exponential backoff

    return None  # If all attempts fail
