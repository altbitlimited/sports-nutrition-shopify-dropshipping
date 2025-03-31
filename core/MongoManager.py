from pymongo import MongoClient
from core.config import MONGODB_URI, MONGODB_DB_NAME
from core.encryption import encrypt_token, decrypt_token


class MongoManager:
    def __init__(self):
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client[MONGODB_DB_NAME]
        self.shops = self.db["shops"]
        self.logs = self.db["logs"]

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
