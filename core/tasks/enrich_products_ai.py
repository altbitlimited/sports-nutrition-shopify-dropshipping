# core/tasks/enrich_products_ai.py

import sys
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI
from core.MongoManager import MongoManager
from core.product import Product
from core.products import Products
from core.Logger import AppLogger
from core.config import OPENAI_API_KEY, USE_DUMMY_DATA, OPENAI_PRICING, OPENAI_MODEL
from core.cache import Cache
from core.schemas.ai_response import AIResponse

mongo = MongoManager()
logger = AppLogger(mongo)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
openai_cache = Cache(mongo.openai_cache)

SYSTEM_PROMPT = (
    "You are an expert product copywriter for a fun and casual UK-based sports nutrition brand. "
    "You will be provided with raw supplier data and a barcode lookup result. "
    "Use this to generate Shopify listing content for the product.\n"
    "\n===STORE DESCRIPTION===\n"
    "My store 'Shredded Treat' is a sports supplements store selling a wide range of products including protein powders, protein shakes, weight loss aids, protein bars, BCAAs, creatine, protein snacks, protein treats, mass gainers, low calorie treats among many other things.\n"
    "We cater for a wide range of customers from gym newbies to hardcore body builders, you can usually tell which product is aimed at which end of the scale from the way it is described.\n"
    "We are a fun, casual brand and like our listings to be fun as well as informative.\n"
    "Start by relating the product to the customer, and how the products primary benefit is of use to them and the problem it solves.\n"
    "Talk about why this specific product and brand is a good choice of this type of product.\n"
    "If describing a specific flavour, we try to be super descriptive with things such as \"imagine the taste of your grandma's warm apple pie on a cold winter morning\" or \"the smell of walking into a bakery when a fresh batch of bread has just been taken out of the oven\". Do not use these examples directly but it gives you an idea of what we strive for.\n"
    "Finish with a bullet point list of this product's benefits using emoji bullets.\n"
    "===END STORE DESCRIPTION==="
)

USER_PROMPT_TEMPLATE = (
    "Generate Shopify listing content based on the following JSON input:\n"
    "{{\n  'barcode_lookup_data': {barcode_lookup},\n  'supplier_data': {supplier_data}\n}}\n"
    "\nUse British English."
)

RATE_LIMIT_DELAY = 1.5  # seconds between requests
rate_limit_lock = threading.Lock()
last_request_time = [0.0]  # shared mutable object

def simulate_openai_response(barcode):
    if barcode == "857640006424":
        return AIResponse(
            title="Ghost Whey Protein – Peanut Butter Cereal Milk – 924g – 26 Servings",
            description="<h3>The ultimate throwback flavour for grown-up gains</h3><p>...</p>",
            snippet="Peanut butter meets cereal milk in this nostalgic, high-protein shake...",
            product_type="Protein Powder",
            suggested_use="Mix one scoop with 250-300ml...",
            ingredients=["Whey protein Isolate 90%", "..."],
            nutritional_facts=[],
            tags=["ghost", "protein", "..."],
            seo_title="Ghost Whey Protein Peanut Butter Cereal Milk – 924g",
            seo_description="Peanut Butter Cereal Milk meets 25g protein...",
            primary_collection="Protein Powders",
            secondary_collections=["Ghost"]
        )
    return None

def rate_limited_openai_call(prompt):
    with rate_limit_lock:
        elapsed = time.time() - last_request_time[0]
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        last_request_time[0] = time.time()

    return openai_client.beta.chat.completions.parse(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        response_format=AIResponse
    )

def calculate_costs(input_tokens, output_tokens, model=OPENAI_MODEL):
    """
    Calculate the cost for OpenAI API usage based on token usage and model.
    """
    pricing = OPENAI_PRICING.get(model, OPENAI_PRICING['gpt-4o'])

    input_cost = (input_tokens / 1000) * pricing["cost_per_1k_input_tokens"]
    output_cost = (output_tokens / 1000) * pricing["cost_per_1k_output_tokens"]

    total_cost = input_cost + output_cost
    return total_cost, input_cost, output_cost

