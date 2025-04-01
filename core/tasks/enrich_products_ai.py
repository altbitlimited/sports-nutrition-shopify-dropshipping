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

RATE_LIMIT_DELAY = 1.5
rate_limit_lock = threading.Lock()
last_request_time = [0.0]

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
    pricing = OPENAI_PRICING.get(model, OPENAI_PRICING['gpt-4o'])
    input_cost = (input_tokens / 1000) * pricing["cost_per_1k_input_tokens"]
    output_cost = (output_tokens / 1000) * pricing["cost_per_1k_output_tokens"]
    return input_cost + output_cost, input_cost, output_cost

def enrich_product(barcode, task_id=None, stats=None):
    logger.log("ai_enriching_product", level="info", task_id=task_id, data={"barcode": barcode})
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
        logger.log("ai_cache_hit", level="info", task_id=task_id, data={"barcode": barcode})
        product.update_product(ai_generated_data=cached, ai_generate_status="success")
        if stats:
            stats["cache_hits"] += 1
            stats["success"] += 1
        return

    if USE_DUMMY_DATA:
        simulated = simulate_openai_response(barcode)
        product.update_product(ai_generated_data=simulated.dict(), ai_generate_status="success")
        if stats:
            stats["success"] += 1
        return

    prompt = USER_PROMPT_TEMPLATE.format(
        barcode_lookup=barcode_lookup,
        supplier_data=supplier_raw
    )

    try:
        response = rate_limited_openai_call(prompt)
        output = response.choices[0].message.parsed
        output_dict = output.model_dump(mode="json")

        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        total_cost, input_cost, output_cost = calculate_costs(input_tokens, output_tokens)

        product.update_product(ai_generated_data=output_dict, ai_generate_status="success")
        openai_cache.set(cache_key, output_dict)

        logger.log("ai_generation_success", level="success", task_id=task_id, data={
            "barcode": barcode,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_cost": round(total_cost, 4)
        })

        if stats:
            stats["success"] += 1
            stats["total_cost"] += total_cost

    except Exception as e:
        logger.log_product_error(barcode, str(e), task_id=task_id)
        product.update_product(ai_generate_status="failed")
        if stats:
            stats["failed"] += 1

def enrich_products(limit=None, barcodes=None, brand=None):
    task_id = logger.log_task_start("enrich_products_ai")
    start_time = time.time()

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

    logger.log("ai_enrichment_started", level="info", task_id=task_id, data={
        "message": "🧠 Starting AI enrichment",
        "total_products": len(barcodes_to_process)
    })

    stats = {
        "success": 0,
        "failed": 0,
        "cache_hits": 0,
        "total_cost": 0.0
    }

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(enrich_product, barcode, task_id, stats) for barcode in barcodes_to_process]
        for future in as_completed(futures):
            future.result()

    duration = time.time() - start_time

    logger.log_task_end(
        task_id=task_id,
        event="enrich_products_ai",
        success=stats["success"],
        failed=stats["failed"],
        duration=duration,
        cache_hits=stats["cache_hits"]
    )

    logger.log("ai_enrichment_cost_summary", level="info", task_id=task_id, data={
        "total_cost": round(stats["total_cost"], 4)
    })

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
        logger.log("invalid_command", level="warning", data={"message": "No valid command provided"})
