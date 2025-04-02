# core/MongoManager.py

from pymongo import MongoClient, ASCENDING, DESCENDING
from core.config import MONGODB_URI, MONGODB_DB_NAME
from core.encryption import encrypt_token, decrypt_token


class MongoManager:
    def __init__(self):
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client[MONGODB_DB_NAME]
        self.shops = self.db["shops"]
        self.logs = self.db["logs"]
        self.products = self.db["products"]
        self.barcode_lookup_cache = self.db["barcode_lookup_cache"]
        self.openai_cache = self.db["openai_cache"]

        # Create indexes for efficient querying
        self.create_indexes()

    def create_indexes(self):
        """
        Create indexes for commonly queried fields to improve performance.
        """
        # === Products Indexes ===
        self.products.create_index([("barcode", ASCENDING)], name="barcode_index", unique=True)
        self.products.create_index([("suppliers.name", ASCENDING)], name="suppliers_name_index")
        self.products.create_index([("updated_at", DESCENDING)], name="updated_at_index")
        self.products.create_index([("created_at", DESCENDING)], name="created_at_index")
        self.products.create_index([("barcode_lookup_data.brand", ASCENDING)], name="brand_index")
        self.products.create_index([("barcode_lookup_status", ASCENDING)], name="barcode_lookup_status_index")
        self.products.create_index([("images_status", ASCENDING)], name="images_status_index")
        self.products.create_index([("ai_generate_status", ASCENDING)], name="ai_generate_status_index")

        self.products.create_index(
            [("barcode_lookup_status", ASCENDING), ("images_status", ASCENDING)],
            name="enrich_products_barcode_lookup_images_status"
        )
        self.products.create_index(
            [("barcode_lookup_status", ASCENDING), ("images_status", ASCENDING), ("ai_generate_status", ASCENDING)],
            name="enrich_products_barcode_lookup_images_ai_generate_status"
        )
        self.products.create_index(
            [("barcode", ASCENDING), ("suppliers.name", ASCENDING)],
            name="barcode_supplier_index"
        )

        # === Shops Indexes ===
        self.shops.create_index([("shop", ASCENDING)], name="shop_domain_index", unique=True)
        self.shops.create_index([("settings.exclude_suppliers", ASCENDING)], name="exclude_suppliers_index")
        self.shops.create_index([("settings.exclude_brands", ASCENDING)], name="exclude_brands_index")
        self.shops.create_index([("settings.include_suppliers", ASCENDING)], name="include_suppliers_index")
        self.shops.create_index([("settings.include_brands", ASCENDING)], name="include_brands_index")

        # === Cache Indexes ===
        self.barcode_lookup_cache.create_index([("key", ASCENDING)], name="key_index")
        self.openai_cache.create_index([("key", ASCENDING)], name="key_index")
