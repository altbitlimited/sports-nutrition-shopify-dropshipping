# core/cache.py

from datetime import datetime

class Cache:
    def __init__(self, collection):
        self.collection = collection

    def get(self, key: str):
        cached = self.collection.find_one({"key": key})
        return cached["data"] if cached else None

    def set(self, key: str, data):
        self.collection.update_one(
            {"key": key},
            {
                "$set": {
                    "data": data,
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )
