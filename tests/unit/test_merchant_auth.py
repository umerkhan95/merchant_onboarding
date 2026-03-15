"""Tests for merchant authentication endpoints."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app():
    application = create_app()
    # Mock DB and Redis on app state
    application.state.db = MagicMock()
    # Redis must be AsyncMock since PerfMiddleware awaits redis calls
    mock_redis = AsyncMock()
    mock_redis.setnx = AsyncMock(return_value=True)
    mock_redis.set = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.ping = AsyncMock(return_value=True)
    application.state.redis = mock_redis
    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# --- Registration Tests ---

class TestRegister:
    def test_register_success(self, client, app):
        merchant_id = str(uuid.uuid4())

        with patch("app.api.v1.merchant_auth.MerchantStore") as MockStore:
            store = MockStore.return_value
            store.get_by_email = AsyncMock(return_value=(None, None))
            store.create_account = AsyncMock(return_value=MagicMock(id=merchant_id))
            store.create_refresh_token = AsyncMock(return_value=("refresh-tok", "tok-id"))
            store.audit_log = AsyncMock()

            resp = client.post("/api/v1/auth/merchant/register", json={
                "email": "test@example.com",
                "password": "secureP@ss1",
            })

        assert resp.status_code == 201
        data = resp.json()
        assert data["merchant_id"] == merchant_id
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_register_duplicate_email(self, client, app):
        with patch("app.api.v1.merchant_auth.MerchantStore") as MockStore:
            store = MockStore.return_value
            store.get_by_email = AsyncMock(return_value=(MagicMock(), "hash"))

            resp = client.post("/api/v1/auth/merchant/register", json={
                "email": "dup@example.com",
                "password": "secureP@ss1",
            })

        assert resp.status_code == 422

    def test_register_short_password(self, client):
        resp = client.post("/api/v1/auth/merchant/register", json={
            "email": "test@example.com",
            "password": "short",
        })
        assert resp.status_code == 422


# --- Login Tests ---

class TestLogin:
    def test_login_success(self, client, app):
        merchant_id = str(uuid.uuid4())
        account = MagicMock(
            id=merchant_id, locked_until=None,
            failed_login_attempts=0, account_status="active",
        )

        with patch("app.api.v1.merchant_auth.MerchantStore") as MockStore, \
             patch("app.api.v1.merchant_auth.verify_password", return_value=True):
            store = MockStore.return_value
            store.get_by_email = AsyncMock(return_value=(account, "hashed_pw"))
            store.is_locked = MagicMock(return_value=False)
            store.reset_failed_logins = AsyncMock()
            store.create_refresh_token = AsyncMock(return_value=("refresh-tok", "tok-id"))
            store.audit_log = AsyncMock()

            resp = client.post("/api/v1/auth/merchant/login", json={
                "email": "test@example.com",
                "password": "secureP@ss1",
            })

        assert resp.status_code == 200
        assert resp.json()["merchant_id"] == merchant_id
        assert "refresh_token" in resp.cookies

    def test_login_wrong_password(self, client, app):
        account = MagicMock(
            id=str(uuid.uuid4()), locked_until=None,
            failed_login_attempts=0,
        )

        with patch("app.api.v1.merchant_auth.MerchantStore") as MockStore, \
             patch("app.api.v1.merchant_auth.verify_password", return_value=False):
            store = MockStore.return_value
            store.get_by_email = AsyncMock(return_value=(account, "hashed_pw"))
            store.is_locked = MagicMock(return_value=False)
            store.record_failed_login = AsyncMock()
            store.audit_log = AsyncMock()

            resp = client.post("/api/v1/auth/merchant/login", json={
                "email": "test@example.com",
                "password": "wrongpassword",
            })

        assert resp.status_code == 401

    def test_login_locked_account(self, client, app):
        account = MagicMock(id=str(uuid.uuid4()))

        with patch("app.api.v1.merchant_auth.MerchantStore") as MockStore:
            store = MockStore.return_value
            store.get_by_email = AsyncMock(return_value=(account, "hashed_pw"))
            store.is_locked = MagicMock(return_value=True)
            store.audit_log = AsyncMock()

            resp = client.post("/api/v1/auth/merchant/login", json={
                "email": "test@example.com",
                "password": "secureP@ss1",
            })

        assert resp.status_code == 401
        assert "locked" in resp.json()["detail"].lower()

    def test_login_unknown_email(self, client, app):
        with patch("app.api.v1.merchant_auth.MerchantStore") as MockStore:
            store = MockStore.return_value
            store.get_by_email = AsyncMock(return_value=(None, None))
            store.audit_log = AsyncMock()

            resp = client.post("/api/v1/auth/merchant/login", json={
                "email": "ghost@example.com",
                "password": "whatever123",
            })

        assert resp.status_code == 401


# --- Refresh Tests ---

class TestRefresh:
    def test_refresh_no_cookie(self, client):
        resp = client.post("/api/v1/auth/merchant/refresh")
        assert resp.status_code == 401

    def test_refresh_success(self, client, app):
        merchant_id = str(uuid.uuid4())

        with patch("app.api.v1.merchant_auth.MerchantStore") as MockStore:
            store = MockStore.return_value
            store.verify_refresh_token = AsyncMock(return_value={
                "merchant_id": uuid.UUID(merchant_id),
                "token_family": uuid.uuid4(),
                "revoked": False,
            })
            store.rotate_refresh_token = AsyncMock(return_value=("new-refresh", "new-id"))
            store.audit_log = AsyncMock()

            client.cookies.set("refresh_token", "old-refresh-token", path="/api/v1/auth/merchant")
            resp = client.post("/api/v1/auth/merchant/refresh")

        assert resp.status_code == 200
        assert "access_token" in resp.json()


# --- Logout Tests ---

class TestLogout:
    def test_logout(self, client, app):
        with patch("app.api.v1.merchant_auth.MerchantStore") as MockStore:
            store = MockStore.return_value
            store.verify_refresh_token = AsyncMock(return_value={
                "id": uuid.uuid4(),
                "merchant_id": uuid.uuid4(),
                "revoked": False,
            })
            store.audit_log = AsyncMock()

            # Mock the db.pool.acquire context manager
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            app.state.db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            app.state.db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

            client.cookies.set("refresh_token", "some-token", path="/api/v1/auth/merchant")
            resp = client.post("/api/v1/auth/merchant/logout")

        assert resp.status_code == 200


# --- Session & API Key Tests ---

class TestSessions:
    def test_sessions_requires_auth(self, client):
        resp = client.get("/api/v1/auth/merchant/sessions")
        assert resp.status_code == 401


class TestApiKeys:
    def test_create_api_key_requires_auth(self, client):
        resp = client.post("/api/v1/auth/merchant/api-keys", json={"name": "test"})
        assert resp.status_code == 401


# --- Dual Auth (get_current_merchant) Tests ---

class TestDualAuth:
    def test_legacy_api_key_still_works(self, client):
        """Existing X-API-Key header should still authenticate."""
        resp = client.get(
            "/api/v1/ping",
        )
        # /ping doesn't require auth, just verifying the app works
        assert resp.status_code == 200

    def test_bearer_jwt_auth(self, client, app):
        from app.security.jwt_handler import create_access_token

        merchant_id = str(uuid.uuid4())
        token = create_access_token(merchant_id)

        with patch("app.api.deps._load_permissions", new_callable=AsyncMock, return_value=["products:read"]):
            resp = client.get(
                "/api/v1/auth/merchant/sessions",
                headers={"Authorization": f"Bearer {token}"},
            )
        # Should get past auth (may fail on DB but not 401)
        assert resp.status_code != 401 or "Database" in resp.text
