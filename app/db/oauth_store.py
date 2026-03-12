"""Encrypted OAuth token/credential storage backed by PostgreSQL."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.db.queries import (
    DELETE_OAUTH_CONNECTION,
    SELECT_ALL_OAUTH_CONNECTIONS,
    SELECT_OAUTH_CONNECTION,
    SELECT_OAUTH_CONNECTION_BY_DOMAIN,
    UPDATE_OAUTH_LAST_USED,
    UPSERT_OAUTH_CONNECTION,
)

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient

logger = logging.getLogger(__name__)


@dataclass
class OAuthConnection:
    """Decrypted OAuth connection data."""

    id: int
    platform: str
    shop_domain: str
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    scopes: str | None = None
    consumer_key: str | None = None
    consumer_secret: str | None = None
    access_token_secret: str | None = None
    store_hash: str | None = None
    extra_data: dict | None = None
    connected_at: datetime | None = None
    last_used_at: datetime | None = None
    status: str = "active"

    def __post_init__(self):
        if self.extra_data is None:
            self.extra_data = {}


class OAuthStore:
    """Manages encrypted OAuth credentials in PostgreSQL via asyncpg."""

    def __init__(self, db: DatabaseClient):
        self._db = db
        self._fernet = self._init_fernet()

    @staticmethod
    def _init_fernet() -> Fernet | None:
        key = settings.oauth_encryption_key
        if not key:
            logger.warning("OAUTH_ENCRYPTION_KEY not set — OAuth tokens will not be stored")
            return None
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except Exception:
            logger.error("Invalid OAUTH_ENCRYPTION_KEY — must be a valid Fernet key")
            return None

    def _encrypt(self, value: str | None) -> bytes | None:
        if not value or not self._fernet:
            return None
        return self._fernet.encrypt(value.encode("utf-8"))

    def _decrypt(self, value: bytes | None) -> str | None:
        if not value or not self._fernet:
            return None
        try:
            return self._fernet.decrypt(value).decode("utf-8")
        except InvalidToken:
            logger.error("Failed to decrypt OAuth token — key may have changed")
            return None

    async def store_connection(
        self,
        platform: str,
        shop_domain: str,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expires_at: datetime | None = None,
        scopes: str | None = None,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        access_token_secret: str | None = None,
        store_hash: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        """Encrypt and store an OAuth connection."""
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                UPSERT_OAUTH_CONNECTION,
                platform,
                shop_domain,
                self._encrypt(access_token),
                self._encrypt(refresh_token),
                token_expires_at,
                scopes,
                self._encrypt(consumer_key),
                self._encrypt(consumer_secret),
                self._encrypt(access_token_secret),
                store_hash,
                json.dumps(extra_data or {}),
            )
        logger.info("Stored OAuth connection: %s / %s", platform, shop_domain)

    async def get_connection(self, platform: str, shop_domain: str) -> OAuthConnection | None:
        """Retrieve and decrypt a specific OAuth connection."""
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(SELECT_OAUTH_CONNECTION, platform, shop_domain)
        if not row:
            return None
        await self._touch_last_used(platform, shop_domain)
        return self._row_to_connection(row)

    async def get_connection_by_domain(self, shop_domain: str) -> OAuthConnection | None:
        """Retrieve any active OAuth connection for a shop domain."""
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(SELECT_OAUTH_CONNECTION_BY_DOMAIN, shop_domain)
        if not row:
            return None
        await self._touch_last_used(row["platform"], shop_domain)
        return self._row_to_connection(row)

    async def list_connections(self) -> list[dict]:
        """List all connections (without decrypted tokens)."""
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(SELECT_ALL_OAUTH_CONNECTIONS)
        return [dict(r) for r in rows]

    async def revoke_connection(self, platform: str, shop_domain: str) -> None:
        """Mark a connection as revoked (soft delete)."""
        async with self._db.pool.acquire() as conn:
            await conn.execute(DELETE_OAUTH_CONNECTION, platform, shop_domain)
        logger.info("Revoked OAuth connection: %s / %s", platform, shop_domain)

    async def _touch_last_used(self, platform: str, shop_domain: str) -> None:
        """Update last_used_at timestamp."""
        try:
            async with self._db.pool.acquire() as conn:
                await conn.execute(UPDATE_OAUTH_LAST_USED, platform, shop_domain)
        except Exception:
            pass  # Non-critical — don't fail extraction for a timestamp update

    def _row_to_connection(self, row) -> OAuthConnection:
        """Convert a DB row to a decrypted OAuthConnection."""
        extra = row.get("extra_data", "{}")
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except (json.JSONDecodeError, TypeError):
                extra = {}

        return OAuthConnection(
            id=row["id"],
            platform=row["platform"],
            shop_domain=row["shop_domain"],
            access_token=self._decrypt(row.get("access_token_encrypted")),
            refresh_token=self._decrypt(row.get("refresh_token_encrypted")),
            token_expires_at=row.get("token_expires_at"),
            scopes=row.get("scopes"),
            consumer_key=self._decrypt(row.get("consumer_key_encrypted")),
            consumer_secret=self._decrypt(row.get("consumer_secret_encrypted")),
            access_token_secret=self._decrypt(row.get("access_token_secret_encrypted")),
            store_hash=row.get("store_hash"),
            extra_data=extra,
            connected_at=row.get("connected_at"),
            last_used_at=row.get("last_used_at"),
            status=row.get("status", "active"),
        )
