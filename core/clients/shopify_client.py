# core/clients/shopify_client.py

import time
import requests
import mimetypes
from typing import Dict, Any
from urllib.parse import urlparse
from io import BytesIO
from requests_toolbelt import MultipartEncoder

from core.config import SHOPIFY_API_KEY, SHOPIFY_API_SECRET, SHOPIFY_API_VERSION, APP_BASE_URL
from core.shopify_graphql.mutations import (
    PRODUCT_CREATE_MUTATION,
    PRODUCT_VARIANTS_BULK_UPDATE_MUTATION,
    COLLECTION_ADD_PRODUCTS_MUTATION,
    COLLECTION_CREATE_MUTATION
)
from core.shopify_graphql.queries import GET_COLLECTIONS_QUERY
import shopify

class ShopifyGraphQLError(Exception):
    pass


class ShopifyClient:
    def __init__(self, shop):
        from core.shop import Shop  # avoid circular import

        if not isinstance(shop, Shop):
            raise TypeError("Expected a Shop instance")

        self.shop = shop
        self.domain = shop.domain
        self.token = shop.get_access_token()

        if not self.token:
            self.shop.log_action(
                event="webhook_token_missing",
                level="error",
                data={
                    "shop": self.domain,
                    "message": "❌ Cannot initialize ShopifyClient — access token is missing."
                }
            )
            raise ValueError(f"❌ ShopifyClient init failed: access token missing for {self.domain}")

        self.endpoint = f"https://{self.domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.token,
        }

    @staticmethod
    def get_default_scopes() -> list[str]:
        return ["read_products", "write_products", "read_locations", "write_inventory"]

    @staticmethod
    def extract_legacy_id(gid: str) -> str:
        if not gid:
            raise ValueError("GID is missing or invalid.")
        return gid.split("/")[-1]

    def rest(self, method: str, path: str, json: dict = None, params: dict = None, task_id: str = None,
             timeout: int = 10) -> dict:
        url = f"https://{self.domain}/admin/api/{SHOPIFY_API_VERSION}/{path.lstrip('/')}"
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.token,
        }

        try:
            response = requests.request(method, url, headers=headers, json=json, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()

        except requests.HTTPError as e:
            self.shop.log_action("❌ shopify_rest_http_error", "error", {
                "method": method,
                "url": url,
                "status_code": response.status_code,
                "response_text": response.text,
                "error": str(e)
            }, task_id=task_id)
            raise

        except Exception as e:
            self.shop.log_action("❌ shopify_rest_exception", "error", {
                "method": method,
                "url": url,
                "params": params,
                "json": json,
                "error": str(e)
            }, task_id=task_id)
            raise

    def _post_graphql(self, query: str, variables: Dict[str, Any], task_id=None) -> Dict[str, Any]:
        for attempt in range(5):
            try:
                response = requests.post(
                    self.endpoint,
                    json={"query": query, "variables": variables},
                    headers=self.headers,
                    timeout=15
                )
            except Exception as e:
                self.shop.log_action(
                    event="❌ shopify_request_failed",
                    level="error",
                    data={"error": str(e)},
                    task_id=task_id
                )
                raise ShopifyGraphQLError(str(e))

            if response.status_code == 429:
                self.shop.log_action(
                    event="⚠️ shopify_rate_limited",
                    level="warning",
                    data={"attempt": attempt + 1},
                    task_id=task_id
                )
                time.sleep(2 ** attempt)
                continue

            try:
                json_data = response.json()
            except Exception as e:
                self.shop.log_action(
                    event="❌ shopify_invalid_json",
                    level="error",
                    data={"error": str(e), "text": response.text},
                    task_id=task_id
                )
                raise ShopifyGraphQLError("Invalid JSON from Shopify")

            if "errors" in json_data:
                self.shop.log_action(
                    event="❌ shopify_graphql_error",
                    level="error",
                    data={"errors": json_data["errors"]},
                    task_id=task_id
                )
                raise ShopifyGraphQLError(json_data["errors"])

            return json_data["data"]

        raise ShopifyGraphQLError("Too many retries – Shopify API")

    def upload_image_rest(self, product_id: str, image_url: str, task_id=None) -> dict:
        result = self.rest(
            method="POST",
            path=f"products/{product_id}/images.json",
            json={"image": {"src": image_url}},
            task_id=task_id
        )
        image = result.get("image", {})
        self.shop.log_action("✅ shopify_rest_image_attached", "info", {
            "product_id": product_id,
            "image_url": image_url,
            "response_id": image.get("id")
        }, task_id=task_id)
        return result

    def set_inventory_level_rest(self, inventory_item_id: str, location_id: str, quantity: int, task_id=None) -> dict:
        result = self.rest(
            method="POST",
            path="inventory_levels/set.json",
            json={
                "inventory_item_id": inventory_item_id,
                "location_id": location_id,
                "available": quantity
            },
            task_id=task_id
        )
        self.shop.log_action("✅ shopify_inventory_set_rest", "info", {
            "inventory_item_id": inventory_item_id,
            "location_id": location_id,
            "quantity": quantity
        }, task_id=task_id)
        return result

    def delete_product_rest(self, product_id: str, task_id=None) -> bool:
        try:
            self.rest("DELETE", f"products/{product_id}.json", task_id=task_id)
            self.shop.log_action("✅ shopify_product_deleted", "info", {
                "product_id": product_id,
                "message": "🧹 Product deleted successfully from Shopify."
            }, task_id=task_id)
            return True
        except Exception as e:
            self.shop.log_action("❌ shopify_product_delete_failed", "error", {
                "product_id": product_id,
                "error": str(e),
                "message": "❌ Failed to delete product from Shopify."
            }, task_id=task_id)
            return False

    def get_locations_rest(self, task_id=None) -> list[dict]:
        result = self.rest("GET", "locations.json", task_id=task_id)
        locations = result.get("locations", [])
        self.shop.log_action("✅ shopify_locations_fetched", "info", {
            "count": len(locations),
            "location_ids": [loc.get("id") for loc in locations]
        }, task_id=task_id)
        return locations

    def get_primary_location_id(self, task_id=None) -> str:
        locations = self.get_locations_rest(task_id=task_id)
        if not locations:
            raise Exception("❌ No active locations found for this shop.")

        primary_id = str(locations[0]["id"])

        self.shop.log_action("📍primary_location_id_fetched", "info", {
            "primary_location_id_retrieved": primary_id,
        }, task_id=task_id)

        return primary_id

    def create_product(self, payload: Dict[str, Any], task_id=None) -> Dict[str, Any]:
        data = self._post_graphql(PRODUCT_CREATE_MUTATION, {"input": payload}, task_id=task_id)

        result = data["productCreate"]
        errors = result.get("userErrors", [])

        if errors:
            self.shop.log_action(
                event="⚠️ shopify_product_create_errors",
                level="warning",
                data={"errors": errors},
                task_id=task_id
            )
            raise ShopifyGraphQLError(errors)

        product = result["product"]
        product_info = {
            "id": product["legacyResourceId"],
            "gid": product["id"],
            "handle": product.get("handle"),
            "url": product.get("onlineStoreUrl"),
            "variants": product.get("variants", {})  # includes edges
        }

        self.shop.log_action(
            event="✅ shopify_product_created",
            level="success",
            data=product_info,
            task_id=task_id
        )

        return product_info

    def update_variant_bulk(self, product_gid: str, variant_payload: dict, task_id=None) -> dict:
        variables = {
            "productId": product_gid,
            "variants": [variant_payload]
        }

        data = self._post_graphql(PRODUCT_VARIANTS_BULK_UPDATE_MUTATION, variables, task_id=task_id)

        result = data["productVariantsBulkUpdate"]
        errors = result.get("userErrors", [])

        if errors:
            self.shop.log_action(
                event="❌ shopify_variant_bulk_update_failed",
                level="error",
                data={"errors": errors},
                task_id=task_id
            )
            raise ShopifyGraphQLError(errors)

        self.shop.log_action(
            event="✅ shopify_variant_bulk_updated",
            level="success",
            data={"variants": result.get("productVariants", [])},
            task_id=task_id
        )

        return result["productVariants"]

    def get_collections(self, first: int = 100, task_id=None) -> list[dict]:
        variables = {"first": first}
        data = self._post_graphql(GET_COLLECTIONS_QUERY, variables, task_id=task_id)

        try:
            edges = data["collections"]["edges"]
            collections = [
                {
                    "id": edge["node"]["legacyResourceId"],  # REST ID
                    "gid": edge["node"]["id"],  # GraphQL ID
                    "title": edge["node"]["title"],
                    "handle": edge["node"]["handle"]
                }
                for edge in edges
            ]
            self.shop.log_action(
                event="✅ shopify_collections_fetched",
                level="info",
                data={"count": len(collections)},
                task_id=task_id
            )
            return collections
        except Exception as e:
            self.shop.log_action(
                event="❌ shopify_collections_fetch_failed",
                level="error",
                data={"error": str(e)},
                task_id=task_id
            )
            raise

    def get_install_url(self) -> str:
        shopify.Session.setup(api_key=SHOPIFY_API_KEY, secret=SHOPIFY_API_SECRET)
        session = shopify.Session(self.domain, SHOPIFY_API_VERSION)
        scopes = self.get_scopes()
        return session.create_permission_url(scopes, self.get_callback_url())

    def get_callback_url(self) -> str:
        return f"{APP_BASE_URL}/auth/shopify/callback"

    def get_scopes(self) -> list:
        return self.get_default_scopes()

    @staticmethod
    def generate_install_url(shop_domain: str) -> str:
        """
        Generates the Shopify install URL for OAuth flow, using static scopes and redirect URI.
        """
        import shopify
        shopify.Session.setup(api_key=SHOPIFY_API_KEY, secret=SHOPIFY_API_SECRET)
        session = shopify.Session(shop_domain, SHOPIFY_API_VERSION)
        scopes = ShopifyClient.get_default_scopes()
        redirect_uri = f"{APP_BASE_URL}/auth/shopify/callback"
        return session.create_permission_url(scopes, redirect_uri)


    def exchange_token(self, params: dict) -> str:
        shopify.Session.setup(api_key=SHOPIFY_API_KEY, secret=SHOPIFY_API_SECRET)
        session = shopify.Session(self.domain, SHOPIFY_API_VERSION)
        token = session.request_token(params)
        shopify.ShopifyResource.activate_session(session)
        return token

    def fetch_access_scopes(self) -> list:
        try:
            scopes = [s.attributes["handle"] for s in shopify.AccessScope.find()]
        except Exception:
            scopes = []
        return scopes

    def register_webhooks(self, task_id=None) -> bool:
        """
        Registers essential Shopify webhooks for the app.
        - Validates APP_BASE_URL
        - Deletes outdated webhooks (same topic but different address)
        - Registers new webhooks if missing
        """
        import shopify
        from core.config import APP_BASE_URL

        if not APP_BASE_URL or not isinstance(APP_BASE_URL, str):
            self.shop.log_action("webhook_config_error", "error", {
                "message": "❌ APP_BASE_URL is missing or invalid."
            }, task_id=task_id)
            raise ValueError("APP_BASE_URL is not set.")

        parsed = urlparse(APP_BASE_URL)
        if not parsed.scheme or not parsed.netloc:
            self.shop.log_action("webhook_config_error", "error", {
                "message": f"❌ APP_BASE_URL is malformed: {APP_BASE_URL}"
            }, task_id=task_id)
            raise ValueError("APP_BASE_URL must be a valid URL.")

        # Validate token
        if not self.token:
            self.shop.log_action("webhook_token_missing", "error", {
                "message": "❌ Cannot register webhooks — access token is missing.",
                "shop": self.shop.domain
            }, task_id=task_id)
            return False

        topics = [
            "app/uninstalled",
            # Note, we are updating collections before each run of adding products so no need for this. More reliable the new way
            # "collections/create",
            # "collections/update",
            # "collections/delete",
            "products/delete",
        ]

        success = True
        registered = []

        try:
            shopify.ShopifyResource.activate_session(
                shopify.Session(self.domain, SHOPIFY_API_VERSION, self.token)
            )

            existing_hooks = shopify.Webhook.find()

            for topic in topics:
                target_url = f"{APP_BASE_URL}/webhooks/shopify/{topic}"

                matched_hook = next((hook for hook in existing_hooks if hook.topic == topic), None)

                if matched_hook:
                    if matched_hook.address != target_url:
                        try:
                            matched_hook.destroy()
                            self.shop.log_action("webhook_deleted_existing", "info", {
                                "topic": topic,
                                "webhook_id": matched_hook.id,
                                "previous_address": matched_hook.address,
                                "created_at": getattr(matched_hook, "created_at", None),
                                "message": "💥 Deleted existing webhook due to address mismatch."
                            }, task_id=task_id)
                        except Exception as delete_err:
                            self.shop.log_action("webhook_delete_failed", "warning", {
                                "topic": topic,
                                "webhook_id": matched_hook.id,
                                "error": str(delete_err)
                            }, task_id=task_id)
                            success = False
                            continue
                    else:
                        self.shop.log_action("webhook_already_exists", "debug", {
                            "topic": topic,
                            "address": target_url
                        }, task_id=task_id)
                        continue

                # Create new webhook
                webhook = shopify.Webhook.create({
                    "topic": topic,
                    "address": target_url,
                    "format": "json"
                })

                if webhook.errors:
                    try:
                        raw_errors = webhook.errors.full_messages()
                        errors = [str(e) for e in raw_errors if e is not None]
                    except Exception as err:
                        self.shop.log_action("webhook_errors_structure_debug", "debug", {
                            "topic": topic,
                            "raw_errors_type": str(type(webhook.errors)),
                            "raw_errors_dir": dir(webhook.errors),
                            "raw_errors_dict": getattr(webhook.errors, 'errors', 'Unavailable'),
                            "exception": str(err)
                        }, task_id=task_id)
                        errors = [f"⚠️ full_messages() failed: {err}"]

                    self.shop.log_action("webhook_register_failed", "warning", {
                        "topic": topic,
                        "errors": errors
                    }, task_id=task_id)
                    success = False
                else:
                    self.shop.log_action("webhook_registered", "info", {
                        "topic": topic,
                        "address": target_url,
                        "webhook_id": webhook.id,
                        "message": f"📬 Webhook '{topic}' registered."
                    }, task_id=task_id)
                    registered.append({"topic": topic, "address": target_url})

        except Exception as e:
            import traceback

            # Capture traceback in log-friendly string
            trace = traceback.format_exc()

            self.shop.log_action("webhook_register_exception", "error", {
                "message": "❌ Error registering webhooks.",
                "error_type": type(e).__name__,
                "error_str": str(e),
                "traceback": trace
            }, task_id=task_id)
            success = False
        finally:
            shopify.ShopifyResource.clear_session()

        if registered:
            self.shop.log_action("webhooks_registered_summary", "info", {
                "registered_webhooks": registered
            }, task_id=task_id)

        return success

    def add_product_to_collection(self, collection_id: str, product_ids: list[str], product_gids: list[str], task_id=None) -> dict:
        variables = {
            "id": collection_id,
            "productIds": product_gids
        }

        data = self._post_graphql(COLLECTION_ADD_PRODUCTS_MUTATION, variables, task_id=task_id)

        result = data["collectionAddProducts"]
        errors = result.get("userErrors", [])

        if errors:
            self.shop.log_action(
                event="❌ shopify_collection_add_failed",
                level="error",
                data={"errors": errors},
                task_id=task_id
            )
            raise ShopifyGraphQLError(errors)

        collection_info = result.get("collection", {})
        self.shop.log_action(
            event="✅ shopify_product_added_to_collection",
            level="info",
            data={"collection_id": collection_info.get("id"), "collection_title": collection_info.get("title")},
            task_id=task_id
        )
        return collection_info

    def create_collection(self, title: str, task_id=None) -> dict:
        variables = {"input": {"title": title}}

        data = self._post_graphql(COLLECTION_CREATE_MUTATION, variables, task_id=task_id)
        result = data["collectionCreate"]
        errors = result.get("userErrors", [])

        if errors:
            self.shop.log_action("❌ shopify_create_collection_failed", "error", {"errors": errors}, task_id=task_id)
            raise ShopifyGraphQLError(errors)

        collection = result["collection"]
        self.shop.log_action("✅ shopify_collection_created", "info", {
            "title": collection["title"],
            "id": str(collection.get("legacyResourceId")),
            "gid": collection["id"],
        }, task_id=task_id)

        return {
            "id": str(collection.get("legacyResourceId")),
            "gid": collection["id"],
            "title": collection["title"],
            "handle": collection["handle"]
        }
