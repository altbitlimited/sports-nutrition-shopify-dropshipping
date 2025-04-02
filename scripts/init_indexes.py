# scripts/init_indexes.py

from core.MongoManager import MongoManager

if __name__ == "__main__":
    print("🔧 Running MongoDB index initialization...")
    mongo = MongoManager()
    mongo.create_indexes()