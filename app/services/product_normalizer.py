"""Product normalizer — map raw data from any extractor to unified schema."""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

from app.models.enums import Platform
from app.models.product import Product, Variant
from app.security.html_sanitizer import HTMLSanitizer

logger = logging.getLogger(__name__)


class ProductNormalizer:
    """Normalize raw product data from various platforms to unified Product model."""

    def normalize(
        self, raw: dict, shop_id: str, platform: Platform, shop_url: str
    ) -> Product | None:
        """Normalize raw product dict from ANY extractor to unified Product model.

        Args:
            raw: Raw product data dictionary from platform/extractor
            shop_id: Merchant/shop identifier
            platform: Source platform enum
            shop_url: Base shop URL (e.g., "https://example.com")

        Returns:
            Product model instance or None if data insufficient for valid product
        """
        # Route to platform-specific normalizer first, then fall through
        # to format-based detection if platform normalizer fails.
        # This handles cases where we detect Magento/WooCommerce but extract
        # via OpenGraph/Schema.org fallback instead of the platform API.
        normalizers = {
            Platform.SHOPIFY: self._normalize_shopify,
            Platform.WOOCOMMERCE: self._normalize_woocommerce,
            Platform.MAGENTO: self._normalize_magento,
        }

        normalized_data = None
        if platform in normalizers:
            normalized_data = normalizers[platform](raw, shop_url)

        # If platform-specific normalizer returned None, try generic detection
        if not normalized_data:
            normalized_data = self._normalize_generic(raw, shop_url)

        if not normalized_data:
            return None

        # Add common fields
        normalized_data["shop_id"] = shop_id
        normalized_data["platform"] = platform
        normalized_data["raw_data"] = raw

        # Validate and create Product
        try:
            product = Product(**normalized_data)
        except Exception as e:
            logger.warning(f"Failed to create Product from normalized data: {e}")
            return None

        if not self._is_valid_product(product):
            return None
        return product

    @staticmethod
    def _validate_gtin(value: str | None) -> str | None:
        """Validate and normalize a GTIN/EAN/UPC value.

        Accepts 8, 12, 13, or 14-digit numeric strings. Zero-pads 12-digit
        UPC-A to 13-digit EAN-13. Rejects non-numeric, all-zeros, and
        wrong-length values.
        """
        if not value:
            return None
        value = value.strip().replace("-", "").replace(" ", "")
        if not value:
            return None
        if not value.isdigit():
            return None
        if set(value) == {"0"}:
            return None
        if len(value) == 12:
            value = "0" + value
        if len(value) not in (8, 13, 14):
            return None
        return value

    @staticmethod
    def _parse_additional_properties(props: list) -> dict:
        """Extract GTIN/MPN identifiers from Schema.org additionalProperty array."""
        known_ids = {"gtin", "gtin13", "gtin12", "gtin14", "gtin8", "ean", "mpn", "isbn"}
        result = {}
        for prop in props:
            if not isinstance(prop, dict):
                continue
            prop_id = str(prop.get("propertyID", "") or prop.get("name", "")).lower()
            if prop_id in known_ids:
                result[prop_id] = prop.get("value", "")
        return result

    def _is_valid_product(self, product: Product) -> bool:
        """Reject products that have no price, no image, AND no identifier.

        This catches non-product pages (blog posts, category pages) that slip
        through extraction with zero price and no meaningful data.  Products
        with at least one identifying attribute (price > 0, an image, a SKU,
        or an external_id) are kept.
        """
        has_price = product.price > 0
        has_image = bool(product.image_url and product.image_url.strip())
        has_identifier = bool(product.sku) or bool(
            product.external_id and product.external_id.strip()
        )
        if not has_price and not has_image and not has_identifier:
            logger.info(
                "Rejected non-product: title=%r price=%s", product.title, product.price
            )
            return False
        return True

    def _normalize_shopify(self, raw: dict, shop_url: str) -> dict | None:
        """Normalize Shopify /products.json format."""
        title = raw.get("title", "").strip()
        if not title:
            logger.debug("Shopify product missing title, skipping platform normalizer")
            return None

        # Extract first variant data
        variants_raw = raw.get("variants", [])
        first_variant = variants_raw[0] if variants_raw else {}

        # Parse price
        try:
            price = Decimal(first_variant.get("price", "0"))
        except (InvalidOperation, ValueError):
            logger.warning(f"Invalid Shopify price for product {raw.get('id')}")
            price = Decimal("0")

        # Parse compare_at_price
        compare_at_price = None
        if compare_at_raw := first_variant.get("compare_at_price"):
            try:
                compare_at_price = Decimal(compare_at_raw)
            except (InvalidOperation, ValueError):
                logger.warning(f"Invalid compare_at_price for Shopify product {raw.get('id')}")
                compare_at_price = None

        # Extract image URLs (primary + additional)
        images = raw.get("images", [])
        image_url = images[0]["src"] if images else ""
        additional_images = [img["src"] for img in images[1:] if img.get("src")]

        # Extract and validate GTIN/barcode from first variant
        gtin = self._validate_gtin(first_variant.get("barcode"))

        # Build product URL
        handle = raw.get("handle", "")
        product_url = f"{shop_url.rstrip('/')}/products/{handle}" if handle else shop_url

        # Parse tags (can be string or list)
        tags_raw = raw.get("tags", "")
        if isinstance(tags_raw, str):
            tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()]
        else:
            tags = list(tags_raw) if tags_raw else []

        # Determine in_stock: True if ANY variant has stock > 0 or no inventory tracking
        if variants_raw:
            in_stock = False
            for variant in variants_raw:
                inventory_qty = variant.get("inventory_quantity")
                if inventory_qty is None:
                    # No inventory tracking — assume in stock
                    in_stock = True
                    break
                if inventory_qty > 0:
                    in_stock = True
                    break
        else:
            in_stock = True  # No variants = assume in stock

        # Map variants
        variants = []
        for v in variants_raw:
            try:
                variant_price = Decimal(v.get("price", "0"))
                variant_in_stock = True
                inventory_qty = v.get("inventory_quantity")
                if inventory_qty is not None:
                    variant_in_stock = inventory_qty > 0

                variants.append(
                    Variant(
                        variant_id=str(v.get("id", "")),
                        title=v.get("title", ""),
                        price=variant_price,
                        sku=v.get("sku"),
                        in_stock=variant_in_stock,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to parse Shopify variant: {e}")
                continue

        return {
            "external_id": str(raw.get("id", "")),
            "title": title,
            "description": HTMLSanitizer.sanitize(raw.get("body_html", "")),
            "price": price,
            "compare_at_price": compare_at_price,
            "currency": raw.get("_shop_currency", "USD"),
            "image_url": image_url,
            "product_url": product_url,
            "sku": first_variant.get("sku"),
            "gtin": gtin,
            "mpn": None,
            "vendor": raw.get("vendor"),
            "product_type": raw.get("product_type"),
            "in_stock": in_stock,
            "condition": None,
            "variants": variants,
            "tags": tags,
            "additional_images": additional_images,
            "category_path": [raw["product_type"]] if raw.get("product_type") else [],
        }

    def _normalize_woocommerce(self, raw: dict, shop_url: str) -> dict | None:
        """Normalize WooCommerce Store API format."""
        title = raw.get("name", "").strip()
        if not title:
            logger.warning("WooCommerce product missing name")
            return None

        # Extract prices with currency conversion
        prices = raw.get("prices", {})
        currency_minor_unit = prices.get("currency_minor_unit", 2)
        divisor = 10**currency_minor_unit

        try:
            price = Decimal(prices.get("price", "0")) / divisor
        except (InvalidOperation, ValueError):
            logger.warning(f"Invalid WooCommerce price for product {raw.get('id')}")
            price = Decimal("0")

        # Compare at price (only if different from price)
        compare_at_price = None
        regular_price_raw = prices.get("regular_price")
        if regular_price_raw:
            try:
                regular_price = Decimal(regular_price_raw) / divisor
                if regular_price != price:
                    compare_at_price = regular_price
            except (InvalidOperation, ValueError):
                pass

        # Extract image URLs (primary + additional)
        images = raw.get("images", [])
        image_url = images[0].get("src", "") if images else ""
        additional_images = [img["src"] for img in images[1:] if img.get("src")]

        # Product URL
        product_url = raw.get("permalink", "")

        # Extract tags
        tags_raw = raw.get("tags", [])
        tags = [t.get("name", "") for t in tags_raw if isinstance(t, dict)]

        # Extract category path
        categories = raw.get("categories", [])
        category_path = [
            c.get("name", "") for c in categories
            if isinstance(c, dict) and c.get("name")
        ]

        return {
            "external_id": str(raw.get("id", "")),
            "title": title,
            "description": HTMLSanitizer.sanitize(raw.get("description", "")),
            "price": price,
            "compare_at_price": compare_at_price,
            "currency": prices.get("currency_code", "USD"),
            "image_url": image_url,
            "product_url": product_url,
            "sku": raw.get("sku"),
            "gtin": None,
            "mpn": None,
            "vendor": None,
            "product_type": None,
            "in_stock": True,
            "condition": None,
            "variants": [],
            "tags": tags,
            "additional_images": additional_images,
            "category_path": category_path,
        }

    def _normalize_magento(self, raw: dict, shop_url: str) -> dict | None:
        """Normalize Magento REST API format."""
        title = raw.get("name", "").strip()
        if not title:
            logger.warning("Magento product missing name")
            return None

        # Parse price
        try:
            price = Decimal(str(raw.get("price", "0")))
        except (InvalidOperation, ValueError):
            logger.warning(f"Invalid Magento price for product {raw.get('id')}")
            price = Decimal("0")

        # Extract custom attributes
        custom_attrs = raw.get("custom_attributes", [])
        description = ""
        image_path = ""
        url_key = ""
        gtin = None
        mpn = None
        manufacturer = None

        for attr in custom_attrs:
            if not isinstance(attr, dict):
                continue
            code = attr.get("attribute_code", "")
            value = attr.get("value", "")

            if code == "description":
                description = value
            elif code == "image":
                image_path = value
            elif code == "url_key":
                url_key = value
            elif code in ("ean", "gtin", "barcode"):
                gtin = value if value else None
            elif code == "mpn":
                mpn = value if value else None
            elif code == "manufacturer":
                manufacturer = value if value else None

        # Build image URL
        image_url = ""
        if image_path:
            image_url = f"{shop_url.rstrip('/')}/media/catalog/product{image_path}"

        # Build additional images from media gallery
        gallery = raw.get("media_gallery_entries", [])
        additional_images = []
        for entry in gallery:
            if not isinstance(entry, dict):
                continue
            file_path = entry.get("file", "")
            if file_path and not entry.get("disabled") and file_path != image_path:
                additional_images.append(
                    f"{shop_url.rstrip('/')}/media/catalog/product{file_path}"
                )

        # Build product URL
        product_url = shop_url
        if url_key:
            product_url = f"{shop_url.rstrip('/')}/{url_key}.html"

        return {
            "external_id": raw.get("sku", str(raw.get("id", ""))),
            "title": title,
            "description": HTMLSanitizer.sanitize(description),
            "price": price,
            "compare_at_price": None,
            "currency": "USD",
            "image_url": image_url,
            "product_url": product_url,
            "sku": raw.get("sku"),
            "gtin": gtin,
            "mpn": mpn,
            "vendor": manufacturer,
            "product_type": None,
            "in_stock": True,
            "condition": None,
            "variants": [],
            "tags": [],
            "additional_images": additional_images,
            "category_path": [],
        }

    def _normalize_generic(self, raw: dict, shop_url: str) -> dict | None:
        """Normalize generic/unknown format using detection heuristics.

        Tries to detect Schema.org JSON-LD, OpenGraph, or direct field mapping.
        """
        # Try Schema.org JSON-LD — route if has "offers" or looks like a Product type
        is_schema_org = "name" in raw and (
            "offers" in raw
            or (isinstance(raw.get("@type"), str) and "Product" in raw.get("@type", ""))
            or (isinstance(raw.get("@type"), list) and any("Product" in str(t) for t in raw["@type"]))
        )
        if is_schema_org:
            return self._normalize_schema_org(raw, shop_url)

        # Try OpenGraph
        if "og:title" in raw or "product:price:amount" in raw:
            return self._normalize_opengraph(raw, shop_url)

        # Try direct field mapping
        return self._normalize_css_generic(raw, shop_url)

    @staticmethod
    def _parse_condition(condition_str: str) -> str | None:
        """Map Schema.org itemCondition to idealo condition values."""
        if not condition_str:
            return None
        condition_str = str(condition_str)
        if "NewCondition" in condition_str:
            return "NEW"
        if "RefurbishedCondition" in condition_str:
            return "REFURBISHED"
        if "UsedCondition" in condition_str or "DamagedCondition" in condition_str:
            return "USED"
        return None

    @staticmethod
    def _extract_image_url(img: str | dict) -> str:
        """Extract URL string from Schema.org image (string or ImageObject)."""
        if isinstance(img, dict):
            return img.get("url") or img.get("contentUrl") or ""
        return str(img) if img else ""

    def _normalize_schema_org(self, raw: dict, shop_url: str) -> dict | None:
        """Normalize Schema.org JSON-LD format."""
        title = raw.get("name", "").strip()
        if not title:
            logger.warning("Schema.org product missing name")
            return None

        # Extract offers
        offers = raw.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        # Parse price
        try:
            price = Decimal(str(offers.get("price", "0")))
        except (InvalidOperation, ValueError):
            logger.warning(f"Invalid Schema.org price for product {raw.get('name')}")
            price = Decimal("0")

        # Extract image (can be string, list, or dict ImageObject)
        image = raw.get("image", "")
        additional_images: list[str] = []
        if isinstance(image, dict):
            image_url = self._extract_image_url(image)
        elif isinstance(image, list):
            image_url = self._extract_image_url(image[0]) if image else ""
            additional_images = [
                url for img in image[1:]
                if (url := self._extract_image_url(img))
            ]
        else:
            image_url = str(image) if image else ""

        # Fallback chain for missing image: thumbnailUrl → og:image
        if not image_url:
            image_url = raw.get("thumbnailUrl", "")
        if not image_url:
            image_url = raw.get("og:image", "")

        # Extract availability from offers (already normalised to dict above)
        availability = offers.get("availability", "")
        in_stock = "InStock" in str(availability) if availability else True

        # Parse additionalProperty as fallback for GTIN/MPN identifiers
        additional = self._parse_additional_properties(raw.get("additionalProperty", []))

        # Extract GTIN: product root -> offers -> additionalProperty
        gtin_raw = (
            raw.get("gtin13") or raw.get("gtin") or raw.get("gtin14")
            or raw.get("gtin12") or raw.get("gtin8") or raw.get("isbn")
            or offers.get("gtin13") or offers.get("gtin") or offers.get("gtin14")
            or offers.get("gtin12") or offers.get("gtin8")
            or additional.get("gtin13") or additional.get("gtin12")
            or additional.get("gtin14") or additional.get("gtin8")
            or additional.get("gtin") or additional.get("ean")
            or additional.get("isbn")
        )
        gtin = self._validate_gtin(gtin_raw)

        # Extract MPN from product root, fallback to offers
        mpn = raw.get("mpn") or offers.get("mpn") or None

        sku = raw.get("sku") or additional.get("mpn")
        external_id = raw.get("sku") or raw.get("productID") or gtin or ""

        # Extract condition from offers
        condition = self._parse_condition(offers.get("itemCondition", ""))

        # Extract category path
        category = raw.get("category")
        category_path: list[str] = []
        if isinstance(category, str) and category.strip():
            category_path = [c.strip() for c in re.split(r"[>/]", category) if c.strip()]
        elif isinstance(category, list):
            category_path = [str(c) for c in category if c]

        return {
            "external_id": external_id,
            "title": title,
            "description": HTMLSanitizer.sanitize(raw.get("description", "")),
            "price": price,
            "compare_at_price": None,
            "currency": offers.get("priceCurrency", "USD"),
            "image_url": image_url,
            "product_url": raw.get("url", shop_url),
            "sku": sku,
            "gtin": gtin,
            "mpn": mpn,
            "vendor": raw.get("brand", {}).get("name") if isinstance(raw.get("brand"), dict) else raw.get("brand"),
            "product_type": None,
            "in_stock": in_stock,
            "condition": condition,
            "variants": [],
            "tags": [],
            "additional_images": additional_images,
            "category_path": category_path,
        }

    def _normalize_opengraph(self, raw: dict, shop_url: str) -> dict | None:
        """Normalize OpenGraph meta tags format."""
        title = raw.get("og:title", "").strip()
        if not title:
            logger.warning("OpenGraph product missing og:title")
            return None

        # Parse price from various OG properties
        price_amount = raw.get("og:price:amount") or raw.get("product:price:amount", "0")
        try:
            price = Decimal(str(price_amount))
        except (InvalidOperation, ValueError):
            logger.warning(f"Invalid OpenGraph price for product {title}")
            price = Decimal("0")

        return {
            "external_id": raw.get("og:product_id", raw.get("product:retailer_item_id", "")),
            "title": title,
            "description": HTMLSanitizer.sanitize(raw.get("og:description", "")),
            "price": price,
            "compare_at_price": None,
            "currency": raw.get("og:price:currency") or raw.get("product:price:currency", "USD"),
            "image_url": raw.get("og:image", ""),
            "product_url": raw.get("og:url", shop_url),
            "sku": None,
            "gtin": None,
            "mpn": None,
            "vendor": None,
            "product_type": None,
            "in_stock": True,
            "condition": raw.get("product:condition") or None,
            "variants": [],
            "tags": [],
            "additional_images": [],
            "category_path": [raw["product:category"]] if raw.get("product:category") else [],
        }

    def _normalize_css_generic(self, raw: dict, shop_url: str) -> dict | None:
        """Normalize generic CSS-extracted fields."""
        title = (
            raw.get("title")
            or raw.get("name")
            or raw.get("product_name")
            or raw.get("heading")
            or ""
        ).strip()
        if not title:
            logger.warning("Generic product missing title")
            return None

        # Parse price from text
        price_raw = raw.get("price", "0")
        try:
            # Try to extract numeric value from price string
            if isinstance(price_raw, str):
                # Remove common currency symbols
                price_cleaned = price_raw.replace("$", "").replace("€", "").replace("£", "").strip()

                # Handle European format (comma as decimal separator)
                # If there's a comma and a period, comma is thousands separator (1,299.99)
                # If there's only a comma, it's decimal separator (49,99)
                if "," in price_cleaned and "." in price_cleaned:
                    # US format: 1,299.99 -> remove comma
                    price_cleaned = price_cleaned.replace(",", "")
                elif "," in price_cleaned:
                    # European format: 49,99 -> replace comma with period
                    price_cleaned = price_cleaned.replace(",", ".")
                else:
                    # No comma, could have period (19.95) or neither (25)
                    pass

                price = Decimal(price_cleaned)
            else:
                price = Decimal(str(price_raw))
        except (InvalidOperation, ValueError):
            logger.warning(f"Invalid generic price for product {title}")
            price = Decimal("0")

        return {
            "external_id": raw.get("sku", raw.get("id", "")),
            "title": title,
            "description": HTMLSanitizer.sanitize(raw.get("description", "")),
            "price": price,
            "compare_at_price": None,
            "currency": raw.get("currency") or raw.get("price_currency") or "USD",
            "image_url": raw.get("image") or raw.get("image_url") or raw.get("src") or "",
            "product_url": raw.get("product_url") or raw.get("url") or raw.get("canonical") or shop_url,
            "sku": raw.get("sku"),
            "gtin": self._validate_gtin(raw.get("gtin") or raw.get("ean") or raw.get("barcode")),
            "mpn": raw.get("mpn") or None,
            "vendor": None,
            "product_type": None,
            "in_stock": True,
            "condition": None,
            "variants": [],
            "tags": [],
            "additional_images": [],
            "category_path": [],
        }
