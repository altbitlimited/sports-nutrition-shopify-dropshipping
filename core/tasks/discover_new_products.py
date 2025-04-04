import sys
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from suppliers.dummy_supplier import DummySupplier
from suppliers.tropicana_wholesale_supplier import TropicanaWholesaleSupplier
from core.MongoManager import MongoManager
from core.products import Products
from core.product import Product
from core.Logger import AppLogger

mongo = MongoManager()
logger = AppLogger(mongo)

def fetch_product_data(barcode, supplier, retries=3, delay=2, task_id=None):
    attempt = 0
    while attempt < retries:
        try:
            return supplier.get_product_by_barcode(barcode)
        except Exception as e:
            attempt += 1
            logger.log_product_error(
                barcode=barcode,
                error=f"{str(e)} (attempt {attempt})",
                task_id=task_id,
                extra={"supplier": supplier.name}
            )
            time.sleep(delay * (2 ** attempt) + random.uniform(0, 1))
    return None

def process_barcodes_for_supplier(
    supplier,
    supplier_barcodes,
    products,
    task_id=None,
    batch_size=500,
    max_new_products=None,
    max_workers=4
):
    new_barcodes = []
    new_supplier_links = []
    supplier_barcodes = list(supplier_barcodes)

    for i in range(0, len(supplier_barcodes), batch_size):
        batch = supplier_barcodes[i:i + batch_size]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_barcode = {
                executor.submit(fetch_product_data, barcode, supplier, task_id=task_id): barcode
                for barcode in batch
            }

            for future in as_completed(future_to_barcode):
                barcode = future_to_barcode[future]
                product_data = future.result()
                if product_data is None:
                    continue

                product = mongo.db.products.find_one({"barcode": barcode})
                if not product:
                    if max_new_products and len(new_barcodes) >= max_new_products:
                        return new_barcodes, new_supplier_links

                    new_barcodes.append(barcode)
                    supplier_data = {
                        "name": supplier.name,
                        "data": product_data['data'],
                        "parsed": product_data['parsed']
                    }
                    products.add_new_product(barcode=barcode, supplier_data=supplier_data)
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

                        # 🟡 Set shops with status "created" or "updated" to "update_pending"
                        mongo.db.products.update_one(
                            {
                                "barcode": barcode,
                                "shops.status": {"$in": ["created", "updated"]}
                            },
                            {
                                "$set": {"shops.$[elem].status": "update_pending"}
                            },
                            array_filters=[{"elem.status": {"$in": ["created", "updated"]}}]
                        )

                        logger.log(
                            event="supplier_added_to_product",
                            store=None,
                            level="info",
                            task_id=task_id,
                            data={
                                "barcode": barcode,
                                "supplier": supplier.name,
                                "message": f"Supplier {supplier.name} added to product.",
                                "product_data": product_data['parsed']
                            }
                        )

    return new_barcodes, new_supplier_links

def prune_supplier_links_for_supplier(supplier_name, all_barcodes, task_id=None):
    pruned_supplier_links = []
    for product in mongo.db.products.find({"suppliers.name": supplier_name}):
        if product["barcode"] not in all_barcodes:
            product_obj = Product(product["barcode"])
            product_obj.prune_supplier_link(supplier_name)
            pruned_supplier_links.append(product["barcode"])
            logger.log(
                event="supplier_pruned_from_product",
                store=None,
                level="info",
                task_id=task_id,
                data={
                    "barcode": product["barcode"],
                    "supplier": supplier_name,
                    "message": f"Supplier {supplier_name} pruned from product."
                }
            )
    return pruned_supplier_links

def discover_new_products(batch_size=500, limit_per_supplier=None, brand_filters=None, max_new_products=None):
    task_id = logger.log_task_start(event="product_discovery")

    start_time = time.time()
    supplier_classes = [
        DummySupplier(),
        # TropicanaWholesaleSupplier()
    ]
    discovery_summary = {}
    products = Products()
    all_barcodes = set()

    total_success = 0
    total_failed = 0

    logger.log(event="task_status", level="info", task_id=task_id, data={"message": "🔍 Starting new product discovery..."})

    for supplier in supplier_classes:
        supplier_name = supplier.name
        logger.log(event="supplier_processing_started", level="info", data={"supplier": supplier_name}, task_id=task_id)

        try:
            supplier_barcodes = supplier.get_all_barcodes()
            if brand_filters:
                filtered = []
                for b in supplier_barcodes:
                    try:
                        data = supplier.get_product_by_barcode(b)
                        brand = data['parsed']['brand'].strip().lower()
                        if brand in [brand.lower() for brand in brand_filters]:
                            filtered.append(b)
                    except Exception as e:
                        logger.log_product_error(barcode=b, error=f"Brand filter error: {str(e)}", task_id=task_id)
                supplier_barcodes = filtered
            if limit_per_supplier:
                supplier_barcodes = supplier_barcodes[:limit_per_supplier]
            supplier_barcodes = set(supplier_barcodes)
            logger.log(event="supplier_barcodes_loaded", level="info", task_id=task_id, data={
                "supplier": supplier_name,
                "barcode_count": len(supplier_barcodes)
            })
        except Exception as e:
            logger.log_product_error(barcode="*", error=f"Failed to load barcodes from {supplier_name}: {str(e)}", task_id=task_id)
            continue

        new_barcodes, new_supplier_links = process_barcodes_for_supplier(
            supplier,
            supplier_barcodes,
            products,
            task_id=task_id,
            batch_size=batch_size,
            max_new_products=max_new_products
        )

        total_success += len(new_barcodes) + len(new_supplier_links)
        all_barcodes.update(supplier_barcodes)

        logger.log(
            event="product_discovery",
            store=None,
            level="info",
            task_id=task_id,
            data={
                "supplier": supplier_name,
                "new_barcodes": len(new_barcodes),
                "new_supplier_links": len(new_supplier_links),
                "duration": round(time.time() - start_time, 2)
            }
        )

        discovery_summary[supplier_name] = {
            "new_barcodes": new_barcodes,
            "new_supplier_links": new_supplier_links
        }

        pruned_supplier_links = prune_supplier_links_for_supplier(supplier_name, all_barcodes, task_id=task_id)
        if pruned_supplier_links:
            logger.log(
                event="supplier_link_pruned",
                store=None,
                level="info",
                task_id=task_id,
                data={
                    "supplier": supplier_name,
                    "pruned_supplier_links": len(pruned_supplier_links),
                    "duration": round(time.time() - start_time, 2)
                }
            )

    logger.log_task_end(
        task_id=task_id,
        event="product_discovery",
        success=total_success,
        failed=total_failed,
        duration=time.time() - start_time
    )

    return discovery_summary

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Discover new products from suppliers")
    parser.add_argument("command", choices=["discover_new_products"], help="Command to run")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of products per supplier")
    parser.add_argument("--brands", nargs="*", help="Filter by brand names (space-separated)")
    parser.add_argument("--max-new-products", type=int, help="Limit the number of new products added per supplier")
    parser.add_argument("--workers", type=int, default=4, help="Max number of threads for batch processing")

    args = parser.parse_args()

    if args.command == "discover_new_products":
        discover_new_products(limit_per_supplier=args.limit, brand_filters=args.brands, max_new_products=args.max_new_products)
    else:
        logger.log(event="invalid_command", level="warning", data={"message": "No valid command provided"})
