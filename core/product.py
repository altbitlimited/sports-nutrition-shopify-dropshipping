# core/product.py

from core.MongoManager import MongoManager
from core.Logger import AppLogger
from datetime import datetime
from core.exceptions import ProductNotFoundError  # Import the custom exception

mongo = MongoManager()
logger = AppLogger(mongo)

class Product:
    def __init__(self, barcode: str):
        self.barcode = barcode
        self.product = self.get_product()

    def get_product(self):
        """
        Retrieve the product from the database by barcode and automatically populate.
        If the product is not found, raise an exception.
        """
        try:
            product = mongo.db.products.find_one({"barcode": self.barcode})
            if not product:
                raise ProductNotFoundError(self.barcode)
            return product
        except Exception as e:
            logger.log(
                event="mongodb_error",
                level="error",
                data={"barcode": self.barcode, "message": f"Error fetching product: {str(e)}"}
            )
            raise

    def add_supplier(self, supplier_name, supplier_data, supplier_parsed_data):
        """
        Adds a new supplier to the product.
        Logs the action.
        """
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

            logger.log(
                event="supplier_added",
                store=None,
                level="info",
                data={
                    "barcode": self.barcode,
                    "supplier_name": supplier_name,
                    "message": f"🔗 Supplier {supplier_name} added to product."
                }
            )
        else:
            logger.log(
                event="supplier_already_exists",
                store=None,
                level="debug",
                data={
                    "barcode": self.barcode,
                    "supplier_name": supplier_name,
                    "message": f"Supplier {supplier_name} already linked to product."
                }
            )

    def prune_supplier_link(self, supplier_name):
        """
        Removes a supplier link from the product.
        Logs the action.
        """
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

            logger.log(
                event="supplier_removed",
                store=None,
                level="info",
                data={
                    "barcode": self.barcode,
                    "supplier_name": supplier_name,
                    "message": f"🧹 Supplier {supplier_name} removed from product."
                }
            )
        else:
            logger.log(
                event="supplier_not_found",
                store=None,
                level="warning",
                data={
                    "barcode": self.barcode,
                    "supplier_name": supplier_name,
                    "message": f"⚠️ Supplier {supplier_name} not found in product."
                }
            )

    def update_product(self, barcode_lookup_data=None, barcode_lookup_status=None,
                       ai_generated_data=None, ai_generate_status=None,
                       image_urls=None, suppliers=None, images_status=None):
        """
        Update the product in the database.
        Logs the action.
        """
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
                logger.log(
                    event="product_updated",
                    store=None,
                    level="success",
                    data={
                        "barcode": self.barcode,
                        "message": f"✅ Product updated successfully."
                    }
                )
            else:
                logger.log(
                    event="product_no_changes",
                    store=None,
                    level="debug",
                    data={
                        "barcode": self.barcode,
                        "message": "No changes made to product."
                    }
                )
        except Exception as e:
            logger.log(
                event="mongodb_error",
                level="error",
                data={"barcode": self.barcode, "message": f"Database update failed: {str(e)}"}
            )
            raise Exception(f"Database operation failed: {str(e)}")
