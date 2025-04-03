from fastapi import APIRouter, Request, Header, HTTPException
import hmac, hashlib, base64
from datetime import datetime
from core.config import SHOPIFY_API_SECRET
from core.shops import Shops
from core.shop import Shop
from core.Logger import AppLogger
from core.MongoManager import MongoManager
mongo = MongoManager()

router = APIRouter(prefix="/webhooks/shopify")
logger = AppLogger()
shops = Shops()

# --- HMAC Verification ---

def verify_hmac(hmac_header: str, body: bytes) -> bool:
    digest = hmac.new(SHOPIFY_API_SECRET.encode(), body, hashlib.sha256).digest()
    calc_hmac = base64.b64encode(digest).decode()
    return hmac.compare_digest(calc_hmac, hmac_header)

# --- Webhook Topic Handlers ---

async def handle_app_uninstalled(shop_domain: str, payload: dict):
    shop = Shop(shop_domain)
    if shop:
        shops.delete_shop(shop_domain)
        logger.log(
            event="shop_deleted_via_uninstall",
            data={"message": "🧹 Shop deleted after uninstall webhook."},
            store=shop_domain,
            level="info"
        )
    else:
        logger.log(
            event="uninstall_unknown_shop",
            data={"message": "⚠️ Uninstall webhook received for unknown shop."},
            store=shop_domain,
            level="warning"
        )

async def handle_collection_created(shop_domain: str, payload: dict):
    shop = Shop(shop_domain)
    collection = {
        "id": str(payload["id"]),
        "gid": payload["admin_graphql_api_id"],
        "title": payload.get("title"),
        "handle": payload.get("handle"),
    }

    added = shop.add_local_collection(collection)

    if added:
        shop.log_action(
            event="collection_created_webhook",
            level="info",
            data={"collection": collection, "message": "📦 Collection created via webhook."}
        )


async def handle_collection_updated(shop_domain: str, payload: dict):
    shop = Shop(shop_domain)
    updated_data = {
        "id": str(payload["id"]),
        "gid": payload["admin_graphql_api_id"],
        "title": payload.get("title"),
        "handle": payload.get("handle"),
    }

    if shop.update_local_collection(updated_data):
        shop.log_action(
            event="collection_updated_webhook",
            level="info",
            data={
                "collection": updated_data,
                "message": "♻️ Collection updated via webhook."
            }
        )


async def handle_collection_deleted(shop_domain: str, payload: dict):
    shop = Shop(shop_domain)
    collection_id = str(payload.get("id"))

    if shop.remove_local_collection(collection_id):
        shop.log_action(
            event="collection_deleted_webhook",
            level="info",
            data={
                "collection_id": collection_id,
                "message": "🗑️ Collection deleted via webhook."
            }
        )

async def handle_product_deleted(shop_domain: str, payload: dict):
    from core.product import Product
    shop = Shop(shop_domain)
    product_id = str(payload.get("id"))

    if not product_id:
        return

    result = mongo.db.products.find_one(
        {"shops": {"$elemMatch": {"shop": shop.domain, "shopify_id": product_id}}},
        {"barcode": 1}
    )

    if not result:
        shop.log_action("product_delete_webhook_not_found", "warning", {
            "shopify_id": product_id,
            "message": "⚠️ Received delete webhook but could not find product by ID"
        })
        return

    product = Product(result["barcode"])

    product.mark_listed_to_shop(shop, {
        "status": "unmanaged",
        "message": "deleted_from_shopify"
    })

    shop.log_action("product_unmanaged_via_webhook", "info", {
        "barcode": product.barcode,
        "shopify_id": product_id,
        "message": "🛑 Product marked as unmanaged after Shopify deletion."
    })

# --- Webhook Topic Registry ---

WEBHOOK_HANDLERS = {
    "app/uninstalled": handle_app_uninstalled,
    # "collections/create": handle_collection_created,
    # "collections/update": handle_collection_updated,
    # "collections/delete": handle_collection_deleted,
    "products/delete": handle_product_deleted,
}

# --- Central Webhook Endpoint ---

@router.post("/{topic:path}")
async def handle_shopify_webhook(
    topic: str,
    request: Request,
    x_shopify_hmac_sha256: str = Header(None),
    x_shopify_shop_domain: str = Header(None)
):
    raw_body = await request.body()

    if not verify_hmac(x_shopify_hmac_sha256, raw_body):
        logger.log(
            event="webhook_invalid_hmac",
            data={"message": "⚠️ Invalid HMAC received from Shopify.", "raw": raw_body.decode()},
            level="warning"
        )
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    if not x_shopify_shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop domain")

    if topic not in WEBHOOK_HANDLERS:
        logger.log(
            event="webhook_topic_not_supported",
            data={"message": f"⚠️ Webhook topic not supported: {topic}"},
            store=x_shopify_shop_domain,
            level="warning"
        )
        raise HTTPException(status_code=400, detail=f"Unsupported webhook topic: {topic}")

    payload = await request.json()

    logger.log(
        event="webhook_received",
        level="debug",
        store=x_shopify_shop_domain,
        data={"topic": topic, "payload": payload}
    )

    await WEBHOOK_HANDLERS[topic](x_shopify_shop_domain, payload)

    return {"status": "ok", "message": f"✅ Webhook '{topic}' handled"}
