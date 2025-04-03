# core/helpers/shopify_auth.py

import shopify
from core.config import SHOPIFY_API_KEY, SHOPIFY_API_SECRET, SHOPIFY_API_VERSION

def exchange_token_and_scopes(shop_domain: str, params: dict) -> tuple[str, list[str]]:
    """
    Exchanges the temporary auth code for an access token and fetches granted scopes.
    """
    shopify.Session.setup(api_key=SHOPIFY_API_KEY, secret=SHOPIFY_API_SECRET)
    session = shopify.Session(shop_domain, SHOPIFY_API_VERSION)
    token = session.request_token(params)
    shopify.ShopifyResource.activate_session(session)

    try:
        scopes = [s.attributes["handle"] for s in shopify.AccessScope.find()]
    except Exception:
        scopes = []

    shopify.ShopifyResource.clear_session()
    return token, scopes
