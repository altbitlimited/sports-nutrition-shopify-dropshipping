import shopify
import requests
import base64
import time

class ShopifyManager:
    def __init__(self, shop_url, api_version, access_token, db_connection=None):
        """
        Initialize the ShopifyManager with store credentials and optional DB connection.

        Args:
            shop_url (str): The full Shopify store URL.
            api_version (str): API version (e.g. '2023-10').
            access_token (str): Admin API access token.
            db_connection (optional): Object to interface with a local DB (e.g. for category descriptions).
        """
        self.shop_url = shop_url
        self.api_version = api_version
        self.access_token = access_token
        self.db = db_connection
        self.category_body_cache = {}  # Cache category descriptions to reduce DB calls
        self._activate_session()

    def _activate_session(self):
        """
        Activates a Shopify session so API calls are authenticated and scoped to this store.
        """
        session = shopify.Session(self.shop_url, self.api_version, self.access_token)
        shopify.ShopifyResource.activate_session(session)

    def close_session(self):
        """
        Clears the Shopify session (to be called when you're done).
        """
        shopify.ShopifyResource.clear_session()

    def _throttle_if_necessary(self):
        """
        Shopify allows a limited number of API calls per second (default: 2/sec, 40 in burst).
        This method reads headers to pause the app before exceeding limits.
        """
        response = shopify.ShopifyResource.connection.response
        if not response or not hasattr(response, "headers"):
            time.sleep(0.6)
            return

        headers = response.headers
        used, limit = map(int, headers.get("X-Shopify-Shop-Api-Call-Limit", "0/40").split("/"))
        if used >= limit - 2:
            print(f"⏳ Throttling: {used}/{limit} used. Waiting 1.5s.")
            time.sleep(1.5)

        time.sleep(0.6)  # Standard delay for good measure

    def _safe_shopify_call(self, call_fn, *args, **kwargs):
        """
        Wraps Shopify API calls with retries and throttling logic to gracefully handle rate limits.

        Args:
            call_fn: The callable API method (e.g. product.save).
        """
        for attempt in range(5):
            try:
                self._throttle_if_necessary()
                return call_fn(*args, **kwargs)
            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    print(f"⚠️ Rate limit hit, retrying in 2 seconds (attempt {attempt+1})")
                    time.sleep(2)
                    continue
                raise e
        raise Exception("❌ Max retries exceeded")

    def create_product(self, title, body_html="", vendor="", tags=None,
                       image_urls=None, seo_title=None, seo_description=None,
                       category_names=None, inventory_quantity=None, price=None,
                       cost=None, sku=None, barcode=None):
        """
        Creates a new product in Shopify with optional metadata, images, and category assignments.
        """
        product = shopify.Product()
        product.title = title
        product.body_html = body_html
        product.vendor = vendor
        product.tags = tags or []

        if seo_title:
            product.metafields_global_title_tag = seo_title
        if seo_description:
            product.metafields_global_description_tag = seo_description

        # Attach images
        if image_urls:
            product.images = [self._download_and_encode_image(url) for url in image_urls]

        # Save the product
        if not self._safe_shopify_call(product.save):
            raise Exception(f"Failed to create product: {product.errors.full_messages()}")

        # Add to collections (categories)
        if category_names:
            self._add_to_collections(product.id, category_names, product)

        # Set variant details and inventory
        self._set_variant_details(product, price, cost, sku, barcode)

        if inventory_quantity is not None:
            self._set_initial_inventory(product, inventory_quantity)

        return product.to_dict()

    def update_product(self, product_id, **fields):
        """
        Updates an existing Shopify product with any provided fields.
        """
        product = shopify.Product.find(product_id)

        # Update top-level product fields
        if "title" in fields:
            product.title = fields["title"]
        if "body_html" in fields:
            product.body_html = fields["body_html"]
        if "vendor" in fields:
            product.vendor = fields["vendor"]
        if "tags" in fields:
            product.tags = fields["tags"]
        if "seo_title" in fields:
            product.metafields_global_title_tag = fields["seo_title"]
        if "seo_description" in fields:
            product.metafields_global_description_tag = fields["seo_description"]
        if "image_urls" in fields:
            product.images = [self._download_and_encode_image(url) for url in fields["image_urls"]]

        if not self._safe_shopify_call(product.save):
            raise Exception(f"Failed to update product: {product.errors.full_messages()}")

        if "category_names" in fields:
            self._add_to_collections(product.id, fields["category_names"], product)

        self._set_variant_details(
            product,
            price=fields.get("price"),
            cost=fields.get("cost"),
            sku=fields.get("sku"),
            barcode=fields.get("barcode")
        )

        if "inventory_quantity" in fields:
            self._set_initial_inventory(product, fields["inventory_quantity"])

        return product.to_dict()

    def _set_variant_details(self, product, price, cost, sku, barcode):
        """
        Sets variant-level data like price, cost, SKU, and barcode.
        """
        variant = product.variants[0]

        if price is not None:
            variant.price = str(price)
        if cost is not None:
            variant.cost = str(cost)
        if sku is not None:
            variant.sku = sku
        if barcode is not None:
            variant.barcode = barcode

        variant.inventory_management = "shopify"

        if not self._safe_shopify_call(variant.save):
            raise Exception(f"Failed to update variant: {variant.errors.full_messages()}")

    def _set_initial_inventory(self, product, quantity):
        """
        Assigns an initial inventory quantity to the product.
        """
        variant = product.variants[0]
        inventory_item_id = variant.inventory_item_id

        locations = shopify.Location.find()
        if not locations:
            raise Exception("No locations found for this shop.")
        location_id = locations[0].id

        inventory_level = self._safe_shopify_call(
            shopify.InventoryLevel.set,
            location_id=location_id,
            inventory_item_id=inventory_item_id,
            available=quantity
        )
        return inventory_level.to_dict()

    def _add_to_collections(self, product_id, category_names, product):
        """
        Adds a product to custom collections (which function like categories).
        """
        for name in category_names:
            collection = self._get_or_create_custom_collection(name)
            self._safe_shopify_call(shopify.Collect.create, {
                "product_id": product_id,
                "collection_id": collection.id
            })

    def _get_or_create_custom_collection(self, name):
        """
        Looks for a custom collection by name. If not found, creates it (optionally with a description).
        """
        collections = shopify.CustomCollection.find(title=name)
        if collections:
            collection = collections[0]
        else:
            collection = shopify.CustomCollection()
            collection.title = name

            # Try to pull description from DB and cache it
            category_body = self.category_body_cache.get(name)

            if category_body is None and self.db:
                category_body = self.db.category_get_body_by_name(name)
                self.category_body_cache[name] = category_body

                if category_body is not None:
                    collection.body_html = category_body

            if not self._safe_shopify_call(collection.save):
                raise Exception(f"Failed to create collection: {collection.errors.full_messages()}")

        return collection

    def _download_and_encode_image(self, url):
        """
        Downloads an image and base64-encodes it for the Shopify API.
        """
        response = requests.get(url)
        if response.status_code != 200:
            raise Exception(f"Failed to download image from {url}")
        encoded = base64.b64encode(response.content).decode("utf-8")
        return {"attachment": encoded}
