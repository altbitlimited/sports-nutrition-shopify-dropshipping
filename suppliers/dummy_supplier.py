# core/suppliers/dummy_supplier.py

# Inherit from the base Supplier class
from .base_supplier import Supplier

class DummySupplier(Supplier):
    def __init__(self):
        super().__init__('Dummy Supplier')
        self._products = []
        self._products_parsed = []
        self._populate_products()

    def _populate_products(self):
        """
        Returns a static list of dummy products for testing purposes.
        """
        # Dummy data (mimicking supplier feed)
        self._products = [
            {
                "ean": "857640006424",
                "name": "Dummy Product 1",
                "stock_count": 100,
                "price": 25.00,
                "product_code": "XYZ123",
                "brand": "Brand A",
                "weight": "900g",
                "other_data": "something"
            },
            {
                "ean": "810028293847",
                "name": "Dummy Product 2",
                "stock_count": 10,
                "price": 3.00,
                "product_code": "XYZ124",
                "brand": "Brand B",
                "weight": "200g",
                "other_data": "something"
            },
            # {
            #     "ean": "857640006158",
            #     "name": "Dummy Product 3",
            #     "stock_count": 55,
            #     "price": 30.00,
            #     "product_code": "XYZ125",
            #     "brand": "Brand C",
            #     "weight": "700g",
            #     "other_data": "something"
            # },
        ]

        # and populate our dummy parsed data
        for product in self._products:
            self._products_parsed.append({
                "data": product,
                "parsed": {
                    'barcode': product['ean'],
                    'brand': product['brand'],
                    'name': product['name'],
                    'sku': product['product_code'],
                    'stock_level': product['stock_count'],
                    'price': product['price'],
                }
            })

    def get_all_barcodes(self):
        barcodes = []
        for product in self._products_parsed:
            barcodes.append(product['parsed']['barcode'])

        return barcodes

    def get_product_by_barcode(self, barcode):
        products = list(filter(lambda d: d['parsed']['barcode'] == barcode, self._products_parsed))
        if len(products) == 0:
            return None

        return products[0]

    def get_products_by_barcodes(self, barcodes):
        return list(filter(lambda d: d['parsed']['barcode'] in barcodes, self._products_parsed))
