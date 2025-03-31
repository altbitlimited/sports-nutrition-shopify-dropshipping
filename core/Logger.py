from datetime import datetime
from core.MongoManager import MongoManager


class AppLogger:
    def __init__(self, mongo: MongoManager = None):
        self.mongo = mongo or MongoManager()

    def log(self, event: str, data: dict, store: str = None, level: str = "info"):
        log_entry = {
            "event": event,
            "level": level,
            "store": store,
            "data": data,
            "timestamp": datetime.utcnow()
        }
        self.mongo.logs.insert_one(log_entry)
