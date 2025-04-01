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
        # Index on the barcode field to speed up product lookups
        self.products.create_index([("barcode", ASCENDING)], name="barcode_index", unique=True)

        # Index on suppliers.name for faster queries filtering products by supplier
        self.products.create_index([("suppliers.name", ASCENDING)], name="suppliers_name_index")

        # Index on updated_at to speed up queries that involve sorting by modification date
        self.products.create_index([("updated_at", DESCENDING)], name="updated_at_index")

        # Index on barcode_lookup_status to speed up filtering by enrichment status
        self.products.create_index([("barcode_lookup_status", ASCENDING)], name="barcode_lookup_status_index")
        self.products.create_index([("images_status", ASCENDING)], name="images_status_index")
        self.products.create_index([("ai_generate_status", ASCENDING)], name="ai_generate_status_index")
        self.products.create_index([("barcode_lookup_status", ASCENDING), ("images_status", ASCENDING)], name="enrich_products_barcode_lookup_images_status")
        self.products.create_index([("barcode_lookup_status", ASCENDING), ("images_status", ASCENDING), ("ai_generate_status", ASCENDING)], name="enrich_products_barcode_lookup_images_ai_generate_status")

        # Compound index on barcode and supplier.name for fast queries filtering by both
        self.products.create_index([("barcode", ASCENDING), ("suppliers.name", ASCENDING)],
                                   name="barcode_supplier_index")

        # Index on created_at for efficient querying and sorting by product creation date
        self.products.create_index([("created_at", DESCENDING)], name="created_at_index")
        self.products.create_index([("barcode_lookup_data.brand", ASCENDING)], name="brand_index")

        self.barcode_lookup_cache.create_index([("key", ASCENDING)], name="key_index")
        self.openai_cache.create_index([("key", ASCENDING)], name="key_index")



    def get_shop_by_domain(self, shop_domain):
        return self.shops.find_one({"shop": shop_domain})

    def save_shop_token(self, shop_domain, access_token, scopes):
        encrypted = encrypt_token(access_token)
        self.shops.update_one(
            {"shop": shop_domain},
            {"$set": {
                "access_token": encrypted,
                "scopes": scopes
            }},
            upsert=True
        )

    def get_decrypted_token(self, shop_domain):
        shop = self.shops.find_one({"shop": shop_domain})
        if not shop or "access_token" not in shop:
            return None
        return decrypt_token(shop["access_token"])

    def update_shop_settings(self, shop_domain, settings: dict):
        self.shops.update_one(
            {"shop": shop_domain},
            {"$set": {"settings": settings}},
            upsert=True
        )
