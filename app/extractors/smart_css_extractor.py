"""Auto-generating CSS extractor — uses LLM once per domain to create selectors, then reuses."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, Comment
from crawl4ai import AsyncWebCrawler, LLMConfig
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import (
    StealthLevel,
    get_browser_config,
    get_crawl_config,
    get_crawler_strategy,
)

if TYPE_CHECKING:
    from app.extractors.schema_cache import SchemaCache

logger = logging.getLogger(__name__)

SCHEMA_GENERATION_QUERY = (
    "This is a SINGLE product detail page with exactly ONE product. "
    "The baseSelector must match the ONE main product info container. "
    "Generate CSS selectors for exactly these fields: "
    "title (main product heading h1/h2), price (sale or regular price text), "
    "currency (ISO 4217 code if shown), description (product description paragraph), "
    "image_url (main product image src attribute), sku (product SKU or ID), "
    "in_stock (stock/availability text), vendor (brand name), "
    "product_url (canonical link), product_type (product category). "
    "Use class names and data attributes — never nth-child. "
    "Do NOT target variant pickers, color swatches, review widgets, or FAQ sections."
)

TARGET_JSON_EXAMPLE = json.dumps({
    "title": "Product Name",
    "price": "29.99",
    "currency": "USD",
    "description": "Product description text",
    "image_url": "https://example.com/product-image.jpg",
    "sku": "SKU-001",
    "in_stock": "true",
    "vendor": "Brand Name",
    "product_url": "https://example.com/products/product-name",
    "product_type": "Headphones",
})


class SmartCSSExtractor(BaseExtractor):
    """Auto-generates CSS selectors per domain via LLM, caches and reuses them.

    First call for a domain: fetches page HTML, calls generate_schema() with LLM, caches result.
    Subsequent calls: loads cached schema, uses JsonCssExtractionStrategy (zero LLM cost).
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        schema_cache: SchemaCache,
        stealth_level: StealthLevel = StealthLevel.STANDARD,
    ):
        """Initialize SmartCSS extractor.

        Args:
            llm_config: crawl4ai LLMConfig for schema generation
            schema_cache: Redis-backed schema cache
            stealth_level: Anti-bot protection tier for browser sessions
        """
        self.llm_config = llm_config
        self.cache = schema_cache
        self.stealth_level = stealth_level

    async def _fetch_html_for_schema(self, url: str) -> str | None:
        """Fetch page HTML for schema generation using a headless browser.

        Prefers crawl4ai's ``fit_html`` (content-only HTML with navigation,
        headers, footers stripped) over raw HTML.  Falls back to
        ``_extract_product_region()`` when ``fit_html`` is not available.

        Uses AsyncWebCrawler with stealth settings to get the JS-rendered DOM.
        This is critical for SPAs and Shopify themes that render product
        details client-side.
        """
        try:
            browser_config = get_browser_config(self.stealth_level, text_mode=False)
            crawler_config = get_crawl_config(stealth_level=self.stealth_level)
            crawler_strategy = get_crawler_strategy(self.stealth_level, browser_config)
            async with AsyncWebCrawler(
                config=browser_config,
                crawler_strategy=crawler_strategy,
            ) as crawler:
                result = await crawler.arun(url=url, config=crawler_config)
                if not result.success:
                    logger.error(
                        "Browser fetch failed for schema generation from %s: %s",
                        url, result.error_message,
                    )
                    return None

                # Prefer fit_html (crawl4ai's content-focused HTML) over raw HTML
                fit = getattr(result, "fit_html", None)
                if fit:
                    logger.debug("Using fit_html (%d bytes) for schema generation from %s", len(fit), url)
                    return fit

                # Fallback: strip page chrome with BeautifulSoup heuristics
                if result.html:
                    logger.debug("fit_html not available, falling back to _extract_product_region for %s", url)
                    return self._extract_product_region(result.html)

                return None
        except Exception as e:
            logger.error("Failed to fetch HTML for schema generation from %s: %s", url, e)
            return None

    # Max HTML bytes to send to generate_schema() LLM call
    _MAX_SCHEMA_HTML_BYTES = 150_000

    @staticmethod
    def _extract_product_region(html: str) -> str:
        """Extract the product-relevant DOM region from full-page HTML.

        Fallback for when crawl4ai's ``fit_html`` is not available.  Removes
        header, footer, nav, aside, variant pickers, reviews, media galleries,
        and other non-product sections, then looks for a product info container.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Remove page chrome -- these never contain product data
        for tag in soup.find_all([
            "script", "style", "svg", "noscript", "iframe",
            "header", "footer", "nav", "aside", "form",
            "link", "meta",
        ]):
            tag.decompose()

        # Remove variant pickers (Shopify custom elements and common patterns)
        for tag in soup.find_all(["variant-radios", "variant-selects"]):
            tag.decompose()

        # Remove media galleries (huge, just need one image reference)
        noise_selectors = [
            "[class*='review']", "[class*='yotpo']",
            "[class*='faq']", "[class*='accordion']",
            "[class*='related-product']", "[class*='recommendation']",
            "[class*='upsell']", "[class*='cross-sell']",
            "[data-reviews]", "[data-related-products]",
            "[class*='media-list']", "[class*='gallery']",
            "[class*='slider']", "[class*='carousel']",
        ]
        for selector in noise_selectors:
            for tag in soup.select(selector):
                tag.decompose()

        # Strip HTML comments
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        # Try to find a product info container -- prefer info wrappers over
        # full product wrappers (which include media galleries, reviews, etc.)
        product_selectors = [
            # Info-specific wrappers (title + price + description area)
            ".product__info-wrapper",
            ".product-info",
            ".product__info",
            ".product-detail__info",
            ".product-single__meta",
            # Standard product containers
            "[data-component-type='product']",
            ".product-detail",
            ".product-single",
            ".product-container",
            "#product",
            ".product",
            "main",
            "[role='main']",
            "#main",
            "#content",
            ".main-content",
        ]

        for selector in product_selectors:
            container = soup.select_one(selector)
            if container and len(str(container)) > 200:
                return str(container)

        # Fallback: return body (already stripped of chrome)
        body = soup.find("body")
        return str(body) if body else str(soup)

    @staticmethod
    def _score_selector_robustness(schema: dict) -> float:
        """Score how robust the CSS selectors are (0.0-1.0).

        attribute-based ([data-*], [itemprop]) = 1.0
        class-based (.product-title) = 0.8
        tag-based (h1, span) = 0.5
        nth-child = 0.2
        """
        scores = []
        for field_def in schema.get("fields", []):
            selector = field_def.get("selector", "")
            if re.search(r':nth-child\(\d+\)', selector):
                scores.append(0.2)
            elif re.search(r'\[[\w-]+', selector):  # attribute selector
                scores.append(1.0)
            elif '.' in selector:  # class selector
                scores.append(0.8)
            else:
                scores.append(0.5)

        # Also check baseSelector
        base = schema.get("baseSelector", "")
        if re.search(r':nth-child\(\d+\)', base):
            scores.append(0.2)
        elif re.search(r'\[[\w-]+', base):
            scores.append(1.0)
        elif '.' in base:
            scores.append(0.8)
        else:
            scores.append(0.5)

        return sum(scores) / len(scores) if scores else 0.0

    async def _validate_schema(self, schema: dict, sample_htmls: list[str]) -> bool:
        """Validate that a generated schema extracts products from all sample pages.

        Returns True if the schema extracts at least 1 product from each sample.
        """
        for html in sample_htmls:
            try:
                # Use BeautifulSoup to apply CSS selectors directly
                soup = BeautifulSoup(html, "html.parser")
                base_selector = schema.get("baseSelector", "")
                if not base_selector:
                    return False

                # Try to find at least one element matching the base selector
                containers = soup.select(base_selector)
                if not containers:
                    logger.warning("Schema validation failed: baseSelector '%s' matched 0 elements", base_selector)
                    return False

                # Check if at least one field can be extracted
                fields = schema.get("fields", [])
                if not fields:
                    return False

                found_data = False
                for container in containers[:1]:  # Check first match only
                    for field_def in fields:
                        field_selector = field_def.get("selector", "")
                        if not field_selector:
                            continue
                        elements = container.select(field_selector)
                        if elements and elements[0].get_text(strip=True):
                            found_data = True
                            break
                    if found_data:
                        break

                if not found_data:
                    logger.warning("Schema validation failed: no field data extracted from sample")
                    return False

            except Exception as e:
                logger.warning("Schema validation error: %s", e)
                return False

        logger.info("Schema validation passed: extracts data from all %d samples", len(sample_htmls))
        return True

    async def _generate_schema(self, html: str) -> dict | None:
        """Generate CSS extraction schema from sample HTML using LLM.

        Expects HTML that has already been reduced to the product region
        (via fit_html or _extract_product_region).  Truncates to
        _MAX_SCHEMA_HTML_BYTES before sending to the LLM.
        """
        try:
            if len(html) > self._MAX_SCHEMA_HTML_BYTES:
                html = html[: self._MAX_SCHEMA_HTML_BYTES]
                # Avoid cutting mid-tag -- find last '>' before the limit
                last_close = html.rfind(">")
                if last_close > 0:
                    html = html[: last_close + 1]
            logger.info(
                "HTML reduced to %d bytes for schema generation",
                len(html),
            )
            schema = JsonCssExtractionStrategy.generate_schema(
                html=html,
                schema_type="CSS",
                query=SCHEMA_GENERATION_QUERY,
                target_json_example=TARGET_JSON_EXAMPLE,
                llm_config=self.llm_config,
            )
            if not schema or not schema.get("baseSelector") or not schema.get("fields"):
                logger.warning("LLM generated invalid schema (missing baseSelector or fields)")
                return None

            # Check selector robustness
            robustness_score = self._score_selector_robustness(schema)
            logger.info("Generated CSS schema with baseSelector='%s', %d fields, robustness=%.2f",
                        schema.get("baseSelector"), len(schema.get("fields", [])), robustness_score)

            if robustness_score < 0.3:
                logger.warning("Generated schema has very low robustness score (%.2f) -- selectors are too brittle",
                              robustness_score)
                return None

            if robustness_score < 0.5:
                logger.info("Generated schema has moderate robustness score (%.2f) -- proceeding with caution",
                            robustness_score)

            return schema
        except Exception as e:
            logger.error("Schema generation failed: %s", e)
            return None

    async def _get_or_generate_schema(self, url: str, sample_urls: list[str] | None = None) -> dict | None:
        """Get cached schema or generate a new one.

        Args:
            url: Primary URL to generate schema from
            sample_urls: Optional list of additional product URLs for multi-sample validation

        Returns:
            Generated and validated CSS schema, or None if generation/validation fails
        """
        # Try cache first
        schema = await self.cache.get(url)
        if schema:
            return schema

        # Fetch HTML from primary URL (prefers fit_html, falls back to DOM stripping)
        html = await self._fetch_html_for_schema(url)
        if not html:
            return None

        # Generate schema from primary HTML
        schema = await self._generate_schema(html)
        if not schema:
            return None

        # Multi-sample validation if sample URLs provided
        if sample_urls and len(sample_urls) > 1:
            logger.info("Validating schema against %d sample URLs", len(sample_urls))
            sample_htmls = [html]  # Include primary HTML

            # Fetch additional samples (skip first URL since it's the primary)
            for sample_url in sample_urls[1:]:
                sample_html = await self._fetch_html_for_schema(sample_url)
                if sample_html:
                    sample_htmls.append(sample_html)

            # Validate schema works on all samples
            if len(sample_htmls) > 1:
                is_valid = await self._validate_schema(schema, sample_htmls)
                if not is_valid:
                    logger.warning("Schema failed multi-sample validation, rejecting")
                    return None
                logger.info("Schema passed multi-sample validation with %d samples", len(sample_htmls))

        # Cache for reuse
        await self.cache.set(url, schema)
        return schema

    async def extract(self, url: str) -> ExtractorResult:
        """Extract products using auto-generated CSS selectors.

        Args:
            url: Product page URL

        Returns:
            ExtractorResult with products or error details.
        """
        schema = await self._get_or_generate_schema(url)
        if not schema:
            return ExtractorResult(products=[], complete=False, error="Schema generation failed")

        try:
            browser_config = get_browser_config(self.stealth_level)
            extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)
            crawler_config = get_crawl_config(
                stealth_level=self.stealth_level,
                extraction_strategy=extraction_strategy,
            )

            crawler_strategy = get_crawler_strategy(self.stealth_level, browser_config)
            async with AsyncWebCrawler(
                config=browser_config,
                crawler_strategy=crawler_strategy,
            ) as crawler:
                result = await crawler.arun(url=url, config=crawler_config)

                if not result.success:
                    logger.error("SmartCSS crawl failed for %s: %s", url, result.error_message)
                    return ExtractorResult(products=[], complete=False, error=f"Crawl failed: {result.error_message}")

                if not result.extracted_content:
                    logger.warning("SmartCSS returned no content for %s", url)
                    return ExtractorResult(products=[], complete=False, error="No content extracted")

                try:
                    extracted = json.loads(result.extracted_content)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse SmartCSS output for %s: %s", url, e)
                    return ExtractorResult(products=[], complete=False, error=f"JSON parse error: {e}")

                if isinstance(extracted, dict):
                    products = [extracted] if extracted else []
                elif isinstance(extracted, list):
                    products = [p for p in extracted if isinstance(p, dict)]
                else:
                    products = []

                # If cached schema produced 0 results, invalidate and retry once
                if not products:
                    cached = await self.cache.get(url)
                    if cached:
                        logger.info("SmartCSS cached schema produced 0 results for %s, invalidating", url)
                        await self.cache.invalidate(url)
                    return ExtractorResult(products=[])

                logger.info("SmartCSS extracted %d products from %s", len(products), url)
                return ExtractorResult(products=products)

        except Exception as e:
            logger.exception("SmartCSS extraction failed for %s: %s", url, e)
            return ExtractorResult(products=[], complete=False, error=str(e))

    async def extract_batch(self, urls: list[str]) -> ExtractorResult:
        """Extract products from multiple URLs using a single browser instance.

        Generates/fetches CSS schema from the first URL, then uses arun_many()
        to crawl all URLs concurrently with that schema.
        """
        if not urls:
            return ExtractorResult(products=[])

        # Get or generate schema from first URL with multi-sample validation
        sample_urls = urls[:3] if len(urls) >= 3 else urls
        schema = await self._get_or_generate_schema(urls[0], sample_urls=sample_urls)
        if not schema:
            return ExtractorResult(products=[], complete=False, error="Schema generation failed")

        browser_config = get_browser_config(self.stealth_level)
        extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)
        crawler_config = get_crawl_config(
            stealth_level=self.stealth_level,
            extraction_strategy=extraction_strategy,
        )
        dispatcher = MemoryAdaptiveDispatcher(
            max_session_permit=5,
            memory_threshold_percent=70.0,
        )

        all_products = []
        error: str | None = None
        try:
            crawler_strategy = get_crawler_strategy(self.stealth_level, browser_config)
            async with AsyncWebCrawler(
                config=browser_config,
                crawler_strategy=crawler_strategy,
            ) as crawler:
                results = await crawler.arun_many(
                    urls=urls,
                    config=crawler_config,
                    dispatcher=dispatcher,
                )
                for result in results:
                    if not result.success or not result.extracted_content:
                        continue
                    try:
                        extracted = json.loads(result.extracted_content)
                        if isinstance(extracted, list):
                            all_products.extend(
                                p for p in extracted if isinstance(p, dict)
                            )
                        elif isinstance(extracted, dict) and extracted:
                            all_products.append(extracted)
                    except json.JSONDecodeError:
                        logger.error("Failed to parse SmartCSS JSON from %s", result.url)
        except Exception as e:
            logger.exception("Batch SmartCSS extraction failed: %s", e)
            error = str(e)

        if not all_products:
            # Invalidate cache if batch produced nothing
            cached = await self.cache.get(urls[0])
            if cached:
                logger.info("SmartCSS batch produced 0 results, invalidating cached schema")
                await self.cache.invalidate(urls[0])

        return ExtractorResult(products=all_products, complete=error is None, error=error)
