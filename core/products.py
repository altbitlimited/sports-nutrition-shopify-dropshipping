# core/products.py

from core.MongoManager import MongoManager
from core.product import Product
from core.shop import Shop
from core.Logger import AppLogger
from datetime import datetime


class Products:
    def __init__(self):
        self.mongo = MongoManager()
        self.logger = AppLogger(self.mongo)
        self.collection = self.mongo.db.products

    def log_action(self, event: str, level: str = "info", data: dict = None, task_id: str = None):
        self.logger.log(
            event=event,
            level=level,
            data=data or {},
            task_id=task_id
        )

    def add_new_product(self, barcode, supplier_data):
        existing_product = self.collection.find_one({"barcode": barcode})

        if existing_product:
            self.log_action(
                event="product_exists",
                level="debug",
                data={
                    "barcode": barcode,
                    "message": f"🔁 Product already exists in database."
                }
            )
            return Product(barcode)

        product_data = {
            "barcode": barcode,
            "barcode_lookup_data": None,
            "barcode_lookup_status": "pending",
            "ai_generated_data": None,
            "ai_generate_status": "pending",
            "image_urls": None,
            "images_status": "pending",
            "suppliers": [
                {
                    "name": supplier_data["name"],
                    "data": supplier_data["data"],
                    "parsed": supplier_data["parsed"]
                }
            ],
            "shops": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        self.collection.insert_one(product_data)

        self.log_action(
            event="product_added",
            level="success",
            data={
                "barcode": barcode,
                "supplier": supplier_data["name"],
                "message": f"✨ New product added to database."
            }
        )

        return Product(barcode)

    def bulk_update_products(self, product_updates):
        for product_update in product_updates:
            barcode = product_update['barcode']
            product_obj = Product(barcode)

            product_obj.update_product(
                barcode_lookup_data=product_update.get("barcode_lookup_data"),
                ai_generated_data=product_update.get("ai_generated_data"),
                image_urls=product_update.get("image_urls"),
                suppliers=product_update.get("suppliers")
            )

            self.log_action(
                event="product_bulk_updated",
                level="info",
                data={
                    "barcode": barcode,
                    "message": "🔄 Product updated via bulk operation."
                }
            )

    def prune_supplier_links_bulk(self, supplier_name, barcodes):
        for barcode in barcodes:
            product_obj = Product(barcode)
            product_obj.prune_supplier_link(supplier_name)

            self.log_action(
                event="supplier_pruned_bulk",
                level="info",
                data={
                    "barcode": barcode,
                    "supplier": supplier_name,
                    "message": f"🧹 Supplier link pruned from product."
                }
            )

    def bulk_add_supplier(self, supplier_name: str, barcode_data_list: list):
        updated = 0
        skipped = 0
        failed = 0
        updated_barcodes = []

        for item in barcode_data_list:
            barcode = item.get("barcode")
            if not barcode:
                self.log_action(
                    event="bulk_add_supplier_missing_barcode",
                    level="warning",
                    data={"message": "⚠️ Skipping item with missing barcode.", "item": item}
                )
                failed += 1
                continue

            try:
                product = Product(barcode)
                existing_suppliers = [s["name"] for s in product.product.get("suppliers", [])]

                if supplier_name in existing_suppliers:
                    self.log_action(
                        event="supplier_already_exists_bulk",
                        level="debug",
                        data={
                            "barcode": barcode,
                            "supplier": supplier_name,
                            "message": f"Supplier already linked to product."
                        }
                    )
                    skipped += 1
                    continue

                product.add_supplier(
                    supplier_name=supplier_name,
                    supplier_data=item["data"],
                    supplier_parsed_data=item["parsed"]
                )
                updated += 1
                updated_barcodes.append(barcode)

            except Exception as e:
                self.log_action(
                    event="bulk_add_supplier_error",
                    level="error",
                    data={
                        "barcode": barcode,
                        "supplier": supplier_name,
                        "message": f"❌ Failed to add supplier to product.",
                        "error": str(e)
                    }
                )
                failed += 1

        self.log_action(
            event="bulk_add_supplier_summary",
            level="info",
            data={
                "supplier": supplier_name,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
                "message": f"📦 Bulk supplier add complete. {updated} updated, {skipped} skipped, {failed} failed."
            }
        )

        return {
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "updated_barcodes": updated_barcodes
        }

    def get_products_for_shop(self, shop: Shop):
        """
        Returns a list of products that are eligible for the given shop.
        Excludes products that match shop's excluded suppliers or brands.
        """
        eligible_products = []

        excluded_suppliers = set(shop.get_excluded_suppliers())
        excluded_brands = set(shop.get_excluded_brands())

        products = self.collection.find()

        for p in products:
            suppliers = {s.get("name") for s in p.get("suppliers", [])}
            brand = p.get("barcode_lookup_data", {}).get("brand") or \
                    p.get("barcode_lookup_data", {}).get("manufacturer")

            if suppliers & excluded_suppliers:
                continue  # skip if any supplier is excluded

            if brand and brand in excluded_brands:
                continue  # skip if brand is excluded

            eligible_products.append(p)

        self.log_action(
            event="eligible_products_fetched",
            level="debug",
            data={
                "shop": shop.domain,
                "count": len(eligible_products),
                "message": f"🎯 {len(eligible_products)} products eligible for shop."
            }
        )

        return eligible_products
