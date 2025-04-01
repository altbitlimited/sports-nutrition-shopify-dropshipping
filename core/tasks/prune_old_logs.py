# core/tasks/prune_old_logs.py

import sys
import time
from datetime import datetime, timedelta
from core.MongoManager import MongoManager
from core.Logger import AppLogger

mongo = MongoManager()
logger = AppLogger(mongo)

def prune_old_logs():
    """
    Prunes logs older than 30 days to keep the database clean.
    """
    task_id = logger.log_task_start("prune_old_logs")
    start_time = time.time()

    try:
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        logger.log("prune_old_logs_start", level="info", task_id=task_id, data={
            "cutoff_date": thirty_days_ago.isoformat(),
            "message": "🧹 Starting to prune logs older than 30 days"
        })

        result = mongo.logs.delete_many({"timestamp": {"$lt": thirty_days_ago}})

        logger.log("prune_old_logs_complete", level="success", task_id=task_id, data={
            "deleted_count": result.deleted_count,
            "cutoff_date": thirty_days_ago.isoformat(),
            "message": f"✅ Pruned {result.deleted_count} log entries"
        })

        logger.log_task_end(
            task_id=task_id,
            event="prune_old_logs",
            success=result.deleted_count,
            failed=0,
            duration=time.time() - start_time
        )

    except Exception as e:
        logger.log("prune_old_logs_error", level="error", task_id=task_id, data={
            "error": str(e),
            "message": "❌ Error occurred while pruning logs"
        })
        logger.log_task_end(
            task_id=task_id,
            event="prune_old_logs",
            success=0,
            failed=1,
            duration=time.time() - start_time
        )

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prune old logs from the database")
    parser.add_argument("command", choices=["prune_old_logs"], help="Command to run")

    args = parser.parse_args()

    if args.command == "prune_old_logs":
        prune_old_logs()
    else:
        logger.log("invalid_command", level="warning", data={"message": "⚠️ No valid command provided"})
