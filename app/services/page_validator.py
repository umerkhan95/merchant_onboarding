"""HTML-based product page validation. Pure analysis, no network calls."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class PageValidationResult:
    is_product_page: bool
    confidence: float
    signals: list[str]
    rejection_reason: str = ""


class ProductPageValidator:
    """Validates whether an HTML page is a product page using signal-based scoring.

    Performs purely local HTML analysis — no network calls, no side effects.
    """

    def __init__(self, threshold: float = 0.3) -> None:
        self._threshold = threshold

    def validate(self, html: str, url: str) -> PageValidationResult:
        """Analyse raw HTML and determine whether the page is a product page.

        Args:
            html: Raw HTML content of the page.
            url: Canonical URL of the page (used only for context, not fetched).

        Returns:
            PageValidationResult with a confidence score and named signals.
        """
        soup = BeautifulSoup(html, "html.parser")

        # ------------------------------------------------------------------
        # Phase 1: Rejection checks
        # ------------------------------------------------------------------
        rejection = self._check_rejections(soup)
        if rejection:
            logger.debug("Page rejected (%s): %s", rejection, url)
            return PageValidationResult(
                is_product_page=False,
                confidence=0.0,
                signals=[],
                rejection_reason=rejection,
            )

        # ------------------------------------------------------------------
        # Phase 2: Confidence signal accumulation
        # ------------------------------------------------------------------
        signals: list[str] = []
        score: float = 0.0

        if self._has_json_ld_product(soup):
            signals.append("json_ld_product")
            score += 0.4

        if self._has_og_product_price(soup):
            signals.append("og_product_price")
            score += 0.3

        if self._has_add_to_cart(soup):
            signals.append("add_to_cart")
            score += 0.2

        if self._has_price_element(soup):
            signals.append("price_element")
            score += 0.15

        if self._has_product_title(soup):
            signals.append("product_title")
            score += 0.1

        confidence = min(score, 1.0)
        is_product_page = confidence >= self._threshold

        return PageValidationResult(
            is_product_page=is_product_page,
            confidence=confidence,
            signals=signals,
            rejection_reason="",
        )

    # ------------------------------------------------------------------
    # Phase 1 helpers
    # ------------------------------------------------------------------

    def _check_rejections(self, soup: BeautifulSoup) -> str:
        """Return a rejection reason string, or empty string if no rejection."""
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text(strip=True).lower()
            for marker in ("404", "not found", "page not available"):
                if marker in title_text:
                    return "error_page_title"

        refresh_tag = soup.find("meta", attrs={"http-equiv": re.compile(r"^refresh$", re.IGNORECASE)})
        if refresh_tag:
            content = refresh_tag.get("content", "")
            # Extract the URL portion from e.g. "0; url=/"
            match = re.search(r"url\s*=\s*(.+)", str(content), re.IGNORECASE)
            if match:
                redirect_target = match.group(1).strip().rstrip("/")
                if redirect_target in ("", "/"):
                    return "redirect_to_homepage"

        body_text = soup.get_text(strip=True)
        if len(body_text) < 500:
            return "insufficient_content"

        return ""

    # ------------------------------------------------------------------
    # Phase 2 helpers
    # ------------------------------------------------------------------

    def _has_json_ld_product(self, soup: BeautifulSoup) -> bool:
        """Return True if any JSON-LD block declares @type Product."""
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Product":
                        return True
            elif isinstance(data, dict):
                if data.get("@type") == "Product":
                    return True

        return False

    def _has_og_product_price(self, soup: BeautifulSoup) -> bool:
        """Return True if any meta tag carries product:price:amount."""
        return bool(
            soup.find("meta", attrs={"property": "product:price:amount"})
        )

    def _has_add_to_cart(self, soup: BeautifulSoup) -> bool:
        """Return True if any button, input, or form element references cart actions."""
        _CART_PATTERN = re.compile(r"cart|add[_-]to[_-]cart", re.IGNORECASE)
        for tag in soup.find_all(["button", "input", "form"]):
            for attr in ("name", "action", "id"):
                value = tag.get(attr, "")
                if _CART_PATTERN.search(str(value)):
                    return True
            # class attribute may be a list (BeautifulSoup normalises it)
            classes = tag.get("class", [])
            class_str = " ".join(classes) if isinstance(classes, list) else str(classes)
            if _CART_PATTERN.search(class_str):
                return True
        return False

    def _has_price_element(self, soup: BeautifulSoup) -> bool:
        """Return True if any structured price element is present."""
        for selector in ('[itemprop="price"]', ".price", "[data-price]"):
            if soup.select(selector):
                return True
        return False

    def _has_product_title(self, soup: BeautifulSoup) -> bool:
        """Return True if any structured product title element is present."""
        for selector in ('[itemprop="name"]', ".product-title", "h1.product-name"):
            if soup.select(selector):
                return True
        return False
