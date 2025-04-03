import sys
import time
from datetime import datetime, timedelta
from core.shops import Shops
from core.product import Product
from core.Logger import AppLogger

logger = AppLogger()

RETRY_BACKOFF_HOURS = [12, 24, 48]


def retry_failed_listings():
    task_id = logger.log_task_start("retry_failed_listings")
    start = time.time()

    shops = Shops().get_ready_shops()

    retried = 0
    skipped = 0
    failed = 0

    for shop in shops:
        products = shop.mongo.products.find({
            "shops": {
                "$elemMatch": {
                    "shop": shop.domain,
                    "status": "create_failed"
                }
            }
        })

        for product_data in products:
            barcode = product_data["barcode"]
            listing = next((s for s in product_data["shops"] if s["shop"] == shop.domain), None)

            if not listing:
                continue

            retry_count = listing.get("retry_count", 0)
            updated_at = listing.get("updated_at")

            if not updated_at:
                skipped += 1
                continue

            retry_hours = RETRY_BACKOFF_HOURS[min(retry_count, len(RETRY_BACKOFF_HOURS) - 1)]
            retry_after = updated_at + timedelta(hours=retry_hours)

            if datetime.utcnow() < retry_after:
                skipped += 1
                continue

            try:
                product = Product(barcode)
                product.mark_listed_to_shop(shop, {
                    **listing,
                    "status": "create_pending",
                    "retry_count": retry_count + 1
                })

                product.log_action(
                    event="shopify_listing_retry_flagged",
                    level="info",
                    data={
                        "shop": shop.domain,
                        "retry_count": retry_count + 1,
                        "message": f"♻️ Re-attempt flagged after {retry_count} previous retries."
                    },
                    task_id=task_id
                )

                retried += 1

            except Exception as e:
                failed += 1
                logger.log(
                    event="shopify_listing_retry_failed",
                    level="error",
                    store=shop.domain,
                    data={
                        "barcode": barcode,
                        "error": str(e),
                        "message": "❌ Failed to flag product for retry."
                    },
                    task_id=task_id
                )

    duration = time.time() - start
    logger.log_task_end(
        task_id=task_id,
        event="retry_failed_listings",
        success=retried,
        failed=failed,
        duration=duration
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "retry_failed_listings":
        retry_failed_listings()
    else:
        print("No valid command provided.")
