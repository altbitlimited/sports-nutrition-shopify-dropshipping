# core/products.py

from core.MongoManager import MongoManager
from core.product import Product
from core.Logger import AppLogger
from datetime import datetime

logger = AppLogger(MongoManager())  # Initialize logger with MongoDB

class Products:
    def __init__(self):
        self.mongo = MongoManager()

    def add_new_product(self, barcode, supplier_data):
        """
        Add a new product to the database in the Products class.
        After adding the product, return an instance of Product.
        Logs the action.
        """
        existing_product = self.mongo.db.products.find_one({"barcode": barcode})

        if existing_product:
            logger.log(
                event="product_exists",
                store=None,
                level="info",
                data={
                    "barcode": barcode,
                    "message": f"Product with barcode {barcode} already exists."
                }
            )
            return Product(barcode)

        # Insert the new product into the database with minimal data
        product_data = {
            "barcode": barcode,
            "barcode_lookup_data": None,  # Set to None (null in MongoDB)
            "ai_generated_data": None,    # Set to None (null in MongoDB)
            "image_urls": None,           # Set to None (null in MongoDB)
            "suppliers": [
                {"name": supplier_data["name"], "data": supplier_data["data"], "parsed": supplier_data["parsed"]}],
            "shops": [],  # Placeholder for shops, can be populated later
            "created_at": datetime.utcnow(),  # Set the created_at timestamp
            "updated_at": datetime.utcnow()   # Set the updated_at timestamp
        }

        self.mongo.db.products.insert_one(product_data)

        logger.log(
            event="product_added",
            store=None,
            level="info",
            data={
                "barcode": barcode,
                "message": f"New product with barcode {barcode} added to the database.",
                "supplier_count": 1
            }
        )

        print(f"Product {barcode} added to database.")
        return Product(barcode)

    def bulk_update_products(self, product_updates):
        """
        Update multiple products in bulk.
        Logs the action.
        """
        for product_update in product_updates:
            barcode = product_update['barcode']
            product_obj = Product(barcode)

            product_obj.update_product(
                barcode_lookup_data=product_update.get("barcode_lookup_data"),
                ai_generated_data=product_update.get("ai_generated_data"),
                image_urls=product_update.get("image_urls"),
                suppliers=product_update.get("suppliers")
            )

            logger.log(
                event="product_bulk_update",
                store=None,
                level="info",
                data={
                    "barcode": barcode,
                    "message": f"Product with barcode {barcode} updated in bulk."
                }
            )

    def prune_supplier_links_bulk(self, supplier_name, barcodes):
        """
        Prune supplier links in bulk for multiple products.
        Logs the action.
        """
        for barcode in barcodes:
            product_obj = Product(barcode)
            product_obj.prune_supplier_link(supplier_name)

            logger.log(
                event="supplier_link_pruned",
                store=None,
                level="info",
                data={
                    "barcode": barcode,
                    "supplier_name": supplier_name,
                    "message": f"Supplier {supplier_name} link pruned for product {barcode}."
                }
            )
