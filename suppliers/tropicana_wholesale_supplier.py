import os
import xml.etree.ElementTree as ET
import paramiko
import io
from suppliers.base_supplier import Supplier
from core.Logger import AppLogger
from core.config import TROPICANA_SFTP_HOST, TROPICANA_SFTP_PORT, TROPICANA_SFTP_USERNAME, TROPICANA_SFTP_PASSWORD, TROPICANA_SFTP_PATH

logger = AppLogger()

class TropicanaWholesaleSupplier(Supplier):
    def __init__(self):
        super().__init__('Tropicana Wholesale')
        self._products_by_barcode = {}
        self._load_and_parse_feed()

    def _load_and_parse_feed(self):
        host = TROPICANA_SFTP_HOST
        port = int(TROPICANA_SFTP_PORT)
        username = TROPICANA_SFTP_USERNAME
        password = TROPICANA_SFTP_PASSWORD
        remote_path = TROPICANA_SFTP_PATH

        try:
            transport = paramiko.Transport((host, port))
            transport.connect(username=username, password=password)
            sftp = paramiko.SFTPClient.from_transport(transport)

            with sftp.open(remote_path, 'r') as file:
                data = file.read()
                tree = ET.parse(io.StringIO(data.decode("utf-8", errors="replace")))
                root = tree.getroot()
                self._parse_products(root)

            sftp.close()
            transport.close()
        except Exception as e:
            logger.log(event="tropicana_feed_load_error", level="error", data={"error": str(e)})
            raise

    def _parse_products(self, root):
        for product_elem in root.findall("Product"):
            try:
                barcode = product_elem.findtext("Barcode")
                if not barcode:
                    continue  # Skip if no barcode

                product_code = product_elem.findtext("ProductCode")
                name = product_elem.findtext("TranslationName")
                stock_level = int(product_elem.findtext("StockLevel") or 0)
                brand = product_elem.findtext("Brand")
                price = float(product_elem.findtext("ProductPrice") or 0.0)
                category = product_elem.findtext("FilterByCategory")

                key = barcode

                parsed = {
                    "barcode": barcode,
                    "brand": brand,
                    "name": name,
                    "sku": product_code,
                    "stock_level": stock_level,
                    "price": price
                }

                raw_data = {child.tag: child.text for child in product_elem}

                if key not in self._products_by_barcode:
                    self._products_by_barcode[key] = {
                        "data": raw_data,
                        "parsed": parsed,
                        "categories": set([category] if category else [])
                    }
                else:
                    self._products_by_barcode[key]["categories"].add(category)

            except Exception as e:
                logger.log(event="tropicana_product_parse_error", level="error", data={"error": str(e)})
                continue

        for product in self._products_by_barcode.values():
            product["parsed"]["categories"] = list(product["categories"])
            del product["categories"]

    def get_all_barcodes(self):
        return list(self._products_by_barcode.keys())

    def get_product_by_barcode(self, barcode):
        return self._products_by_barcode.get(barcode)

    def get_products_by_barcodes(self, barcodes):
        return [self._products_by_barcode[b] for b in barcodes if b in self._products_by_barcode]
