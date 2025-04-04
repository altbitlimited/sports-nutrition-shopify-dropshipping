import sys
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

from core.products import Products
from core.Logger import AppLogger
from core.exceptions import ShopNotReadyError

logger = AppLogger()


def create_products_on_shopify(barcodes=None, shop_domains=None, limit=None, max_workers=3, dry_run=False):
    task_id = logger.log_task_start("create_products_on_shopify", count=0)
    start_time = time.time()

    products_manager = Products()
    all_pairs = products_manager.get_products_ready_for_posting()

    # Filter and group by shop
    shop_to_products = defaultdict(list)
    total_considered = 0
    total_skipped = 0

    for product, shop in all_pairs:
        total_considered += 1

        if barcodes and product.barcode not in barcodes:
            total_skipped += 1
            continue

        if shop_domains and shop.domain not in shop_domains:
            total_skipped += 1
            continue

        shop_to_products[shop.domain].append((product, shop))

    if limit:
        # Apply limit globally across all shops
        limited_pairs = []
        for domain, items in shop_to_products.items():
            for pair in items:
                if len(limited_pairs) < limit:
                    limited_pairs.append(pair)
        shop_to_products = defaultdict(list)
        for product, shop in limited_pairs:
            shop_to_products[shop.domain].append((product, shop))

    success = 0
    failed = 0
    skipped = 0
    futures = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for domain, product_shop_list in shop_to_products.items():
            shop = product_shop_list[0][1]
            products = [ps[0] for ps in product_shop_list]
            futures.append(executor.submit(
                _process_shop_products, shop, products, task_id, dry_run
            ))

        for future in as_completed(futures):
            try:
                result = future.result()
                success += result.get("success", 0)
                failed += result.get("failed", 0)
                skipped += result.get("skipped", 0)
            except Exception as e:
                failed += 1
                logger.log("shopify_create_unhandled_exception", {
                    "error": str(e)
                }, None, "error", task_id=task_id)

    duration = time.time() - start_time
    logger.log_task_end(
        task_id=task_id,
        event="create_products_on_shopify",
        success=success,
        failed=failed,
        duration=duration
    )


def _process_shop_products(shop, products, task_id, dry_run):
    success = 0
    failed = 0
    skipped = 0

    try:
        shop.log_action("prepare_for_product_actions_start", "debug", {
            "message": "🔧 Preparing shop for product actions..."
        }, task_id=task_id)

        shop.prepare_for_product_actions(task_id=task_id)

        shop.log_action("prepare_for_product_actions_success", "info", {
            "message": "✅ Shop is ready for product actions."
        }, task_id=task_id)

    except ShopNotReadyError as e:
        shop.log_action("shop_not_ready_skipped", "warning", {
            "message": f"⚠️ Shop is not ready and will be skipped. Reason: {str(e)}"
        }, task_id=task_id)
        return {"success": 0, "failed": 0, "skipped": len(products)}

    # Gather collection titles
    collection_titles = []
    for product in products:
        ai = product.product.get("ai_generated_data", {})
        if not ai:
            continue
        titles = list(filter(None, [ai.get("primary_collection")] + (ai.get("secondary_collections") or [])))
        collection_titles.extend(titles)

    shop.log_action("preflight_collection_titles_gathered", "debug", {
        "count": len(collection_titles),
        "unique": len(set(collection_titles)),
        "titles": list(set(collection_titles)),
        "message": "📋 Gathered collection titles for preflight."
    }, task_id=task_id)

    created = shop.ensure_collections_exist_from_products(products, task_id=task_id)

    if created:
        shop.log_action("collections_created_preflight", "info", {
            "count": len(created),
            "created": created,
            "message": "📚 New collections created before listing."
        }, task_id=task_id)
    else:
        shop.log_action("collections_created_preflight", "info", {
            "count": 0,
            "message": "✅ No new collections needed before listing."
        }, task_id=task_id)

    for product in products:
        if dry_run:
            product.log_action("dry_run_product", "info", {
                "shop": shop.domain,
                "message": "🧪 Dry run — product would be created on Shopify."
            }, task_id=task_id)
            skipped += 1
            continue

        product.log_action("shopify_product_attempt_start", "debug", {
            "shop": shop.domain,
            "message": "🚀 Attempting to create product on Shopify."
        }, task_id=task_id)

        shop.log_action("_process_product_creation_collection_check", "debug", {
            "collections_in_shop": shop.shop.get("collections", [])
        })

        try:
            product.create_on_shopify(shop, task_id=task_id)
            product.log_action("shopify_product_created", "success", {
                "shop": shop.domain,
                "message": "✅ Product successfully created on Shopify."
            }, task_id=task_id)
            time.sleep(1)
            success += 1
        except Exception as e:
            product.log_action("shopify_product_create_failed", "error", {
                "shop": shop.domain,
                "message": "❌ Product creation on Shopify failed.",
                "error": str(e)
            }, task_id=task_id)
            failed += 1

    return {"success": success, "failed": failed, "skipped": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create_products_on_shopify"])
    parser.add_argument("--barcode", action="append", help="Limit to specific barcode(s). Can be passed multiple times.")
    parser.add_argument("--shop", action="append", help="Limit to specific shop(s). Can be passed multiple times.")
    parser.add_argument("--limit", type=int, help="Maximum number of products to process.")
    parser.add_argument("--workers", type=int, default=4, help="Thread pool max workers (default: 4)")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without creating products.")

    args = parser.parse_args()

    if args.command == "create_products_on_shopify":
        create_products_on_shopify(
            barcodes=args.barcode,
            shop_domains=args.shop,
            limit=args.limit,
            max_workers=args.workers,
            dry_run=args.dry_run
        )
