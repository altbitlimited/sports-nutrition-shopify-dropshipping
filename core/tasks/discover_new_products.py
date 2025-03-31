# core/tasks/discover_new_products.py

import sys
from suppliers.dummy_supplier import DummySupplier
from core.MongoManager import MongoManager
from core.Logger import AppLogger

mongo = MongoManager()
logger = AppLogger(mongo)

def discover_new_products():
    print("🔍 Starting new product discovery...")

    supplier_classes = [DummySupplier()]  # Extend with real suppliers later
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
                # Completely new product
                new_barcodes.append(barcode)
            else:
                # Product exists, check if supplier is listed
                supplied_by = [s["name"] for s in product.get("suppliers", [])]
                if supplier_name not in supplied_by:
                    # Supplier isn't in the list, so we need to add it
                    new_supplier_links.append(barcode)
                else:
                    # The product exists and the supplier is listed — check if we need to prune the link
                    current_suppliers = product["suppliers"]
                    current_suppliers = [s for s in current_suppliers if s["name"] != supplier_name]

                    if len(current_suppliers) != len(product["suppliers"]):
                        # Supplier was removed, so we prune the link
                        mongo.db.products.update_one(
                            {"barcode": barcode},
                            {"$set": {"suppliers": current_suppliers}}
                        )
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
