from dotenv import load_dotenv
import os

load_dotenv()

SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET")
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-01").strip()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME")

ENCRYPTION_SECRET = os.getenv("ENCRYPTION_SECRET")

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")