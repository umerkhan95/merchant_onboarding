"""Tests for JWT access token creation and verification."""

import time

import jwt as pyjwt
import pytest

from app.security.jwt_handler import create_access_token, decode_access_token


def test_create_and_decode():
    merchant_id = "abc-123-def"
    token = create_access_token(merchant_id)
    payload = decode_access_token(token)
    assert payload["sub"] == merchant_id
    assert payload["type"] == "access"


def test_expired_token():
    token = create_access_token("merchant-1", expires_minutes=-1)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_access_token(token)


def test_invalid_token():
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_access_token("not.a.valid.token")


def test_tampered_token():
    token = create_access_token("merchant-1")
    # Replace the entire signature with garbage
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.INVALIDSIGNATUREDATA"
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_access_token(tampered)


def test_wrong_token_type():
    """A token with type != 'access' should be rejected."""
    from app.config import settings

    payload = {
        "sub": "merchant-1",
        "type": "refresh",
        "iat": time.time(),
        "exp": time.time() + 3600,
    }
    token = pyjwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    with pytest.raises(pyjwt.InvalidTokenError, match="Not an access token"):
        decode_access_token(token)


def test_custom_expiry():
    token = create_access_token("m-1", expires_minutes=60)
    payload = decode_access_token(token)
    assert payload["sub"] == "m-1"
