# core/clients/shopify_client.py

import time
import requests
import mimetypes
from typing import Dict, Any

from core.config import SHOPIFY_API_KEY, SHOPIFY_API_SECRET, SHOPIFY_API_VERSION, APP_BASE_URL
from core.shopify_graphql.mutations import (
    PRODUCT_CREATE_MUTATION,
    STAGED_UPLOADS_CREATE_MUTATION,
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
        from core.shop import Shop  # moved here to avoid circular import
        if not isinstance(shop, Shop):
            raise TypeError("Expected a Shop instance")
        self.shop = shop
        self.domain = shop.domain
        self.token = shop.get_access_token()
        self.endpoint = f"https://{self.domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.token,
        }

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

    def upload_image(self, image_url: str, task_id=None) -> str:
        filename = image_url.split("/")[-1]
        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "image/jpeg"  # fallback

        variables = {
            "input": [{
                "filename": filename,
                "mimeType": mime_type,
                "resource": "IMAGE",
                "url": image_url,
            }]
        }

        data = self._post_graphql(STAGED_UPLOADS_CREATE_MUTATION, variables, task_id=task_id)

        try:
            resource_url = data["stagedUploadsCreate"]["stagedTargets"][0]["resourceUrl"]
            self.shop.log_action(
                event="🖼️ shopify_image_uploaded",
                level="info",
                data={"original_url": image_url, "shopify_url": resource_url, "mime_type": mime_type},
                task_id=task_id
            )
            return resource_url
        except Exception as e:
            self.shop.log_action(
                event="❌ shopify_upload_image_failed",
                level="error",
                data={"error": str(e), "image_url": image_url, "mime_type": mime_type},
                task_id=task_id
            )
            raise

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
            "id": product["id"],
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

    def update_variant_bulk(self, product_id: str, variant_payload: dict, task_id=None) -> dict:
        variables = {
            "productId": product_id,
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
                    "id": edge["node"]["id"],
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
        return ["read_products", "write_products"]

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
        """
        topics = [
            "app/uninstalled",
            "collections/create",
            "collections/update",
            "collections/delete",
            "products/delete",
        ]

        success = True

        for topic in topics:
            webhook_data = {
                "topic": topic,
                "address": f"{APP_BASE_URL}/webhooks/shopify/{topic}",
                "format": "json"
            }

            try:
                import shopify
                shopify.ShopifyResource.activate_session(shopify.Session(self.domain, SHOPIFY_API_VERSION, self.token))
                webhook = shopify.Webhook.create(webhook_data)

                if webhook.errors:
                    errors = webhook.errors.full_messages()
                    self.shop.log_action(
                        event="webhook_register_failed",
                        level="warning",
                        data={"topic": topic, "errors": errors}
                    )
                    success = False
                else:
                    self.shop.log_action(
                        event="webhook_registered",
                        level="info",
                        data={"topic": topic, "message": f"📬 Webhook '{topic}' registered."}
                    )
            except Exception as e:
                self.shop.log_action(
                    event="webhook_register_exception",
                    level="error",
                    data={"topic": topic, "error": str(e)}
                )
                success = False
            finally:
                shopify.ShopifyResource.clear_session()

        return success

    def add_product_to_collection(self, collection_id: str, product_ids: list[str], task_id=None) -> dict:
        variables = {
            "id": collection_id,
            "productIds": product_ids
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
            "id": collection["id"]
        }, task_id=task_id)

        return collection
