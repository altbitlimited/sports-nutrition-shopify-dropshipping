import sys
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from suppliers.dummy_supplier import DummySupplier  # Replace with real supplier imports later
from suppliers.tropicana_wholesale_supplier import TropicanaWholesaleSupplier
from core.MongoManager import MongoManager
from core.products import Products
from core.product import Product  # Import the Product class
from core.Logger import AppLogger

mongo = MongoManager()
logger = AppLogger(mongo)

def fetch_product_data(barcode, supplier, retries=3, delay=2):
    attempt = 0
    while attempt < retries:
        try:
            return supplier.get_product_by_barcode(barcode)
        except Exception as e:
            attempt += 1
            logger.log(event="product_discovery_error", level="error", data={
                "supplier": supplier.name,
                "barcode": barcode,
                "error": str(e),
                "attempt": attempt
            })
            time.sleep(delay * (2 ** attempt) + random.uniform(0, 1))
    return None

def process_barcodes_for_supplier(supplier, supplier_barcodes, products, batch_size=500):
    new_barcodes = []
    new_supplier_links = []
    supplier_barcodes = list(supplier_barcodes)

    for i in range(0, len(supplier_barcodes), batch_size):
        batch = supplier_barcodes[i:i + batch_size]

        with ThreadPoolExecutor() as executor:
            future_to_barcode = {
                executor.submit(fetch_product_data, barcode, supplier): barcode
                for barcode in batch
            }

            for future in as_completed(future_to_barcode):
                barcode = future_to_barcode[future]
                product_data = future.result()
                if product_data is None:
                    continue

                product = mongo.db.products.find_one({"barcode": barcode})
                if not product:
                    new_barcodes.append(barcode)
                    supplier_data = {
                        "name": supplier.name,
                        "data": product_data['data'],
                        "parsed": product_data['parsed']
                    }
                    products.add_new_product(barcode=barcode, supplier_data=supplier_data)
                    logger.log(
                        event="new_product_created",
                        store=None,
                        level="info",
                        data={
                            "barcode": barcode,
                            "supplier": supplier.name,
                            "message": f"New product created by {supplier.name}.",
                            "product_data": product_data['parsed']
                        }
                    )
                else:
                    product_obj = Product(barcode)
                    existing_suppliers = [s["name"] for s in product.get("suppliers", [])]
                    if supplier.name not in existing_suppliers:
                        supplier_data = {
                            "name": supplier.name,
                            "data": product_data['data'],
                            "parsed": product_data['parsed']
                        }
                        product_obj.add_supplier(
                            supplier_name=supplier.name,
                            supplier_data=supplier_data["data"],
                            supplier_parsed_data=supplier_data["parsed"]
                        )
                        new_supplier_links.append(barcode)
                        logger.log(
                            event="supplier_added_to_product",
                            store=None,
                            level="info",
                            data={
                                "barcode": barcode,
                                "supplier": supplier.name,
                                "message": f"Supplier {supplier.name} added to product.",
                                "product_data": product_data['parsed']
                            }
                        )

    return new_barcodes, new_supplier_links

def prune_supplier_links_for_supplier(supplier_name, all_barcodes):
    pruned_supplier_links = []
    for product in mongo.db.products.find({"suppliers.name": supplier_name}):
        if product["barcode"] not in all_barcodes:
            product_obj = Product(product["barcode"])
            product_obj.prune_supplier_link(supplier_name)
            pruned_supplier_links.append(product["barcode"])
            print(f"Supplier {supplier_name} pruned from product {product['barcode']}.")
    return pruned_supplier_links

def discover_new_products(batch_size=500, limit_per_supplier=None, brand_filters=None):
    print("🔍 Starting new product discovery...")
    start_time = time.time()
    supplier_classes = [
        # DummySupplier(),
        TropicanaWholesaleSupplier()
    ]
    discovery_summary = {}
    products = Products()
    all_barcodes = set()

    for supplier in supplier_classes:
        supplier_name = supplier.name
        print(f"📦 Processing supplier: {supplier_name}")
        try:
            supplier_barcodes = supplier.get_all_barcodes()
            if brand_filters:
                supplier_barcodes = [
                    b for b in supplier_barcodes
                    if supplier.get_product_by_barcode(b)['parsed']['brand'].strip().lower() in [brand.lower() for brand in brand_filters]
                ]
            if limit_per_supplier:
                supplier_barcodes = supplier_barcodes[:limit_per_supplier]
            supplier_barcodes = set(supplier_barcodes)
            print(f"✅ Loaded {len(supplier_barcodes)} barcodes from {supplier_name}")
        except Exception as e:
            print(f"❌ Error loading barcodes for {supplier_name}: {e}")
            continue

        new_barcodes, new_supplier_links = process_barcodes_for_supplier(supplier, supplier_barcodes, products, batch_size)
        all_barcodes.update(supplier_barcodes)
        logger.log(
            event="product_discovery",
            store=None,
            level="info",
            data={
                "supplier": supplier_name,
                "new_barcodes": len(new_barcodes),
                "new_supplier_links": len(new_supplier_links),
                "duration": time.time() - start_time
            }
        )
        discovery_summary[supplier_name] = {
            "new_barcodes": new_barcodes,
            "new_supplier_links": new_supplier_links
        }
        pruned_supplier_links = prune_supplier_links_for_supplier(supplier_name, all_barcodes)
        if pruned_supplier_links:
            logger.log(
                event="supplier_link_pruned",
                store=None,
                level="info",
                data={
                    "supplier": supplier_name,
                    "pruned_supplier_links": len(pruned_supplier_links),
                    "duration": time.time() - start_time
                }
            )
    logger.log(
        event="product_discovery_summary",
        store=None,
        level="info",
        data={
            "task_duration": time.time() - start_time
        }
    )
    print(f"Completed in {time.time() - start_time:.2f} seconds.")
    return discovery_summary

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Discover new products from suppliers")
    parser.add_argument("command", choices=["discover_new_products"], help="Command to run")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of products per supplier")
    parser.add_argument("--brands", nargs="*", help="Filter by brand names (space-separated)")

    args = parser.parse_args()

    if args.command == "discover_new_products":
        discover_new_products(limit_per_supplier=args.limit, brand_filters=args.brands)
    else:
        print("No valid command provided.")
