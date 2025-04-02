# core/shops.py

from core.MongoManager import MongoManager
from core.Logger import AppLogger
from core.shop import Shop


class Shops:
    def __init__(self):
        self.mongo = MongoManager()
        self.logger = AppLogger(self.mongo)
        self.collection = self.mongo.shops

    def log_action(self, event: str, level: str = "info", data: dict = None, task_id: str = None):
        self.logger.log(
            event=event,
            level=level,
            data=data or {},
            task_id=task_id
        )

    def get_by_domain(self, shop_domain: str) -> Shop | None:
        shop_data = self.collection.find_one({"shop": shop_domain})
        if shop_data:
            return Shop(shop_domain)
        return None

    def get_all_shops(self):
        shops = list(self.collection.find())
        self.log_action(
            event="shops_loaded",
            level="info",
            data={
                "message": f"📦 Loaded {len(shops)} shops from database."
            }
        )
        return shops

    def get_ready_shops(self):
        ready = []
        for shop_data in self.collection.find():
            shop = Shop(shop_data["shop"])
            if shop.is_ready_for_listing():
                ready.append(shop)
        self.log_action(
            event="ready_shops_loaded",
            level="info",
            data={
                "message": f"✅ Found {len(ready)} ready-to-list shops."
            }
        )
        return ready

    def get_excluded_suppliers_for(self, shop_domain):
        shop = Shop(shop_domain)
        return shop.get_excluded_suppliers()

    def get_excluded_brands_for(self, shop_domain):
        shop = Shop(shop_domain)
        return shop.get_excluded_brands()

    def add_new_shop(self, shop_domain: str, settings: dict = None):
        existing = self.collection.find_one({"shop": shop_domain})
        if existing:
            self.log_action(
                event="shop_exists",
                level="warning",
                data={
                    "shop": shop_domain,
                    "message": "⚠️ Attempted to create shop but it already exists."
                }
            )
            return False

        from core.shop import Shop  # Safe circular import for class reuse
        defaults = settings or Shop.DEFAULT_SETTINGS.copy()

        self.collection.insert_one({
            "shop": shop_domain,
            "access_token": None,
            "scopes": [],
            "settings": defaults,
            "collections": []
        })

        self.log_action(
            event="shop_created",
            level="success",
            data={
                "shop": shop_domain,
                "message": "✨ New shop created with default settings."
            }
        )
        return True

    def delete_shop(self, shop_domain: str, cleanup_related: bool = True):
        shop_record = self.collection.find_one({"shop": shop_domain})

        if not shop_record:
            self.log_action(
                event="shop_delete_not_found",
                level="warning",
                data={
                    "shop": shop_domain,
                    "message": "⚠️ Attempted to delete a shop that doesn't exist."
                }
            )
            return False

        self.collection.delete_one({"shop": shop_domain})

        self.log_action(
            event="shop_deleted",
            level="warning",
            data={
                "shop": shop_domain,
                "message": "🗑️ Shop deleted from database."
            }
        )

        if cleanup_related:
            mongo = self.mongo

            # ❌ Remove this shop from all products' "shops" array
            result_products = mongo.products.update_many(
                {"shops.shop": shop_domain},
                {"$pull": {"shops": {"shop": shop_domain}}}
            )

            self.log_action(
                event="shop_references_removed_from_products",
                level="info",
                data={
                    "shop": shop_domain,
                    "modified_count": result_products.modified_count,
                    "message": f"🧼 Removed shop references from {result_products.modified_count} products."
                }
            )

            # ❌ Remove logs for this shop
            result_logs = mongo.logs.delete_many({"store": shop_domain})

            self.log_action(
                event="shop_logs_deleted",
                level="info",
                data={
                    "shop": shop_domain,
                    "deleted_logs": result_logs.deleted_count,
                    "message": f"🧹 Deleted {result_logs.deleted_count} logs related to this shop."
                }
            )

        return True
