"""Tests for app.services.url_normalizer."""

from __future__ import annotations

from app.services.url_normalizer import normalize_shop_url


class TestNormalizeShopUrl:
    def test_strips_trailing_slash(self):
        assert normalize_shop_url("https://example.com/") == "https://example.com"

    def test_lowercases_hostname(self):
        assert normalize_shop_url("https://WWW.Example.COM/") == "https://www.example.com"

    def test_lowercases_scheme(self):
        assert normalize_shop_url("HTTPS://example.com") == "https://example.com"

    def test_removes_fragment(self):
        assert normalize_shop_url("https://example.com/#section") == "https://example.com"

    def test_removes_default_https_port(self):
        assert normalize_shop_url("https://example.com:443/") == "https://example.com"

    def test_removes_default_http_port(self):
        assert normalize_shop_url("http://example.com:80/") == "http://example.com"

    def test_preserves_non_default_port(self):
        assert normalize_shop_url("https://example.com:8080/") == "https://example.com:8080"

    def test_preserves_path(self):
        assert normalize_shop_url("https://example.com/shop") == "https://example.com/shop"

    def test_preserves_www(self):
        assert normalize_shop_url("https://www.example.com") == "https://www.example.com"

    def test_strips_trailing_slash_from_path(self):
        assert normalize_shop_url("https://example.com/shop/") == "https://example.com/shop"

    def test_idempotent(self):
        url = "https://www.AhmadTea.com/"
        once = normalize_shop_url(url)
        twice = normalize_shop_url(once)
        assert once == twice

    def test_preserves_query_params(self):
        assert (
            normalize_shop_url("https://example.com?ref=123")
            == "https://example.com?ref=123"
        )
