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
        self.product = self.get_product()  # Automatically populate the product data when instantiated

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
            logger.log(event="mongodb_error", level="error", data={"message": f"Error fetching product: {str(e)}"})
            raise

    def add_supplier(self, supplier_name, supplier_data, supplier_parsed_data):
        """
        Adds a new supplier to the product.
        Logs the action.
        """
        if not self.product:
            raise ProductNotFoundError(self.barcode)

        # Check if the supplier is already associated with the product
        existing_suppliers = [s["name"] for s in self.product.get("suppliers", [])]
        if supplier_name not in existing_suppliers:
            self.product["suppliers"].append({
                "name": supplier_name,
                "data": supplier_data,  # Directly use the supplier's data
                "parsed": supplier_parsed_data  # Use the parsed standardized data
            })

            # Update the product with the new supplier
            mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$set": {
                    "suppliers": self.product["suppliers"],
                    "updated_at": datetime.utcnow()  # Update the updated_at timestamp
                }}
            )

            logger.log(
                event="supplier_added",
                store=None,
                level="info",
                data={
                    "barcode": self.barcode,
                    "supplier_name": supplier_name,
                    "message": "Supplier added to the product"
                }
            )
            print(f"Supplier {supplier_name} added to product {self.barcode}.")
        else:
            print(f"Supplier {supplier_name} already exists for product {self.barcode}.")

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
                    "updated_at": datetime.utcnow()  # Update the updated_at timestamp
                }}
            )
            logger.log(
                event="supplier_removed",
                store=None,
                level="info",
                data={
                    "barcode": self.barcode,
                    "supplier_name": supplier_name,
                    "message": "Supplier removed from the product"
                }
            )
            print(f"Supplier {supplier_name} removed from product {self.barcode}.")
        else:
            print(f"Supplier {supplier_name} not found in product {self.barcode}.")

    def update_product(self, barcode_lookup_data=None, ai_generated_data=None, image_urls=None, suppliers=None):
        """
        Update the product in the database.
        Logs the action.
        """
        if not self.product:
            raise ProductNotFoundError(self.barcode)

        update_data = {}
        if barcode_lookup_data:
            update_data["barcode_lookup_data"] = barcode_lookup_data
        if ai_generated_data:
            update_data["ai_generated_data"] = ai_generated_data
        if image_urls:
            update_data["image_urls"] = image_urls
        if suppliers:
            update_data["suppliers"] = suppliers

        update_data["updated_at"] = datetime.utcnow()  # Always update the updated_at timestamp

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
                    level="info",
                    data={
                        "barcode": self.barcode,
                        "message": "Product updated in the database"
                    }
                )
                print(f"Product {self.barcode} updated.")
            else:
                print(f"No changes made for product {self.barcode}.")
        except Exception as e:
            logger.log(event="mongodb_error", level="error", data={"message": str(e)})
            raise Exception(f"Database operation failed: {str(e)}")
