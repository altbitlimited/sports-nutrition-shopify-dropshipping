# core/exceptions.py

class ProductNotFoundError(Exception):
    """
    Exception raised when a product is not found in the database.
    """
    def __init__(self, barcode):
        self.barcode = barcode
        self.message = f"Product with barcode {self.barcode} not found in the database."
        super().__init__(self.message)

class ShopifyProductCreationError(Exception):
    """
    Exception raised when a product fails to fully create on Shopify and is cleaned up.
    """
    def __init__(self, barcode, message=None, original_exception=None):
        self.barcode = barcode
        self.original_exception = original_exception
        self.message = message or f"Product creation failed for barcode {barcode}."
        super().__init__(self.message)

class ShopNotReadyError(Exception):
    """
    Exception raised when we attempt to prepare a store ready for interacting with products.
    """
    def __init__(self, shop, original_exception=None):
        self.shop = shop
        self.original_exception = original_exception
        self.message = f"Shop {shop.shop} is not ready for product actions."
        super().__init__(self.message)