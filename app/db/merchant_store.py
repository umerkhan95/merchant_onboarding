"""Merchant account, API key, refresh token, and audit log CRUD."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.db.queries import (
    INSERT_API_KEY,
    INSERT_AUDIT_LOG,
    INSERT_MERCHANT_ACCOUNT,
    INSERT_MERCHANT_ROLE,
    INSERT_REFRESH_TOKEN,
    RESET_MERCHANT_FAILED_LOGIN,
    REVOKE_ALL_MERCHANT_REFRESH_TOKENS,
    REVOKE_API_KEY,
    REVOKE_REFRESH_TOKEN,
    REVOKE_REFRESH_TOKEN_FAMILY,
    SELECT_ACTIVE_SESSIONS,
    SELECT_API_KEY_BY_HASH,
    SELECT_API_KEYS_BY_MERCHANT,
    SELECT_MERCHANT_BY_EMAIL_HASH,
    SELECT_MERCHANT_BY_ID,
    SELECT_MERCHANT_PERMISSIONS,
    SELECT_REFRESH_TOKEN_BY_HASH,
    UPDATE_API_KEY_LAST_USED,
    UPDATE_MERCHANT_FAILED_LOGIN,
)
from app.security.password import hash_password, verify_password

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient

logger = logging.getLogger(__name__)


@dataclass
class MerchantAccount:
    """Decrypted merchant account data."""

    id: str
    email: str
    account_status: str = "active"
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    permissions: list[str] = field(default_factory=list)


class MerchantStore:
    """Manages merchant accounts, API keys, refresh tokens, and audit log."""

    def __init__(self, db: DatabaseClient):
        self._db = db
        self._fernet = self._init_fernet()

    @staticmethod
    def _init_fernet() -> Fernet | None:
        key = settings.oauth_encryption_key
        if not key:
            logger.warning("OAUTH_ENCRYPTION_KEY not set — email encryption unavailable")
            return None
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except Exception:
            logger.error("Invalid OAUTH_ENCRYPTION_KEY")
            return None

    def _encrypt(self, value: str) -> bytes:
        if not self._fernet:
            return value.encode("utf-8")
        return self._fernet.encrypt(value.encode("utf-8"))

    def _decrypt(self, value: bytes) -> str:
        if not self._fernet:
            return value.decode("utf-8") if isinstance(value, bytes) else str(value)
        try:
            return self._fernet.decrypt(value).decode("utf-8")
        except InvalidToken:
            logger.error("Failed to decrypt email — key may have changed")
            return ""

    @staticmethod
    def _hash_email(email: str) -> str:
        return hashlib.sha256(email.lower().strip().encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    # --- Account CRUD ---

    async def create_account(self, email: str, password: str) -> MerchantAccount:
        """Create a new merchant account with 'merchant' role.

        Uses a transaction to ensure account + role assignment are atomic.
        Raises asyncpg.UniqueViolationError if email already exists (race condition safe).
        """
        merchant_id = str(uuid.uuid4())
        email_hash = self._hash_email(email)
        email_enc = self._encrypt(email.lower().strip())
        pw_hash = hash_password(password)

        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                await conn.fetchrow(
                    INSERT_MERCHANT_ACCOUNT, merchant_id, email_hash, email_enc, pw_hash,
                )
                await conn.execute(INSERT_MERCHANT_ROLE, merchant_id, "merchant")

        logger.info("Created merchant account: %s", merchant_id)
        return MerchantAccount(id=merchant_id, email=email.lower().strip())

    async def get_by_email(self, email: str) -> tuple[MerchantAccount | None, str | None]:
        """Look up account by email. Returns (account, password_hash)."""
        email_hash = self._hash_email(email)
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(SELECT_MERCHANT_BY_EMAIL_HASH, email_hash)
        if not row:
            return None, None
        account = MerchantAccount(
            id=str(row["id"]),
            email=self._decrypt(row["email_encrypted"]),
            account_status=row["account_status"],
            failed_login_attempts=row["failed_login_attempts"],
            locked_until=row["locked_until"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        return account, row["password_hash"]

    async def get_by_id(self, merchant_id: str) -> MerchantAccount | None:
        """Look up account by UUID."""
        try:
            mid = uuid.UUID(merchant_id)
        except (ValueError, AttributeError):
            return None
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(SELECT_MERCHANT_BY_ID, mid)
        if not row:
            return None
        return MerchantAccount(
            id=str(row["id"]),
            email=self._decrypt(row["email_encrypted"]),
            account_status=row["account_status"],
            failed_login_attempts=row["failed_login_attempts"],
            locked_until=row["locked_until"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def record_failed_login(self, merchant_id: str) -> None:
        try:
            mid = uuid.UUID(merchant_id)
        except (ValueError, AttributeError):
            logger.warning("Invalid merchant_id in record_failed_login: %s", merchant_id)
            return
        async with self._db.pool.acquire() as conn:
            await conn.execute(
                UPDATE_MERCHANT_FAILED_LOGIN,
                mid,
                settings.account_lockout_attempts,
                str(settings.account_lockout_minutes),
            )

    async def reset_failed_logins(self, merchant_id: str) -> None:
        try:
            mid = uuid.UUID(merchant_id)
        except (ValueError, AttributeError):
            return
        async with self._db.pool.acquire() as conn:
            await conn.execute(RESET_MERCHANT_FAILED_LOGIN, mid)

    def is_locked(self, account: MerchantAccount) -> bool:
        if not account.locked_until:
            return False
        return account.locked_until > datetime.now(timezone.utc)

    async def get_permissions(self, merchant_id: str) -> list[str]:
        try:
            mid = uuid.UUID(merchant_id)
        except (ValueError, AttributeError):
            return []
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(SELECT_MERCHANT_PERMISSIONS, mid)
        return [r["code"] for r in rows]

    # --- Refresh Tokens ---

    async def create_refresh_token(
        self, merchant_id: str, *, user_agent: str = "", ip_address: str = "",
        token_family: str | None = None,
    ) -> tuple[str, str]:
        """Create a refresh token. Returns (raw_token, token_id)."""
        raw_token = secrets.token_urlsafe(64)
        token_id = str(uuid.uuid4())
        family = token_family or str(uuid.uuid4())
        token_hash = self._hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expiry_days)

        async with self._db.pool.acquire() as conn:
            await conn.execute(
                INSERT_REFRESH_TOKEN,
                uuid.UUID(token_id),
                uuid.UUID(merchant_id),
                token_hash,
                uuid.UUID(family),
                expires_at,
                user_agent,
                ip_address,
            )
        return raw_token, token_id

    async def verify_refresh_token(self, raw_token: str) -> dict | None:
        """Verify a refresh token. Returns token row dict or None."""
        token_hash = self._hash_token(raw_token)
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(SELECT_REFRESH_TOKEN_BY_HASH, token_hash)
        if not row:
            return None
        return dict(row)

    async def rotate_refresh_token(
        self, old_token: str, merchant_id: str, *,
        user_agent: str = "", ip_address: str = "",
    ) -> tuple[str, str] | None:
        """Rotate a refresh token. Revokes old, creates new in same family.

        Uses a transaction to ensure atomicity -- if the server crashes between
        revoking the old token and inserting the new one, both operations roll back.

        Returns (new_raw_token, new_token_id) or None if replay detected.
        """
        token_data = await self.verify_refresh_token(old_token)
        if not token_data:
            return None

        # Replay detection: if already revoked, revoke entire family
        if token_data["revoked"]:
            logger.warning("Refresh token replay detected for family %s", token_data["token_family"])
            await self._revoke_family(str(token_data["token_family"]))
            await self.audit_log(merchant_id, "refresh_token_replay", ip_address, user_agent)
            return None

        # Check expiry
        if token_data["expires_at"] < datetime.now(timezone.utc):
            return None

        # Check merchant match
        if str(token_data["merchant_id"]) != merchant_id:
            return None

        # Atomic rotation: revoke old + insert new in one transaction
        raw_token = secrets.token_urlsafe(64)
        token_id = str(uuid.uuid4())
        family = str(token_data["token_family"])
        token_hash = self._hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_expiry_days)

        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(REVOKE_REFRESH_TOKEN, token_data["id"])
                await conn.execute(
                    INSERT_REFRESH_TOKEN,
                    uuid.UUID(token_id),
                    uuid.UUID(merchant_id),
                    token_hash,
                    uuid.UUID(family),
                    expires_at,
                    user_agent,
                    ip_address,
                )

        return raw_token, token_id

    async def _revoke_family(self, token_family: str) -> None:
        async with self._db.pool.acquire() as conn:
            await conn.execute(REVOKE_REFRESH_TOKEN_FAMILY, uuid.UUID(token_family))

    async def revoke_all_sessions(self, merchant_id: str) -> None:
        try:
            mid = uuid.UUID(merchant_id)
        except (ValueError, AttributeError):
            return
        async with self._db.pool.acquire() as conn:
            await conn.execute(REVOKE_ALL_MERCHANT_REFRESH_TOKENS, mid)

    async def list_sessions(self, merchant_id: str) -> list[dict]:
        try:
            mid = uuid.UUID(merchant_id)
        except (ValueError, AttributeError):
            return []
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(SELECT_ACTIVE_SESSIONS, mid)
        return [
            {
                "id": str(r["id"]),
                "token_family": str(r["token_family"]),
                "user_agent": r["user_agent"],
                "ip_address": r["ip_address"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
            }
            for r in rows
        ]

    # --- API Keys ---

    async def create_api_key(
        self, merchant_id: str, *, name: str = "", scopes: str = "",
        expires_at: datetime | None = None,
    ) -> tuple[str, dict]:
        """Create a per-merchant API key. Returns (raw_key, key_metadata)."""
        raw_key = f"mk_{secrets.token_urlsafe(32)}"
        key_id = str(uuid.uuid4())
        key_hash = self._hash_token(raw_key)
        key_prefix = raw_key[:12]

        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(
                INSERT_API_KEY,
                uuid.UUID(key_id),
                uuid.UUID(merchant_id),
                key_hash,
                key_prefix,
                name,
                scopes,
                expires_at,
            )
        metadata = {
            "id": str(row["id"]),
            "key_prefix": row["key_prefix"],
            "name": row["name"],
            "scopes": row["scopes"],
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        return raw_key, metadata

    async def verify_api_key(self, raw_key: str) -> dict | None:
        """Verify a per-merchant API key. Returns key row dict or None."""
        key_hash = self._hash_token(raw_key)
        async with self._db.pool.acquire() as conn:
            row = await conn.fetchrow(SELECT_API_KEY_BY_HASH, key_hash)
        if not row:
            return None
        if row["account_status"] != "active":
            return None
        # Touch last_used (non-critical)
        try:
            async with self._db.pool.acquire() as conn:
                await conn.execute(UPDATE_API_KEY_LAST_USED, row["id"])
        except Exception:
            pass
        return dict(row)

    async def list_api_keys(self, merchant_id: str) -> list[dict]:
        async with self._db.pool.acquire() as conn:
            rows = await conn.fetch(SELECT_API_KEYS_BY_MERCHANT, uuid.UUID(merchant_id))
        return [
            {
                "id": str(r["id"]),
                "key_prefix": r["key_prefix"],
                "name": r["name"],
                "scopes": r["scopes"],
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
                "revoked": r["revoked"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

    async def revoke_api_key(self, key_id: str, merchant_id: str) -> bool:
        """Revoke an API key. Returns True if a key was actually revoked."""
        try:
            kid = uuid.UUID(key_id)
            mid = uuid.UUID(merchant_id)
        except (ValueError, AttributeError):
            return False
        async with self._db.pool.acquire() as conn:
            result = await conn.execute(REVOKE_API_KEY, kid, mid)
        # asyncpg returns "UPDATE N" -- check if any row was updated
        return result != "UPDATE 0"

    # --- Audit Log ---

    async def audit_log(
        self, merchant_id: str | None, event_type: str,
        ip_address: str = "", user_agent: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        try:
            mid = uuid.UUID(merchant_id) if merchant_id else None
            async with self._db.pool.acquire() as conn:
                await conn.execute(
                    INSERT_AUDIT_LOG, mid, event_type, ip_address, user_agent,
                    json.dumps(details or {}),
                )
        except Exception:
            logger.warning("Failed to write audit log: %s", event_type, exc_info=True)
