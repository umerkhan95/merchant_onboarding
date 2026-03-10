"""GTIN/MPN supplementation service for API-extracted products.

Supplements API-extracted products with GTIN/MPN identifiers parsed from
Schema.org JSON-LD on individual product pages. HTTP-only, no browser.
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# GTIN fields to look for in JSON-LD, in priority order
_GTIN_FIELDS = ("gtin13", "gtin14", "gtin12", "gtin8", "gtin")


class GTINSupplementer:
    """Supplements API-extracted products with GTIN/MPN from Schema.org JSON-LD."""

    _MAX_URLS = 500
    _CONCURRENCY = 10

    def __init__(self, http_client: httpx.AsyncClient, logger: logging.Logger | None = None) -> None:
        self._client = http_client
        self._log = logger or globals()["logger"]

    async def supplement(self, products: list[dict], shop_url: str) -> list[dict]:
        """Fetch product pages and inject GTIN/MPN into products missing them.

        Args:
            products: Raw product dicts from API extractors
            shop_url: Base shop URL (used only for logging context)

        Returns:
            Same list with gtin/mpn fields filled where found
        """
        # Collect products that need supplementation (missing gtin)
        needs_gtin = [p for p in products if not p.get("gtin")]
        if not needs_gtin:
            return products

        # Gather unique URLs to fetch
        urls_to_fetch: list[str] = []
        seen: set[str] = set()
        for product in needs_gtin:
            url = product.get("product_url") or product.get("url") or ""
            if url and url not in seen:
                seen.add(url)
                urls_to_fetch.append(url)

        if not urls_to_fetch:
            return products

        if len(urls_to_fetch) > self._MAX_URLS:
            self._log.warning(
                "GTIN supplementer capped at %d URLs (had %d) for %s",
                self._MAX_URLS,
                len(urls_to_fetch),
                shop_url,
            )
            urls_to_fetch = urls_to_fetch[: self._MAX_URLS]

        # Fetch HTML in concurrent batches and build URL-path -> identifiers lookup
        identifiers_by_path: dict[str, dict] = {}
        for batch_start in range(0, len(urls_to_fetch), self._CONCURRENCY):
            batch = urls_to_fetch[batch_start : batch_start + self._CONCURRENCY]
            results = await asyncio.gather(
                *[self._fetch_identifiers(url) for url in batch],
            )
            for url, result in zip(batch, results):
                if result:
                    path = _url_path(url)
                    identifiers_by_path[path] = result

        if not identifiers_by_path:
            return products

        # Build title lookup as fallback
        identifiers_by_title: dict[str, dict] = {}
        for url, identifiers in identifiers_by_path.items():
            title = identifiers.pop("_title", None)
            if title:
                identifiers_by_title[title.lower().strip()] = identifiers

        # Merge identifiers back into products
        filled = 0
        for product in products:
            if product.get("gtin"):
                continue

            identifiers = self._match(product, identifiers_by_path, identifiers_by_title)
            if not identifiers:
                continue

            if gtin := identifiers.get("gtin"):
                product["gtin"] = gtin
                filled += 1
            if mpn := identifiers.get("mpn"):
                if not product.get("mpn"):
                    product["mpn"] = mpn

        if filled:
            self._log.info(
                "GTIN supplementer filled %d/%d products for %s",
                filled,
                len(needs_gtin),
                shop_url,
            )

        return products

    async def _fetch_identifiers(self, url: str) -> dict | None:
        """Fetch a product page and extract GTIN/MPN from JSON-LD.

        Returns None on any error (supplementation is optional).
        """
        try:
            response = await self._client.get(url, timeout=15.0)
            response.raise_for_status()
            return self._extract_identifiers_from_html(response.text)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._log.debug("GTIN fetch failed for %s: %s", url, e)
            return None

    @staticmethod
    def _extract_identifiers_from_html(html: str) -> dict | None:
        """Parse JSON-LD from HTML and return GTIN/MPN identifiers.

        Args:
            html: Raw HTML content of a product page

        Returns:
            Dict with keys "gtin", "mpn" (and "_title" for title-based fallback matching),
            or None if no identifiers found.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                except json.JSONDecodeError:
                    continue

                candidates = []
                if isinstance(data, dict):
                    type_val = data.get("@type", "")
                    if _is_product_type(type_val):
                        candidates.append(data)
                    elif "@graph" in data and isinstance(data["@graph"], list):
                        candidates.extend(
                            item for item in data["@graph"]
                            if isinstance(item, dict) and _is_product_type(item.get("@type", ""))
                        )
                elif isinstance(data, list):
                    candidates.extend(
                        item for item in data
                        if isinstance(item, dict) and _is_product_type(item.get("@type", ""))
                    )

                for candidate in candidates:
                    gtin = None
                    for field in _GTIN_FIELDS:
                        if val := candidate.get(field):
                            gtin = str(val).strip()
                            break
                    mpn = str(candidate["mpn"]).strip() if candidate.get("mpn") else None

                    if gtin or mpn:
                        result: dict = {}
                        if gtin:
                            result["gtin"] = gtin
                        if mpn:
                            result["mpn"] = mpn
                        name = candidate.get("name", "")
                        if name:
                            result["_title"] = str(name)
                        return result

        except Exception:
            pass
        return None

    @staticmethod
    def _match(
        product: dict,
        by_path: dict[str, dict],
        by_title: dict[str, dict],
    ) -> dict | None:
        """Match a product to identifier data by URL path, then by title."""
        url = product.get("product_url") or product.get("url") or ""
        if url:
            path = _url_path(url)
            if path in by_path:
                return by_path[path]

        title = (product.get("title") or product.get("name") or "").lower().strip()
        if title and title in by_title:
            return by_title[title]

        return None


def _url_path(url: str) -> str:
    """Return the path component of a URL, stripped of trailing slash and query params."""
    parsed = urlparse(url)
    return parsed.path.rstrip("/")


def _is_product_type(type_value) -> bool:
    """Return True if the JSON-LD @type value indicates a Product."""
    if isinstance(type_value, str):
        return "Product" in type_value
    if isinstance(type_value, list):
        return any("Product" in str(t) for t in type_value)
    return False
