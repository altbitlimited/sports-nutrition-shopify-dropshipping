# core/shop.py

from core.MongoManager import MongoManager
from core.encryption import encrypt_token, decrypt_token
from core.Logger import AppLogger
from datetime import datetime
import difflib
import re
from core.exceptions import ShopNotReadyError

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

    @staticmethod
    def normalize_collection_key(value: str) -> str:
        """
        Normalize a collection title or handle:
        - Trim whitespace
        - Lowercase
        - Replace spaces with underscores
        - Remove all punctuation
        """
        if not isinstance(value, str):
            return ""
        value = value.strip().lower().replace(" ", "_")
        return re.sub(r"[^\w]", "", value)

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

    def update_primary_location_id(self, task_id=None):
        try:
            primary_location_id = self.client.get_primary_location_id(task_id=task_id)

            # ⬇️ Update DB
            self.collection.update_one(
                {"shop": self.domain},
                {"$set": {"primary_location_id": primary_location_id}}
            )

            self.log_action(
                event="📍shopify_primary_location_id_updated",
                level="info",
                data={"primary_location_id": primary_location_id},
                task_id=task_id
            )

            return primary_location_id

        except Exception as e:
            self.log_action(
                event="❌ shopify_collections_update_failed",
                level="error",
                data={"error": str(e)},
                task_id=task_id
            )
            raise

    def get_primary_location_id(self):
        primary_location_id = self.shop.get("primary_location_id", None)

        if primary_location_id is None:
            self.log_action(
                event="primary_location_id_not_set",
                level="info",
                data={
                    "message": "Used get_primary_location_id() but it is not set, attempting to get it."
                }
            )

            primary_location_id = self.update_primary_location_id()

        if primary_location_id is None:
            self.log_action(
                event="primary_location_id_not_retrievable",
                level="error",
                data={
                    "message": "⚠️ Attempted to get shop primary location ID but failed."
                }
            )

        return primary_location_id

    def prepare_for_product_actions(self, task_id=None):
        self.log_action(
            event="✅ prepare_for_product_actions",
            level="info",
            data={"message": "Making sure this store is ready for product actions"},
            task_id=task_id
        )

        self.update_collections()
        self.update_primary_location_id()
        self.reload()

        if self.get_primary_location_id() is None:
            raise ShopNotReadyError(self)

        return True

    def update_collections(self, task_id=None):
        try:
            raw_collections = self.client.get_collections(task_id=task_id)

            # ✅ Validate and clean
            collections = []
            for c in raw_collections:
                if not isinstance(c, dict):
                    continue
                if "id" in c and "title" in c and "handle" in c:
                    collections.append({
                        "id": str(c["id"]),
                        "gid": c["gid"],
                        "title": c["title"],
                        "handle": c["handle"],
                        "normalized_title": self.normalize_collection_key(c["title"]),
                        "normalized_handle": self.normalize_collection_key(c["handle"]),
                    })
                else:
                    self.log_action(
                        event="⚠️ shopify_collection_invalid_structure",
                        level="warning",
                        data={"collection": c},
                        task_id=task_id
                    )

            # ⬇️ Update DB
            self.collection.update_one(
                {"shop": self.domain},
                {"$set": {"collections": collections}}
            )

            self.log_action(
                event="✅ shopify_collections_updated",
                level="info",
                data={"count": len(collections)},
                task_id=task_id
            )

            return collections

        except Exception as e:
            self.log_action(
                event="❌ shopify_collections_update_failed",
                level="error",
                data={"error": str(e)},
                task_id=task_id
            )
            raise

    def resolve_collection_id(
            self,
            *,
            handle: str = None,
            title: str = None,
            return_type: str = "gid"  # 'gid', 'id', or 'both'
    ) -> str | dict | None:
        """
        Resolves a collection ID by exact match on normalized handle or title.

        `return_type` can be:
          - 'gid': returns the GraphQL global ID (default)
          - 'id': returns the numeric Shopify ID
          - 'both': returns {'gid': ..., 'id': ...}
        """
        assert return_type in ("gid", "id", "both"), f"Invalid return_type '{return_type}'."

        collections = self.shop.get("collections", [])
        self.log_action("resolve_collection_id_collections_check", "debug", {
            "shop_collections": collections,
        })

        normalized_input_handle = self.normalize_collection_key(handle) if handle else None
        normalized_input_title = self.normalize_collection_key(title) if title else None

        def extract(c):
            if return_type == "both":
                return {"gid": c.get("gid"), "id": c.get("id")}
            return c.get(return_type)

        for c in collections:
            normalized_title = c.get("normalized_title") or self.normalize_collection_key(c.get("title", ""))
            normalized_handle = c.get("normalized_handle") or self.normalize_collection_key(c.get("handle", ""))

            if normalized_input_handle and normalized_input_handle == normalized_handle:
                return extract(c)

            if normalized_input_title and normalized_input_title == normalized_title:
                return extract(c)

        self.log_action("collection_exact_match_failed", "debug", {
            "handle": handle,
            "title": title,
            "normalized_handle": normalized_input_handle,
            "normalized_title": normalized_input_title,
            "collection_titles": [c.get("title") for c in collections],
            "collection_handles": [c.get("handle") for c in collections],
        })

        self.log_action("collection_match_not_found", "debug", {
            "handle": handle,
            "title": title,
            "message": "❌ No collection found via exact match."
        })

        return None

    # Old resolve_collection_id with fuzzy matching that was causing issues
    # def resolve_collection_id(
    #         self,
    #         *,
    #         handle: str = None,
    #         title: str = None,
    #         return_type: str = "gid"  # 'gid', 'id', or 'both'
    # ) -> str | dict | None:
    #     """
    #     Attempts to resolve a collection ID by handle or title.
    #     Prioritizes exact match, then fuzzy match.
    #
    #     `return_type` can be:
    #       - 'gid': returns the GraphQL global ID (default)
    #       - 'id': returns the numeric Shopify ID
    #       - 'both': returns {'gid': ..., 'id': ...}
    #     """
    #     assert return_type in ("gid", "id", "both"), f"Invalid return_type '{return_type}'."
    #
    #     collections = self.shop.get("collections", [])
    #
    #     # Normalize input
    #     input_title = title.strip().lower() if title else None
    #     input_handle = handle.strip().lower() if handle else None
    #
    #     def extract(c):
    #         if return_type == "both":
    #             return {"gid": c.get("gid"), "id": c.get("id")}
    #         return c.get(return_type)
    #
    #     def log_fuzzy(input_val, matched_val, match_type, c):
    #         payload = {
    #             "input": input_val,
    #             "matched": matched_val,
    #             "type": match_type,
    #         }
    #         if return_type == "both":
    #             payload.update({"collection_gid": c.get("gid"), "collection_id": c.get("id")})
    #         else:
    #             payload[f"collection_{return_type}"] = c.get(return_type)
    #         self.log_action("collection_fuzzy_match_used", "info", payload)
    #
    #     # ✅ Exact match
    #     for c in collections:
    #         c_title = c.get("title", "").strip().lower()
    #         c_handle = c.get("handle", "").strip().lower()
    #
    #         if input_handle and c_handle == input_handle:
    #             return extract(c)
    #
    #         if input_title and c_title == input_title:
    #             return extract(c)
    #
    #     # 🐞 Log missed exact match
    #     self.log_action("collection_exact_match_failed", "debug", {
    #         "handle": handle,
    #         "title": title,
    #         "normalized_handle": input_handle,
    #         "normalized_title": input_title,
    #         "collection_titles": [c.get("title") for c in collections],
    #         "collection_handles": [c.get("handle") for c in collections],
    #     })
    #
    #     # 🤏 Fuzzy fallback
    #     from difflib import get_close_matches
    #
    #     if handle:
    #         handles = [c.get("handle", "") for c in collections]
    #         match = get_close_matches(handle.strip(), handles, n=1, cutoff=0.85)
    #         if match:
    #             matched = match[0]
    #             for c in collections:
    #                 if c.get("handle") == matched:
    #                     log_fuzzy(handle, matched, "handle", c)
    #                     return extract(c)
    #
    #     if title:
    #         titles = [c.get("title", "") for c in collections]
    #         match = get_close_matches(title.strip(), titles, n=1, cutoff=0.85)
    #         if match:
    #             matched = match[0]
    #             for c in collections:
    #                 if c.get("title") == matched:
    #                     log_fuzzy(title, matched, "title", c)
    #                     return extract(c)
    #
    #     # ❌ Total failure
    #     self.log_action("collection_match_not_found", "debug", {
    #         "handle": handle, "title": title, "message": "❌ No collection found via fuzzy or exact match."
    #     })
    #     return None

    def ensure_collections_exist_from_products(self, products: list, task_id: str = None) -> list[str]:
        seen_titles = set()
        created_titles = []

        self.log_action("ensure_collections_exist_from_products_before_loop", "debug", {
            "collections_in_shop": self.shop.get("collections", [])
        })

        for product in products:
            ai = product.product.get("ai_generated_data", {})
            if not ai:
                continue

            titles = list(filter(None, [ai.get("primary_collection")] + ai.get("secondary_collections", [])))

            for title in titles:
                normalized = title.strip().lower()
                if normalized in seen_titles:
                    continue
                seen_titles.add(normalized)

                if self.resolve_collection_id(title=title):
                    continue  # already exists

                try:
                    created = self.client.create_collection(title=title, task_id=task_id)
                    self.add_local_collection(created)
                    created_titles.append(title)
                    self.log_action("collection_created_bulk", "info", {
                        "title": title,
                        "collection_id": created.get("id"),
                        "collection_gid": created.get("gid"),
                        "message": "✅ Collection created during preflight batch step."
                    }, task_id=task_id)

                except Exception as e:
                    self.log_action("collection_create_failed", "error", {
                        "title": title,
                        "error": str(e),
                        "message": "❌ Failed to create collection during preflight."
                    }, task_id=task_id)

        return created_titles

    def add_product_to_collection(
            self,
            product_id: str,
            product_gid: str,
            handle: str = None,
            title: str = None,
            task_id: str = None
    ) -> bool:
        """
        Resolves a collection by handle or title and adds a single product ID to it.
        Returns True if successful, False otherwise.
        """
        collection_id = self.resolve_collection_id(handle=handle, title=title, return_type="both")

        # self.log_action("collection_debug_check_before_add", "debug", {
        #     "handle": handle,
        #     "title": title,
        #     "resolved_collection": collection_id,
        #     "collections_in_shop": self.shop.get("collections", [])
        # })

        if not collection_id:
            self.log_action(
                event="collection_add_failed_no_match",
                level="warning",
                data={
                    "product_id": product_id,
                    "product_gid": product_gid,
                    "handle": handle,
                    "title": title,
                    "message": "❌ Could not resolve collection."
                },
                task_id=task_id
            )
            return False

        try:
            self.client.add_product_to_collection(
                collection_id=collection_id["gid"],
                product_gids=[product_gid],
                task_id=task_id
            )
            return True

        except Exception as e:
            self.log_action(
                event="collection_add_failed_exception",
                level="error",
                data={
                    "product_id": product_id,
                    "product_gid": product_gid,
                    "collection_id": collection_id,
                    "handle": handle,
                    "title": title,
                    "error": str(e),
                    "message": "❌ Failed to add product to collection."
                },
                task_id=task_id
            )
            return False

    def add_local_collection(self, collection: dict):
        existing = self.shop.get("collections", [])
        if any(str(c["id"]) == str(collection["id"]) for c in existing):
            return False  # Already exists

        # ✅ Normalize handle/title on insert
        collection["normalized_title"] = self.normalize_collection_key(collection.get("title", ""))
        collection["normalized_handle"] = self.normalize_collection_key(collection.get("handle", ""))

        self.shop.setdefault("collections", []).append(collection)
        self.collection.update_one(
            {"shop": self.domain},
            {"$push": {"collections": collection}}
        )

        self.log_action(
            event="local_collection_added",
            level="info",
            data={"collection": collection, "message": "📚 Collection added to local + DB."}
        )
        return True

    def update_local_collection(self, collection: dict) -> bool:
        """
        Updates an existing collection entry in the shop record.
        Returns True if updated, False if no match was found.
        """
        self.reload()
        collections = self.shop.get("collections", [])

        updated = False
        for idx, existing in enumerate(collections):
            if str(existing["id"]) == str(collection["id"]):
                collections[idx] = {
                    "id": str(collection["id"]),
                    "gid": str(collection["gid"]),
                    "title": collection.get("title"),
                    "handle": collection.get("handle")
                }
                updated = True
                break

        if updated:
            self.collection.update_one(
                {"shop": self.domain},
                {"$set": {"collections": collections}}
            )
        return updated

    def remove_local_collection(self, collection_id: str) -> bool:
        """
        Removes a collection from the shop document by ID.
        Returns True if a collection was removed, False otherwise.
        """
        self.reload()
        collections = self.shop.get("collections", [])
        new_collections = [c for c in collections if str(c["id"]) != str(collection_id)]

        if len(new_collections) == len(collections):
            return False

        self.collection.update_one(
            {"shop": self.domain},
            {"$set": {"collections": new_collections}}
        )
        return True

    @property
    def client(self):
        from core.clients.shopify_client import ShopifyClient
        token = self.get_access_token()
        if not token:
            self.log_action("webhook_token_missing", "error", {
                "shop": self.domain,
                "message": "❌ Cannot initialize ShopifyClient — access token is missing."
            })
            raise ValueError(f"❌ ShopifyClient init failed: access token missing for {self.domain}")
        return ShopifyClient(self)