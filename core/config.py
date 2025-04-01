# core/config.py

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

BARCODELOOKUP_API_KEY = os.getenv("BARCODELOOKUP_API_KEY", None)

USE_DUMMY_DATA = os.getenv("USE_DUMMY_DATA", "false").lower() == "true"

BUNNY_REGION = os.getenv("BUNNY_REGION", None)
BUNNY_STORAGE_ZONE_NAME = os.getenv("BUNNY_STORAGE_ZONE_NAME", None)
BUNNY_ACCESS_KEY = os.getenv("BUNNY_ACCESS_KEY", None)

ENABLE_BARCODELOOKUP_CACHE = os.getenv("ENABLE_BARCODELOOKUP_CACHE", "false").lower() == "true"
ENABLE_OPENAI_CACHE = os.getenv("ENABLE_OPENAI_CACHE", "false").lower() == "true"
