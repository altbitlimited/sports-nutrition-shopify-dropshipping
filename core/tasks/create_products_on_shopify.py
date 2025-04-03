# core/tasks/create_products_on_shopify.py

import sys
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.products import Products
from core.Logger import AppLogger
from core.exceptions import ShopNotReadyError

logger = AppLogger()


def create_products_on_shopify(barcodes=None, shop_domains=None, limit=None, max_workers=4, dry_run=False):
    task_id = logger.log_task_start("create_products_on_shopify", count=0)
    start_time = time.time()

    products_manager = Products()
    all_pairs = products_manager.get_products_ready_for_posting()

    ready_pairs = []
    shop_ready_cache = {}
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

        if shop.domain in shop_ready_cache:
            if not shop_ready_cache[shop.domain]:
                total_skipped += 1
                continue
        else:
            try:
                shop.log_action("prepare_for_product_actions_start", "debug", {
                    "message": "🔧 Preparing shop for product actions..."
                }, task_id=task_id)

                shop.prepare_for_product_actions(task_id=task_id)
                shop_ready_cache[shop.domain] = True

                shop.log_action("prepare_for_product_actions_success", "info", {
                    "message": "✅ Shop is ready for product actions."
                }, task_id=task_id)

            except ShopNotReadyError as e:
                shop_ready_cache[shop.domain] = False
                total_skipped += 1

                shop.log_action("shop_not_ready_skipped", "warning", {
                    "message": f"⚠️ Shop is not ready and will be skipped. Reason: {str(e)}"
                }, task_id=task_id)

                continue

        ready_pairs.append((product, shop))

    if limit:
        ready_pairs = ready_pairs[:limit]

    success = 0
    failed = 0
    skipped = 0
    futures = []

    if dry_run:
        for product, shop in ready_pairs:
            product.log_action("dry_run_product", "info", {
                "shop": shop.domain,
                "message": "🧪 Dry run — product would be created on Shopify."
            }, task_id=task_id)
            skipped += 1
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for product, shop in ready_pairs:
                futures.append(
                    executor.submit(_process_product_creation, product, shop, task_id)
                )

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        success += 1
                    else:
                        failed += 1
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


def _process_product_creation(product, shop, task_id):
    product.log_action("shopify_product_attempt_start", "debug", {
        "shop": shop.domain,
        "message": "🚀 Attempting to create product on Shopify."
    }, task_id=task_id)

    try:
        product.create_on_shopify(shop, task_id=task_id)
        product.log_action("shopify_product_created", "success", {
            "shop": shop.domain,
            "message": "✅ Product successfully created on Shopify."
        }, task_id=task_id)
        return True

    except Exception as e:
        product.log_action("shopify_product_create_failed", "error", {
            "shop": shop.domain,
            "message": "❌ Product creation on Shopify failed.",
            "error": str(e)
        }, task_id=task_id)
        return False


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
