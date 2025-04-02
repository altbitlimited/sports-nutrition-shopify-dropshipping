import argparse
from core.shop import Shop
from core.Logger import AppLogger

def main(shop_domain: str):
    shop = Shop(shop_domain)
    logger = AppLogger()
    task_id = logger.log_task_start("test_update_shop_collections", count=1)

    try:
        collections = shop.update_collections(task_id=task_id)
        print(f"✅ {len(collections)} collections updated for {shop_domain}")
        for c in collections:
            print(f"- {c['title']} ({c['id']})")
        logger.log_task_end(task_id, "test_update_shop_collections", success=1, failed=0, duration=0)
    except Exception as e:
        print(f"❌ Failed to update collections: {e}")
        logger.log_task_end(task_id, "test_update_shop_collections", success=0, failed=1, duration=0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update collections from Shopify and store to shop record.")
    parser.add_argument("--shop", type=str, required=True, help="Shop domain (e.g. mystore.myshopify.com)")
    args = parser.parse_args()
    main(args.shop)
