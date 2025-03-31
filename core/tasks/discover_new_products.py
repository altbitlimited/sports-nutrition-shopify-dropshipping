# core/tasks/discover_new_products.py

import sys
from suppliers.dummy_supplier import DummySupplier  # Replace with real supplier imports later
from core.MongoManager import MongoManager
from core.product import Product
from core.Logger import AppLogger

mongo = MongoManager()
logger = AppLogger(mongo)

def discover_new_products():
    print("🔍 Starting new product discovery...")

    supplier_classes = [DummySupplier()]  # Add real suppliers later
    discovery_summary = {}

    for supplier in supplier_classes:
        supplier_name = supplier.name
        print(f"📦 Processing supplier: {supplier_name}")

        try:
            supplier_barcodes = set(supplier.get_all_barcodes())
            print(f"✅ Loaded {len(supplier_barcodes)} barcodes from {supplier_name}")
        except Exception as e:
            print(f"❌ Error loading barcodes for {supplier_name}: {e}")
            continue

        new_barcodes = []
        new_supplier_links = []
        pruned_supplier_links = []  # List for tracking removed supplier links

        for barcode in supplier_barcodes:
            product = mongo.db.products.find_one({"barcode": barcode})

            if not product:
                # If product doesn't exist, it's a new product
                new_barcodes.append(barcode)

                # Create Product object and add it to the database
                product_obj = Product(barcode)
                barcode_lookup_data = {"name": "Product Name", "description": "Product Description"}  # Example, update with actual data
                ai_generated_data = {"title": "AI Title", "description": "AI Description"}
                image_urls = ["https://example.com/image.jpg"]  # Replace with actual image URLs
                suppliers = [{"name": supplier_name, "data": {}, "parsed": {}}]

                product_obj.add_new_product(barcode_lookup_data, ai_generated_data, image_urls, suppliers)
            else:
                # Product exists — check if this supplier is linked
                product_obj = Product(barcode)  # Create Product instance
                existing_suppliers = [s["name"] for s in product.get("suppliers", [])]

                if supplier_name not in existing_suppliers:
                    # Supplier isn't linked, so add it
                    product_obj.add_supplier(
                        supplier_name=supplier_name,
                        supplier_data={},  # Add supplier-specific data here
                        supplier_parsed_data={}  # Add parsed data here
                    )
                    new_supplier_links.append(barcode)
                else:
                    # The supplier is already linked, check for pruning
                    product_obj.prune_supplier_link(supplier_name)  # This will prune the supplier if it’s removed
                    pruned_supplier_links.append(barcode)

        print(f"➕ {len(new_barcodes)} new barcodes, 🔗 {len(new_supplier_links)} new supplier links, 🗑️ {len(pruned_supplier_links)} pruned supplier links for {supplier_name}")

        discovery_summary[supplier_name] = {
            "new_barcodes": new_barcodes,
            "new_supplier_links": new_supplier_links,
            "pruned_supplier_links": pruned_supplier_links
        }

        # Log summary for this supplier
        logger.log(
            event="product_discovery",
            store=None,
            level="info",
            data={
                "supplier": supplier_name,
                "new_barcodes": len(new_barcodes),
                "new_supplier_links": len(new_supplier_links),
                "pruned_supplier_links": len(pruned_supplier_links)
            }
        )

    return discovery_summary


# Entry point for cron or manual run
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "discover_new_products":
        discover_new_products()
    else:
        print("No valid command provided.")
