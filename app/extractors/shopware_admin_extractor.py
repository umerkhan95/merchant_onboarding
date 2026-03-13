"""Shopware 6 Admin API extractor using OAuth 2.0 Client Credentials.

Shopware 6 uses short-lived bearer tokens (10-minute TTL) obtained via the
Client Credentials grant. The extractor transparently refreshes the token
before expiry so pagination across large catalogs works without interruption.

Credentials are stored in OAuthConnection as:
  - access_token  → Shopware client_id  (permanent, issued by the store)
  - refresh_token → Shopware client_secret (permanent, never actually rotated)

EAN is a first-class field on the Shopware Product entity (`product.ean`),
unlike WooCommerce where it lives in meta_data plugins.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.db.oauth_store import OAuthConnection
from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import get_default_user_agent

logger = logging.getLogger(__name__)

_PAGE_LIMIT = 100   # Shopware search API max practical page size
_MAX_PAGES = 100    # Safety cap: 100 * 100 = 10 000 products per run
_TOKEN_BUFFER = 30  # Refresh token this many seconds before actual expiry


class ShopwareAdminExtractor(BaseExtractor):
    """Extract products from Shopware 6 stores via the Admin Search API.

    Uses POST /api/search/product with the Shopware Criteria API to retrieve
    paginated product data including cover image, manufacturer, categories,
    and child variants.

    Token lifecycle: tokens expire after 10 minutes. `_ensure_token()` is
    called before every page request and refreshes proactively using a 30s
    buffer, so extraction of large catalogs never fails mid-pagination due
    to a stale token.
    """

    def __init__(self, connection: OAuthConnection, timeout: int = 30) -> None:
        """Initialize with a stored OAuth connection.

        The OAuthConnection reuses existing fields for Shopware credentials:
          - ``connection.access_token``  → Shopware client_id  (permanent)
          - ``connection.refresh_token`` → Shopware client_secret (permanent)
          - ``connection.shop_domain``   → store hostname (no scheme)

        Args:
            connection: OAuthConnection with access_token and refresh_token set.
            timeout: Per-request HTTP timeout in seconds.

        Raises:
            ValueError: If access_token (client_id) or refresh_token
                (client_secret) are absent on the connection.
        """
        if not connection.access_token or not connection.refresh_token:
            raise ValueError(
                "Shopware connection requires access_token (client_id) "
                "and refresh_token (client_secret)"
            )
        self._client_id: str = connection.access_token
        self._client_secret: str = connection.refresh_token
        self._shop_domain: str = connection.shop_domain
        self._timeout: int = timeout

        # Ephemeral bearer token state — obtained on first request, refreshed
        # automatically. Never persisted to the DB (10-minute TTL makes that
        # pointless).
        self._bearer_token: str | None = None
        self._token_expires_at: float = 0.0  # monotonic clock value

    # ── Token Management ─────────────────────────────────────────────────────

    async def _ensure_token(
        self,
        client: httpx.AsyncClient,
        *,
        force: bool = False,
    ) -> str:
        """Return a valid bearer token, refreshing if needed.

        Proactively refreshes the token ``_TOKEN_BUFFER`` seconds before it
        expires to avoid mid-page failures on slow stores.

        Args:
            client: Active httpx client (reuses connection pool).
            force: When True, always fetches a new token regardless of expiry.
                   Used after receiving a 401 response.

        Returns:
            A valid bearer token string.

        Raises:
            RuntimeError: If the token endpoint returns a non-200 response.
        """
        now = time.monotonic()
        if (
            not force
            and self._bearer_token is not None
            and now < self._token_expires_at - _TOKEN_BUFFER
        ):
            return self._bearer_token

        token_url = f"https://{self._shop_domain}/api/oauth/token"
        logger.debug(
            "Shopware Admin API: requesting new bearer token for %s",
            self._shop_domain,
        )

        resp = await client.post(
            token_url,
            json={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Shopware token endpoint returned HTTP {resp.status_code} "
                f"for {self._shop_domain}: {resp.text[:200]}"
            )

        token_data = resp.json()
        self._bearer_token = token_data["access_token"]
        expires_in: int = token_data.get("expires_in", 600)
        self._token_expires_at = time.monotonic() + expires_in

        logger.debug(
            "Shopware Admin API: token obtained for %s (expires_in=%ds)",
            self._shop_domain, expires_in,
        )
        return self._bearer_token

    # ── Extraction ───────────────────────────────────────────────────────────

    async def extract(self, shop_url: str) -> ExtractorResult:
        """Fetch all active products from the Shopware 6 Admin Search API.

        Uses POST /api/search/product with page-based pagination. Associations
        (cover, media, manufacturer, categories, children) are requested inline
        to avoid N+1 requests.

        Args:
            shop_url: The shop URL — used for logging context only; the actual
                      base URL is derived from ``_shop_domain``.

        Returns:
            ExtractorResult with all products and pagination metadata.
        """
        all_products: list[dict[str, Any]] = []
        complete = True
        error: str | None = None
        total_items: int | None = None
        page = 1

        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": get_default_user_agent(),
            },
            follow_redirects=True,
        ) as client:
            # Obtain initial token before the loop
            try:
                await self._ensure_token(client)
            except RuntimeError as exc:
                logger.error(
                    "Shopware Admin API: failed to obtain token for %s: %s",
                    self._shop_domain, exc,
                )
                return ExtractorResult(
                    products=[], complete=False, error=str(exc)
                )

            search_url = f"https://{self._shop_domain}/api/search/product"

            while page <= _MAX_PAGES:
                logger.info(
                    "Shopware Admin API: fetching page %d for %s",
                    page, self._shop_domain,
                )

                body = self._build_search_body(page)

                try:
                    token = await self._ensure_token(client)
                    resp = await client.post(
                        search_url,
                        json=body,
                        headers={"Authorization": f"Bearer {token}"},
                    )

                    # Transparent token refresh on 401
                    if resp.status_code == 401:
                        logger.info(
                            "Shopware Admin API: 401 received, forcing token refresh "
                            "for %s (page %d)",
                            self._shop_domain, page,
                        )
                        token = await self._ensure_token(client, force=True)
                        resp = await client.post(
                            search_url,
                            json=body,
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if resp.status_code == 401:
                            logger.error(
                                "Shopware Admin API: credentials invalid for %s",
                                self._shop_domain,
                            )
                            return ExtractorResult(
                                products=[], complete=False,
                                error="API credentials invalid"
                            )

                    # Rate limiting
                    if resp.status_code == 429:
                        retry_after = float(
                            resp.headers.get("Retry-After", "5")
                        )
                        logger.warning(
                            "Shopware Admin API: rate limited, waiting %.1fs",
                            retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        token = await self._ensure_token(client)
                        resp = await client.post(
                            search_url,
                            json=body,
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if resp.status_code == 429:
                            complete = False
                            error = f"Rate limited on page {page}"
                            break

                    if resp.status_code != 200:
                        logger.error(
                            "Shopware Admin API: HTTP %d on page %d for %s",
                            resp.status_code, page, self._shop_domain,
                        )
                        complete = False
                        error = f"HTTP {resp.status_code} on page {page}"
                        break

                    data = resp.json()
                    products_page: list[dict] = data.get("data") or []

                    # Capture total item count from first response
                    if total_items is None:
                        total_items = data.get("total", 0)
                        logger.info(
                            "Shopware Admin API: %d total products found at %s",
                            total_items, self._shop_domain,
                        )

                    if not products_page:
                        break

                    for product in products_page:
                        mapped = self._map_product(product, shop_url)
                        all_products.append(mapped)

                    logger.info(
                        "Shopware Admin API: page %d returned %d products "
                        "(cumulative: %d)",
                        page, len(products_page), len(all_products),
                    )

                    # Stop when we have retrieved all items or hit the page cap
                    if total_items is not None and len(all_products) >= total_items:
                        break

                    page += 1

                except httpx.TimeoutException:
                    logger.warning(
                        "Shopware Admin API: timeout on page %d for %s",
                        page, self._shop_domain,
                    )
                    complete = False
                    error = f"Timeout on page {page}"
                    break
                except RuntimeError as exc:
                    # Token refresh failure mid-pagination
                    logger.error(
                        "Shopware Admin API: token error on page %d for %s: %s",
                        page, self._shop_domain, exc,
                    )
                    complete = False
                    error = str(exc)
                    break
                except httpx.RequestError as exc:
                    logger.error(
                        "Shopware Admin API: request error on page %d for %s: %s",
                        page, self._shop_domain, exc,
                    )
                    complete = False
                    error = f"Request error on page {page}: {exc}"
                    break

        logger.info(
            "Shopware Admin API: extracted %d products from %d pages for %s",
            len(all_products), page, self._shop_domain,
        )
        pages_expected = (
            (total_items + _PAGE_LIMIT - 1) // _PAGE_LIMIT
            if total_items
            else None
        )
        return ExtractorResult(
            products=all_products,
            complete=complete,
            error=error,
            pages_completed=page if all_products else 0,
            pages_expected=pages_expected,
        )

    # ── Search Criteria ───────────────────────────────────────────────────────

    @staticmethod
    def _build_search_body(page: int) -> dict:
        """Build the Shopware Criteria API body for a single page.

        Requests only active (non-child) parent products. Associations are
        fetched inline to avoid N+1 requests. ``total-count-mode: 1`` returns
        the exact total so we know when to stop paginating.

        Args:
            page: 1-indexed page number.

        Returns:
            JSON-serialisable dict for the POST body.
        """
        return {
            "page": page,
            "limit": _PAGE_LIMIT,
            "filter": [
                {"type": "equals", "field": "active", "value": True},
                # Exclude child/variant products from the top-level listing —
                # they are returned as ``children`` on their parent.
                {"type": "equals", "field": "parentId", "value": None},
            ],
            "associations": {
                "cover": {
                    "associations": {"media": {}}
                },
                "media": {
                    "associations": {"media": {}}
                },
                "manufacturer": {},
                "categories": {},
                "children": {
                    "limit": 100,
                    "associations": {
                        "cover": {
                            "associations": {"media": {}}
                        }
                    },
                },
            },
            "total-count-mode": 1,
        }

    # ── Field Mapping ─────────────────────────────────────────────────────────

    def _map_product(self, product: dict, shop_url: str) -> dict:
        """Map a Shopware product entity to the raw dict expected by ProductNormalizer.

        Field names match those produced by other extractors (Shopify, WooCommerce,
        BigCommerce) so ProductNormalizer handles them uniformly.

        Args:
            product: Raw product dict from the Shopware API response.
            shop_url: Provided for context; product URL is built from the product id.

        Returns:
            Normalised raw product dict.
        """
        cover_url = self._extract_cover_url(product)
        additional_images = self._extract_media_urls(product, exclude_url=cover_url)

        # Price — Shopware stores as an array keyed by currency rule.
        # price[0].gross is the default storefront price (incl. VAT).
        gross_price_str = ""
        list_price_str: str | None = None
        price_array = product.get("price") or []
        if price_array and isinstance(price_array, list):
            first_price = price_array[0] if isinstance(price_array[0], dict) else {}
            gross = first_price.get("gross")
            if gross is not None:
                gross_price_str = str(gross)
            list_price = first_price.get("listPrice")
            if isinstance(list_price, dict):
                list_gross = list_price.get("gross")
                if list_gross is not None:
                    list_price_str = str(list_gross)

        # Vendor / manufacturer
        manufacturer = product.get("manufacturer") or {}
        vendor = manufacturer.get("name", "") if isinstance(manufacturer, dict) else ""

        # Categories — flat list of names
        categories = product.get("categories") or []
        category_names = [
            c.get("name", "")
            for c in categories
            if isinstance(c, dict) and c.get("name")
        ]

        # Stock
        stock = product.get("stock") or 0
        active = product.get("active", False)
        in_stock = stock > 0 and bool(active)

        # Product URL — Shopware canonical detail URL
        product_id = product.get("id", "")
        product_url = f"https://{self._shop_domain}/detail/{product_id}"

        # EAN is first-class in Shopware (unlike WooCommerce meta_data)
        ean = product.get("ean") or ""

        return {
            "id": product_id,
            "title": product.get("name", ""),
            "description": product.get("description", ""),
            "handle": product.get("productNumber", ""),
            "sku": product.get("productNumber", ""),
            "gtin": ean,
            "barcode": ean,
            "mpn": product.get("manufacturerNumber", ""),
            "price": gross_price_str,
            "compare_at_price": list_price_str,
            "currency": "EUR",  # Shopware default; German market standard
            "vendor": vendor,
            "product_type": "",
            "tags": category_names,
            "in_stock": in_stock,
            "image_url": cover_url,
            "additional_images": additional_images,
            "product_url": product_url,
            "variants": self._map_variants(product.get("children") or []),
            "weight": product.get("weight"),
            "condition": "New",
            "_source": "shopware_admin_api",
            "_platform": "shopware",
        }

    def _map_variants(self, children: list[dict]) -> list[dict]:
        """Map Shopware child products (variants) to the standard variant format.

        Shopware models each option combination as a separate child product
        entity. We expose them as a flat variant list so ProductNormalizer
        can handle them identically to Shopify/WooCommerce variants.

        Args:
            children: List of raw child product dicts from the ``children``
                      association on the parent product.

        Returns:
            List of variant dicts, empty if the product has no children.
        """
        variants: list[dict] = []
        for child in children:
            if not isinstance(child, dict):
                continue

            price_array = child.get("price") or []
            child_price_gross: float | None = None
            if price_array and isinstance(price_array, list):
                first_price = price_array[0] if isinstance(price_array[0], dict) else {}
                raw = first_price.get("gross")
                if raw is not None:
                    try:
                        child_price_gross = float(raw)
                    except (TypeError, ValueError):
                        pass

            stock = child.get("stock") or 0
            variants.append({
                "variant_id": child.get("id", ""),
                "title": child.get("name") or child.get("productNumber", ""),
                "price": str(child_price_gross) if child_price_gross is not None else "",
                "sku": child.get("productNumber") or "",
                "barcode": child.get("ean") or "",
                "gtin": child.get("ean") or "",
                "in_stock": stock > 0,
            })
        return variants

    def _extract_cover_url(self, product: dict) -> str:
        """Extract the cover image URL from the nested cover→media association.

        Shopware structure:
            product.cover.media.url

        Args:
            product: Raw product dict from the Shopware API.

        Returns:
            URL string, or empty string if unavailable.
        """
        cover = product.get("cover")
        if not isinstance(cover, dict):
            return ""
        media = cover.get("media")
        if not isinstance(media, dict):
            return ""
        return media.get("url", "") or ""

    def _extract_media_urls(
        self, product: dict, exclude_url: str = ""
    ) -> list[str]:
        """Extract additional image URLs from the product media gallery.

        Shopware structure:
            product.media[].media.url

        The cover image is excluded to avoid duplication in additional_images.

        Args:
            product: Raw product dict from the Shopware API.
            exclude_url: URL to exclude (typically the cover image URL).

        Returns:
            List of additional image URL strings.
        """
        media_list = product.get("media") or []
        if not isinstance(media_list, list):
            return []

        urls: list[str] = []
        for entry in media_list:
            if not isinstance(entry, dict):
                continue
            media = entry.get("media")
            if not isinstance(media, dict):
                continue
            url = media.get("url", "") or ""
            if url and url != exclude_url:
                urls.append(url)

        return urls
