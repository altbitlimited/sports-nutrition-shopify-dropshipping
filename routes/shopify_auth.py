# routes/shopify_auth.py

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from core.Logger import AppLogger
from core.shops import Shops
from core.shop import Shop
from core.config import SHOPIFY_API_KEY, SHOPIFY_API_SECRET, SHOPIFY_API_VERSION, APP_BASE_URL
from core.clients.shopify_client import ShopifyClient
from core.clients.shopify_client_lite import ShopifyClientLite
from core.helpers.shopify_auth import exchange_token_and_scopes

router = APIRouter(prefix="/auth/shopify")
logger = AppLogger()
shops = Shops()


@router.get("/install")
def install(shop: str):
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    permission_url = ShopifyClient.generate_install_url(shop)

    logger.log(
        event="install_redirect",
        level="info",
        store=shop,
        data={
            "redirect_uri": f"{APP_BASE_URL}/auth/shopify/callback",
            "scopes": ShopifyClient.get_default_scopes(),
            "message": "🔗 Redirecting merchant to install screen."
        }
    )

    return RedirectResponse(permission_url)


@router.get("/callback")
def callback(request: Request):
    params = dict(request.query_params)
    shop_domain = params.get("shop")
    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    try:
        shop_instance = shops.get_by_domain(shop_domain) or shops.add_new_shop(shop_domain)

        # ✅ Use lite client to exchange token without requiring access token
        temp_client = ShopifyClientLite(shop_domain)

        token = temp_client.exchange_token(params)
        scopes = temp_client.fetch_access_scopes()

        # ✅ Reload shop after saving token to ensure fresh data
        shop_instance.set_access_token(token, scopes)
        shop_instance.update_settings(Shop.DEFAULT_SETTINGS)
        shop_instance.reload()

        # ✅ Now safe to use full client with token
        client = shop_instance.client
        success = client.register_webhooks()
        shop_instance.update_collections()
        shop_instance.update_primary_location_id()

        shop_instance.log_action(
            event="shop_installed",
            level="success",
            data={
                "message": "✅ App installed successfully.",
                "token_saved": True,
                "scopes": scopes,
                "settings": Shop.DEFAULT_SETTINGS
            }
        )

        return {
            "message": "App installed successfully.",
            "shop": shop_domain,
            "token_saved": True,
            "settings_initialized": True,
            "webhook_registered": success
        }

    except Exception as e:
        logger.log(
            event="❌ shopify_auth_callback_error",
            level="error",
            store=shop_domain,
            data={"error": str(e)}
        )
        raise HTTPException(status_code=500, detail=f"OAuth flow failed: {str(e)}")
