from fastapi import APIRouter, Request, Header, HTTPException
import hmac
import hashlib
import base64

from core.config import SHOPIFY_API_SECRET
from core.shop import Shop
from core.shops import Shops
from core.Logger import AppLogger

router = APIRouter(prefix="/webhooks/shopify")
logger = AppLogger()
shops = Shops()


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
        logger.log(
            event="webhook_invalid_hmac",
            level="warning",
            data={
                "message": "⚠️ Invalid HMAC received from Shopify.",
                "raw": raw_body.decode()
            }
        )
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    if not x_shopify_shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop domain")

    # Load the shop
    shop = shops.get_by_domain(x_shopify_shop_domain)
    if shop:
        shops.delete_shop(x_shopify_shop_domain)  # Deletes shop and logs automatically
    else:
        logger.log(
            event="uninstall_unknown_shop",
            level="warning",
            store=x_shopify_shop_domain,
            data={"message": "⚠️ Uninstall webhook received for unknown shop."}
        )

    return {"status": "ok", "message": f"Shop {x_shopify_shop_domain} deleted"}