def enrich_product(barcode):
    print(f"🔄 Enriching product {barcode}")
    product = Product(barcode)

    if product.product.get("ai_generate_status") != "pending":
        return

    barcode_lookup = product.product.get("barcode_lookup_data")
    if not barcode_lookup:
        return

    supplier_raw = [s["data"] for s in product.product.get("suppliers", []) if s.get("data")]
    if not supplier_raw:
        return

    cache_key = f"ai_generated::{barcode}"
    cached = openai_cache.get(cache_key)
    if cached:
        print(f"[CACHE HIT] Using cached response for barcode {barcode}")
        logger.log("ai_cache_hit", level="info", data={"barcode": barcode})
        product.update_product(ai_generated_data=cached, ai_generate_status="success")
        return

    if USE_DUMMY_DATA:
        simulated = simulate_openai_response(barcode)
        product.update_product(ai_generated_data=simulated.dict(), ai_generate_status="success")
        return

    prompt = USER_PROMPT_TEMPLATE.format(
        barcode_lookup=barcode_lookup,
        supplier_data=supplier_raw
    )

    try:
        # Make the rate-limited OpenAI API call
        response = rate_limited_openai_call(prompt)

        # Parse the OpenAI response
        output = response.choices[0].message.parsed
        output_dict = output.model_dump(mode="json")

        # Extract token usage info from the response
        input_tokens = response.usage.prompt_tokens  # Access using dot notation
        output_tokens = response.usage.completion_tokens  # Access using dot notation

        # Calculate the cost of the request
        total_cost, input_cost, output_cost = calculate_costs(
            input_tokens, output_tokens, model=OPENAI_MODEL  # Use the dynamic model
        )

        # Log the cost breakdown
        print(f"API Call cost breakdown for barcode {barcode}:")
        print(f"  Input tokens: {input_tokens} => ${input_cost:.4f}")
        print(f"  Output tokens: {output_tokens} => ${output_cost:.4f}")
        print(f"  Total cost: ${total_cost:.4f}")

        # Update product and cache the response
        product.update_product(ai_generated_data=output_dict, ai_generate_status="success")
        openai_cache.set(cache_key, output_dict)

        print(f"✅ Enriched barcode {barcode}. Total cost: ${total_cost:.4f}")
        logger.log("ai_generation_success", level="info", data={"barcode": barcode, "total_cost": total_cost})

    except Exception as e:
        print(f"[ERROR] Barcode {barcode}: {str(e)}")
        logger.log("ai_generation_error", level="error", data={"barcode": barcode, "error": str(e)})
        product.update_product(ai_generate_status="failed")

def enrich_products(limit=None, barcodes=None, brand=None):
    total_enrichment_cost = 0
    query = {
        "barcode_lookup_status": "success",
        "images_status": "success",
        "ai_generate_status": "pending"
    }
    if barcodes:
        query["barcode"] = {"$in": barcodes}
    if brand:
        query["barcode_lookup_data.brand"] = brand

    cursor = mongo.db.products.find(query)
    if limit:
        cursor = cursor.limit(limit)

    barcodes_to_process = [doc["barcode"] for doc in cursor]

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(enrich_product, barcode) for barcode in barcodes_to_process]
        for future in as_completed(futures):
            future.result()

    print(f"✅ Enrichment completed. Total cost for all enrichments: ${total_enrichment_cost:.4f}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate AI-powered Shopify product listings")
    parser.add_argument("command", choices=["enrich_products_ai"], help="Command to run")
    parser.add_argument("--limit", type=int, help="Limit the number of products to enrich")
    parser.add_argument("--barcodes", nargs="*", help="Specific barcodes to enrich")
    parser.add_argument("--brand", type=str, help="Filter by brand")
    args = parser.parse_args()

    if args.command == "enrich_products_ai":
        enrich_products(limit=args.limit, barcodes=args.barcodes, brand=args.brand)
    else:
        print("No valid command provided.")
