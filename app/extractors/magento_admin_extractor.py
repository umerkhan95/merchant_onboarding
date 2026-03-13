"""Magento 2 Admin API extractor using Integration access tokens.

Magento Integration tokens are permanent Bearer tokens issued from the Admin
panel (System > Integrations). No token lifecycle management is needed --
just send the token as ``Authorization: Bearer {token}`` on every request.

Products are fetched via GET /rest/V1/products with searchCriteria query
parameters. Only visible (visibility=4, catalog+search) and enabled
(status=1) products are returned.

GTIN is extracted from the ``custom_attributes`` array by scanning for
common attribute codes: ean, gtin, gtin13, barcode, upc, ean13.

Configurable products have their children listed in
``extension_attributes.configurable_product_links`` as an array of entity
IDs. Children are batch-fetched with an ``entity_id`` IN filter, capped at
50 per parent to prevent runaway requests.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.db.oauth_store import OAuthConnection
from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import get_default_user_agent

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100    # searchCriteria[pageSize]
_MAX_PAGES = 100    # Safety cap: 100 * 100 = 10 000 products
_MAX_CHILDREN = 50  # Cap children per configurable parent

# Attribute codes to scan for GTIN in custom_attributes
_GTIN_ATTRIBUTE_CODES = ("ean", "gtin", "gtin13", "barcode", "upc", "ean13")


class MagentoAdminExtractor(BaseExtractor):
    """Extract products from Magento 2 stores via the Admin REST API.

    Uses GET /rest/V1/products with searchCriteria pagination. Only enabled,
    catalog-visible products are fetched. Configurable products have their
    children batch-fetched and mapped as variants.

    Auth is a permanent Integration Bearer token -- no refresh needed.
    """

    def __init__(self, connection: OAuthConnection, timeout: int = 30) -> None:
        """Initialize with a stored OAuth connection.

        Args:
            connection: OAuthConnection with access_token set (Magento
                Integration token). Currency can be provided via
                ``connection.extra_data["currency"]``.
            timeout: Per-request HTTP timeout in seconds.

        Raises:
            ValueError: If access_token is absent on the connection.
        """
        if not connection.access_token:
            raise ValueError(
                "Magento connection requires access_token (Integration token)"
            )
        self._access_token: str = connection.access_token
        self._shop_domain: str = connection.shop_domain
        self._timeout: int = timeout
        self._currency: str = (
            (connection.extra_data or {}).get("currency", "EUR")
        )

    # -- URL Construction ---------------------------------------------------

    def _base_url(self) -> str:
        return f"https://{self._shop_domain}/rest/V1"

    def _product_url(self, url_key: str) -> str:
        """Build the frontend product URL from url_key custom attribute."""
        if not url_key:
            return ""
        return f"https://{self._shop_domain}/{url_key}.html"

    def _image_url(self, image_path: str) -> str:
        """Build the full image URL from the image custom attribute path."""
        if not image_path:
            return ""
        return f"https://{self._shop_domain}/media/catalog/product{image_path}"

    # -- SearchCriteria Helpers ---------------------------------------------

    @staticmethod
    def _build_search_params(page: int) -> dict[str, str]:
        """Build searchCriteria query parameters for a product listing page.

        Filters:
          - filter_groups[0][filters][0]: visibility = 4 (catalog+search)
          - filter_groups[1][filters][0]: status = 1 (enabled)

        Args:
            page: 1-indexed page number.

        Returns:
            Dict of query parameter key-value pairs.
        """
        return {
            "searchCriteria[pageSize]": str(_PAGE_SIZE),
            "searchCriteria[currentPage]": str(page),
            "searchCriteria[filter_groups][0][filters][0][field]": "visibility",
            "searchCriteria[filter_groups][0][filters][0][value]": "4",
            "searchCriteria[filter_groups][0][filters][0][condition_type]": "eq",
            "searchCriteria[filter_groups][1][filters][0][field]": "status",
            "searchCriteria[filter_groups][1][filters][0][value]": "1",
            "searchCriteria[filter_groups][1][filters][0][condition_type]": "eq",
        }

    @staticmethod
    def _build_children_params(entity_ids: list[int]) -> dict[str, str]:
        """Build searchCriteria to fetch children by entity_id IN filter.

        Args:
            entity_ids: List of child product entity IDs.

        Returns:
            Dict of query parameter key-value pairs.
        """
        ids_csv = ",".join(str(eid) for eid in entity_ids)
        return {
            "searchCriteria[pageSize]": str(len(entity_ids)),
            "searchCriteria[currentPage]": "1",
            "searchCriteria[filter_groups][0][filters][0][field]": "entity_id",
            "searchCriteria[filter_groups][0][filters][0][value]": ids_csv,
            "searchCriteria[filter_groups][0][filters][0][condition_type]": "in",
        }

    # -- Custom Attribute Helpers -------------------------------------------

    @staticmethod
    def _get_custom_attribute(
        product: dict, attribute_code: str
    ) -> str:
        """Extract a value from the custom_attributes array.

        Args:
            product: Raw Magento product dict.
            attribute_code: The attribute_code to look for.

        Returns:
            The attribute value as a string, or empty string if not found.
        """
        for attr in product.get("custom_attributes") or []:
            if not isinstance(attr, dict):
                continue
            if attr.get("attribute_code") == attribute_code:
                val = attr.get("value")
                if val is not None:
                    return str(val)
        return ""

    @staticmethod
    def _extract_gtin(product: dict) -> str:
        """Scan custom_attributes for GTIN-like attribute codes.

        Checks ean, gtin, gtin13, barcode, upc, ean13 in order and returns
        the first non-empty value found.

        Args:
            product: Raw Magento product dict.

        Returns:
            GTIN string or empty string.
        """
        for code in _GTIN_ATTRIBUTE_CODES:
            for attr in product.get("custom_attributes") or []:
                if not isinstance(attr, dict):
                    continue
                if attr.get("attribute_code") == code:
                    val = attr.get("value")
                    if val is not None and str(val).strip():
                        return str(val).strip()
        return ""

    # -- Field Mapping ------------------------------------------------------

    def _map_product(
        self,
        product: dict,
        children: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Map a Magento product to the raw dict expected by ProductNormalizer.

        Args:
            product: Raw product dict from the Magento API.
            children: Optional list of child product dicts for configurable
                products.

        Returns:
            Mapped product dict.
        """
        url_key = self._get_custom_attribute(product, "url_key")
        image_path = self._get_custom_attribute(product, "image")
        description = self._get_custom_attribute(product, "description")
        manufacturer = self._get_custom_attribute(product, "manufacturer")
        gtin = self._extract_gtin(product)

        # Additional images from media_gallery_entries
        additional_images: list[str] = []
        primary_image_url = self._image_url(image_path)
        for entry in product.get("media_gallery_entries") or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("disabled"):
                continue
            file_path = entry.get("file", "")
            if file_path:
                img_url = self._image_url(file_path)
                if img_url and img_url != primary_image_url:
                    additional_images.append(img_url)

        # Stock from extension_attributes.stock_item
        ext_attrs = product.get("extension_attributes") or {}
        stock_item = ext_attrs.get("stock_item") or {}
        in_stock = bool(stock_item.get("is_in_stock", False))
        qty = stock_item.get("qty", 0)

        # Variants from children
        variants: list[dict] = []
        if children:
            variants = self._map_variants(children)

        return {
            "id": product.get("id", ""),
            "title": product.get("name", ""),
            "description": description,
            "handle": url_key,
            "sku": product.get("sku", ""),
            "gtin": gtin,
            "barcode": gtin,
            "mpn": "",
            "price": str(product.get("price", "")),
            "compare_at_price": None,
            "currency": self._currency,
            "vendor": manufacturer,
            "product_type": product.get("type_id", ""),
            "tags": [],
            "in_stock": in_stock,
            "stock_quantity": qty,
            "image_url": primary_image_url,
            "additional_images": additional_images,
            "product_url": self._product_url(url_key),
            "variants": variants,
            "weight": product.get("weight"),
            "condition": "New",
            "_source": "magento_admin_api",
            "_platform": "magento",
        }

    def _map_variants(self, children: list[dict]) -> list[dict]:
        """Map Magento child products to the standard variant format.

        Args:
            children: List of raw child product dicts.

        Returns:
            List of variant dicts.
        """
        variants: list[dict] = []
        for child in children:
            if not isinstance(child, dict):
                continue

            ext_attrs = child.get("extension_attributes") or {}
            stock_item = ext_attrs.get("stock_item") or {}
            in_stock = bool(stock_item.get("is_in_stock", False))

            variants.append({
                "variant_id": child.get("id", ""),
                "title": child.get("name", ""),
                "price": str(child.get("price", "")),
                "sku": child.get("sku", ""),
                "gtin": self._extract_gtin(child),
                "barcode": self._extract_gtin(child),
                "in_stock": in_stock,
            })
        return variants

    # -- Extraction ---------------------------------------------------------

    async def extract(self, shop_url: str) -> ExtractorResult:
        """Fetch all enabled, visible products from the Magento 2 Admin API.

        Paginates through GET /rest/V1/products with searchCriteria. For
        configurable products, batch-fetches children and maps them as
        variants.

        Args:
            shop_url: The shop URL -- used for logging context only.

        Returns:
            ExtractorResult with all products and pagination metadata.
        """
        all_products: list[dict[str, Any]] = []
        configurable_ids: dict[int, list[int]] = {}  # parent_id -> child_ids
        complete = True
        error: str | None = None
        total_count: int | None = None
        page = 1

        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._access_token}",
                "User-Agent": get_default_user_agent(),
            },
            follow_redirects=True,
        ) as client:
            products_url = f"{self._base_url()}/products"

            while page <= _MAX_PAGES:
                logger.info(
                    "Magento Admin API: fetching page %d for %s",
                    page, self._shop_domain,
                )

                params = self._build_search_params(page)

                try:
                    resp = await client.get(products_url, params=params)

                    # 401 -- permanent token, no refresh possible
                    if resp.status_code == 401:
                        logger.error(
                            "Magento Admin API: 401 Unauthorized for %s",
                            self._shop_domain,
                        )
                        return ExtractorResult(
                            products=[],
                            complete=False,
                            error="API credentials invalid (401 Unauthorized)",
                        )

                    # 429 -- rate limited, retry once
                    if resp.status_code == 429:
                        retry_after = float(
                            resp.headers.get("Retry-After", "5")
                        )
                        logger.warning(
                            "Magento Admin API: rate limited, waiting %.1fs",
                            retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        resp = await client.get(products_url, params=params)
                        if resp.status_code == 429:
                            complete = False
                            error = f"Rate limited on page {page}"
                            break

                    if resp.status_code != 200:
                        logger.error(
                            "Magento Admin API: HTTP %d on page %d for %s",
                            resp.status_code, page, self._shop_domain,
                        )
                        complete = False
                        error = f"HTTP {resp.status_code} on page {page}"
                        break

                    data = resp.json()
                    items: list[dict] = data.get("items") or []

                    if total_count is None:
                        total_count = data.get("total_count", 0)
                        logger.info(
                            "Magento Admin API: %d total products found at %s",
                            total_count, self._shop_domain,
                        )

                    if not items:
                        break

                    for item in items:
                        # Track configurable products for child fetching
                        if item.get("type_id") == "configurable":
                            ext = item.get("extension_attributes") or {}
                            child_ids = ext.get(
                                "configurable_product_links", []
                            )
                            if child_ids:
                                configurable_ids[item["id"]] = [
                                    int(cid) for cid in child_ids[:_MAX_CHILDREN]
                                ]

                        mapped = self._map_product(item)
                        all_products.append(mapped)

                    logger.info(
                        "Magento Admin API: page %d returned %d products "
                        "(cumulative: %d)",
                        page, len(items), len(all_products),
                    )

                    if total_count is not None and len(all_products) >= total_count:
                        break

                    page += 1

                except httpx.TimeoutException:
                    logger.warning(
                        "Magento Admin API: timeout on page %d for %s",
                        page, self._shop_domain,
                    )
                    complete = False
                    error = f"Timeout on page {page}"
                    break
                except httpx.RequestError as exc:
                    logger.error(
                        "Magento Admin API: request error on page %d for %s: %s",
                        page, self._shop_domain, exc,
                    )
                    complete = False
                    error = f"Request error on page {page}: {exc}"
                    break

            # Batch-fetch children for configurable products
            if configurable_ids:
                await self._fetch_and_attach_children(
                    client, all_products, configurable_ids
                )

        logger.info(
            "Magento Admin API: extracted %d products from %d pages for %s",
            len(all_products), page, self._shop_domain,
        )
        pages_expected = (
            (total_count + _PAGE_SIZE - 1) // _PAGE_SIZE
            if total_count
            else None
        )
        return ExtractorResult(
            products=all_products,
            complete=complete,
            error=error,
            pages_completed=page if all_products else 0,
            pages_expected=pages_expected,
        )

    async def _fetch_and_attach_children(
        self,
        client: httpx.AsyncClient,
        all_products: list[dict],
        configurable_ids: dict[int, list[int]],
    ) -> None:
        """Batch-fetch children for configurable products and attach as variants.

        Args:
            client: Active httpx client.
            all_products: Mutable list of mapped products -- variants are
                attached in-place.
            configurable_ids: Mapping of parent product ID to child entity IDs.
        """
        # Collect all child IDs
        all_child_ids: list[int] = []
        for child_ids in configurable_ids.values():
            all_child_ids.extend(child_ids)

        if not all_child_ids:
            return

        # Deduplicate
        all_child_ids = list(set(all_child_ids))

        logger.info(
            "Magento Admin API: fetching %d children for %d configurable "
            "products at %s",
            len(all_child_ids), len(configurable_ids), self._shop_domain,
        )

        products_url = f"{self._base_url()}/products"
        params = self._build_children_params(all_child_ids)

        try:
            resp = await client.get(products_url, params=params)
            if resp.status_code != 200:
                logger.warning(
                    "Magento Admin API: HTTP %d fetching children for %s",
                    resp.status_code, self._shop_domain,
                )
                return

            data = resp.json()
            children_items = data.get("items") or []

            # Index children by ID
            children_by_id: dict[int, dict] = {}
            for child in children_items:
                if isinstance(child, dict):
                    children_by_id[child.get("id")] = child

            # Attach variants to parent products
            for product in all_products:
                parent_id = product.get("id")
                if parent_id not in configurable_ids:
                    continue

                child_ids = configurable_ids[parent_id]
                children = [
                    children_by_id[cid]
                    for cid in child_ids
                    if cid in children_by_id
                ]
                if children:
                    product["variants"] = self._map_variants(children)

        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning(
                "Magento Admin API: error fetching children for %s: %s",
                self._shop_domain, exc,
            )
