from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
import shopify
from shopify import AccessScope

from core.config import (
    SHOPIFY_API_KEY,
    SHOPIFY_API_SECRET,
    SHOPIFY_API_VERSION,
    APP_BASE_URL,
)

from core.Logger import AppLogger
from core.shop import Shop
from core.shops import Shops

router = APIRouter(prefix="/auth/shopify")

logger = AppLogger()
shops = Shops()

DEFAULT_SETTINGS = {}  # Could eventually hold initial setup values


@router.get("/install")
def install(shop: str):
    """
    Redirects merchant to Shopify install screen.
    """
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    shopify.Session.setup(api_key=SHOPIFY_API_KEY, secret=SHOPIFY_API_SECRET)
    session = shopify.Session(shop, SHOPIFY_API_VERSION)

    redirect_uri = f"{APP_BASE_URL}/auth/shopify/callback"
    scopes = ["read_products", "write_products"]

    permission_url = session.create_permission_url(scopes, redirect_uri)

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
    """
    Handles Shopify OAuth callback, verifies and stores access token and granted scopes.
    Detects scope changes on re-installation.
    """
    params = dict(request.query_params)
    shop_domain = params.get("shop")

    if not shop_domain:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    shopify.Session.setup(api_key=SHOPIFY_API_KEY, secret=SHOPIFY_API_SECRET)

    try:
        session = shopify.Session(shop_domain, SHOPIFY_API_VERSION)
        token = session.request_token(params)
    except Exception as e:
        logger.log(
            event="oauth_failed",
            level="error",
            store=shop_domain,
            data={"error": str(e), "message": "❌ OAuth verification failed."}
        )
        raise HTTPException(status_code=400, detail=f"OAuth verification failed: {str(e)}")

    shopify.ShopifyResource.activate_session(session)

    try:
        scopes = [scope.attributes["handle"] for scope in AccessScope.find()]
    except Exception as e:
        logger.log(
            event="scope_fetch_failed",
            level="warning",
            store=shop_domain,
            data={"error": str(e), "message": "⚠️ Could not fetch access scopes."}
        )
        scopes = []

    # Create shop in DB if not exists
    shop_instance = shops.get_by_domain(shop_domain)
    if not shop_instance:
        shop_instance = shops.add_new_shop(shop_domain)

    # Detect scope changes
    previous_scopes = shop_instance.get_scopes()
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

    # Save token and scopes
    shop_instance.set_token(token)
    shop_instance.set_scopes(scopes)
    shop_instance.set_settings(DEFAULT_SETTINGS)

    shop_instance.log_action(
        event="shop_installed",
        level="success",
        data={
            "message": "✅ App installed successfully.",
            "token_saved": True,
            "scopes": scopes,
            "settings": DEFAULT_SETTINGS
        }
    )

    # Register uninstall webhook
    uninstall_webhook = shopify.Webhook.create({
        "topic": "app/uninstalled",
        "address": f"{APP_BASE_URL}/webhooks/shopify/uninstalled",
        "format": "json"
    })

    if uninstall_webhook.errors:
        errors = uninstall_webhook.errors.full_messages()
        shop_instance.log_action(
            event="webhook_failed",
            level="warning",
            data={"errors": errors, "message": "⚠️ Failed to register uninstall webhook."}
        )
        webhook_success = False
    else:
        shop_instance.log_action(
            event="webhook_registered",
            level="info",
            data={"topic": "app/uninstalled", "message": "📬 Uninstall webhook registered."}
        )
        webhook_success = True

    shopify.ShopifyResource.clear_session()

    return {
        "message": "App installed successfully.",
        "shop": shop_domain,
        "token_saved": True,
        "settings_initialized": True,
        "webhook_registered": webhook_success
    }
