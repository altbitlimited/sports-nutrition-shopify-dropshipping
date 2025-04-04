import time
from core.MongoManager import MongoManager
from core.Logger import AppLogger
from core.product import Product
from core.products import Products
from suppliers.tropicana_wholesale_supplier import TropicanaWholesaleSupplier
from suppliers.dummy_supplier import DummySupplier

mongo = MongoManager()
logger = AppLogger(mongo)

def update_supplier_data(dry_run=False, limit=None):
    task_id = logger.log_task_start("update_supplier_data")
    start_time = time.time()

    supplier_classes = [
        DummySupplier(),
        # TropicanaWholesaleSupplier(),
    ]

    total_updated = 0
    total_pruned = 0

    for supplier in supplier_classes:
        supplier_name = supplier.name
        logger.log("supplier_update_started", level="info", task_id=task_id, data={"supplier": supplier_name})

        updated_count = 0
        pruned_count = 0

        all_supplier_barcodes = set(supplier.get_all_barcodes())
        barcode_to_data = {
            barcode: supplier.get_product_by_barcode(barcode)
            for barcode in all_supplier_barcodes
        }

        query = {
            "barcode_lookup_status": "success",
            "images_status": "success",
            "ai_generate_status": "success",
            "suppliers.name": supplier_name
        }

        cursor = mongo.db.products.find(query).limit(limit) if limit else mongo.db.products.find(query)

        seen_barcodes = set()

        for doc in cursor:
            barcode = doc["barcode"]
            seen_barcodes.add(barcode)
            product_obj = Product(barcode)
            existing = next((s for s in doc["suppliers"] if s["name"] == supplier_name), None)

            if barcode not in all_supplier_barcodes:
                logger.log("supplier_barcode_missing", level="info", task_id=task_id, data={
                    "barcode": barcode,
                    "supplier": supplier_name,
                    "message": "Barcode no longer present in supplier feed. Removing link."
                })
                if not dry_run:
                    product_obj.prune_supplier_link(supplier_name)
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
                pruned_count += 1
                continue

            new_data = barcode_to_data[barcode]
            changes = product_obj.update_supplier_entry(
                supplier_name=supplier_name,
                new_data=new_data["data"],
                new_parsed=new_data["parsed"],
                dry_run=dry_run
            )

            if changes["parsed"] or changes["data"]:
                logger.log("supplier_data_changed", level="info", task_id=task_id, data={
                    "barcode": barcode,
                    "supplier": supplier_name,
                    "updates": changes
                })
                if not dry_run:
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
                updated_count += 1

        logger.log("supplier_update_complete", level="info", task_id=task_id, data={
            "supplier": supplier_name,
            "updated_products": updated_count,
            "pruned_links": pruned_count,
            "duration": round(time.time() - start_time, 2)
        })

        total_updated += updated_count
        total_pruned += pruned_count

    logger.log("supplier_update_summary", level="info", task_id=task_id, data={
        "message": "✅ Supplier update completed",
        "total_updated_products": total_updated,
        "total_pruned_links": total_pruned,
        "duration": round(time.time() - start_time, 2)
    })

    logger.log_task_end(
        task_id=task_id,
        event="update_supplier_data",
        success=total_updated,
        failed=0,
        duration=time.time() - start_time,
        cache_hits=0
    )

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Update supplier stock/price info")
    parser.add_argument("command", choices=["update_supplier_data"], help="Command to run")
    parser.add_argument("--dry-run", action="store_true", help="Simulate changes without writing to DB")
    parser.add_argument("--limit", type=int, help="Limit number of products to check")

    args = parser.parse_args()

    if args.command == "update_supplier_data":
        update_supplier_data(dry_run=args.dry_run, limit=args.limit)