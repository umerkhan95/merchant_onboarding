"""Schema.org JSON-LD structured data extractor."""

from __future__ import annotations

import json
import logging

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Fields that may contain PII (reviewer names, personal data)
_SCHEMA_ORG_PII_FIELDS = frozenset({
    "review", "reviews", "author", "aggregateRating",
    "creator", "contributor", "editor", "publisher",
    "reviewedBy", "commentCount", "comment",
    "interactionStatistic",
})


class SchemaOrgExtractor:
    """Extract JSON-LD structured data from <script type='application/ld+json'> tags.

    The ``extract(url)`` instance method has been removed -- pipeline and
    UnifiedCrawl call the static ``extract_from_html()`` method directly.
    """

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    @staticmethod
    def _is_product_type(type_value) -> bool:
        """Check if JSON-LD @type indicates a Product (handles arrays and IRIs)."""
        if isinstance(type_value, str):
            return "Product" in type_value
        if isinstance(type_value, list):
            return any("Product" in str(t) for t in type_value)
        return False

    @staticmethod
    def _strip_pii_fields(product: dict) -> dict:
        """Remove fields that may contain PII from a Schema.org product dict."""
        return {k: v for k, v in product.items() if k not in _SCHEMA_ORG_PII_FIELDS}

    @staticmethod
    def _has_nonzero_price(offers) -> bool:
        """Check if offers contain a non-zero price."""
        if isinstance(offers, dict):
            try:
                return float(offers.get("price", 0)) > 0
            except (ValueError, TypeError):
                return bool(offers.get("price"))
        if isinstance(offers, list):
            for offer in offers:
                if isinstance(offer, dict):
                    try:
                        if float(offer.get("price", 0)) > 0:
                            return True
                    except (ValueError, TypeError):
                        if offer.get("price"):
                            return True
        return False

    @staticmethod
    def _enrich_product_group(product: dict) -> None:
        """Pull first variant's non-zero offers into a ProductGroup with no direct price.

        Shopify uses ProductGroup + hasVariant for variable-priced products
        (e.g. rugs with size options). The parent ProductGroup has no offers,
        but each variant Product inside hasVariant does.

        Skips variants with zero price (out-of-stock items) to avoid setting
        a misleading $0 price on the parent.
        """
        # Already has a usable non-zero price — nothing to do
        offers = product.get("offers")
        if SchemaOrgExtractor._has_nonzero_price(offers):
            return

        variants = product.get("hasVariant", [])
        if not isinstance(variants, list) or not variants:
            return

        # Find first variant with a non-zero price
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            v_offers = variant.get("offers")
            if isinstance(v_offers, dict):
                try:
                    if float(v_offers.get("price", 0)) > 0:
                        product["offers"] = v_offers
                        return
                except (ValueError, TypeError):
                    if v_offers.get("price"):
                        product["offers"] = v_offers
                        return
            if isinstance(v_offers, list):
                for offer in v_offers:
                    if not isinstance(offer, dict):
                        continue
                    try:
                        if float(offer.get("price", 0)) > 0:
                            product["offers"] = [offer]
                            return
                    except (ValueError, TypeError):
                        if offer.get("price"):
                            product["offers"] = [offer]
                            return

    @staticmethod
    def _extract_og_meta(soup: BeautifulSoup) -> dict[str, str]:
        """Extract OpenGraph meta tags from page as a fallback data source.

        Returns:
            Dict of OG properties (e.g., {"og:image": "https://...", "og:title": "..."})
        """
        og_data: dict[str, str] = {}
        for meta in soup.find_all("meta", attrs={"property": True}):
            prop = meta.get("property", "")
            content = meta.get("content", "")
            if prop.startswith("og:") and content:
                og_data[prop] = content.strip()
        return og_data

    @staticmethod
    def extract_from_html(html: str, url: str) -> list[dict]:
        """Extract JSON-LD from raw HTML content.

        Enriches sparse JSON-LD products with OpenGraph meta tags from the same
        page. This handles sites (like Bombas) that embed minimal JSON-LD stubs
        on some pages but still include og:image and other OG tags.

        Args:
            html: Raw HTML content
            url: URL for logging purposes

        Returns:
            List of raw Product JSON-LD dicts. Empty list on error or if no Product found.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            script_tags = soup.find_all("script", type="application/ld+json")

            if not script_tags:
                logger.debug("No JSON-LD script tags found on %s", url)
                return []

            products = []

            for script in script_tags:
                try:
                    data = json.loads(script.string)

                    # Handle single object
                    if isinstance(data, dict):
                        if SchemaOrgExtractor._is_product_type(data.get("@type")):
                            products.append(data)
                        # Handle @graph array (common pattern)
                        elif "@graph" in data and isinstance(data["@graph"], list):
                            for item in data["@graph"]:
                                if not isinstance(item, dict):
                                    continue
                                if SchemaOrgExtractor._is_product_type(item.get("@type")):
                                    products.append(item)
                                else:
                                    # Check mainEntity / mainEntityOfPage for nested Product
                                    # (common with Yoast SEO: ItemPage wrapping a Product)
                                    item_type = item.get("@type", "")
                                    page_types = ("WebPage", "ItemPage", "CollectionPage")
                                    is_page_type = (
                                        isinstance(item_type, str) and any(pt in item_type for pt in page_types)
                                    ) or (
                                        isinstance(item_type, list) and any(
                                            any(pt in str(t) for pt in page_types) for t in item_type
                                        )
                                    )
                                    if is_page_type:
                                        for key in ("mainEntity", "mainEntityOfPage"):
                                            nested = item.get(key)
                                            if isinstance(nested, dict) and SchemaOrgExtractor._is_product_type(nested.get("@type")):
                                                products.append(nested)
                                            elif isinstance(nested, list):
                                                for sub in nested:
                                                    if isinstance(sub, dict) and SchemaOrgExtractor._is_product_type(sub.get("@type")):
                                                        products.append(sub)

                    # Handle array of objects
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and SchemaOrgExtractor._is_product_type(item.get("@type")):
                                products.append(item)

                except json.JSONDecodeError as e:
                    logger.warning("Failed to parse JSON-LD from %s: %s", url, e)
                    continue
                except Exception as e:
                    logger.warning("Error processing JSON-LD script from %s: %s", url, e)
                    continue

            if not products:
                logger.debug("No Product objects found in JSON-LD on %s", url)
                return products

            # Enrich ProductGroup: pull first variant's offers into parent
            # when parent has no direct price (common Shopify pattern for
            # variable-priced products like rugs with size options).
            for product in products:
                if product.get("@type") == "ProductGroup":
                    SchemaOrgExtractor._enrich_product_group(product)

            # Strip PII fields before returning
            products = [SchemaOrgExtractor._strip_pii_fields(p) for p in products]

            # Enrich sparse JSON-LD with OG meta tags from the same page
            og_data = SchemaOrgExtractor._extract_og_meta(soup)
            if og_data:
                for product in products:
                    # Fill missing image from og:image (set canonical key)
                    if not product.get("image") and og_data.get("og:image"):
                        product["image"] = og_data["og:image"]
                    # Fill missing URL from og:url
                    if not product.get("url") and og_data.get("og:url"):
                        product["url"] = og_data["og:url"]
                    # Fill missing description from og:description
                    if not product.get("description") and og_data.get("og:description"):
                        product["description"] = og_data["og:description"]

            return products

        except Exception as e:
            logger.exception("Schema.org extraction failed for %s: %s", url, e)
            return []

