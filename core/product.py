# core/product.py
from pycparser.ply.yacc import error_count

from core.MongoManager import MongoManager
from core.Logger import AppLogger
from datetime import datetime
from core.exceptions import ProductNotFoundError
from core.shop import Shop
from math import ceil, floor
from core.clients.shopify_client import ShopifyClient, ShopifyGraphQLError
import time

mongo = MongoManager()
logger = AppLogger(mongo)

MAX_FAIL_COUNT = 3

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
            self.log_action(
                event="product_not_eligible_enrichment_incomplete",
                level="debug",
                data={"message": "⚠️ Enrichment incomplete."}
            )
            return False

        if not self.get_image_urls():
            self.log_action(
                event="product_missing_images_but_continuing",
                level="warning",
                data={"message": "⚠️ Product has no image URLs but will be considered eligible."}
            )

        brand = self.get_brand()
        if brand.lower() in shop.get_excluded_brands():
            self.log_action(
                event="product_not_eligible_excluded_brand",
                level="debug",
                data={"brand": brand, "message": "🚫 Brand excluded."}
            )
            return False

        for supplier in self.product.get("suppliers", []):
            name = supplier.get("name")
            parsed = supplier.get("parsed", {})
            if name.lower() in shop.get_excluded_suppliers():
                continue
            if parsed.get("price", 0) > 0:
                return True

        self.log_action(
            event="product_not_eligible_no_valid_supplier",
            level="debug",
            data={"message": "🚫 No usable suppliers with stock and price."}
        )
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
                            "sku": best["sku"],
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

    def has_shop_listing(self, shop: Shop, statuses: tuple[str] = None) -> bool:
        for entry in self.product.get("shops", []):
            if entry.get("shop") == shop.domain:
                if statuses is None or entry.get("status") in statuses:
                    return True
        return False

    def is_ready_to_post_to_shopify(self, shop: Shop) -> tuple[bool, str]:
        """
        Determines if this product is eligible and ready to be posted to the given shop.
        Blocks if it has already been created or is currently being processed.
        """
        if not self.is_enriched_for_listing():
            return False, "❌ Product is not enriched."
        if not self.is_product_eligible(shop):
            return False, "❌ Product is not eligible for this shop."
        if self.has_shop_listing(shop, statuses=("created",)):
            return False, "❌ Product has already been created."
        if self.has_shop_listing(shop, statuses=("create_processing",)):
            return False, "❌ Product is being processed."
        if self.has_shop_listing(shop, statuses=("create_fail",)):
            return False, "❌ Product has been marked as fail and will not be re-attempted."
        if self.has_shop_listing(shop, statuses=("unmanaged",)):
            return False, "❌ Product is unmanaged."
        return True, "✅ Product is ready to be listed."

    def _upsert_shop_listing(self, shop: Shop, listing_data: dict):
        from datetime import datetime
        now = datetime.utcnow()
        status = listing_data.get("status")
        listing_data["shop"] = shop.domain
        listing_data["updated_at"] = now

        GLOBAL_DEFAULTS = {
            "supplier": None,
            "cost": None,
            "stock_level": None,
            "margin_used": None,
            "rounding_used": None,
            "round_to": None,
            "selling_price": None,
            "sku": None,
            "shopify_id": None,
            "shopify_gid": None,
            "shopify_url": None,
            "shopify_variant_id": None,
            "shopify_handle": None,
            "error_count": 0,
            "message": None,
        }

        LISTING_CONFIGS = {
            "create_pending": {"required": [], "defaults": {}},
            "create_processing": {"required": [], "defaults": {}},
            "create_error": {"required": [], "defaults": {}, "increment_error_count": True},
            "create_fail": {"required": [], "defaults": {}},
            "created": {
                "required": [
                    "shopify_id", "shopify_gid", "shopify_variant_id", "shopify_url", "shopify_handle",
                    "supplier", "cost", "stock_level", "selling_price", "sku",
                    "margin_used", "rounding_used", "round_to"
                ],
                "defaults": {},
                "reset_error_count": True
            },
            "update_pending": {"required": [], "defaults": {}},
            "update_processing": {"required": [], "defaults": {}},
            "update_error": {"required": [], "defaults": {}, "increment_error_count": True},
            "update_fail": {"required": [], "defaults": {}},
            "updated": {
                "required": [
                    "supplier", "cost", "stock_level", "selling_price", "sku",
                    "margin_used", "rounding_used", "round_to"
                ],
                "defaults": {},
                "reset_error_count": True
            },
            "unmanaged": {"required": [], "defaults": {}},
        }

        if status not in LISTING_CONFIGS:
            raise ValueError(f"❌ Unknown shop listing status '{status}'.")

        config = LISTING_CONFIGS[status]

        for field in config.get("required", []):
            if field not in listing_data or listing_data[field] in (None, "__clear__"):
                raise ValueError(f"❌ Missing required field '{field}' for status '{status}'.")

        # Get current values
        existing_entry = next((s for s in self.product.get("shops", []) if s["shop"] == shop.domain), None)
        full_listing = existing_entry.copy() if existing_entry else GLOBAL_DEFAULTS.copy()

        # Merge config defaults
        full_listing.update(config.get("defaults", {}))

        # Merge incoming data
        for k, v in listing_data.items():
            if v == "__clear__":
                full_listing[k] = None
            else:
                full_listing[k] = v

        # Preserve created_at
        full_listing["created_at"] = existing_entry.get("created_at", now) if existing_entry else now

        if config.get("reset_error_count"):
            full_listing["error_count"] = 0
        elif config.get("increment_error_count"):
            full_listing["error_count"] += 1

            if full_listing["error_count"] >= MAX_FAIL_COUNT:
                full_listing["status"] = "create_fail"
                error_count_temp = full_listing["error_count"]
                self.log_action("shop_reached_max_creation_attempts", "error", {
                    "shop": shop.domain,
                    "product_id": self.barcode,
                    "message": f"🚨 Product reached {error_count_temp}/{MAX_FAIL_COUNT} max creation attempts, no more attempts will be made."
                })

        valid_keys = set(GLOBAL_DEFAULTS) | {"status", "shop", "created_at", "updated_at"}
        valid_keys.update(config.get("required", []))
        valid_keys.update(config.get("defaults", {}).keys())

        unexpected = set(full_listing.keys()) - valid_keys
        if unexpected:
            raise ValueError(f"❌ Unexpected fields in listing_data: {unexpected}")

        if existing_entry:
            result = mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$set": {"shops.$[elem]": full_listing}},
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
                    {"$push": {"shops": full_listing}}
                )
        else:
            mongo.db.products.update_one(
                {"barcode": self.barcode},
                {"$push": {"shops": full_listing}}
            )
            self.log_action(
                event="shop_listing_created",
                level="info",
                data={"shop": shop.domain,"status": status, "message": "✨ New listing entry created for shop."}
            )

        self.product.setdefault("shops", [])
        for i, entry in enumerate(self.product["shops"]):
            if entry["shop"] == shop.domain:
                self.product["shops"][i] = full_listing
                break
        else:
            self.product["shops"].append(full_listing)

        return full_listing

    def mark_listed_to_shop(self, shop: Shop, listing_data: dict):
        """
        Public-facing method to mark a product as listed to a specific shop,
        delegating the heavy lifting to _upsert_shop_listing.
        """
        updated_listing_data = self._upsert_shop_listing(shop, listing_data)

        self.log_action(
            event="product_marked_as_listed",
            level="info",
            data={
                "shop": shop.domain,
                "status": updated_listing_data['status'],
                "listing_data": updated_listing_data,
                "message": "📌 Shop product listing updated."
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

    def get_image_urls(self):
        return self.product.get("image_urls") or []

    # TODO I think published should be a shop level setting
    def generate_shopify_payload(self, shop: Shop, published=True) -> dict | None:
        if not self.is_enriched_for_listing() or not self.is_product_eligible(shop):
            self.log_action(
                event="shopify_payload_generation_skipped",
                level="debug",
                data={"shop": shop.domain, "message": "Product is not eligible or fully enriched."}
            )
            return None

        ai = self.product.get("ai_generated_data", {})
        lookup = self.product.get("barcode_lookup_data", {})

        # Build body HTML
        description = (ai.get("description", "") or "").strip()
        if description.startswith("<p>"): description = description[3:]
        if description.endswith("</p>"): description = description[:-4]

        body_html = f"<p>{description}</p>"
        if suggested := ai.get("suggested_use"):
            body_html += f"<h3>Suggested Use</h3><p>{suggested}</p>"
        if ingredients := ai.get("ingredients"):
            body_html += f"<h3>Ingredients</h3><p>{', '.join(filter(None, ingredients))}</p>"
        nutrition_lines = []
        if nutrition := ai.get("nutritional_facts"):
            nutrition_lines = [f"{n['type']}: {n['amount']}{n['unit']}"
                               for n in nutrition if n.get("type") and n.get("amount") and n.get("unit")]
            body_html += "<h3>Nutritional Information</h3><ul>" + "".join(
                [f"<li>{line}</li>" for line in nutrition_lines]) + "</ul>"

        payload = {
            "published": published,
            "title": ai.get("title", "Untitled Product"),
            "descriptionHtml": body_html,
            "vendor": self.get_brand() or "Unknown",
            "productType": ai.get("product_type", "Misc"),
            "tags": ai.get("tags", []),
            "metafields": []
        }

        def meta(key, ns, val, typ):
            payload["metafields"].append({
                "key": key, "namespace": ns, "value": val, "type": typ
            })

        if ai.get("seo_title"): meta("title", "seo", ai["seo_title"], "single_line_text_field")
        if ai.get("seo_description"): meta("description", "seo", ai["seo_description"], "multi_line_text_field")
        if ai.get("seo_keywords"): meta("keywords", "seo", ", ".join(ai["seo_keywords"]), "single_line_text_field")
        if ai.get("snippet"): meta("snippet", "seo", ai["snippet"], "multi_line_text_field")
        if ingredients: meta("ingredients", "nutrition", ", ".join(ingredients), "multi_line_text_field")
        if nutrition_lines: meta("facts", "nutrition", "\n".join(nutrition_lines), "multi_line_text_field")
        if suggested: meta("suggested_use", "usage", suggested, "multi_line_text_field")

        self.log_action("shopify_payload_generated", "info", {
            "shop": shop.domain, "message": "✅ Shopify product payload generated"
        })
        return payload

    def generate_variant_payload(self, shop: Shop, product_id: str) -> dict | None:
        lookup = self.product.get("barcode_lookup_data", {})
        best_supplier = self.get_best_supplier_for_shop(shop)

        if not best_supplier:
            self.log_action("variant_generation_failed", "warning", {
                "message": "❌ No best supplier."
            })
            return None

        selling_price = self.get_selling_price_for_shop(shop)
        if selling_price is None:
            return None

        payload = {
            "productId": product_id,
            "sku": best_supplier['sku'],
            "barcode": self.barcode,
            "price": str(round(selling_price, 2)),
            "inventoryItem": {
                "tracked": True
            }
        }

        self.log_action("shopify_variant_payload_generated", "info", {
            "shop": shop.domain,
            "product_id": product_id,
            "price": selling_price
        })
        return payload

    # NOTE: When implementing create/update tasks, support a debug/test param to simulate failure
    # e.g., if barcode == "TEST-BREAK-123", raise Exception("Forced failure for test purposes")
    def create_on_shopify(self, shop: Shop, task_id: str = None) -> dict:
        self.log_action("shopify_create_flow_started", "info", {
            "shop": shop.domain,
            "message": "🚀 Starting Shopify product creation flow."
        }, task_id=task_id)

        product_id = None  # 👈 Needed for failsafe cleanup

        self.mark_listed_to_shop(shop, {
            "status": "create_processing",
        })

        try:
            product_id, product_gid, variant_gid, handle, url = self.create_base_product_on_shopify(shop, task_id)

            self.update_shopify_variant(shop, product_gid, variant_gid, task_id)
            self.set_shopify_inventory(shop, variant_gid, task_id)
            # NOTE: Use this to force failure for testing
            # raise Exception("force_fail")
            self.upload_product_images_to_shopify(shop, product_id, task_id)

            best_supplier = self.get_best_supplier_for_shop(shop)
            selling_price = self.get_selling_price_for_shop(shop)

            self.assign_product_collections(shop, product_id, product_gid, task_id)

            self.mark_listed_to_shop(shop, {
                "status": "created",
                "shopify_id": product_id,
                "shopify_gid": product_gid,
                "shopify_url": url,
                "shopify_variant_id": variant_gid,
                "shopify_handle": handle,
                "supplier": best_supplier["supplier_name"],
                "cost": best_supplier["price"],
                "stock_level": best_supplier.get("stock_level", 0),
                "selling_price": selling_price,
                "sku": best_supplier["sku"],
                "margin_used": shop.get_setting("profit_margin", 1.5),
                "rounding_used": shop.get_setting("rounding", 0.99),
                "round_to": shop.get_setting("round_to", "closest")
            })

            self.log_action("shopify_create_flow_completed", "success", {
                "shop": shop.domain,
                "product_id": product_id,
                "product_gid": product_gid,
                "variant_id": variant_gid,
                "handle": handle,
                "url": url,
                "message": "✅ Product and variant successfully created and enriched on Shopify."
            }, task_id=task_id)

            return {
                "product_id": product_id,
                "product_gid": product_gid,
                "variant_id": variant_gid,
                "handle": handle,
                "url": url
            }
        except Exception as e:
            self.mark_listed_to_shop(shop, {
                "status": "create_error",
            })

            self.log_action("shopify_create_flow_failed", "error", {
                "shop": shop.domain,
                "product_id": product_id,
                "error": str(e),
                "message": "💥 Shopify creation flow failed — attempting cleanup."
            }, task_id=task_id)

            if product_id:
                shop.client.delete_product_rest(product_id, task_id=task_id)

            raise

    def update_on_shopify(self, shop: Shop, task_id: str = None):
        self.log_action("shopify_update_flow_started", "info", {
            "shop": shop.domain,
            "message": "🔄 Starting Shopify product update flow."
        }, task_id=task_id)

        # Failsafe: mark as processing
        self.mark_listed_to_shop(shop, {
            "status": "update_processing"
        })

        try:
            # Validate existing listing
            existing = next((s for s in self.product.get("shops", []) if s.get("shop") == shop.domain), None)
            if not existing or not existing.get("shopify_gid") or not existing.get("shopify_variant_id"):
                raise Exception("❌ Cannot update — Shopify IDs missing from shop entry.")

            product_gid = existing["shopify_gid"]
            variant_gid = existing["shopify_variant_id"]

            # Update price + SKU
            self.update_shopify_variant(shop, product_gid, variant_gid, task_id)

            # Update stock level
            self.set_shopify_inventory(shop, variant_gid, task_id)

            # Update internal record
            best_supplier = self.get_best_supplier_for_shop(shop)
            selling_price = self.get_selling_price_for_shop(shop)

            self.mark_listed_to_shop(shop, {
                "status": "updated",
                "supplier": best_supplier["supplier_name"],
                "cost": best_supplier["price"],
                "stock_level": best_supplier.get("stock_level", 0),
                "selling_price": selling_price,
                "sku": best_supplier["sku"],
                "margin_used": shop.get_setting("profit_margin", 1.5),
                "rounding_used": shop.get_setting("rounding", 0.99),
                "round_to": shop.get_setting("round_to", "closest")
            })

            self.log_action("shopify_update_flow_completed", "success", {
                "shop": shop.domain,
                "product_gid": product_gid,
                "variant_gid": variant_gid,
                "message": "✅ Shopify listing successfully updated."
            }, task_id=task_id)

            return True

        except Exception as e:
            self.mark_listed_to_shop(shop, {
                "status": "update_error"  # We'll retry later
            })

            self.log_action("shopify_update_flow_failed", "error", {
                "shop": shop.domain,
                "error": str(e),
                "message": "❌ Shopify update flow failed — marked as update_error for retry."
            }, task_id=task_id)

            raise

    def create_base_product_on_shopify(self, shop: Shop, task_id=None):
        payload = self.generate_shopify_payload(shop)
        if not payload:
            raise Exception("Product payload generation failed.")

        response = shop.client.create_product(payload, task_id=task_id)
        product_id = response["id"]
        product_gid = response["gid"]
        variant_edges = response.get("variants", {}).get("edges", [])

        if not variant_edges:
            # Fallback via REST
            resp = shop.client.rest("GET", f"products/{product_id}.json")
            variants = resp.get("product", {}).get("variants", [])
            if not variants:
                raise Exception("❌ No variants found even after fallback.")
            variant_gid = variants[0]["id"]
        else:
            variant_gid = variant_edges[0]["node"]["id"]

        handle = response.get("handle")
        url = f"https://{shop.domain}/products/{handle}" if handle else None

        return product_id, product_gid, variant_gid, handle, url

    def update_shopify_variant(self, shop: Shop, product_gid: str, variant_gid: str, task_id=None):
        best_supplier = self.get_best_supplier_for_shop(shop)
        selling_price = self.get_selling_price_for_shop(shop)
        sku = best_supplier['sku']

        shop.client.update_variant_bulk(product_gid, {
            "id": variant_gid,
            "price": str(selling_price),
            "inventoryItem": {
                "sku": sku,
                "tracked": True
            }
        }, task_id=task_id)

        self.log_action("variant_updated", "info", {
            "variant_gid": variant_gid,
            "price": selling_price,
            "sku": sku,
            "message": "✏️ Variant updated with SKU and price."
        }, task_id=task_id)

    def set_shopify_inventory(self, shop: Shop, variant_gid: str, task_id=None):
        best_supplier = self.get_best_supplier_for_shop(shop)
        stock = best_supplier.get("stock_level", 0)
        location_id = shop.get_primary_location_id()

        variant_id = ShopifyClient.extract_legacy_id(variant_gid)
        variant = shop.client.rest("GET", f"variants/{variant_id}.json").get("variant", {})
        inventory_item_id = variant.get("inventory_item_id")
        if not inventory_item_id:
            raise Exception("❌ Could not determine inventory_item_id from variant.")

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                shop.client.set_inventory_level_rest(inventory_item_id, location_id, stock, task_id=task_id)
                self.log_action("inventory_set", "info", {
                    "inventory_item_id": inventory_item_id,
                    "stock_level": stock,
                    "location_id": location_id,
                    "message": f"📦 Inventory set on attempt {attempt}"
                }, task_id=task_id)
                break
            except Exception as e:
                self.log_action("inventory_set_failed", "warning", {
                    "inventory_item_id": inventory_item_id,
                    "location_id": location_id,
                    "attempt": attempt,
                    "error": str(e),
                    "message": f"⚠️ Inventory update attempt {attempt} failed."
                }, task_id=task_id)
                if attempt == max_attempts:
                    raise
                time.sleep(2 ** attempt)

    def upload_product_images_to_shopify(self, shop: Shop, product_id: str, task_id=None):
        for url in self.product.get("image_urls", []) or []:
            try:
                shop.client.upload_image_rest(product_id, url, task_id=task_id)
            except Exception as e:
                self.log_action("shopify_image_upload_failed", "warning", {
                    "original_url": url,
                    "error": str(e),
                    "message": "⚠️ Failed to upload product image via REST."
                }, task_id=task_id)

    def assign_product_collections(self, shop: Shop, product_id: str, product_gid: str, task_id: str = None):
        ai = self.product.get("ai_generated_data", {})
        primary = ai.get("primary_collection")
        secondary = ai.get("secondary_collections") or []
        collection_names = list(set(filter(None, [primary] + secondary)))

        for name in collection_names:
            success = shop.add_product_to_collection(
                product_id=product_id,
                product_gid=product_gid,
                title=name,
                task_id=task_id
            )

            if not success:
                try:
                    created = shop.client.create_collection(title=name, task_id=task_id)
                    shop.add_local_collection(created)

                    retry_success = shop.add_product_to_collection(
                        product_id=product_id,
                        product_gid=product_gid,
                        title=name,
                        task_id=task_id
                    )

                    if retry_success:
                        self.log_action("collection_created_and_added", "info", {
                            "collection": name,
                            "product_id": product_id,
                            "product_gid": product_gid,
                            "collection_id": created["id"],
                            "collection_gid": created["gid"],
                            "message": "🌱 Created collection and added product."
                        }, task_id=task_id)
                    else:
                        self.log_action("collection_create_retry_failed", "warning", {
                            "collection": name,
                            "product_id": product_id,
                            "product_gid": product_gid,
                            "message": "❌ Created collection but failed to add product."
                        }, task_id=task_id)

                except Exception as e:
                    self.log_action("collection_create_failed", "error", {
                        "collection": name,
                        "product_id": product_id,
                        "product_gid": product_gid,
                        "message": "❌ Failed to create collection.",
                        "error": str(e)
                    }, task_id=task_id)

    def update_supplier_parsed_data(self, supplier_name: str, parsed_updates: dict):
        """
        Updates parsed supplier data for a given supplier in the product.
        """
        updated = False

        for supplier in self.product.get("suppliers", []):
            if supplier["name"] == supplier_name:
                supplier["parsed"].update(parsed_updates)
                updated = True
                break

        if updated:
            mongo.db.products.update_one(
                {"barcode": self.barcode},
                {
                    "$set": {
                        "suppliers": self.product["suppliers"],
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            self.log_action(
                "supplier_parsed_updated",
                "info",
                {
                    "supplier": supplier_name,
                    "updates": parsed_updates,
                    "message": f"✅ Updated parsed data for supplier {supplier_name}"
                }
            )
        else:
            self.log_action(
                "supplier_parsed_update_failed",
                "warning",
                {
                    "supplier": supplier_name,
                    "message": f"⚠️ Could not find supplier {supplier_name} to update parsed data"
                }
            )

    def update_supplier_entry(self, supplier_name: str, new_data: dict, new_parsed: dict,
                              dry_run: bool = False) -> dict:
        """
        Compares and updates supplier's raw `data` and `parsed` fields.
        Returns a dictionary summarizing what changed.
        """
        changed_fields = {"parsed": {}, "data": {}}
        updated = False

        for supplier in self.product.get("suppliers", []):
            if supplier["name"] != supplier_name:
                continue

            # Check and compare parsed fields
            for key, new_value in new_parsed.items():
                old_value = supplier.get("parsed", {}).get(key)
                if old_value != new_value:
                    changed_fields["parsed"][key] = {"old": old_value, "new": new_value}
                    if not dry_run:
                        supplier["parsed"][key] = new_value
                        updated = True

            # Check and compare raw data fields (if any)
            for key, new_value in new_data.items():
                old_value = supplier.get("data", {}).get(key)
                if old_value != new_value:
                    changed_fields["data"][key] = {"old": old_value, "new": new_value}
                    if not dry_run:
                        supplier["data"][key] = new_value
                        updated = True

            break

        if updated:
            mongo.db.products.update_one(
                {"barcode": self.barcode},
                {
                    "$set": {
                        "suppliers": self.product["suppliers"],
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            self.log_action(
                event="supplier_entry_updated",
                level="info",
                data={
                    "supplier": supplier_name,
                    "message": "🔁 Supplier entry updated",
                    "changed_fields": changed_fields
                }
            )
        elif changed_fields["parsed"] or changed_fields["data"]:
            self.log_action(
                event="supplier_entry_dry_run_detected_changes",
                level="info",
                data={
                    "supplier": supplier_name,
                    "message": "💡 Would update supplier entry (dry-run)",
                    "changed_fields": changed_fields
                }
            )

        return changed_fields

    def log_action(self, event: str, level: str = "info", data: dict = None, task_id: str = None):
        logger.log(
            event=event,
            store=None,
            level=level,
            data={"barcode": self.barcode, **(data or {})},
            task_id=task_id
        )
