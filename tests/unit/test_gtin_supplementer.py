"""Unit tests for GTINSupplementer service."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.gtin_supplementer import GTINSupplementer


def _html_with_gtin(gtin: str, title: str = "Test Product", mpn: str | None = None) -> str:
    """Build minimal HTML with a JSON-LD Product containing the given GTIN/MPN."""
    product_data: dict = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": title,
        "gtin13": gtin,
    }
    if mpn:
        product_data["mpn"] = mpn
    return f"<html><head><script type='application/ld+json'>{json.dumps(product_data)}</script></head></html>"


def _make_client(html: str | None = None, status: int = 200) -> httpx.AsyncClient:
    """Create a mock httpx.AsyncClient that returns the given HTML."""
    client = MagicMock(spec=httpx.AsyncClient)
    if html is None:
        client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    else:
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()
        if status >= 400:
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=MagicMock()
            )
        client.get = AsyncMock(return_value=mock_response)
    return client


@pytest.mark.asyncio
async def test_supplement_fills_gtin_from_jsonld():
    """Products missing GTIN get it filled from JSON-LD on the product page."""
    html = _html_with_gtin("1234567890123", title="Widget")
    client = _make_client(html)
    supplementer = GTINSupplementer(client)

    products = [
        {"title": "Widget", "product_url": "https://shop.example.com/products/widget"},
    ]
    result = await supplementer.supplement(products, "https://shop.example.com")

    assert result[0]["gtin"] == "1234567890123"


@pytest.mark.asyncio
async def test_supplement_skips_products_with_existing_gtin():
    """Products that already have a GTIN are not re-fetched or overwritten."""
    client = _make_client(_html_with_gtin("0000000000000"))
    supplementer = GTINSupplementer(client)

    products = [
        {
            "title": "Widget",
            "product_url": "https://shop.example.com/products/widget",
            "gtin": "9999999999999",
        }
    ]
    result = await supplementer.supplement(products, "https://shop.example.com")

    # Existing GTIN preserved; HTTP fetch should not have been made
    assert result[0]["gtin"] == "9999999999999"
    client.get.assert_not_called()


@pytest.mark.asyncio
async def test_supplement_handles_http_errors_gracefully():
    """Network errors during supplementation are silently skipped."""
    client = _make_client(None)  # raises TimeoutException
    supplementer = GTINSupplementer(client)

    products = [
        {"title": "Widget", "product_url": "https://shop.example.com/products/widget"},
    ]
    result = await supplementer.supplement(products, "https://shop.example.com")

    # No GTIN added, but no exception raised
    assert result[0].get("gtin") is None


@pytest.mark.asyncio
async def test_supplement_handles_404_gracefully():
    """HTTP 4xx responses are silently skipped."""
    client = _make_client("<html></html>", status=404)
    supplementer = GTINSupplementer(client)

    products = [
        {"title": "Widget", "product_url": "https://shop.example.com/products/widget"},
    ]
    result = await supplementer.supplement(products, "https://shop.example.com")

    assert result[0].get("gtin") is None


@pytest.mark.asyncio
async def test_supplement_caps_at_max_urls():
    """When more than _MAX_URLS products need supplementation, only _MAX_URLS are fetched."""
    html = _html_with_gtin("1234567890123")
    client = _make_client(html)
    supplementer = GTINSupplementer(client)
    supplementer._MAX_URLS = 3  # Override for test speed

    products = [
        {"title": f"Product {i}", "product_url": f"https://shop.example.com/products/p{i}"}
        for i in range(10)
    ]
    await supplementer.supplement(products, "https://shop.example.com")

    assert client.get.call_count == 3


@pytest.mark.asyncio
async def test_supplement_matches_by_url_path():
    """GTIN is matched to a product via its URL path."""
    html = _html_with_gtin("1234567890123", title="Red Shirt")
    client = _make_client(html)
    supplementer = GTINSupplementer(client)

    products = [
        # URL path will match the fetched URL path /products/red-shirt
        {"title": "Red Shirt", "product_url": "https://shop.example.com/products/red-shirt"},
    ]
    result = await supplementer.supplement(products, "https://shop.example.com")

    assert result[0]["gtin"] == "1234567890123"


@pytest.mark.asyncio
async def test_supplement_matches_by_title_fallback():
    """When URL path doesn't match (different URL), title matching finds the GTIN.

    Scenario: a product whose stored URL is different from the URL fetched for
    supplementation (e.g. a redirect or variant URL). Both share the same title so
    the title-based fallback kicks in.
    """
    # Page fetched for /source-url returns a Product titled "Blue Hoodie"
    html = _html_with_gtin("9876543210987", title="Blue Hoodie")

    # The product has a *different* URL path (/p/hoodie) than the fetched page (/source-url)
    # We simulate this by providing a second product with a matching URL that triggers the
    # fetch, but the *target* product has no URL so path lookup fails, leaving only title.

    client = _make_client(html)
    supplementer = GTINSupplementer(client)

    products = [
        # This product has NO url — path lookup will find nothing; only title can match
        {"title": "Blue Hoodie"},
        # This product has the URL that gets fetched; its result is stored by path
        {"title": "Blue Hoodie", "product_url": "https://shop.example.com/source-url"},
    ]
    result = await supplementer.supplement(products, "https://shop.example.com")

    # Both products share the title, so both should get the GTIN
    assert result[0].get("gtin") == "9876543210987"
    assert result[1].get("gtin") == "9876543210987"


@pytest.mark.asyncio
async def test_supplement_returns_unchanged_when_no_urls_need_enrichment():
    """If all products already have a GTIN, no HTTP calls are made and list is returned as-is."""
    client = _make_client(_html_with_gtin("1111111111111"))
    supplementer = GTINSupplementer(client)

    products = [
        {"title": "Widget", "product_url": "https://shop.example.com/p/1", "gtin": "9999999999999"},
        {"title": "Gadget", "product_url": "https://shop.example.com/p/2", "gtin": "8888888888888"},
    ]
    result = await supplementer.supplement(products, "https://shop.example.com")

    client.get.assert_not_called()
    assert result[0]["gtin"] == "9999999999999"
    assert result[1]["gtin"] == "8888888888888"


@pytest.mark.asyncio
async def test_supplement_extracts_mpn_alongside_gtin():
    """MPN field is also extracted and injected when present in JSON-LD."""
    html = _html_with_gtin("1234567890123", title="Camera", mpn="CAM-001")
    client = _make_client(html)
    supplementer = GTINSupplementer(client)

    products = [
        {"title": "Camera", "product_url": "https://shop.example.com/products/camera"},
    ]
    result = await supplementer.supplement(products, "https://shop.example.com")

    assert result[0]["gtin"] == "1234567890123"
    assert result[0]["mpn"] == "CAM-001"


@pytest.mark.asyncio
async def test_supplement_does_not_overwrite_existing_mpn():
    """Existing MPN is not overwritten even when a different MPN is found on the page."""
    html = _html_with_gtin("1234567890123", title="Camera", mpn="PAGE-MPN")
    client = _make_client(html)
    supplementer = GTINSupplementer(client)

    products = [
        {
            "title": "Camera",
            "product_url": "https://shop.example.com/products/camera",
            "mpn": "EXISTING-MPN",
        }
    ]
    result = await supplementer.supplement(products, "https://shop.example.com")

    assert result[0]["gtin"] == "1234567890123"
    assert result[0]["mpn"] == "EXISTING-MPN"


class TestExtractIdentifiersFromHtml:
    """Unit tests for the static HTML parser."""

    def test_extracts_gtin13(self):
        html = _html_with_gtin("1234567890123")
        result = GTINSupplementer._extract_identifiers_from_html(html)
        assert result is not None
        assert result["gtin"] == "1234567890123"

    def test_returns_none_when_no_jsonld(self):
        result = GTINSupplementer._extract_identifiers_from_html("<html><body>no scripts</body></html>")
        assert result is None

    def test_returns_none_when_no_product_type(self):
        html = "<html><head><script type='application/ld+json'>{\"@type\": \"Organization\"}</script></head></html>"
        result = GTINSupplementer._extract_identifiers_from_html(html)
        assert result is None

    def test_extracts_from_graph(self):
        data = {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebPage"},
                {"@type": "Product", "name": "Donut", "gtin13": "0000000000001"},
            ],
        }
        html = f"<html><head><script type='application/ld+json'>{json.dumps(data)}</script></head></html>"
        result = GTINSupplementer._extract_identifiers_from_html(html)
        assert result is not None
        assert result["gtin"] == "0000000000001"

    def test_prefers_gtin13_over_gtin(self):
        data = {
            "@type": "Product",
            "name": "Widget",
            "gtin": "short",
            "gtin13": "1234567890123",
        }
        html = f"<html><head><script type='application/ld+json'>{json.dumps(data)}</script></head></html>"
        result = GTINSupplementer._extract_identifiers_from_html(html)
        assert result["gtin"] == "1234567890123"

    def test_returns_none_on_malformed_json(self):
        html = "<html><head><script type='application/ld+json'>not json</script></head></html>"
        result = GTINSupplementer._extract_identifiers_from_html(html)
        assert result is None

    def test_includes_title_for_fallback_matching(self):
        html = _html_with_gtin("1234567890123", title="My Product")
        result = GTINSupplementer._extract_identifiers_from_html(html)
        assert result["_title"] == "My Product"
