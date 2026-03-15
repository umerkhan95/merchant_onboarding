"""Tests for password hashing and verification."""

from app.security.password import hash_password, verify_password


def test_hash_and_verify():
    pw = "secureP@ss123"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed)


def test_wrong_password():
    hashed = hash_password("correct-password")
    assert not verify_password("wrong-password", hashed)


def test_different_hashes_for_same_password():
    pw = "samepassword"
    h1 = hash_password(pw)
    h2 = hash_password(pw)
    assert h1 != h2  # bcrypt uses random salt
    assert verify_password(pw, h1)
    assert verify_password(pw, h2)


def test_unicode_password():
    pw = "p\u00e4ssw\u00f6rd\U0001f512"
    hashed = hash_password(pw)
    assert verify_password(pw, hashed)


def test_empty_password():
    hashed = hash_password("")
    assert verify_password("", hashed)
    assert not verify_password("notempty", hashed)
