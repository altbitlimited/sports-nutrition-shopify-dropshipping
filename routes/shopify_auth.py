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
from core.MongoManager import MongoManager
from core.Logger import AppLogger

router = APIRouter(prefix="/auth/shopify")
mongo = MongoManager()
logger = AppLogger(mongo)

DEFAULT_SETTINGS = {}


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
    scopes = ["read_products", "write_products"]  # Add more as needed

    permission_url = session.create_permission_url(scopes, redirect_uri)
    logger.log("install_redirect", {"redirect_uri": redirect_uri}, store=shop)

    return RedirectResponse(permission_url)


@router.get("/callback")
def callback(request: Request):
    """
    Handles Shopify OAuth callback, verifies and stores access token and granted scopes.
    Detects scope changes on re-installation.
    """
    params = dict(request.query_params)
    shop = params.get("shop")

    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    shopify.Session.setup(api_key=SHOPIFY_API_KEY, secret=SHOPIFY_API_SECRET)

    try:
        session = shopify.Session(shop, SHOPIFY_API_VERSION)
        token = session.request_token(params)
    except Exception as e:
        logger.log("oauth_failed", {"error": str(e)}, store=shop, level="error")
        raise HTTPException(status_code=400, detail=f"OAuth verification failed: {str(e)}")

    # Activate session and fetch scopes
    shopify.ShopifyResource.activate_session(session)
    try:
        scopes = [scope.attributes["handle"] for scope in AccessScope.find()]
    except Exception as e:
        logger.log("scope_fetch_failed", {"error": str(e)}, store=shop, level="warn")
        scopes = []

    # Compare with existing scopes if shop already exists
    existing_shop = mongo.get_shop_by_domain(shop)
    previous_scopes = existing_shop.get("scopes") if existing_shop else None

    if previous_scopes and set(previous_scopes) != set(scopes):
        logger.log("scope_changed", {
            "previous": previous_scopes,
            "current": scopes
        }, store=shop)

    # Save token and settings
    mongo.save_shop_token(shop, token, scopes)
    mongo.update_shop_settings(shop, DEFAULT_SETTINGS)
    logger.log("shop_installed", {
        "token_saved": True,
        "scopes": scopes,
        "settings": DEFAULT_SETTINGS
    }, store=shop)

    # Register uninstall webhook
    uninstall_webhook = shopify.Webhook.create({
        "topic": "app/uninstalled",
        "address": f"{APP_BASE_URL}/webhooks/shopify/uninstalled",
        "format": "json"
    })

    if uninstall_webhook.errors:
        errors = uninstall_webhook.errors.full_messages()
        logger.log("webhook_failed", {"errors": errors}, store=shop, level="warn")
        webhook_success = False
    else:
        logger.log("webhook_registered", {"topic": "app/uninstalled"}, store=shop)
        webhook_success = True

    shopify.ShopifyResource.clear_session()

    return {
        "message": "App installed successfully.",
        "shop": shop,
        "token_saved": True,
        "settings_initialized": True,
        "webhook_registered": webhook_success
    }
