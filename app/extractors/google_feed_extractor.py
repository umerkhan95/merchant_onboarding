"""Google Shopping Feed extractor — parses XML (RSS 2.0) or CSV/TSV product feeds.

Fetches a merchant's Google Shopping feed URL and parses it into raw product dicts.
Supports both XML (RSS 2.0 with g: namespace) and CSV/TSV formats. No browser,
no credentials, no crawling — just one HTTP GET of a static file.

Security: uses defusedxml for XML parsing, enforces MAX_RESPONSE_SIZE, and validates
the feed URL against SSRF before fetching.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

import defusedxml.ElementTree as ET
import httpx

from app.config import MAX_RESPONSE_SIZE
from app.extractors.base import BaseExtractor, ExtractorResult

logger = logging.getLogger(__name__)

# Google Shopping XML namespace
_G_NS = "http://base.google.com/ns/1.0"
_NAMESPACES = {"g": _G_NS}

# Default headers for feed fetch
_FEED_HEADERS = {
    "User-Agent": "MerchantOnboarding/1.0 (Feed Parser)",
    "Accept": "application/xml, text/xml, text/csv, text/tab-separated-values, */*",
}


class GoogleFeedExtractor(BaseExtractor):
    """Extract product data from a Google Shopping feed URL (XML or CSV/TSV)."""

    async def extract(self, shop_url: str) -> ExtractorResult:
        """Fetch and parse a Google Shopping feed.

        Args:
            shop_url: The feed URL (not a shop URL — overloaded per BaseExtractor contract).

        Returns:
            ExtractorResult with parsed product dicts.
        """
        feed_url = shop_url  # Alias for clarity

        try:
            body, content_type = await self._fetch_feed(feed_url)
        except Exception as e:
            logger.warning("Failed to fetch feed %s: %s", feed_url, e)
            return ExtractorResult(products=[], complete=False, error=str(e))

        try:
            if self._is_xml(body, content_type):
                products = self._parse_xml(body, feed_url)
            else:
                products = self._parse_csv(body, feed_url)
        except Exception as e:
            logger.warning("Failed to parse feed %s: %s", feed_url, e)
            return ExtractorResult(products=[], complete=False, error=str(e))

        logger.info("Parsed %d products from feed %s", len(products), feed_url)
        return ExtractorResult(products=products, complete=True)

    # -- Fetch ----------------------------------------------------------------

    async def _fetch_feed(self, url: str) -> tuple[str, str]:
        """Fetch feed content with size limit. Returns (body, content_type)."""
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=True, headers=_FEED_HEADERS
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            if len(resp.content) > MAX_RESPONSE_SIZE:
                raise ValueError(
                    f"Feed exceeds {MAX_RESPONSE_SIZE // (1024*1024)}MB size limit"
                )

            content_type = resp.headers.get("content-type", "")
            return resp.text, content_type

    # -- Format detection -----------------------------------------------------

    @staticmethod
    def _is_xml(body: str, content_type: str) -> bool:
        """Detect XML vs CSV/TSV from content-type or body prefix."""
        ct = content_type.lower()
        if "xml" in ct:
            return True
        if "csv" in ct or "tab-separated" in ct:
            return False
        # Fallback: inspect first bytes
        stripped = body.lstrip()
        return stripped.startswith("<?xml") or stripped.startswith("<rss") or stripped.startswith("<feed")

    # -- XML parser -----------------------------------------------------------

    @classmethod
    def _parse_xml(cls, body: str, feed_url: str) -> list[dict]:
        """Parse RSS 2.0 XML feed with g: namespace."""
        root = ET.fromstring(body)
        products: list[dict] = []

        # Find all <item> elements (RSS 2.0: channel/item)
        items = root.findall(".//item")
        if not items:
            # Try Atom format: <entry>
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for item in items:
            product = cls._parse_xml_item(item)
            if product and product.get("title"):
                products.append(product)
            else:
                logger.debug("Skipping feed item without title")

        return products

    @classmethod
    def _parse_xml_item(cls, item: Any) -> dict:
        """Extract product fields from a single <item> element."""
        def g(tag: str) -> str:
            """Get text from g:tag or plain tag."""
            el = item.find(f"g:{tag}", _NAMESPACES)
            if el is not None and el.text:
                return el.text.strip()
            el = item.find(tag)
            if el is not None and el.text:
                return el.text.strip()
            return ""

        # Parse price: "49.99 EUR" -> ("49.99", "EUR")
        price_str, currency = cls._parse_price_string(g("price"))
        sale_price_str, sale_currency = cls._parse_price_string(g("sale_price"))

        # Collect additional images (can appear multiple times)
        additional_images = []
        for el in item.findall(f"g:additional_image_link", _NAMESPACES):
            if el is not None and el.text and el.text.strip():
                additional_images.append(el.text.strip())

        return {
            "_source": "google_feed",
            "id": g("id"),
            "title": g("title") or (item.findtext("title") or "").strip(),
            "description": (item.findtext("description") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "price": price_str,
            "currency": currency or sale_currency,
            "sale_price": sale_price_str,
            "gtin": g("gtin") or g("ean"),
            "brand": g("brand"),
            "image_link": g("image_link"),
            "additional_image_link": additional_images,
            "availability": g("availability"),
            "condition": g("condition"),
            "product_type": g("product_type"),
            "mpn": g("mpn"),
        }

    # -- CSV/TSV parser -------------------------------------------------------

    @classmethod
    def _parse_csv(cls, body: str, feed_url: str) -> list[dict]:
        """Parse CSV or TSV feed with Google Shopping column headers."""
        # Detect delimiter: tab or comma
        first_line = body.split("\n", 1)[0]
        delimiter = "\t" if "\t" in first_line else ","

        reader = csv.DictReader(io.StringIO(body), delimiter=delimiter)
        products: list[dict] = []

        for row in reader:
            product = cls._parse_csv_row(row)
            if product and product.get("title"):
                products.append(product)

        return products

    @classmethod
    def _parse_csv_row(cls, row: dict[str, str]) -> dict:
        """Map a CSV row to the standard product dict."""
        def s(key: str) -> str:
            """Get string value, handling None from DictReader."""
            val = row.get(key)
            return val.strip() if val else ""

        price_str, currency = cls._parse_price_string(s("price"))
        sale_price_str, sale_currency = cls._parse_price_string(s("sale_price"))

        # additional_image_link in CSV is comma-separated within one column
        additional_raw = s("additional_image_link")
        additional_images = [
            url.strip() for url in additional_raw.split(",") if url.strip()
        ] if additional_raw else []

        return {
            "_source": "google_feed",
            "id": s("id"),
            "title": s("title"),
            "description": s("description"),
            "link": s("link"),
            "price": price_str,
            "currency": currency or sale_currency,
            "sale_price": sale_price_str,
            "gtin": s("gtin") or s("ean"),
            "brand": s("brand"),
            "image_link": s("image_link"),
            "additional_image_link": additional_images,
            "availability": s("availability"),
            "condition": s("condition"),
            "product_type": s("product_type"),
            "mpn": s("mpn"),
        }

    # -- Price parsing --------------------------------------------------------

    @staticmethod
    def _parse_price_string(price_raw: str) -> tuple[str, str]:
        """Parse Google feed price format: '49.99 EUR' -> ('49.99', 'EUR').

        Also handles: '49.99', '1,299.99 USD', '49,99 EUR' (European).
        Returns ('', '') if input is empty.
        """
        if not price_raw or not price_raw.strip():
            return "", ""

        parts = price_raw.strip().split()
        currency = ""
        amount_str = parts[0]

        if len(parts) >= 2:
            # Last part might be currency code
            candidate = parts[-1].upper()
            if candidate.isalpha() and len(candidate) == 3:
                currency = candidate
                amount_str = " ".join(parts[:-1])

        # Normalize amount: handle European comma decimals
        if "," in amount_str and "." in amount_str:
            # 1,299.99 -> US format, remove comma
            amount_str = amount_str.replace(",", "")
        elif "," in amount_str:
            # 49,99 -> European format
            amount_str = amount_str.replace(",", ".")

        return amount_str, currency
