# core/shop.py

from core.MongoManager import MongoManager
from core.encryption import encrypt_token, decrypt_token
from core.Logger import AppLogger


class Shop:
    DEFAULT_SETTINGS = {
        "exclude_suppliers": [],
        "exclude_brands": [],
        "profit_margin": 1.5,
        "rounding": 0.99,
        "round_to": "closest"
    }

    def __init__(self, domain: str):
        self.mongo = MongoManager()
        self.logger = AppLogger(self.mongo)
        self.domain = domain
        self.collection = self.mongo.shops
        self.shop = self.collection.find_one({"shop": domain})

        if not self.shop:
            raise ValueError(f"Shop '{domain}' does not exist. Use Shops.add_new_shop() to create it.")

        self.shop["settings"] = self.shop.get("settings", self.DEFAULT_SETTINGS.copy())

    def get_access_token(self):
        token = self.shop.get("access_token")
        return decrypt_token(token) if token else None

    def set_access_token(self, token: str, scopes: list):
        encrypted = encrypt_token(token)
        self.collection.update_one(
            {"shop": self.domain},
            {
                "$set": {
                    "access_token": encrypted,
                    "scopes": scopes
                }
            },
            upsert=True
        )
        self.shop["access_token"] = encrypted
        self.shop["scopes"] = scopes
        self.log_action(
            event="access_token_saved",
            level="info",
            data={
                "message": "🔐 Access token and scopes saved successfully.",
                "scopes": scopes
            }
        )

    def get_settings(self):
        current_settings = self.shop.get("settings", {})
        updated = False

        # Ensure all default keys are present
        for key, default_value in self.DEFAULT_SETTINGS.items():
            if key not in current_settings:
                current_settings[key] = default_value
                updated = True

        # If any defaults were missing and added, persist the update
        if updated:
            self.collection.update_one(
                {"shop": self.domain},
                {"$set": {"settings": current_settings}}
            )
            self.shop["settings"] = current_settings
            self.log_action(
                event="shop_settings_autofilled_defaults",
                level="info",
                data={
                    "message": "🧩 Missing default settings were added automatically.",
                    "new_settings": current_settings
                }
            )

        return current_settings

    def update_settings(self, new_settings: dict):
        updated = {f"settings.{k}": v for k, v in new_settings.items()}
        self.collection.update_one(
            {"shop": self.domain},
            {"$set": updated},
            upsert=True
        )
        self.shop["settings"].update(new_settings)
        self.log_action(
            event="shop_settings_updated",
            level="info",
            data={
                "message": "🛠️ Shop settings updated.",
                "updated_settings": new_settings
            }
        )

    def get_setting(self, key: str, default=None):
        keys = key.split(".")
        current = self.shop.get("settings", {})
        ref = current

        for k in keys[:-1]:
            if k not in ref or not isinstance(ref[k], dict):
                ref[k] = {}
            ref = ref[k]

        last_key = keys[-1]
        value = ref.get(last_key)

        if value is not None:
            return value

        # Fallback to default if missing
        fallback = self.DEFAULT_SETTINGS.get(key, default)

        # Save fallback into DB and in-memory settings
        self.set_setting(key, fallback)

        self.log_action(
            event="shop_setting_autofilled",
            level="info",
            data={
                "key": key,
                "value": fallback,
                "message": f"🧩 Missing setting '{key}' was autofilled with default."
            }
        )

        return fallback

    def set_setting(self, key: str, value):
        keys = key.split(".")
        query = {}
        path = "settings"
        for k in keys:
            path += f".{k}"
        query[path] = value

        self.collection.update_one(
            {"shop": self.domain},
            {"$set": query},
            upsert=True
        )

        current = self.shop.setdefault("settings", {})
        ref = current
        for k in keys[:-1]:
            ref = ref.setdefault(k, {})
        ref[keys[-1]] = value

        self.log_action(
            event="shop_setting_updated",
            level="info",
            data={
                "message": f"🔧 Setting '{key}' updated to '{value}'",
                "key": key,
                "value": value
            }
        )

    def has_scope(self, scope: str) -> bool:
        return scope in self.shop.get("scopes", [])

    def is_ready_for_listing(self) -> bool:
        token_exists = self.shop.get("access_token") is not None
        has_write_scope = self.has_scope("write_products")
        return token_exists and has_write_scope

    def get_price_config(self):
        return {
            "profit_margin": self.get_setting("profit_margin", 1.5),
            "rounding": self.get_setting("rounding", 0.99)
        }

    def get_excluded_suppliers(self):
        return list(map(lambda x: x.lower(), self.get_setting("exclude_suppliers", [])))

    def get_excluded_brands(self):
        return list(map(lambda x: x.lower(), self.get_setting("exclude_brands", [])))

    def get_log_prefix(self):
        return f"[Shop: {self.domain}]"

    def reload(self):
        self.shop = self.collection.find_one({"shop": self.domain})
        return self.shop

    def log_action(self, event: str, level: str = "info", data: dict = None, task_id: str = None):
        self.logger.log(
            event=event,
            level=level,
            store=self.domain,
            data=data or {},
            task_id=task_id
        )

    def is_product_eligible(self, product: dict) -> bool:
        excluded_suppliers = self.get_excluded_suppliers()
        excluded_brands = self.get_excluded_brands()

        for supplier in product.get("suppliers", []):
            if supplier.get("name") in excluded_suppliers:
                self.log_action(
                    event="product_excluded_by_supplier",
                    level="debug",
                    data={
                        "barcode": product.get("barcode"),
                        "excluded_supplier": supplier.get("name"),
                        "message": f"🚫 Product excluded due to supplier '{supplier.get('name')}'."
                    }
                )
                return False

        brand = product.get("barcode_lookup_data", {}).get("brand") or \
                product.get("barcode_lookup_data", {}).get("manufacturer")

        if brand and brand in excluded_brands:
            self.log_action(
                event="product_excluded_by_brand",
                level="debug",
                data={
                    "barcode": product.get("barcode"),
                    "excluded_brand": brand,
                    "message": f"🚫 Product excluded due to brand '{brand}'."
                }
            )
            return False

        return True

    def get_eligible_product_barcodes_with_count(self, skip: int = None, limit: int = None) -> tuple[list[str], int]:
        excluded_suppliers = self.get_excluded_suppliers()
        excluded_brands = self.get_excluded_brands()

        match_conditions = {
            "ai_generate_status": "success",
            "barcode_lookup_status": "success",
            "images_status": "success",
            "shops.shop": {"$ne": self.domain},
        }

        exclusion_filters = []

        if excluded_suppliers:
            exclusion_filters.append({
                "$not": {
                    "$elemMatch": {
                        "suppliers": {
                            "$elemMatch": {
                                "name": {"$in": excluded_suppliers}
                            }
                        }
                    }
                }
            })

        if excluded_brands:
            exclusion_filters.append({
                "$expr": {
                    "$not": {
                        "$in": [
                            {
                                "$toLower": {
                                    "$ifNull": [
                                        "$barcode_lookup_data.brand",
                                        "$barcode_lookup_data.manufacturer"
                                    ]
                                }
                            },
                            excluded_brands
                        ]
                    }
                }
            })

        if exclusion_filters:
            match_conditions["$and"] = exclusion_filters

        total = self.mongo.products.count_documents(match_conditions)

        pipeline = [{"$match": match_conditions}, {"$sort": {"updated_at": -1}}]

        if skip is not None:
            pipeline.append({"$skip": skip})
        if limit is not None:
            pipeline.append({"$limit": limit})

        pipeline.append({"$project": {"barcode": 1, "_id": 0}})

        cursor = self.mongo.products.aggregate(pipeline)
        barcodes = [doc["barcode"] for doc in cursor]

        return barcodes, total
