# core/Logger.py

from datetime import datetime
from uuid import uuid4
from termcolor import colored
from core.MongoManager import MongoManager
from core.config import IS_DEV

class AppLogger:
    def __init__(self, mongo: MongoManager = None):
        self.mongo = mongo or MongoManager()

    def log(self, event: str, data: dict, store: str = None, level: str = "info", task_id: str = None):
        # Always log to DB
        log_entry = {
            "event": event,
            "level": level,
            "store": store,
            "task_id": task_id,
            "data": data,
            "timestamp": datetime.utcnow()
        }
        self.mongo.logs.insert_one(log_entry)

        # Only print in development
        if IS_DEV:
            icon = {
                "info": "ℹ️",
                "success": "✅",
                "warning": "⚠️",
                "error": "❌",
                "debug": "🐞"
            }.get(level, "🔍")

            color = {
                "info": "blue",
                "success": "green",
                "warning": "yellow",
                "error": "red",
                "debug": "cyan"
            }.get(level, "white")

            label = colored(f"[{level.upper()}]", color)
            print(f"{icon} {label} {event} — {data}")

    def log_task_start(self, event: str, count: int = 0) -> str:
        task_id = str(uuid4())
        self.log(
            event=f"{event}_started",
            level="info",
            data={"message": f"Task started", "count": count},
            task_id=task_id
        )
        return task_id

    def log_task_end(self, task_id: str, event: str, success: int, failed: int, duration: float, cache_hits: int = 0):
        self.log(
            event=f"{event}_completed",
            level="success",
            data={
                "message": "Task completed",
                "success_count": success,
                "failed_count": failed,
                "cache_hits": cache_hits,
                "duration_seconds": round(duration, 2)
            },
            task_id=task_id
        )

    def log_product_error(self, barcode: str, error: str, task_id: str = None, extra: dict = None):
        error_data = {
            "barcode": barcode,
            "error": error
        }
        if extra:
            error_data.update(extra)

        self.log(
            event="product_error",
            level="error",
            data=error_data,
            task_id=task_id
        )
