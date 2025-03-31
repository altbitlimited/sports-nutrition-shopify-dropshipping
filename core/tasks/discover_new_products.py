# core/tasks/discover_new_products.py

import sys
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from suppliers.dummy_supplier import DummySupplier  # Replace with real supplier imports later
from core.MongoManager import MongoManager
from core.products import Products
from core.product import Product  # Import the Product class
from core.Logger import AppLogger

mongo = MongoManager()
logger = AppLogger(mongo)

def fetch_product_data(barcode, supplier, retries=3, delay=2):
    """
    Fetch product data from the supplier for a given barcode.
    Implements retry logic with exponential backoff.
    """
    attempt = 0
    while attempt < retries:
        try:
            product_data = supplier.get_product_by_barcode(barcode)
            return product_data
        except Exception as e:
            attempt += 1
            logger.log(event="product_discovery_error", level="error", data={
                "supplier": supplier.name,
                "barcode": barcode,
                "error": str(e),
                "attempt": attempt
            })
            # Exponential backoff with randomization to avoid thundering herd problem
            time.sleep(delay * (2 ** attempt) + random.uniform(0, 1))  # Exponential backoff
    return None  # If all attempts fail

def process_barcodes_for_supplier(supplier, supplier_barcodes, products, batch_size=500):
    """
    Process the barcodes for a supplier in batches, using parallel threads to fetch product data.
    """
    new_barcodes = []
    new_supplier_links = []

    # Convert the set to a list for slicing and indexing
    supplier_barcodes = list(supplier_barcodes)

    # Process barcodes in batches to prevent large memory consumption
    for i in range(0, len(supplier_barcodes), batch_size):
        batch = supplier_barcodes[i:i + batch_size]

        with ThreadPoolExecutor() as executor:
            future_to_barcode = {
                executor.submit(fetch_product_data, barcode, supplier): barcode
                for barcode in batch
            }

            # Process the results of the concurrent tasks
            for future in as_completed(future_to_barcode):
                barcode = future_to_barcode[future]
                product_data = future.result()

                if product_data is None:
                    continue  # Skip if no product data was returned

                product = mongo.db.products.find_one({"barcode": barcode})
                if not product:
                    # If product doesn't exist, it's a new product
                    new_barcodes.append(barcode)

                    # Add the new product to the database
                    supplier_data = {
                        "name": supplier.name,
                        "data": product_data['data'],
                        "parsed": product_data['parsed']
                    }

                    # Create the new product
                    product_obj = products.add_new_product(barcode=barcode, supplier_data=supplier_data)

                    # Log the new product creation
                    logger.log(
                        event="new_product_created",
                        store=None,
                        level="info",
                        data={
                            "barcode": barcode,
                            "supplier": supplier.name,
                            "message": f"New product created by {supplier.name}.",
                            "product_data": product_data['parsed']  # Log the parsed data
                        }
                    )
                else:
                    # If product exists, check if this supplier is linked
                    product_obj = Product(barcode)
                    existing_suppliers = [s["name"] for s in product.get("suppliers", [])]

                    if supplier.name not in existing_suppliers:
                        supplier_data = {
                            "name": supplier.name,
                            "data": product_data['data'],
                            "parsed": product_data['parsed']
                        }
                        product_obj.add_supplier(supplier_name=supplier.name, supplier_data=supplier_data["data"], supplier_parsed_data=supplier_data["parsed"])

                        new_supplier_links.append(barcode)

                        # Log supplier link addition
                        logger.log(
                            event="supplier_added_to_existing_product",
                            store=None,
                            level="info",
                            data={
                                "barcode": barcode,
                                "supplier": supplier.name,
                                "message": f"Supplier {supplier.name} added to product.",
                                "product_data": product_data['parsed']  # Log the parsed data
                            }
                        )

    return new_barcodes, new_supplier_links

def prune_supplier_links_for_supplier(supplier_name, all_barcodes):
    """
    Prune supplier links for products that no longer exist in the supplier's feed.
    This should happen after all product processing is complete.
    """
    pruned_supplier_links = []
    for product in mongo.db.products.find({"suppliers.name": supplier_name}):
        if product["barcode"] not in all_barcodes:
            # If the supplier was previously linked to this product and the product is now missing from feed
            product_obj = Product(product["barcode"])
            product_obj.prune_supplier_link(supplier_name)  # Prune supplier link
            pruned_supplier_links.append(product["barcode"])  # Track pruned product barcode
            print(f"Supplier {supplier_name} pruned from product {product['barcode']}.")

    return pruned_supplier_links

def discover_new_products(batch_size=500):
    print("🔍 Starting new product discovery...")

    # Start time for task duration
    start_time = time.time()

    supplier_classes = [DummySupplier()]  # Add real suppliers later
    discovery_summary = {}

    # Instantiate Products class for bulk operations
    products = Products()

    # Keep track of barcodes processed in this run
    all_barcodes = set()

    # Loop through suppliers and process their barcodes
    for supplier in supplier_classes:
        supplier_name = supplier.name
        print(f"📦 Processing supplier: {supplier_name}")

        try:
            supplier_barcodes = set(supplier.get_all_barcodes())
            print(f"✅ Loaded {len(supplier_barcodes)} barcodes from {supplier_name}")
        except Exception as e:
            print(f"❌ Error loading barcodes for {supplier_name}: {e}")
            continue

        # Process barcodes for the current supplier in parallel
        new_barcodes, new_supplier_links = process_barcodes_for_supplier(supplier, supplier_barcodes, products, batch_size)

        # Track all barcodes processed in this run
        all_barcodes.update(supplier_barcodes)

        # Log results for the supplier
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

        # After processing all barcodes, prune supplier links that are no longer in the feed
        pruned_supplier_links = prune_supplier_links_for_supplier(supplier_name, all_barcodes)

        # Log the pruned supplier links
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

    # Log overall task metrics
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


# Entry point for cron or manual run
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "discover_new_products":
        discover_new_products()
    else:
        print("No valid command provided.")
