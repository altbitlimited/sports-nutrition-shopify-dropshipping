# scripts/test_create_shopify_product.py

import argparse
from pprint import pprint
from core.product import Product
from core.shop import Shop
from core.Logger import AppLogger

def main(barcode: str, shop_domain: str):
    shop = Shop(shop_domain)
    logger = AppLogger()
    task_id = logger.log_task_start("test_create_shopify_product", count=1)

    try:
        product = Product(barcode)
    except Exception as e:
        print(f"❌ Could not load product with barcode {barcode}: {e}")
        return

    print("🔍 Checking product readiness...")
    ok, reason = product.is_ready_to_post_to_shopify(shop)
    if not ok:
        print(reason)
        return

    try:
        print("🚀 Creating product and variant on Shopify...")
        result = product.create_on_shopify(shop, task_id=task_id)
        print("✅ Product + Variant created!")
        pprint(result)
    except Exception as e:
        print(f"❌ Creation failed: {e}")
        logger.log_task_end(task_id, "test_create_shopify_product", success=0, failed=1, duration=0)
        return

    logger.log_task_end(task_id, "test_create_shopify_product", success=1, failed=0, duration=0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--barcode", type=str, required=True)
    parser.add_argument("--shop", type=str, required=True)
    args = parser.parse_args()
    main(args.barcode, args.shop)
