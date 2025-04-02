# core/MongoManager.py

from pymongo import MongoClient, ASCENDING, DESCENDING
from core.config import MONGODB_URI, MONGODB_DB_NAME
from core.encryption import encrypt_token, decrypt_token
import time


class MongoManager:
    def __init__(self):
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client[MONGODB_DB_NAME]

        # Collections
        self.shops = self.db["shops"]
        self.logs = self.db["logs"]
        self.products = self.db["products"]
        self.barcode_lookup_cache = self.db["barcode_lookup_cache"]
        self.openai_cache = self.db["openai_cache"]

        self._indexes_created = False

    def create_indexes(self):
        """
        Create indexes for commonly queried fields to improve performance.
        This will run only once per MongoManager instance.
        """

        if self._indexes_created:
            return

        start = time.time()
        print("🔧 Creating MongoDB indexes...")

        # === Products Indexes ===
        self._safe_create_index(self.products, [("barcode", ASCENDING)], "barcode_index", unique=True)
        self._safe_create_index(self.products, [("suppliers.name", ASCENDING)], "suppliers_name_index")
        self._safe_create_index(self.products, [("updated_at", DESCENDING)], "updated_at_index")
        self._safe_create_index(self.products, [("created_at", DESCENDING)], "created_at_index")
        self._safe_create_index(self.products, [("barcode_lookup_data.brand", ASCENDING)], "brand_index")
        self._safe_create_index(self.products, [("barcode_lookup_status", ASCENDING)], "barcode_lookup_status_index")
        self._safe_create_index(self.products, [("images_status", ASCENDING)], "images_status_index")
        self._safe_create_index(self.products, [("ai_generate_status", ASCENDING)], "ai_generate_status_index")

        self._safe_create_index(
            self.products,
            [("barcode_lookup_status", ASCENDING), ("images_status", ASCENDING)],
            "enrich_products_barcode_lookup_images_status"
        )
        self._safe_create_index(
            self.products,
            [("barcode_lookup_status", ASCENDING), ("images_status", ASCENDING), ("ai_generate_status", ASCENDING)],
            "enrich_products_barcode_lookup_images_ai_generate_status"
        )
        self._safe_create_index(
            self.products,
            [("barcode", ASCENDING), ("suppliers.name", ASCENDING)],
            "barcode_supplier_index"
        )
        self._safe_create_index(
            self.products,
            [("shops.shop", ASCENDING)],
            "product_shops_shop_index"
        )
        self._safe_create_index(
            self.products,
            [("shops.shop.status", ASCENDING)],
            "product_shops_shop_status_index"
        )
        self._safe_create_index(
            self.products,
            [("shops.shop.shop", ASCENDING), ("shops.shop.status", ASCENDING)],
            "product_shops_shop_shop_status_index"
        )
        self._safe_create_index(
            self.products,
            [
                ("ai_generate_status", ASCENDING),
                ("barcode_lookup_status", ASCENDING),
                ("images_status", ASCENDING),
                ("shops.shop", ASCENDING)
            ],
            "enrichment_status_with_shop_index"
        )
        self._safe_create_index(
            self.products,
            [("suppliers.parsed.brand", ASCENDING), ("suppliers.name", ASCENDING)],
            "suppliers_brand_supplier_index"
        )

        # === Shops Indexes ===
        self._safe_create_index(self.shops, [("shop", ASCENDING)], "shop_domain_index", unique=True)

        # Optional (only if you query based on these settings)
        self._safe_create_index(self.shops, [("settings.exclude_suppliers", ASCENDING)], "exclude_suppliers_index")
        self._safe_create_index(self.shops, [("settings.exclude_brands", ASCENDING)], "exclude_brands_index")

        # === Cache Indexes ===
        self._safe_create_index(self.barcode_lookup_cache, [("key", ASCENDING)], "key_index")
        self._safe_create_index(self.openai_cache, [("key", ASCENDING)], "key_index")

        elapsed = time.time() - start
        print(f"✅ MongoDB index creation completed in {elapsed:.2f}s.\n")

        self._indexes_created = True

    def _safe_create_index(self, collection, fields, name, **kwargs):
        try:
            print(f"⏳ Creating index: {name} on {collection.name}")
            collection.create_index(fields, name=name, **kwargs)
        except Exception as e:
            print(f"❌ Failed to create index {name} on {collection.name}: {e}")
