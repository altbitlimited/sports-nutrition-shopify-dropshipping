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

    def update_product(self, barcode_lookup_data=None, barcode_lookup_status=None, ai_generated_data=None, ai_generate_status=None, image_urls=None, suppliers=None, images_status=None):
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
