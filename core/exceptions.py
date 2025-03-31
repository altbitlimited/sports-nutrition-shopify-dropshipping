# core/exceptions.py

class ProductNotFoundError(Exception):
    """
    Exception raised when a product is not found in the database.
    """
    def __init__(self, barcode):
        self.barcode = barcode
        self.message = f"Product with barcode {self.barcode} not found in the database."
        super().__init__(self.message)
