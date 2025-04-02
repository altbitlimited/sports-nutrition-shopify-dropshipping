# core/product.py

from core.MongoManager import MongoManager
from core.Logger import AppLogger
from datetime import datetime
from core.exceptions import ProductNotFoundError
from core.shop import Shop
from math import ceil, floor

mongo = MongoManager()
logger = AppLogger(mongo)

class Product:
    def __init__(self, barcode: str):
        self.barcode = barcode
        self.product = self.get_product()

    def get_product(self):
        try:
            product = mongo.db.products.find_one({"barcode": self.barcode})
            if not product:
                raise ProductNotFoundError(self.barcode)
            return product
        except Exception as e:
            self.log_action(
                event="mongodb_error",
                level="error",
                data={"message": f"Error fetching product: {str(e)}"}
            )
            raise

    def add_supplier(self, supplier_name, supplier_data, supplier_parsed_data):
        if not self.product:
            raise ProductNotFoundError(self.barcode)

        existing_suppliers = [s["name"] for s in self.product.get("suppliers", [])]
        if supplier_name not in existing_suppliers:
            self.product["suppliers"].append({
                "name": supplier_name,
                "data": supplier_data,
                "parsed": supplier_parsed_data
            })

            mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$set": {
                    "suppliers": self.product["suppliers"],
                    "updated_at": datetime.utcnow()
                }}
            )

            self.log_action(
                event="supplier_added",
                level="info",
                data={
                    "supplier_name": supplier_name,
                    "message": f"🔗 Supplier {supplier_name} added to product."
                }
            )
        else:
            self.log_action(
                event="supplier_already_exists",
                level="debug",
                data={
                    "supplier_name": supplier_name,
                    "message": f"Supplier {supplier_name} already linked to product."
                }
            )

    def prune_supplier_link(self, supplier_name):
        if not self.product:
            raise ProductNotFoundError(self.barcode)

        suppliers = [s for s in self.product.get("suppliers", []) if s["name"] != supplier_name]

        if len(suppliers) != len(self.product["suppliers"]):
            mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$set": {
                    "suppliers": suppliers,
                    "updated_at": datetime.utcnow()
                }}
            )

            self.log_action(
                event="supplier_removed",
                level="info",
                data={
                    "supplier_name": supplier_name,
                    "message": f"🪩 Supplier {supplier_name} removed from product."
                }
            )
        else:
            self.log_action(
                event="supplier_not_found",
                level="warning",
                data={
                    "supplier_name": supplier_name,
                    "message": f"⚠️ Supplier {supplier_name} not found in product."
                }
            )

    def update_product(self, barcode_lookup_data=None, barcode_lookup_status=None,
                       ai_generated_data=None, ai_generate_status=None,
                       image_urls=None, suppliers=None, images_status=None):
        if not self.product:
            raise ProductNotFoundError(self.barcode)

        update_data = {}

        if barcode_lookup_data is not None:
            update_data["barcode_lookup_data"] = barcode_lookup_data
        if barcode_lookup_status is not None:
            update_data["barcode_lookup_status"] = barcode_lookup_status
            update_data["barcode_lookup_at"] = datetime.utcnow()
        if ai_generated_data is not None:
            update_data["ai_generated_data"] = ai_generated_data
        if ai_generate_status is not None:
            update_data["ai_generate_status"] = ai_generate_status
            update_data["ai_generate_at"] = datetime.utcnow()
        if image_urls is not None:
            update_data["image_urls"] = image_urls
        if images_status is not None:
            update_data["images_status"] = images_status
            update_data["images_at"] = datetime.utcnow()
        if suppliers is not None:
            update_data["suppliers"] = suppliers

        update_data["updated_at"] = datetime.utcnow()

        try:
            result = mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$set": update_data}
            )

            if result.modified_count > 0:
                self.product.update(update_data)
                self.log_action(
                    event="product_updated",
                    level="success",
                    data={"message": "✅ Product updated successfully."}
                )
            else:
                self.log_action(
                    event="product_no_changes",
                    level="debug",
                    data={"message": "No changes made to product."}
                )
        except Exception as e:
            self.log_action(
                event="mongodb_error",
                level="error",
                data={"message": f"Database update failed: {str(e)}"}
            )
            raise Exception(f"Database operation failed: {str(e)}")

    def is_enriched_for_listing(self):
        data = self.product
        ai = data.get("ai_generated_data", {})
        lookup = data.get("barcode_lookup_data", {})

        required_fields = [
            ai.get("title"),
            ai.get("description"),
            ai.get("product_type"),
            lookup.get("brand") or lookup.get("manufacturer")
        ]

        is_valid = all(required_fields)
        if not is_valid:
            self.log_action(
                event="product_not_ready",
                level="debug",
                data={"message": "⚠️ Product is missing enrichment fields required for listing."}
            )

        return is_valid

    def is_product_eligible(self, shop: Shop) -> bool:
        if not all([
            self.product.get("barcode_lookup_status") == "success",
            self.product.get("images_status") == "success",
            self.product.get("ai_generate_status") == "success",
        ]):
            self.log_action(event="product_not_eligible_enrichment_incomplete", level="debug", data={"message": "⚠️ Enrichment incomplete."})
            return False

        if not self.product.get("image_urls"):
            self.log_action(event="product_not_eligible_missing_images", level="debug", data={"message": "🚫 No image URLs present."})
            return False

        brand = self.get_brand()

        if brand.lower() in shop.get_excluded_brands():
            self.log_action(event="product_not_eligible_excluded_brand", level="debug", data={"brand": brand, "message": "🚫 Brand excluded."})
            return False

        for supplier in self.product.get("suppliers", []):
            name = supplier.get("name")
            parsed = supplier.get("parsed", {})
            if name.lower() in shop.get_excluded_suppliers():
                continue
            if parsed.get("price", 0) > 0:
                return True

        self.log_action(event="product_not_eligible_no_valid_supplier", level="debug", data={"message": "🚫 No usable suppliers with stock and price."})
        return False

    def get_best_supplier_for_shop(self, shop: Shop, log_fallback = True):
        excluded = set(shop.get_excluded_suppliers())
        in_stock = []
        out_of_stock = []

        for supplier in self.product.get("suppliers", []):
            name = supplier.get("name")
            if name in excluded:
                continue

            parsed = supplier.get("parsed", {})
            price = parsed.get("price")
            stock = parsed.get("stock_level", 0)

            if price and price > 0:
                enriched = {"supplier_name": name, **parsed}
                if stock > 0:
                    in_stock.append(enriched)
                else:
                    out_of_stock.append(enriched)

        best = min(in_stock, key=lambda s: s["price"], default=None)
        if not best:
            best = min(out_of_stock, key=lambda s: s["price"], default=None)
            if best:
                if log_fallback:
                    self.log_action(
                        event="best_supplier_fallback_zero_stock",
                        level="debug",
                        data={
                            "supplier": best["supplier_name"],
                            "price": best["price"],
                            "stock_level": best["stock_level"],
                            "message": "⚠️ Falling back to zero stock supplier for best price."
                        }
                    )

        return best

    def get_selling_price_for_shop(self, shop: Shop):
        best_supplier = self.get_best_supplier_for_shop(shop, False)
        if not best_supplier:
            self.log_action(
                event="selling_price_not_found",
                level="debug",
                data={"message": "❌ No valid supplier found for price."}
            )
            return None

        margin = shop.get_setting("profit_margin", 1.5)
        rounding = shop.get_setting("rounding", 0.99)
        round_to = shop.get_setting("round_to", 'closest')
        base_price = best_supplier["price"] * margin
        # Round up to nearest integer, then adjust to end in specified decimal (e.g., .99)
        # Example: base_price 22.43, rounding 0.99 → 22 + 0.99 = 22.99

        if rounding:
            match round_to:
                case "up":
                    rounded_price = ceil(base_price) + rounding - 1
                case "down":
                    rounded_price = floor(base_price) + rounding - 1
                case _:
                    # Default case, will also catch 'closest'
                    rounded_price = round(base_price) + rounding - 1
        else:
            rounded_price = round(base_price, 2)

        self.log_action(
            event="selling_price_calculated",
            level="info",
            data={
                "message": "💲 Selling price calculated.",
                "best_supplier_price": best_supplier["price"],
                "margin": margin,
                "rounding": rounding,
                "round_to": round_to,
                "base_price": base_price,
                "rounded_price": rounded_price,
            }
        )

        return round(rounded_price, 2)

    def get_stock_level_for_shop(self, shop: Shop) -> int:
        """
        Determines the stock level for the best supplier for this product
        based on the shop's settings (exclusions, stock availability, etc.).
        """
        best_supplier = self.get_best_supplier_for_shop(shop, False)

        if not best_supplier:
            self.log_action(
                event="stock_level_not_found",
                level="debug",
                data={"message": "❌ No valid supplier found for stock level."}
            )
            return 0

        stock_level = best_supplier.get("stock_level", 0)
        self.log_action(
            event="stock_level_fetched",
            level="debug",
            data={
                "supplier": best_supplier.get("supplier_name"),
                "stock_level": stock_level,
                "message": f"📦 Stock level from best supplier: {stock_level}"
            }
        )
        return stock_level

    def has_been_listed_to_shop(self, shop: Shop) -> bool:
        for entry in self.product.get("shops", []):
            if entry.get("shop") == shop.domain:
                return True
        return False

    def _upsert_shop_listing(self, shop: Shop, listing_data: dict):
        """
        Inserts or updates a listing entry in the 'shops' array of the product document.
        If an entry for the shop exists, it updates it. Otherwise, inserts a new one.
        Automatically adds useful defaults for known statuses like 'create_pending'.
        """
        now = datetime.utcnow()
        listing_data["shop"] = shop.domain
        listing_data["updated_at"] = now

        existing_entry = next((s for s in self.product.get("shops", []) if s["shop"] == shop.domain), None)

        if existing_entry:
            listing_data["created_at"] = existing_entry.get("created_at", now)

            result = mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$set": {"shops.$[elem]": listing_data}},
                array_filters=[{"elem.shop": shop.domain}]
            )

            if result.modified_count == 0:
                self.log_action(
                    event="shop_listing_update_fallback_triggered",
                    level="warning",
                    data={"shop": shop.domain, "message": "⚠️ Fallback triggered while updating shop listing."}
                )
                mongo.db.products.update_one(
                    {"barcode": self.barcode},
                    {"$pull": {"shops": {"shop": shop.domain}}}
                )
                mongo.db.products.update_one(
                    {"barcode": self.barcode},
                    {"$push": {"shops": listing_data}}
                )
        else:
            listing_data["created_at"] = now
            listing_data["supplier"] = None
            listing_data["cost"] = None
            listing_data["stock_level"] = None
            listing_data["margin_used"] = None
            listing_data["rounding_used"] = None
            listing_data["round_to"] = None
            listing_data["selling_price"] = None
            listing_data["shopify_id"] = None
            listing_data["shopify_url"] = None
            listing_data["last_sync_attempt_at"] = None
            listing_data["last_sync_status"] = None
            mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$push": {"shops": listing_data}}
            )
            self.log_action(
                event="shop_listing_created",
                level="info",
                data={"shop": shop.domain, "status": listing_data["status"], "message": "✨ New listing entry created for shop."}
            )

        # Update local in-memory product
        self.product.setdefault("shops", [])
        updated = False
        for i, entry in enumerate(self.product["shops"]):
            if entry["shop"] == shop.domain:
                self.product["shops"][i] = listing_data
                updated = True
                break
        if not updated:
            self.product["shops"].append(listing_data)

    def mark_listed_to_shop(self, shop: Shop, listing_data: dict):
        """
        Public-facing method to mark a product as listed to a specific shop,
        delegating the heavy lifting to _upsert_shop_listing.
        """
        self._upsert_shop_listing(shop, listing_data)

        self.log_action(
            event="product_marked_as_listed",
            level="info",
            data={
                "shop": shop.domain,
                "listing_data": listing_data,
                "message": "📌 Product marked as listed or updated for shop."
            }
        )

    def unlist_from_shop(self, shop: Shop):
        mongo.db.products.update_one(
            {"barcode": self.barcode},
            {"$pull": {"shops": {"shop": shop.domain}}}
        )

        self.log_action(
            event="product_unlisted",
            level="warning",
            data={"shop": shop.domain, "message": "🚫 Product unlisted from shop."}
        )

    def get_brand(self):
        return self.product.get("barcode_lookup_data", {}).get("brand") or \
               self.product.get("barcode_lookup_data", {}).get("manufacturer")

    # TODO I think published should be a shop level setting
    def generate_shopify_payload(self, shop: Shop, published = True) -> dict | None:
        """
        Generates a Shopify GraphQL-compatible product payload for the given shop.
        Returns None if the product is not enriched or eligible for listing.
        """
        if not self.is_enriched_for_listing() or not self.is_product_eligible(shop):
            self.log_action(
                event="shopify_payload_generation_skipped",
                level="debug",
                data={"shop": shop.domain, "message": "Product is not eligible or fully enriched."}
            )
            return None

        ai = self.product.get("ai_generated_data", {})
        lookup = self.product.get("barcode_lookup_data", {})
        image_urls = self.product.get("image_urls", [])

        best_supplier = self.get_best_supplier_for_shop(shop)

        if not best_supplier:
            self.log_action(
                event="shopify_payload_generation_failed",
                level="warning",
                data={"message": "🏪 Missing supplier."}
            )
            return None

        selling_price =self.get_selling_price_for_shop(shop)
        stock_level = self.get_stock_level_for_shop(shop)

        if selling_price is None:
            self.log_action(
                event="shopify_payload_generation_failed",
                level="warning",
                data={"message": "💲 Missing pricing data."}
            )
            return None

        if stock_level is None:
            self.log_action(
                event="shopify_payload_generation_failed",
                level="warning",
                data={"message": "📦 Missing stock level data."}
            )
            return None

        # Construct description HTML
        description = ai.get("description", "").strip()
        if description.startswith("<p>"):
            description = description[3:]
        if description.endswith("</p>"):
            description = description[:-4]

        body_html = f"<p>{description}</p>"

        if suggested := ai.get("suggested_use"):
            body_html += f"<h3>Suggested Use</h3><p>{suggested}</p>"

        if ingredients := ai.get("ingredients"):
            body_html += f"<h3>Ingredients</h3><p>{', '.join(ingredients)}</p>"

        if nutrition := ai.get("nutritional_facts"):
            nutrition_lines = [f"{n['type']}: {n['amount']}{n['unit']}" for n in nutrition]
            body_html += "<h3>Nutritional Information</h3><ul>" + "".join(
                [f"<li>{line}</li>" for line in nutrition_lines]) + "</ul>"

        # Prepare image objects
        images = [{"src": url} for url in image_urls]

        # Prepare basic product payload
        product_payload = {
            "published": published,
            "title": ai["title"],
            "bodyHtml": body_html,
            "vendor": self.get_brand(),
            "productType": ai["product_type"],
            "tags": ai.get("tags", []),
            "variants": [
                {
                    "price": selling_price,
                    "sku": lookup.get("mpn", ""),
                    "barcode": self.barcode,
                    "inventoryQuantity": stock_level,
                    "inventoryManagement": "SHOPIFY",
                    "inventoryPolicy": "deny"
                }
            ],
            "images": images,
            "seo": {
                "title": ai.get("seo_title", ai["title"]),
                "description": ai.get("seo_description", "")
            },
            "metafields": []
        }

        # Optional SEO keywords as metafield
        if keywords := ai.get("seo_keywords"):
            product_payload["metafields"].append({
                "namespace": "seo",
                "key": "keywords",
                "value": ", ".join(keywords),
                "type": "single_line_text_field"
            })

        if ai.get("snippet"):
            product_payload["metafields"].append({
                "key": "snippet",
                "namespace": "seo",
                "type": "multi_line_text_field",
                "value": ai["snippet"]
            })

        # Ingredients + Nutrition as metafields
        if ingredients:
            product_payload["metafields"].append({
                "namespace": "nutrition",
                "key": "ingredients",
                "value": ", ".join(ingredients),
                "type": "multi_line_text_field"
            })
        if nutrition:
            facts = "\n".join([f"{n['type']}: {n['amount']}{n['unit']}" for n in nutrition])
            product_payload["metafields"].append({
                "namespace": "nutrition",
                "key": "facts",
                "value": facts,
                "type": "multi_line_text_field"
            })
        if suggested:
            product_payload["metafields"].append({
                "namespace": "usage",
                "key": "suggested_use",
                "value": suggested,
                "type": "multi_line_text_field"
            })

        # Handle collections
        collections = []
        if primary := ai.get("primary_collection"):
            collections.append(primary)
        if secondary := ai.get("secondary_collections", []):
            collections.extend(secondary)

        if collections:
            product_payload["collections"] = collections

        self.log_action(
            event="shopify_payload_generated",
            level="info",
            data={
                "shop": shop.domain,
                "message": "✅ Shopify product payload successfully generated.",
                "price": selling_price,
                "stock_level": stock_level,
                "collections": collections,
                "supplier": best_supplier["supplier_name"]
            }
        )

        if stock_level == 0:
            self.log_action(
                event="shopify_payload_generated_zero_stock",
                level="warning",
                data={
                    "shop": shop.domain,
                    "supplier": best_supplier["supplier_name"],
                    "message": "⚠️ Shopify payload generated with stock level 0"
                }
            )

        return product_payload

    def log_action(self, event: str, level: str = "info", data: dict = None, task_id: str = None):
        logger.log(
            event=event,
            store=None,
            level=level,
            data={"barcode": self.barcode, **(data or {})},
            task_id=task_id
        )
