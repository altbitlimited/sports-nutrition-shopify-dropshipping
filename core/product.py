# core/product.py

from core.MongoManager import MongoManager
from core.Logger import AppLogger
from datetime import datetime
from core.exceptions import ProductNotFoundError
from core.shop import Shop

mongo = MongoManager()
logger = AppLogger(mongo)

class Product:
    def __init__(self, barcode: str):
        self.barcode = barcode
        self.product = self.get_product()

    def get_product(self):
        try:
            product = mongo.db.products.find_one({"barcode": self.barcode})
            if not product:
                raise ProductNotFoundError(self.barcode)
            return product
        except Exception as e:
            self.log_action(
                event="mongodb_error",
                level="error",
                data={"message": f"Error fetching product: {str(e)}"}
            )
            raise

    def add_supplier(self, supplier_name, supplier_data, supplier_parsed_data):
        if not self.product:
            raise ProductNotFoundError(self.barcode)

        existing_suppliers = [s["name"] for s in self.product.get("suppliers", [])]
        if supplier_name not in existing_suppliers:
            self.product["suppliers"].append({
                "name": supplier_name,
                "data": supplier_data,
                "parsed": supplier_parsed_data
            })

            mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$set": {
                    "suppliers": self.product["suppliers"],
                    "updated_at": datetime.utcnow()
                }}
            )

            self.log_action(
                event="supplier_added",
                level="info",
                data={
                    "supplier_name": supplier_name,
                    "message": f"🔗 Supplier {supplier_name} added to product."
                }
            )
        else:
            self.log_action(
                event="supplier_already_exists",
                level="debug",
                data={
                    "supplier_name": supplier_name,
                    "message": f"Supplier {supplier_name} already linked to product."
                }
            )

    def prune_supplier_link(self, supplier_name):
        if not self.product:
            raise ProductNotFoundError(self.barcode)

        suppliers = [s for s in self.product.get("suppliers", []) if s["name"] != supplier_name]

        if len(suppliers) != len(self.product["suppliers"]):
            mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$set": {
                    "suppliers": suppliers,
                    "updated_at": datetime.utcnow()
                }}
            )

            self.log_action(
                event="supplier_removed",
                level="info",
                data={
                    "supplier_name": supplier_name,
                    "message": f"🪩 Supplier {supplier_name} removed from product."
                }
            )
        else:
            self.log_action(
                event="supplier_not_found",
                level="warning",
                data={
                    "supplier_name": supplier_name,
                    "message": f"⚠️ Supplier {supplier_name} not found in product."
                }
            )

    def update_product(self, barcode_lookup_data=None, barcode_lookup_status=None,
                       ai_generated_data=None, ai_generate_status=None,
                       image_urls=None, suppliers=None, images_status=None):
        if not self.product:
            raise ProductNotFoundError(self.barcode)

        update_data = {}

        if barcode_lookup_data is not None:
            update_data["barcode_lookup_data"] = barcode_lookup_data
        if barcode_lookup_status is not None:
            update_data["barcode_lookup_status"] = barcode_lookup_status
            update_data["barcode_lookup_at"] = datetime.utcnow()
        if ai_generated_data is not None:
            update_data["ai_generated_data"] = ai_generated_data
        if ai_generate_status is not None:
            update_data["ai_generate_status"] = ai_generate_status
            update_data["ai_generate_at"] = datetime.utcnow()
        if image_urls is not None:
            update_data["image_urls"] = image_urls
        if images_status is not None:
            update_data["images_status"] = images_status
            update_data["images_at"] = datetime.utcnow()
        if suppliers is not None:
            update_data["suppliers"] = suppliers

        update_data["updated_at"] = datetime.utcnow()

        try:
            result = mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$set": update_data}
            )

            if result.modified_count > 0:
                self.product.update(update_data)
                self.log_action(
                    event="product_updated",
                    level="success",
                    data={"message": "✅ Product updated successfully."}
                )
            else:
                self.log_action(
                    event="product_no_changes",
                    level="debug",
                    data={"message": "No changes made to product."}
                )
        except Exception as e:
            self.log_action(
                event="mongodb_error",
                level="error",
                data={"message": f"Database update failed: {str(e)}"}
            )
            raise Exception(f"Database operation failed: {str(e)}")

    def is_enriched_for_listing(self):
        data = self.product
        ai = data.get("ai_generated_data", {})
        lookup = data.get("barcode_lookup_data", {})

        required_fields = [
            ai.get("title"),
            ai.get("description"),
            ai.get("product_type"),
            lookup.get("brand") or lookup.get("manufacturer")
        ]

        is_valid = all(required_fields)
        if not is_valid:
            self.log_action(
                event="product_not_ready",
                level="debug",
                data={"message": "⚠️ Product is missing enrichment fields required for listing."}
            )

        return is_valid

    def is_product_eligible(self, shop: Shop) -> bool:
        if not all([
            self.product.get("barcode_lookup_status") == "success",
            self.product.get("images_status") == "success",
            self.product.get("ai_generate_status") == "success",
        ]):
            self.log_action(event="product_not_eligible_enrichment_incomplete", level="debug", data={"message": "⚠️ Enrichment incomplete."})
            return False

        if not self.product.get("image_urls"):
            self.log_action(event="product_not_eligible_missing_images", level="debug", data={"message": "🚫 No image URLs present."})
            return False

        brand = self.get_brand()
        if brand in shop.get_excluded_brands():
            self.log_action(event="product_not_eligible_excluded_brand", level="debug", data={"brand": brand, "message": "🚫 Brand excluded."})
            return False

        for supplier in self.product.get("suppliers", []):
            name = supplier.get("name")
            parsed = supplier.get("parsed", {})
            if name in shop.get_excluded_suppliers():
                continue
            if parsed.get("stock_level", 0) > 0 and parsed.get("price", 0) > 0:
                return True

        self.log_action(event="product_not_eligible_no_valid_supplier", level="debug", data={"message": "🚫 No usable suppliers with stock and price."})
        return False

    def get_best_supplier_for_shop(self, shop: Shop):
        valid_suppliers = []
        for supplier in self.product.get("suppliers", []):
            name = supplier.get("name")
            parsed = supplier.get("parsed", {})
            if name in shop.get_excluded_suppliers():
                continue
            if parsed.get("stock_level", 0) > 0 and parsed.get("price", 0) > 0:
                valid_suppliers.append({"name": name, **parsed})

        best = min(valid_suppliers, key=lambda s: s["price"], default=None)
        return best

    def get_selling_price_for_shop(self, shop: Shop):
        best_supplier = self.get_best_supplier_for_shop(shop)
        if not best_supplier:
            return None

        margin = shop.get_setting("profit_margin", 1.5)
        rounding = shop.get_setting("rounding", 0.99)
        base_price = best_supplier["price"] * margin
        rounded_price = round(base_price) + rounding - 1 if rounding else round(base_price, 2)
        return round(rounded_price, 2)

    def has_been_listed_to_shop(self, shop: Shop) -> bool:
        for entry in self.product.get("shops", []):
            if entry.get("shop") == shop.domain:
                return True
        return False

    def mark_listed_to_shop(self, shop: Shop, listing_data: dict):
        listing_data.update({
            "shop": shop.domain,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })

        mongo.db.products.update_one(
            {"barcode": self.barcode},
            {"$push": {"shops": listing_data}}
        )

        self.log_action(
            event="product_marked_as_listed",
            level="info",
            data={
                "shop": shop.domain,
                "listing_data": listing_data,
                "message": "🛒 Product marked as listed to shop."
            }
        )

    def unlist_from_shop(self, shop: Shop):
        mongo.db.products.update_one(
            {"barcode": self.barcode},
            {"$pull": {"shops": {"shop": shop.domain}}}
        )

        self.log_action(
            event="product_unlisted",
            level="warning",
            data={"shop": shop.domain, "message": "🚫 Product unlisted from shop."}
        )

    def get_brand(self):
        return self.product.get("barcode_lookup_data", {}).get("brand") or \
               self.product.get("barcode_lookup_data", {}).get("manufacturer")

    def log_action(self, event: str, level: str = "info", data: dict = None, task_id: str = None):
        logger.log(
            event=event,
            store=None,
            level=level,
            data={"barcode": self.barcode, **(data or {})},
            task_id=task_id
        )
