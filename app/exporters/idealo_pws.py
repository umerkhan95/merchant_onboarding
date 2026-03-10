"""Idealo PWS 2.0 API client — pushes offers via REST API.

Reference: https://import.idealo.com
Auth: OAuth2 client credentials -> JWT (3600s expiry)
Endpoints: PUT/PATCH/DELETE /shop/{shopId}/offer/{sku}
Rate limit: 30,000 requests per 60 seconds
Message size limit: 395 KB
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

if TYPE_CHECKING:
    from app.models.product import Product

logger = logging.getLogger(__name__)

AUTH_URL = "https://api.idealo.com/mer/businessaccount/api/v1/oauth/token"
BASE_URL = "https://import.idealo.com"
TOKEN_EXPIRY_BUFFER = 60  # Refresh 60s before expiry
_PUSH_CONCURRENCY = 20  # Concurrent PUT requests (well within 30k/min limit)


class IdealoPWSClient:
    """Client for idealo PWS 2.0 REST API.

    Use as an async context manager to share a single httpx client:

        async with IdealoPWSClient(...) as pws:
            await pws.push_offers(products)
            await pws.delete_offer("SKU-123")
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        shop_id: str,
        delivery_time: str = "",
        delivery_costs: str = "",
        payment_costs: str = "",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.shop_id = shop_id
        self.delivery_time = delivery_time
        self.delivery_costs = delivery_costs
        self.payment_costs = payment_costs
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock: asyncio.Lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._owns_client: bool = False

    async def __aenter__(self) -> IdealoPWSClient:
        self._client = httpx.AsyncClient(timeout=30.0)
        self._owns_client = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create httpx client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self._client

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        """Get or refresh OAuth2 access token (thread-safe via asyncio.Lock)."""
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        async with self._token_lock:
            # Double-check after acquiring lock (another coroutine may have refreshed)
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token

            try:
                response = await client.post(
                    AUTH_URL,
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials"},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error("idealo PWS authentication failed: HTTP %s", e.response.status_code)
                raise RuntimeError(f"idealo PWS auth failed: HTTP {e.response.status_code}") from e
            except httpx.HTTPError as e:
                logger.error("idealo PWS authentication error: %s", e)
                raise RuntimeError(f"idealo PWS auth error: {e}") from e

            data = response.json()
            token: str = data["access_token"]
            self._access_token = token
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = time.monotonic() + expires_in - TOKEN_EXPIRY_BUFFER

            logger.info("idealo PWS token refreshed, expires in %ds", expires_in)
            return token

    def _product_to_offer(self, product: Product) -> dict[str, Any]:
        """Convert Product model to idealo PWS offer payload."""
        sku = product.sku or product.external_id
        all_images = [product.image_url] if product.image_url else []
        all_images.extend(product.additional_images or [])

        offer: dict[str, Any] = {
            "sku": sku,
            "title": product.title,
            "url": product.product_url,
            "price": str(product.price),
            "currency": product.currency,
            "brand": product.vendor or "",
            "description": product.description or "",
            "imageUrls": all_images,
        }

        if product.gtin:
            offer["eans"] = [product.gtin]
        if product.mpn:
            offer["hans"] = [product.mpn]
        if product.category_path:
            offer["categoryPath"] = product.category_path
        if product.condition:
            offer["condition"] = product.condition.upper()

        if self.delivery_time:
            offer["delivery"] = self.delivery_time
        if self.delivery_costs:
            offer["deliveryCosts"] = self.delivery_costs
        if self.payment_costs:
            offer["paymentCosts"] = self.payment_costs

        return offer

    def _offer_url(self, sku: str) -> str:
        """Build URL-safe offer endpoint path."""
        return f"{BASE_URL}/shop/{quote(self.shop_id, safe='')}/offer/{quote(sku, safe='')}"

    async def push_offers(self, products: list[Product]) -> dict[str, int]:
        """Push product offers to idealo via PWS 2.0 API.

        Uses concurrent requests (capped by _PUSH_CONCURRENCY semaphore)
        to stay well within idealo's 30k/min rate limit.

        Args:
            products: List of Product models to push

        Returns:
            Dict with counts: {"success": N, "failed": N, "skipped": N}
        """
        results = {"success": 0, "failed": 0, "skipped": 0}
        semaphore = asyncio.Semaphore(_PUSH_CONCURRENCY)
        client = self._get_client()

        async def _push_one(product: Product) -> None:
            sku = product.sku or product.external_id
            if not sku or not product.title or not product.price:
                results["skipped"] += 1
                return

            async with semaphore:
                try:
                    token = await self._ensure_token(client)
                    offer = self._product_to_offer(product)

                    response = await client.put(
                        self._offer_url(sku),
                        json=offer,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                    )
                    response.raise_for_status()
                    results["success"] += 1

                except RuntimeError:
                    # Auth failure — already logged in _ensure_token, abort all
                    results["failed"] += 1
                    raise
                except httpx.HTTPStatusError as e:
                    logger.warning("PWS push failed for SKU %s: %s", sku, e.response.status_code)
                    results["failed"] += 1
                except httpx.HTTPError as e:
                    logger.warning("PWS push error for SKU %s: %s", sku, e)
                    results["failed"] += 1

        await asyncio.gather(*[_push_one(p) for p in products])

        logger.info("idealo PWS push: %s", results)
        return results

    async def delete_offer(self, sku: str) -> bool:
        """Delete a single offer from idealo."""
        client = self._get_client()
        try:
            token = await self._ensure_token(client)
            response = await client.delete(
                self._offer_url(sku),
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.warning("PWS delete failed for SKU %s: %s", sku, e)
            return False
