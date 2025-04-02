# core/tasks/flag_products_to_create.py

import sys
import time
from core.shops import Shops
from core.product import Product
from core.Logger import AppLogger

logger = AppLogger()


def flag_products_to_create():
    task_id = logger.log_task_start("flag_products_to_create")
    start = time.time()

    shops = Shops().get_ready_shops()

    total_flagged = 0
    failed = 0

    for shop in shops:
        try:
            barcodes, total = shop.get_eligible_product_barcodes_with_count()

            logger.log(
                event="shop_product_discovery",
                level="info",
                store=shop.domain,
                data={
                    "message": f"🔍 Found {total} eligible products for {shop.domain}, attempting to flag {len(barcodes)} as create_pending.",
                },
                task_id=task_id
            )

            for barcode in barcodes:
                try:
                    product = Product(barcode)

                    if product.has_been_listed_to_shop(shop):
                        logger.log(
                            event="product_already_flagged",
                            level="debug",
                            store=shop.domain,
                            data={
                                "barcode": barcode,
                                "message": f"⚠️ Product already flagged for {shop.domain}, skipping."
                            },
                            task_id=task_id
                        )
                        continue

                    best_supplier = product.get_best_supplier_for_shop(shop)
                    if not best_supplier:
                        logger.log(
                            event="product_no_supplier_available",
                            level="warning",
                            store=shop.domain,
                            data={
                                "barcode": barcode,
                                "message": "⚠️ No valid supplier found for product. Skipping."
                            },
                            task_id=task_id
                        )
                        continue

                    listing_data = {
                        "status": "create_pending",
                    }

                    product.mark_listed_to_shop(shop, listing_data)
                    total_flagged += 1

                except Exception as e:
                    failed += 1
                    try:
                        product.log_action(
                            event="product_flag_create_pending_failed",
                            level="error",
                            data={
                                "shop": shop.domain,
                                "message": "❌ Failed to mark product as pending for listing.",
                                "error": str(e)
                            },
                            task_id=task_id
                        )
                    except Exception as inner:
                        logger.log(
                            event="product_flag_create_pending_failed_fallback",
                            level="error",
                            store=shop.domain,
                            data={
                                "barcode": barcode,
                                "error": str(e),
                                "fallback_error": str(inner)
                            },
                            task_id=task_id
                        )

        except Exception as e:
            failed += 1
            logger.log(
                event="shop_flag_discovery_failed",
                store=shop.domain,
                level="error",
                data={
                    "message": "❌ Failed to discover or process products for shop.",
                    "error": str(e)
                },
                task_id=task_id
            )

    duration = time.time() - start
    logger.log_task_end(
        task_id=task_id,
        event="flag_products_to_create",
        success=total_flagged,
        failed=failed,
        duration=duration
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "flag_products_to_create":
        flag_products_to_create()
    else:
        print("No valid command provided.")
