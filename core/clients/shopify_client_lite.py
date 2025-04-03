import shopify

from core.config import SHOPIFY_API_KEY, SHOPIFY_API_SECRET, SHOPIFY_API_VERSION


class ShopifyClientLite:
    """
    Lightweight Shopify client used during OAuth before token is available.
    Only supports token exchange and access scope fetching.
    """

    def __init__(self, domain: str):
        if not domain:
            raise ValueError("Shop domain is required for ShopifyClientLite.")

        self.domain = domain
        self.api_key = SHOPIFY_API_KEY
        self.api_secret = SHOPIFY_API_SECRET
        self.api_version = SHOPIFY_API_VERSION

        shopify.Session.setup(api_key=self.api_key, secret=self.api_secret)
        self.session = shopify.Session(self.domain, self.api_version)

    def exchange_token(self, params: dict) -> str:
        """
        Exchange authorization code for permanent access token.
        """
        return self.session.request_token(params)

    def fetch_access_scopes(self) -> list:
        """
        Fetch access scopes granted to the app.
        """
        shopify.ShopifyResource.activate_session(self.session)
        try:
            scopes = [s.attributes["handle"] for s in shopify.AccessScope.find()]
        except Exception:
            scopes = []
        finally:
            shopify.ShopifyResource.clear_session()

        return scopes
