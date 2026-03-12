"""Unified crawl extractor — one crawl, all extraction layers.

Replaces the separate Schema.org + OpenGraph HTTP fetch probes with a single
crawl4ai crawl that extracts from every available data layer:

  Layer 1: JSON-LD from result.html (via SchemaOrgExtractor.extract_from_html)
  Layer 2: OG tags from result.metadata + result.html (via OpenGraphExtractor)
  Layer 3: Price/title from result.markdown (via MarkdownPriceExtractor)
  Layer 4: Best image from result.media (scored, no re-fetch)

Layer 1 wins; gaps are filled by successive layers without overwriting.

httpx fast path: fetches HTML via httpx first. If JSON-LD yields a product
with both price and image, returns immediately (no browser). When price or
image is missing, upgrades to browser crawl for rendered markdown + media.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx
from app.config import MAX_RESPONSE_SIZE
from app.extractors import markdown_price_extractor
from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import (
    DEFAULT_HEADERS,
    StealthLevel,
    get_browser_config,
    get_crawl_config,
    get_crawler_strategy,
    get_default_user_agent,
)
from app.extractors.opengraph_extractor import OpenGraphExtractor
from app.extractors.schema_org_extractor import SchemaOrgExtractor

logger = logging.getLogger(__name__)

# Minimum image score from crawl4ai media to consider "good enough"
_MIN_IMAGE_SCORE = 3


class UnifiedCrawlExtractor(BaseExtractor):
    """Extract product data by crawling once and layering all parsers on the result.

    Constructor args:
        stealth_level: Anti-bot tier for browser-based crawling.
        http_client: Optional shared httpx.AsyncClient (closed by caller).
    """

    _ESCALATION_ORDER = [StealthLevel.STANDARD, StealthLevel.STEALTH, StealthLevel.UNDETECTED]

    def __init__(
        self,
        stealth_level: StealthLevel = StealthLevel.STANDARD,
        http_client: httpx.AsyncClient | None = None,
    ):
        self._stealth_level = stealth_level
        self._http_client = http_client

    # ── Public API ─────────────────────────────────────────────────────

    async def extract(self, shop_url: str) -> ExtractorResult:
        """Extract product data from a single URL.

        Fast path: httpx fetch → JSON-LD + OG parsing. If product has price +
        image, returns without launching a browser. Otherwise upgrades to
        browser crawl for markdown / media extraction.
        """
        url = shop_url
        # --- httpx fast path ---
        html = await self._fetch_html_httpx(url)
        if html:
            products = self._extract_structured_from_html(html, url)
            if products and all(self._has_price_and_image(p) for p in products):
                return ExtractorResult(products=products)
            # HTML fetched but structured data incomplete — try browser
            httpx_products = products
        else:
            httpx_products = []

        # --- Browser path ---
        browser_products = await self._extract_with_browser(url)
        if browser_products:
            return ExtractorResult(products=browser_products)

        # Return whatever httpx found (may be partial)
        if httpx_products:
            return ExtractorResult(products=httpx_products)

        return ExtractorResult(products=[])

    async def extract_batch(self, urls: list[str]) -> ExtractorResult:
        """Extract from multiple URLs using a single browser via arun_many().

        Always uses browser path for batch (amortises browser startup across URLs).
        """
        if not urls:
            return ExtractorResult(products=[])

        from crawl4ai import AsyncWebCrawler
        from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher

        browser_config = get_browser_config(self._stealth_level)
        crawl_config = get_crawl_config(
            stealth_level=self._stealth_level,
            scan_full_page=True,
        )
        dispatcher = MemoryAdaptiveDispatcher(
            max_session_permit=5,
            memory_threshold_percent=70.0,
        )

        all_products: list[dict] = []
        error: str | None = None

        try:
            crawler_strategy = get_crawler_strategy(self._stealth_level, browser_config)
            async with AsyncWebCrawler(
                config=browser_config,
                crawler_strategy=crawler_strategy,
            ) as crawler:
                results = await crawler.arun_many(
                    urls=urls,
                    config=crawl_config,
                    dispatcher=dispatcher,
                )
                for result in results:
                    if not result.success:
                        logger.warning(
                            "Unified crawl failed for %s: %s",
                            result.url,
                            getattr(result, "error_message", "unknown"),
                        )
                        continue
                    products = self._extract_from_crawl_result(result, result.url)
                    all_products.extend(products)
        except Exception as e:
            logger.exception("Batch unified crawl failed: %s", e)
            error = str(e)

        return ExtractorResult(
            products=all_products,
            complete=error is None,
            error=error,
        )

    # ── httpx fast path ────────────────────────────────────────────────

    async def _fetch_html_httpx(self, url: str) -> str | None:
        """Fetch HTML via httpx. Returns None on error or bot protection."""
        try:
            headers = {**DEFAULT_HEADERS, "User-Agent": get_default_user_agent()}
            client = self._http_client or httpx.AsyncClient(
                follow_redirects=True, timeout=30.0, headers=headers,
            )
            try:
                response = await client.get(url)
                response.raise_for_status()

                content_length = int(response.headers.get("content-length", 0))
                if content_length > MAX_RESPONSE_SIZE:
                    logger.warning("Response too large (%d) from %s", content_length, url)
                    return None

                html = response.text
                if len(html) > MAX_RESPONSE_SIZE:
                    logger.warning("Response body too large (%d) from %s", len(html), url)
                    return None

                return html
            finally:
                if self._http_client is None:
                    await client.aclose()

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (403, 429, 503):
                logger.debug("httpx blocked (%d) for %s, will try browser", e.response.status_code, url)
            else:
                logger.warning("HTTP %d fetching %s", e.response.status_code, url)
            return None
        except httpx.RequestError as e:
            logger.warning("Request error fetching %s: %s", url, e)
            return None

    @staticmethod
    def _extract_structured_from_html(html: str, url: str) -> list[dict]:
        """Parse JSON-LD + OG from raw HTML (no browser needed)."""
        products = SchemaOrgExtractor.extract_from_html(html, url)
        if products:
            # Enrich with OG data from same HTML
            og_list = OpenGraphExtractor.extract_from_html(html, url)
            if og_list:
                og = og_list[0]
                for product in products:
                    _fill_gaps_from_og(product, og)
            return products

        # No JSON-LD — try OG-only extraction
        og_list = OpenGraphExtractor.extract_from_html(html, url)
        if og_list:
            return og_list

        return []

    # ── Browser path ───────────────────────────────────────────────────

    async def _extract_with_browser(self, url: str) -> list[dict]:
        """Full browser crawl with stealth escalation, extracting all layers."""
        from crawl4ai import AsyncWebCrawler

        for level in self._ESCALATION_ORDER:
            if self._ESCALATION_ORDER.index(level) < self._ESCALATION_ORDER.index(self._stealth_level):
                continue

            browser_config = get_browser_config(level)
            crawl_config = get_crawl_config(stealth_level=level, scan_full_page=True)
            crawler_strategy = get_crawler_strategy(level, browser_config)

            try:
                async with AsyncWebCrawler(
                    config=browser_config,
                    crawler_strategy=crawler_strategy,
                ) as crawler:
                    result = await crawler.arun(url=url, config=crawl_config)

                if not result.success:
                    logger.warning(
                        "Browser crawl (%s) failed for %s: %s",
                        level.value, url, getattr(result, "error_message", "unknown"),
                    )
                    continue

                products = self._extract_from_crawl_result(result, url)
                if products:
                    return products

            except Exception as e:
                logger.warning("Browser crawl (%s) error for %s: %s", level.value, url, e)
                continue

        return []

    # ── Core extraction from CrawlResult ───────────────────────────────

    @staticmethod
    def _extract_from_crawl_result(result: Any, url: str) -> list[dict]:
        """Layer all extraction strategies on a single CrawlResult.

        Layer priority: JSON-LD > OG tags > markdown > media images.
        Gaps are filled without overwriting.
        """
        html = getattr(result, "html", "") or ""
        metadata = getattr(result, "metadata", {}) or {}
        markdown = getattr(result, "markdown", "") or ""
        fit_markdown = getattr(result, "fit_markdown", "") or ""
        media = getattr(result, "media", {}) or {}

        # Layer 1: JSON-LD from HTML
        products = SchemaOrgExtractor.extract_from_html(html, url) if html else []

        # Layer 2: OG tags (from crawl4ai metadata + HTML product:* tags)
        og_from_meta = OpenGraphExtractor.from_metadata(metadata) if metadata else []
        og_from_html = OpenGraphExtractor.extract_from_html(html, url) if html else []
        og = _merge_og(og_from_meta, og_from_html)

        # Layer 3: Markdown price/title
        md_text = fit_markdown or markdown
        md_data = markdown_price_extractor.extract(md_text, url) if md_text else {}

        # Layer 4: Best image from media
        best_image = _extract_best_image(media)

        if products:
            # Deduplicate (pages with @graph + standalone JSON-LD produce dupes)
            products = _deduplicate_products(products)
            # Enrich existing JSON-LD products
            for product in products:
                if og:
                    _fill_gaps_from_og(product, og)
                _fill_gaps_from_markdown(product, md_data)
                if best_image:
                    _fill_image(product, best_image)
            return products

        # No JSON-LD — build product from OG + markdown + media.
        # Require at least one pricing signal to avoid extracting blog/collection
        # pages as products. OG title + image alone is not sufficient.
        if og or md_data:
            product: dict = {}
            if og:
                product.update(og)
            _fill_gaps_from_markdown(product, md_data)
            if best_image:
                _fill_image(product, best_image)
            if product and _has_product_signal(product, og):
                return [product]

        return []

    @staticmethod
    def _has_price_and_image(product: dict) -> bool:
        """Check if product has both price and image (httpx fast path gate)."""
        has_price = bool(
            _get_price(product)
        )
        has_image = bool(
            product.get("image")
            or product.get("og:image")
        )
        return has_price and has_image


# ── Helper functions (module-level, stateless) ─────────────────────────


def _get_price(product: dict) -> str | None:
    """Extract price from product dict (handles Schema.org offers + flat keys)."""
    # Direct price key
    price = product.get("price")
    if price and str(price).strip() and str(price).strip() != "0":
        return str(price)

    # Schema.org offers
    offers = product.get("offers")
    if isinstance(offers, dict):
        p = offers.get("price")
        if p and str(p).strip() and str(p).strip() != "0":
            return str(p)
    elif isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                p = offer.get("price")
                if p and str(p).strip() and str(p).strip() != "0":
                    return str(p)

    # OG price tags
    for key in ("og:price:amount", "product:price:amount"):
        val = product.get(key)
        if val and str(val).strip() and str(val).strip() != "0":
            return str(val)

    return None


def _fill_gaps_from_og(product: dict, og: dict) -> None:
    """Fill missing fields in product from OG data. Never overwrites."""
    if not og:
        return

    mapping = {
        "og:title": "name",
        "og:image": "og:image",
        "og:description": "description",
        "og:url": "url",
        "og:price:amount": "og:price:amount",
        "product:price:amount": "product:price:amount",
        "product:price:currency": "product:price:currency",
    }

    for og_key, product_key in mapping.items():
        val = og.get(og_key)
        if val and not product.get(product_key):
            product[product_key] = val

    # Also fill the image field directly if missing
    if not product.get("image") and og.get("og:image"):
        product["og:image"] = og["og:image"]


def _fill_gaps_from_markdown(product: dict, md_data: dict) -> None:
    """Fill missing fields from markdown extraction. Never overwrites."""
    if not md_data:
        return

    if md_data.get("name") and not product.get("name") and not product.get("og:title"):
        product["name"] = md_data["name"]

    if md_data.get("price") and not _get_price(product):
        product["price"] = md_data["price"]
        if md_data.get("currency"):
            if not product.get("priceCurrency") and not product.get("product:price:currency"):
                product["priceCurrency"] = md_data["currency"]


def _fill_image(product: dict, image_url: str) -> None:
    """Fill image if missing."""
    if not product.get("image") and not product.get("og:image"):
        product["og:image"] = image_url


def _extract_best_image(media: dict | list) -> str | None:
    """Pick the highest-scored image from crawl4ai result.media.

    crawl4ai media format: {"images": [{"src": "...", "score": N, ...}, ...]}
    """
    images = []
    if isinstance(media, dict):
        images = media.get("images", [])
    elif isinstance(media, list):
        images = media

    if not images:
        return None

    # Sort by score descending, pick first with score >= threshold
    scored = [
        img for img in images
        if isinstance(img, dict) and img.get("src") and isinstance(img.get("score", 0), (int, float))
    ]
    if not scored:
        return None

    scored.sort(key=lambda img: img.get("score", 0), reverse=True)
    best = scored[0]
    if best.get("score", 0) >= _MIN_IMAGE_SCORE:
        return best["src"]

    # No high-score image, return first with a src anyway
    return scored[0]["src"] if scored else None


def _has_product_signal(product: dict, og: dict) -> bool:
    """Check if non-JSON-LD extraction has enough signal to be a real product.

    When no Schema.org Product JSON-LD is found, we need at least one of:
    - A price from OG product:price tags (og:price:amount or product:price:amount)
    - A price from markdown extraction
    - An OG type indicating a product (og:type == "product" or "og:type" == "product.item")

    This prevents blog posts, collection pages, and other non-product pages
    from being extracted as products just because they have og:title + og:image.
    """
    # OG product type tag is strong signal
    og_type = og.get("og:type", "").lower() if og else ""
    if "product" in og_type:
        return True

    # OG price tags are strong signal
    for key in ("og:price:amount", "product:price:amount"):
        val = product.get(key) or (og.get(key) if og else None)
        if val and str(val).strip() and str(val).strip() != "0":
            return True

    # Markdown-extracted price (already validated by regex)
    if product.get("price"):
        return True

    return False


def _deduplicate_products(products: list[dict]) -> list[dict]:
    """Remove duplicate products extracted from the same page.

    Pages with both @graph and standalone JSON-LD blocks can produce the same
    product twice. Deduplicates by name+price+sku hash, keeping the more
    complete record. Includes SKU to distinguish genuine variants with the
    same name and price.
    """
    if len(products) <= 1:
        return products

    seen: dict[str, dict] = {}
    for product in products:
        name = (product.get("name") or product.get("og:title") or "").strip().lower()
        price = str(_get_price(product) or "")
        sku = str(product.get("sku") or product.get("productID") or "")
        key = hashlib.md5(f"{name}:{price}:{sku}".encode()).hexdigest()

        if key in seen:
            existing = seen[key]
            # Keep the record with more fields
            if sum(1 for v in product.values() if v) > sum(1 for v in existing.values() if v):
                seen[key] = product
        else:
            seen[key] = product

    deduped = list(seen.values())
    if len(deduped) < len(products):
        logger.debug("Deduplicated %d → %d products", len(products), len(deduped))
    return deduped


def _merge_og(og_from_meta: list[dict], og_from_html: list[dict]) -> dict:
    """Merge OG data from crawl4ai metadata and HTML parsing.

    metadata has og:* keys; HTML parsing also captures product:* namespace.
    HTML wins for product:* tags (not in metadata).
    """
    merged: dict = {}
    if og_from_meta:
        merged.update(og_from_meta[0])
    if og_from_html:
        for k, v in og_from_html[0].items():
            if k not in merged and v:
                merged[k] = v
    return merged
