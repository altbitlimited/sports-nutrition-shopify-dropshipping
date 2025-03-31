class Supplier:
    def __init__(self, name: str):
        self.name = name

    def get_all_barcodes(self):
        """
        Each supplier must implement this method to fetch their products barcodes.
        The method should return a list of barcodes that they stock
        """
        raise NotImplementedError("Each supplier must implement this method.")

    def get_product_by_barcode(self, barcode):
        """
        Each supplier must implement this method to fetch a product by barcode.
        The method should return a product with the suppliers data and parsed data
        """
        raise NotImplementedError("Each supplier must implement this method.")

    def get_products_by_barcodes(self, barcodes):
        """
        Each supplier must implement this method to fetch multiple products by barcode.
        The method should return products with the suppliers data and parsed data
        """
        raise NotImplementedError("Each supplier must implement this method.")