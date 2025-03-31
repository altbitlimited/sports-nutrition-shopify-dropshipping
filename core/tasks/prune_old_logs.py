import sys
from datetime import datetime, timedelta
from core.MongoManager import MongoManager
from core.Logger import AppLogger

# Initialize MongoManager
mongo = MongoManager()
logger = AppLogger(mongo)

def prune_old_logs():
    """
    Prunes logs older than 30 days to keep the database clean.
    """
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    print(f"Attempting to prune logs older than {thirty_days_ago}.")  # Debugging line to verify date

    result = mongo.logs.delete_many({"timestamp": {"$lt": thirty_days_ago}})

    # Debugging output for how many logs were deleted
    print(f"Pruned {result.deleted_count} log entries.")

    logger.log(
        event="prune_logs",
        data={
            "deleted_count": result.deleted_count,
            "cutoff_date": thirty_days_ago.isoformat()
        },
        level="info"
    )


# Check if the command-line arguments are correct and run the function
if __name__ == "__main__":
    print(f"Running prune_logs.py with args: {sys.argv}")

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == 'prune_old_logs':
            prune_old_logs()  # Call the prune_old_logs function
        else:
            print(f"Unknown command: {command}")
    else:
        print("No command provided.")
