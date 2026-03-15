"""Coordinator for OAuth-authenticated admin API extraction.

Encapsulates the repeated pattern of: look up OAuth connection -> validate
credentials -> create admin extractor -> return extractor + tier for the
caller to run.

This is a pure extraction of duplicated logic from Pipeline._extract_products().
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.models.enums import ExtractionTier, Platform

if TYPE_CHECKING:
    from app.db.oauth_store import OAuthConnection, OAuthStore
    from app.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)

# BigCommerce mybigcommerce.com domain pattern: store-{hash}.mybigcommerce.com
_BC_STORE_HASH_RE = re.compile(r"store-([a-z0-9]+)\.mybigcommerce\.com")

# Maps platform enum to (oauth platform name, ExtractionTier)
_PLATFORM_TIER_MAP: dict[Platform, tuple[str, ExtractionTier]] = {
    Platform.SHOPIFY: ("shopify", ExtractionTier.SHOPIFY_ADMIN_API),
    Platform.WOOCOMMERCE: ("woocommerce", ExtractionTier.WOOCOMMERCE_API),
    Platform.BIGCOMMERCE: ("bigcommerce", ExtractionTier.BIGCOMMERCE_API),
    Platform.MAGENTO: ("magento", ExtractionTier.MAGENTO_API),
    Platform.SHOPWARE: ("shopware", ExtractionTier.SHOPWARE_API),
}


class OAuthExtractionCoordinator:
    """Resolves OAuth connections and creates admin API extractors.

    Handles all 5 platforms: Shopify, WooCommerce, BigCommerce, Magento, Shopware.
    Returns an extractor + tier on success, or None when no valid connection exists.
    """

    def __init__(self, oauth_store: OAuthStore) -> None:
        self._oauth_store = oauth_store

    async def resolve_platform_override(
        self, platform: Platform, shop_url: str
    ) -> Platform:
        """Check if an OAuth connection exists for a non-detected platform.

        When the detected platform is not BigCommerce/Shopware/Magento, checks
        for stored OAuth connections that would override the detection result.

        Args:
            platform: Currently detected platform.
            shop_url: Shop URL to look up connections for.

        Returns:
            Possibly overridden Platform enum value.
        """
        if platform in (Platform.BIGCOMMERCE, Platform.SHOPWARE, Platform.MAGENTO):
            return platform

        domain = urlparse(shop_url).netloc or shop_url

        # Check BigCommerce
        bc_conn = await self._oauth_store.get_connection("bigcommerce", domain)
        if not bc_conn:
            m = _BC_STORE_HASH_RE.match(domain)
            if m:
                bc_conn = await self._oauth_store.get_connection("bigcommerce", m.group(1))
        if bc_conn:
            logger.info(
                "Found BigCommerce OAuth connection for %s, overriding platform=%s",
                domain, platform,
            )
            return Platform.BIGCOMMERCE

        # Check Shopware
        sw_conn = await self._oauth_store.get_connection("shopware", domain)
        if not sw_conn:
            sw_conn = await self._oauth_store.get_connection_by_domain(domain)
        if sw_conn:
            logger.info(
                "Found Shopware OAuth for %s, overriding platform=%s",
                domain, platform,
            )
            return Platform.SHOPWARE

        # Check Magento
        mg_conn = await self._oauth_store.get_connection("magento", domain)
        if not mg_conn:
            mg_conn = await self._oauth_store.get_connection_by_domain(domain)
        if mg_conn:
            logger.info(
                "Found Magento OAuth for %s, overriding platform=%s",
                domain, platform,
            )
            return Platform.MAGENTO

        return platform

    async def try_resolve(
        self, platform: Platform, shop_url: str
    ) -> tuple[BaseExtractor, ExtractionTier] | None:
        """Attempt to resolve an OAuth connection and create an admin extractor.

        Looks up the OAuth connection, validates credentials, and creates the
        appropriate admin extractor. Returns None if no connection exists or
        credentials are insufficient.

        Args:
            platform: Platform to resolve for.
            shop_url: Shop URL to look up connections for.

        Returns:
            Tuple of (admin_extractor, extraction_tier) on success, or None.
        """
        if platform not in _PLATFORM_TIER_MAP:
            return None

        oauth_name, extraction_tier = _PLATFORM_TIER_MAP[platform]
        domain = urlparse(shop_url).netloc or shop_url

        conn = await self._lookup_connection(platform, oauth_name, domain)
        if conn is None:
            return None

        extractor = self._create_extractor(platform, conn)
        if extractor is None:
            return None

        return extractor, extraction_tier

    async def _lookup_connection(
        self, platform: Platform, oauth_name: str, domain: str
    ) -> OAuthConnection | None:
        """Look up an OAuth connection for the given platform and domain."""
        conn = await self._oauth_store.get_connection(oauth_name, domain)

        if not conn and platform == Platform.BIGCOMMERCE:
            # Try extracting store hash from mybigcommerce.com domain
            m = _BC_STORE_HASH_RE.match(domain)
            if m:
                conn = await self._oauth_store.get_connection("bigcommerce", m.group(1))
            if not conn:
                conn = await self._oauth_store.get_connection_by_domain(domain)
        elif not conn:
            conn = await self._oauth_store.get_connection_by_domain(domain)

        if not conn:
            return None

        # Validate credentials are sufficient for the platform
        if platform == Platform.SHOPIFY:
            if not conn.access_token:
                return None
        elif platform == Platform.WOOCOMMERCE:
            if not conn.consumer_key or not conn.consumer_secret:
                return None
        elif platform == Platform.BIGCOMMERCE:
            # BigCommerceAdminExtractor validates access_token + store_hash internally
            pass
        elif platform == Platform.MAGENTO:
            if not conn.access_token:
                return None
        elif platform == Platform.SHOPWARE:
            if not conn.access_token or not conn.refresh_token:
                return None

        return conn

    @staticmethod
    def _create_extractor(
        platform: Platform, conn: OAuthConnection
    ) -> BaseExtractor | None:
        """Create the appropriate admin extractor for the platform."""
        if platform == Platform.SHOPIFY:
            from app.extractors.shopify_admin_extractor import ShopifyAdminExtractor
            return ShopifyAdminExtractor(
                access_token=conn.access_token,
                shop_domain=conn.shop_domain,
            )
        elif platform == Platform.WOOCOMMERCE:
            from app.extractors.woocommerce_admin_extractor import WooCommerceAdminExtractor
            return WooCommerceAdminExtractor(conn)
        elif platform == Platform.BIGCOMMERCE:
            from app.extractors.bigcommerce_admin_extractor import BigCommerceAdminExtractor
            return BigCommerceAdminExtractor(conn)
        elif platform == Platform.MAGENTO:
            from app.extractors.magento_admin_extractor import MagentoAdminExtractor
            return MagentoAdminExtractor(conn)
        elif platform == Platform.SHOPWARE:
            from app.extractors.shopware_admin_extractor import ShopwareAdminExtractor
            return ShopwareAdminExtractor(conn)
        return None
