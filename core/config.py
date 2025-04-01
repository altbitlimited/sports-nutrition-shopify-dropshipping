# core/config.py

from dotenv import load_dotenv
import os

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
IS_DEV = ENVIRONMENT == "development"

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


TROPICANA_SFTP_HOST = os.getenv("TROPICANA_SFTP_HOST", None)
TROPICANA_SFTP_PORT = os.getenv("TROPICANA_SFTP_PORT", None)
TROPICANA_SFTP_USERNAME = os.getenv("TROPICANA_SFTP_USERNAME", None)
TROPICANA_SFTP_PASSWORD = os.getenv("TROPICANA_SFTP_PASSWORD", None)
TROPICANA_SFTP_PATH = os.getenv("TROPICANA_SFTP_PATH", None)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", None)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", 'gpt-4o')
OPENAI_PRICING = {
    "gpt-4o": {
        "cost_per_1k_input_tokens": 0.0025,
        "cost_per_1k_output_tokens": 0.01
    }
}