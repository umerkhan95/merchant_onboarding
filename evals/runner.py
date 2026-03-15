"""Evaluation runner — orchestrates extractor runs and scoring.

Supported extraction tiers:
    0. shopify_api - Extract via Shopify /products.json API (free, Shopify-only)
    1. schema_org - Extract from JSON-LD structured data (free)
    2. opengraph - Extract from OpenGraph meta tags (free)
    3. css_generic - Extract via generic CSS selectors (free)
    4. smart_css - Auto-generate CSS selectors per domain via LLM, cache and reuse (one-time LLM cost)
    5. llm - Universal LLM extraction, works on any website (LLM cost per page)

Default tiers (free): schema_org, opengraph, css_generic
All tiers (requires LLM_API_KEY): schema_org, opengraph, css_generic, smart_css, llm
Platform-specific: shopify_api (must be requested explicitly via --tier shopify_api)
"""

from __future__ import annotations

import logging
import re
import time
import tracemalloc
from pathlib import Path

from app.extractors.browser_config import StealthLevel
from evals.models import EvalReport, TestCase, TierResult
from evals.scorer import Scorer

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class EvalRunner:
    """Runs extractors against test cases and scores the results."""

    # Default tiers (free, no LLM cost)
    DEFAULT_TIERS = ["schema_org", "opengraph", "css_generic"]

    # All available tiers including LLM-based ones
    ALL_TIERS = ["schema_org", "opengraph", "css_generic", "smart_css", "llm"]

    def __init__(
        self,
        tiers: list[str] | None = None,
        force_offline: bool = False,
        force_live: bool = False,
        profile: bool = False,
        stealth_level: StealthLevel = StealthLevel.STANDARD,
    ):
        """Initialize the eval runner with a list of tiers to test.

        Args:
            tiers: List of tier names to test. Defaults to ["schema_org", "opengraph", "css_generic"]
            force_offline: If True, fail if snapshot is missing (never hit live URLs)
            force_live: If True, ignore snapshots and always hit live URLs
            profile: Enable memory profiling (slower). Default: False
            stealth_level: Anti-bot protection tier for browser-based extractors
        """
        self.tiers = tiers or self.DEFAULT_TIERS
        self.force_offline = force_offline
        self.force_live = force_live
        self.profile = profile
        self.stealth_level = stealth_level

        if force_offline and force_live:
            raise ValueError("Cannot specify both force_offline and force_live")

    async def run(self, test_case: TestCase) -> EvalReport:
        """Run all configured tiers against a single test case.

        Args:
            test_case: The test case to evaluate

        Returns:
            EvalReport with results from all tiers
        """
        logger.info("Running eval for test case: %s", test_case.name)

        tier_results = []
        for tier_name in self.tiers:
            result = await self._run_tier(tier_name, test_case)
            tier_results.append(result)

        return EvalReport(
            test_case_name=test_case.name,
            url=test_case.url,
            platform=test_case.platform,
            tier_results=tier_results,
        )

    def _extract_offline(self, tier_name: str, html: str, url: str) -> list[dict]:
        """Extract products from saved HTML content.

        Args:
            tier_name: Name of the tier
            html: Raw HTML content
            url: URL for logging purposes

        Returns:
            List of extracted product dicts

        Raises:
            ValueError: If offline mode not supported for this tier
        """
        if tier_name == "schema_org":
            from app.extractors.schema_org_extractor import SchemaOrgExtractor
            return SchemaOrgExtractor.extract_from_html(html, url)

        elif tier_name == "opengraph":
            from app.extractors.opengraph_extractor import OpenGraphExtractor
            return OpenGraphExtractor.extract_from_html(html, url)

        else:
            raise ValueError(f"Offline mode not supported for tier: {tier_name}")

    def _get_product_urls(self, test_case: TestCase) -> list[str]:
        """Get individual product URLs from test case expected products.

        Falls back to the main test case URL if no product URLs are defined.
        """
        urls = []
        for product in test_case.products:
            if product.product_url:
                urls.append(product.product_url)
        return urls if urls else [test_case.url]

    async def _run_tier(self, tier_name: str, test_case: TestCase) -> TierResult:
        """Run a single tier extractor against a test case and score the results.

        Extracts from individual product URLs when available in the fixture,
        otherwise falls back to the main test case URL.

        Args:
            tier_name: Name of the tier to run
            test_case: The test case to evaluate

        Returns:
            TierResult with scores, timing, and error info
        """
        logger.info("Running tier '%s' for %s", tier_name, test_case.name)

        peak_memory_mb = None
        tokens_used = None
        estimated_cost = None

        try:
            # Create the extractor
            extractor = self._create_extractor(tier_name)

            # Check for offline HTML snapshot
            snapshot_html = None
            if test_case.html_file and not self.force_live:
                snapshot_path = FIXTURES_DIR / "snapshots" / test_case.html_file
                if snapshot_path.exists():
                    snapshot_html = snapshot_path.read_text(encoding="utf-8")
                    logger.info("Using offline snapshot: %s", snapshot_path.name)
                elif self.force_offline:
                    raise FileNotFoundError(
                        f"Offline mode enabled but snapshot not found: {snapshot_path}"
                    )

            # Start memory profiling if enabled
            if self.profile:
                tracemalloc.start()

            try:
                # Time the extraction
                start_time = time.monotonic()

                if snapshot_html and not self.force_live:
                    # Offline extraction from single snapshot
                    extracted_products = self._extract_offline(tier_name, snapshot_html, test_case.url)
                elif tier_name == "shopify_api":
                    # Shopify API: extract ALL products from shop URL, then flatten
                    raw_products = await extractor.extract(test_case.url)
                    extracted_products = [
                        self._flatten_shopify_product(p, test_case.url)
                        for p in raw_products
                    ]
                    logger.info(
                        "Shopify API returned %d products, flattened to %d",
                        len(raw_products),
                        len(extracted_products),
                    )
                elif tier_name == "woocommerce_api":
                    # WooCommerce Store API: extract ALL products, then flatten
                    raw_products = await extractor.extract(test_case.url)
                    extracted_products = [
                        self._flatten_wc_product(p, test_case.url)
                        for p in raw_products
                    ]
                    logger.info(
                        "WooCommerce API returned %d products, flattened to %d",
                        len(raw_products),
                        len(extracted_products),
                    )
                elif tier_name == "magento_api":
                    # Magento REST API: extract ALL products, then flatten
                    raw_products = await extractor.extract(test_case.url)
                    extracted_products = [
                        self._flatten_magento_product(p, test_case.url)
                        for p in raw_products
                    ]
                    logger.info(
                        "Magento API returned %d products, flattened to %d",
                        len(raw_products),
                        len(extracted_products),
                    )
                else:
                    # Live extraction — use individual product URLs when available
                    product_urls = self._get_product_urls(test_case)

                    # Browser-based tiers benefit from batch extraction (one browser, many URLs)
                    browser_tiers = {"css_generic", "smart_css", "llm"}
                    if tier_name in browser_tiers and len(product_urls) > 1:
                        extracted_products = await extractor.extract_batch(product_urls)
                    else:
                        extracted_products = []
                        for url in product_urls:
                            try:
                                products = await extractor.extract(url)
                                extracted_products.extend(products)
                            except Exception as e:
                                logger.warning("Extraction failed for %s: %s", url, e)

                duration = time.monotonic() - start_time

                # Get peak memory usage if profiling
                if self.profile:
                    _, peak = tracemalloc.get_traced_memory()
                    peak_memory_mb = peak / (1024 * 1024)

            finally:
                # Always stop tracemalloc if it was started
                if self.profile:
                    tracemalloc.stop()

            # Flatten tier-specific nested structures before scoring
            if tier_name == "schema_org":
                extracted_products = [
                    self._flatten_jsonld_product(p) for p in extracted_products
                ]
            elif tier_name == "opengraph":
                extracted_products = [
                    self._flatten_og_product(p) for p in extracted_products
                ]

            logger.info(
                "Tier '%s' extracted %d products in %.2fs",
                tier_name,
                len(extracted_products),
                duration,
            )

            # Score the results
            product_scores = Scorer.match_products(
                expected=test_case.products,
                extracted=extracted_products,
            )

            products_matched = len([ps for ps in product_scores if ps.extracted_title is not None])

            return TierResult(
                tier_name=tier_name,
                products_extracted=len(extracted_products),
                products_matched=products_matched,
                product_scores=product_scores,
                duration_seconds=duration,
                min_products=test_case.min_products,
                peak_memory_mb=peak_memory_mb,
                tokens_used=tokens_used,
                estimated_cost_usd=estimated_cost,
            )

        except Exception as e:
            logger.exception("Tier '%s' failed for %s: %s", tier_name, test_case.name, e)
            return TierResult(
                tier_name=tier_name,
                products_extracted=0,
                products_matched=0,
                product_scores=[],
                duration_seconds=0.0,
                error=str(e),
                min_products=test_case.min_products,
                peak_memory_mb=peak_memory_mb,
                tokens_used=tokens_used,
                estimated_cost_usd=estimated_cost,
            )

    @staticmethod
    def _flatten_og_product(product: dict) -> dict:
        """Flatten an OpenGraph product dict into scorer-compatible format.

        OpenGraph products have prefixed keys like "og:title", "og:price:amount", etc.
        This resolves them into flat key-value pairs matching the scorer's expected
        field names.
        """
        flat: dict[str, str] = {}

        if product.get("og:title"):
            flat["title"] = product["og:title"]
        if product.get("og:description"):
            flat["description"] = product["og:description"]
        if product.get("og:image"):
            flat["image_url"] = product["og:image"]
        if product.get("og:url"):
            flat["product_url"] = product["og:url"]

        # Price from og:price:amount or product:price:amount
        price = product.get("og:price:amount") or product.get("product:price:amount")
        if price:
            flat["price"] = str(price)

        # Currency
        currency = product.get("og:price:currency") or product.get("product:price:currency")
        if currency:
            flat["currency"] = currency

        # Availability — normalize spaces/underscores before checking
        avail = product.get("og:availability") or product.get("product:availability")
        if avail:
            avail_normalized = avail.lower().replace(" ", "").replace("_", "")
            flat["in_stock"] = str("instock" in avail_normalized).lower()

        # SKU
        sku = product.get("product:sku")
        if sku:
            flat["sku"] = sku

        # Vendor/brand
        brand = product.get("og:brand") or product.get("product:brand")
        if brand:
            flat["vendor"] = brand

        return flat

    @staticmethod
    def _flatten_jsonld_product(product: dict) -> dict:
        """Flatten a JSON-LD product dict into scorer-compatible format.

        JSON-LD products have nested offers, brand, and image structures.
        This resolves them into flat key-value pairs matching the scorer's
        expected field names.
        """
        flat: dict[str, str] = {}

        if product.get("name"):
            flat["title"] = product["name"]
        if product.get("description"):
            flat["description"] = product["description"]
        if product.get("sku"):
            flat["sku"] = product["sku"]
        if product.get("url"):
            flat["product_url"] = product["url"]

        # Brand: can be a dict {"@type": "Brand", "name": "X"} or a plain string
        brand = product.get("brand")
        if isinstance(brand, dict):
            brand_name = brand.get("name")
            if brand_name:
                flat["vendor"] = brand_name
        elif isinstance(brand, str) and brand:
            flat["vendor"] = brand

        # Image: can be a list of URLs, a single URL string, or a list of dicts
        image = product.get("image")
        if isinstance(image, list) and image:
            first = image[0]
            if isinstance(first, dict):
                flat["image_url"] = first.get("url") or first.get("contentUrl") or ""
            elif isinstance(first, str):
                flat["image_url"] = first
        elif isinstance(image, str) and image:
            flat["image_url"] = image

        # Offers: can be a single dict, a list, or nested under "offers"
        offers = product.get("offers")
        if isinstance(offers, dict):
            # Could be an AggregateOffer with sub-offers, or a single Offer
            if "offers" in offers:
                inner = offers["offers"]
                offers = inner if isinstance(inner, list) else [inner]
            else:
                offers = [offers]
        if isinstance(offers, list) and offers:
            offer = offers[0]
            if isinstance(offer, dict):
                if offer.get("price"):
                    flat["price"] = str(offer["price"])
                if offer.get("priceCurrency"):
                    flat["currency"] = offer["priceCurrency"]
                availability = offer.get("availability") or ""
                flat["in_stock"] = str("instock" in str(availability).lower()).lower()

        return flat

    @staticmethod
    def _flatten_shopify_product(product: dict, shop_url: str) -> dict:
        """Flatten a Shopify API product dict into scorer-compatible format.

        Shopify products have nested variants/images. This extracts the
        primary variant's price/sku/availability and constructs product_url
        from the handle.
        """
        flat: dict[str, str] = {}

        if product.get("title"):
            flat["title"] = product["title"]
        if product.get("vendor"):
            flat["vendor"] = product["vendor"]
        if product.get("product_type"):
            flat["product_type"] = product["product_type"]
        if product.get("body_html"):
            flat["description"] = product["body_html"]

        # Construct product URL from handle
        handle = product.get("handle")
        if handle:
            flat["product_url"] = f"{shop_url.rstrip('/')}/products/{handle}"

        # Primary image
        images = product.get("images") or []
        if images:
            src = images[0].get("src")
            if src:
                flat["image_url"] = src

        # Shop currency (injected by ShopifyAPIExtractor from cart_currency cookie)
        if product.get("_shop_currency"):
            flat["currency"] = product["_shop_currency"]

        # First variant: price, sku, availability
        variants = product.get("variants") or []
        if variants:
            v = variants[0]
            if v.get("price"):
                flat["price"] = v["price"]
            if v.get("sku"):
                flat["sku"] = v["sku"]
            if "available" in v:
                flat["in_stock"] = str(v["available"]).lower()

        return flat

    @staticmethod
    def _flatten_wc_product(product: dict, shop_url: str) -> dict:
        """Flatten a WooCommerce Store API product dict into scorer-compatible format.

        WC Store API products have nested prices, images, categories, and brands.
        This resolves them into flat key-value pairs.
        """
        flat: dict[str, str] = {}

        if product.get("name"):
            flat["title"] = product["name"]
        if product.get("sku"):
            flat["sku"] = product["sku"]
        if product.get("permalink"):
            flat["product_url"] = product["permalink"]

        # Description (prefer short_description, fall back to description)
        desc = product.get("short_description") or product.get("description") or ""
        if desc:
            # Strip HTML tags for comparison
            flat["description"] = re.sub(r"<[^>]+>", "", desc).strip()

        # Price: WC Store API stores price as integer (minor units)
        prices = product.get("prices", {})
        if prices.get("price"):
            minor_unit = prices.get("currency_minor_unit", 2)
            try:
                raw_price = int(prices["price"])
                flat["price"] = f"{raw_price / (10 ** minor_unit):.2f}"
            except (ValueError, TypeError):
                pass
        if prices.get("currency_code"):
            flat["currency"] = prices["currency_code"]

        # Image
        images = product.get("images", [])
        if images:
            src = images[0].get("src")
            if src:
                flat["image_url"] = src

        # Stock
        if "is_in_stock" in product:
            flat["in_stock"] = str(product["is_in_stock"]).lower()

        # Vendor from brands or attributes
        brands = product.get("brands", [])
        if brands:
            flat["vendor"] = brands[0].get("name", "")
        else:
            for attr in product.get("attributes", []):
                if attr.get("name", "").lower() in ("brand", "vendor", "manufacturer"):
                    terms = attr.get("terms", [])
                    if terms:
                        flat["vendor"] = terms[0].get("name", "")
                        break

        # Product type from categories
        categories = product.get("categories", [])
        if categories:
            flat["product_type"] = categories[0].get("name", "")

        return flat

    @staticmethod
    def _flatten_magento_product(product: dict, shop_url: str) -> dict:
        """Flatten a Magento REST API product dict into scorer-compatible format.

        Magento products have custom_attributes for price, description, images, etc.
        """
        flat: dict[str, str] = {}

        if product.get("name"):
            flat["title"] = product["name"]
        if product.get("sku"):
            flat["sku"] = product["sku"]

        # Construct URL from URL key
        url_key = None
        for attr in product.get("custom_attributes", []):
            if attr.get("attribute_code") == "url_key":
                url_key = attr.get("value")
                break
        if url_key:
            flat["product_url"] = f"{shop_url.rstrip('/')}/{url_key}.html"

        # Price
        if product.get("price") is not None:
            flat["price"] = f"{float(product['price']):.2f}"

        # Custom attributes: description, image, etc.
        for attr in product.get("custom_attributes", []):
            code = attr.get("attribute_code", "")
            value = attr.get("value", "")
            if code == "description" and value:
                flat["description"] = re.sub(r"<[^>]+>", "", str(value)).strip()
            elif code == "short_description" and "description" not in flat and value:
                flat["description"] = re.sub(r"<[^>]+>", "", str(value)).strip()
            elif code == "image" and value:
                flat["image_url"] = f"{shop_url.rstrip('/')}/media/catalog/product{value}"

        # Stock status
        ext_attrs = product.get("extension_attributes", {})
        stock = ext_attrs.get("stock_item", {})
        if "is_in_stock" in stock:
            flat["in_stock"] = str(stock["is_in_stock"]).lower()

        return flat

    def _create_extractor(self, tier_name: str):
        """Create an extractor instance for the given tier name.

        Args:
            tier_name: Name of the tier ("schema_org", "opengraph", "css_generic", "smart_css", "llm")

        Returns:
            Extractor instance

        Raises:
            ValueError: If tier_name is unknown
            ImportError: If tier dependencies are missing
        """
        if tier_name == "shopify_api":
            from app.extractors.shopify_api import ShopifyAPIExtractor

            return ShopifyAPIExtractor(max_pages=5)

        elif tier_name == "woocommerce_api":
            from app.extractors.woocommerce_api import WooCommerceAPIExtractor

            return WooCommerceAPIExtractor(max_pages=5)

        elif tier_name == "magento_api":
            from app.extractors.magento_api import MagentoAPIExtractor

            return MagentoAPIExtractor(page_size=100)

        elif tier_name in ("schema_org", "opengraph"):
            raise ValueError(
                f"Online mode not supported for {tier_name} -- "
                f"extract(url) has been removed. Use offline mode (extract_from_html) "
                f"or the unified_crawl tier instead."
            )

        elif tier_name == "css_generic":
            from app.extractors.css_extractor import CSSExtractor
            from app.extractors.schemas.generic import GENERIC_SCHEMA

            return CSSExtractor(GENERIC_SCHEMA, stealth_level=self.stealth_level)

        elif tier_name == "smart_css":
            import os

            from app.config import settings
            from app.extractors.schema_cache import SchemaCache
            from app.extractors.smart_css_extractor import SmartCSSExtractor

            # Create LLM config from settings
            llm_config = settings.create_llm_config()
            if not llm_config:
                raise ValueError(
                    "SmartCSS tier requires LLM configuration. "
                    "Set LLM_API_KEY environment variable."
                )

            # Create Redis-backed schema cache
            try:
                import redis.asyncio as aioredis

                redis_client = aioredis.from_url(
                    settings.redis_url,
                    decode_responses=False,
                )
                cache = SchemaCache(redis_client=redis_client, ttl=settings.schema_cache_ttl)
            except Exception as e:
                logger.warning(
                    "Failed to initialize Redis for schema cache: %s. "
                    "Using in-memory fallback (no persistence).",
                    e,
                )
                # Fallback to in-memory cache
                from evals.memory_cache import InMemorySchemaCache

                cache = InMemorySchemaCache()

            return SmartCSSExtractor(
                llm_config=llm_config,
                schema_cache=cache,
                stealth_level=self.stealth_level,
            )

        elif tier_name == "llm":
            from app.config import settings
            from app.extractors.llm_extractor import LLMExtractor

            # Create LLM config from settings
            llm_config = settings.create_llm_config()
            if not llm_config:
                raise ValueError(
                    "LLM tier requires LLM configuration. "
                    "Set LLM_API_KEY environment variable."
                )

            return LLMExtractor(
                llm_config=llm_config,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
                stealth_level=self.stealth_level,
            )

        else:
            raise ValueError(f"Unknown tier: {tier_name}")

    async def run_all(self, test_cases: list[TestCase]) -> list[EvalReport]:
        """Run evaluation on multiple test cases sequentially.

        Args:
            test_cases: List of test cases to evaluate

        Returns:
            List of EvalReports, one per test case
        """
        reports = []
        for test_case in test_cases:
            report = await self.run(test_case)
            reports.append(report)

        return reports
