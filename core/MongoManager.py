# core/MongoManager.py

from pymongo import MongoClient, ASCENDING
from core.config import MONGODB_URI, MONGODB_DB_NAME
from core.encryption import encrypt_token, decrypt_token


class MongoManager:
    def __init__(self):
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client[MONGODB_DB_NAME]
        self.shops = self.db["shops"]
        self.logs = self.db["logs"]
        self.products = self.db["products"]  # Assuming you want to work with the products collection

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
