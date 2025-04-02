# routes/shopify_auth.py

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from core.Logger import AppLogger
from core.shops import Shops
from core.shop import Shop
from core.config import APP_BASE_URL

router = APIRouter(prefix="/auth/shopify")
logger = AppLogger()
shops = Shops()

@router.get("/install")
def install(shop: str):
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    shop_instance = Shop(shop)
    client = shop_instance.client

    redirect_uri = f"{APP_BASE_URL}/auth/shopify/callback"
    scopes = client.get_scopes()
    permission_url = client.get_install_url(scopes, redirect_uri)

    logger.log(
        event="install_redirect",
        level="info",
        store=shop,
        data={
            "redirect_uri": redirect_uri,
            "scopes": scopes,
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
        shop_instance = Shop(shop_domain)  # reload with saved record
        client = shop_instance.client

        token = client.exchange_token(params)
        scopes = client.fetch_access_scopes()

        previous_scopes = shop_instance.shop.get("scopes", [])
        if previous_scopes and set(previous_scopes) != set(scopes):
            shop_instance.log_action(
                event="scope_changed",
                level="info",
                data={
                    "message": "🔁 OAuth scope changed.",
                    "previous": previous_scopes,
                    "current": scopes
                }
            )

        shop_instance.set_access_token(token, scopes)
        shop_instance.update_settings(Shop.DEFAULT_SETTINGS)

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

        success = client.register_webhooks()

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
