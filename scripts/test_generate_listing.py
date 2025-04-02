# scripts/test_generate_listing.py

import argparse
from pprint import pprint
from core.product import Product
from core.shop import Shop


def main(barcode: str, shop_domain: str):
    shop = Shop(shop_domain)
    product = Product(barcode)

    print("\n🔍 Checking product eligibility...")
    if not product.is_enriched_for_listing():
        print("❌ Product is not enriched.")
        return
    if not product.is_product_eligible(shop):
        print("❌ Product is not eligible for this shop.")
        return

    print("✅ Product is enriched and eligible.")
    print("\n🛠️ Generating Shopify payload...")
    payload = product.generate_shopify_payload(shop)

    if payload:
        print("\n📦 Generated Shopify Payload:")
        pprint(payload)
    else:
        print("❌ Failed to generate payload.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test product Shopify listing payload generation.")
    parser.add_argument("--barcode", type=str, required=True, help="Product barcode")
    parser.add_argument("--shop", type=str, required=True, help="Shop domain")

    args = parser.parse_args()
    main(args.barcode, args.shop)
