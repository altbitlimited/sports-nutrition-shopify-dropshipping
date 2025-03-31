# core/product.py

from core.MongoManager import MongoManager
from core.Logger import AppLogger
from datetime import datetime

mongo = MongoManager()
logger = AppLogger(mongo)

class Product:
    def __init__(self, barcode: str):
        self.barcode = barcode

    def get_product(self):
        """
        Retrieve the product from the database by barcode.
        """
        return mongo.db.products.find_one({"barcode": self.barcode})

    def add_new_product(self, barcode_lookup_data, ai_generated_data, image_urls, suppliers):
        """
        Adds a new product to the database with the provided data.
        Logs the action.
        """
        product_data = {
            "barcode": self.barcode,
            "barcode_lookup_data": barcode_lookup_data,
            "ai_generated_data": ai_generated_data,
            "image_urls": image_urls,
            "suppliers": suppliers,
            "shops": [],
        }

        # Insert the product into the database
        result = mongo.db.products.insert_one(product_data)
        logger.log(
            event="product_added",
            store=None,
            level="info",
            data={
                "barcode": self.barcode,
                "message": "New product added to the database",
                "supplier_count": len(suppliers)
            }
        )
        print(f"Product {self.barcode} added to database.")

    def update_product(self, barcode_lookup_data=None, ai_generated_data=None, image_urls=None, suppliers=None):
        """
        Update the product in the database.
        Logs the action.
        """
        update_data = {}
        if barcode_lookup_data:
            update_data["barcode_lookup_data"] = barcode_lookup_data
        if ai_generated_data:
            update_data["ai_generated_data"] = ai_generated_data
        if image_urls:
            update_data["image_urls"] = image_urls
        if suppliers:
            update_data["suppliers"] = suppliers

        update_data["updated_at"] = datetime.utcnow()

        result = mongo.db.products.update_one(
            {"barcode": self.barcode},
            {"$set": update_data}
        )

        if result.modified_count > 0:
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

    def add_supplier(self, supplier_name, supplier_data, supplier_parsed_data):
        """
        Adds a new supplier to the product.
        Logs the action.
        """
        product = self.get_product()
        if product:
            # Check if the supplier is already associated with the product
            existing_suppliers = [s["name"] for s in product.get("suppliers", [])]
            if supplier_name not in existing_suppliers:
                product["suppliers"].append({
                    "name": supplier_name,
                    "data": supplier_data,
                    "parsed": supplier_parsed_data
                })

                # Update the product with the new supplier
                self.mongo.db.products.update_one(
                    {"barcode": self.barcode},
                    {"$set": {"suppliers": product["suppliers"]}}
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
        else:
            print(f"Product {self.barcode} not found.")

    def prune_supplier_link(self, supplier_name):
        """
        Removes a supplier link from the product.
        Logs the action.
        """
        product = self.get_product()
        if product:
            # Check if the supplier exists for this product
            suppliers = [s for s in product.get("suppliers", []) if s["name"] != supplier_name]

            if len(suppliers) != len(product["suppliers"]):
                # Supplier link has been removed, update the product
                self.mongo.db.products.update_one(
                    {"barcode": self.barcode},
                    {"$set": {"suppliers": suppliers}}
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
        else:
            print(f"Product {self.barcode} not found.")
