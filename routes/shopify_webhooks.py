from fastapi import APIRouter, Request, Header, HTTPException
from core.config import SHOPIFY_API_SECRET
from core.MongoManager import MongoManager
from core.Logger import AppLogger
import hmac
import hashlib
import base64

router = APIRouter(prefix="/webhooks/shopify")
mongo = MongoManager()
logger = AppLogger(mongo)


def verify_webhook_hmac(hmac_header: str, raw_body: bytes) -> bool:
    calculated_hmac = base64.b64encode(
        hmac.new(
            SHOPIFY_API_SECRET.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).digest()
    ).decode()

    return hmac.compare_digest(calculated_hmac, hmac_header)


@router.post("/uninstalled")
async def app_uninstalled(
    request: Request,
    x_shopify_hmac_sha256: str = Header(None),
    x_shopify_shop_domain: str = Header(None)
):
    raw_body = await request.body()

    if not verify_webhook_hmac(x_shopify_hmac_sha256, raw_body):
        logger.log("webhook_invalid_hmac", {"raw": raw_body.decode()}, level="warn")
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    if not x_shopify_shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop domain")

    # Clean up shop data
    mongo.shops.delete_one({"shop": x_shopify_shop_domain})
    mongo.logs.delete_many({"store": x_shopify_shop_domain})  # ← delete logs
    logger.log("shop_uninstalled", {"action": "shop and logs deleted"}, store=x_shopify_shop_domain)

    return {"status": "ok", "message": f"Shop {x_shopify_shop_domain} deleted"}