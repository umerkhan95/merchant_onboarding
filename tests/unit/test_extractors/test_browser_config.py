"""Unit tests for browser_config stealth levels and factory functions."""

from __future__ import annotations

from app.extractors.browser_config import (
    DEFAULT_DELAY_BEFORE_RETURN,
    DEFAULT_HEADERS,
    DEFAULT_PAGE_TIMEOUT,
    DISMISS_COOKIE_JS,
    HTTPX_USER_AGENT,
    PRODUCT_WAIT_CONDITION,
    StealthLevel,
    get_browser_config,
    get_crawl_config,
    get_crawler_strategy,
    get_default_user_agent,
)


class TestStealthLevel:
    """Test StealthLevel enum values."""

    def test_standard_value(self):
        assert StealthLevel.STANDARD == "standard"

    def test_stealth_value(self):
        assert StealthLevel.STEALTH == "stealth"

    def test_undetected_value(self):
        assert StealthLevel.UNDETECTED == "undetected"


class TestGetBrowserConfig:
    """Test get_browser_config factory function."""

    def test_standard_config(self):
        config = get_browser_config(StealthLevel.STANDARD)
        assert config.headless is True
        assert config.verbose is False
        assert config.text_mode is False  # JS must be enabled for SPAs
        assert config.enable_stealth is False

    def test_standard_config_has_headers(self):
        config = get_browser_config(StealthLevel.STANDARD)
        assert config.headers["Accept-Language"] == "en-US,en;q=0.9"

    def test_stealth_config_enables_stealth(self):
        config = get_browser_config(StealthLevel.STEALTH)
        assert config.enable_stealth is True

    def test_stealth_config_has_realistic_viewport(self):
        config = get_browser_config(StealthLevel.STEALTH)
        assert config.viewport_width == 1920
        assert config.viewport_height == 1080

    def test_stealth_config_has_accept_language(self):
        config = get_browser_config(StealthLevel.STEALTH)
        assert config.headers["Accept-Language"] == "en-US,en;q=0.9"

    def test_undetected_config_enables_stealth(self):
        config = get_browser_config(StealthLevel.UNDETECTED)
        assert config.enable_stealth is True

    def test_undetected_config_has_realistic_viewport(self):
        config = get_browser_config(StealthLevel.UNDETECTED)
        assert config.viewport_width == 1920
        assert config.viewport_height == 1080

    def test_custom_headless_flag(self):
        config = get_browser_config(StealthLevel.STANDARD, headless=False)
        assert config.headless is False

    def test_custom_text_mode_flag(self):
        config = get_browser_config(StealthLevel.STANDARD, text_mode=True)
        assert config.text_mode is True


class TestGetCrawlerStrategy:
    """Test get_crawler_strategy factory function."""

    def test_standard_returns_none(self):
        result = get_crawler_strategy(StealthLevel.STANDARD)
        assert result is None

    def test_stealth_returns_none(self):
        result = get_crawler_strategy(StealthLevel.STEALTH)
        assert result is None

    def test_undetected_returns_strategy(self):
        strategy = get_crawler_strategy(StealthLevel.UNDETECTED)
        assert strategy is not None

    def test_undetected_strategy_has_adapter(self):
        from crawl4ai import UndetectedAdapter
        strategy = get_crawler_strategy(StealthLevel.UNDETECTED)
        assert strategy is not None
        assert strategy.adapter is not None
        assert isinstance(strategy.adapter, UndetectedAdapter)

    def test_undetected_uses_provided_browser_config(self):
        config = get_browser_config(StealthLevel.UNDETECTED, headless=False)
        strategy = get_crawler_strategy(StealthLevel.UNDETECTED, browser_config=config)
        assert strategy is not None


class TestGetCrawlConfig:
    """Test get_crawl_config factory function."""

    def test_standard_no_anti_bot_flags(self):
        config = get_crawl_config(StealthLevel.STANDARD)
        assert config.simulate_user is False
        assert config.magic is False
        assert config.override_navigator is False

    def test_stealth_enables_anti_bot_flags(self):
        config = get_crawl_config(StealthLevel.STEALTH)
        assert config.simulate_user is True
        assert config.magic is True
        assert config.override_navigator is True

    def test_undetected_enables_anti_bot_flags(self):
        config = get_crawl_config(StealthLevel.UNDETECTED)
        assert config.simulate_user is True
        assert config.magic is True
        assert config.override_navigator is True

    def test_stealth_uses_domcontentloaded_by_default(self):
        config = get_crawl_config(StealthLevel.STEALTH)
        assert config.wait_until == "domcontentloaded"

    def test_stealth_increases_page_timeout(self):
        config = get_crawl_config(StealthLevel.STEALTH)
        assert config.page_timeout == 60000

    def test_stealth_increases_delay(self):
        config = get_crawl_config(StealthLevel.STEALTH)
        assert config.delay_before_return_html == 4.0

    def test_stealth_respects_explicit_wait_until(self):
        config = get_crawl_config(StealthLevel.STEALTH, wait_until="load")
        assert config.wait_until == "load"

    def test_stealth_respects_explicit_timeout(self):
        config = get_crawl_config(StealthLevel.STEALTH, page_timeout=90000)
        assert config.page_timeout == 90000

    def test_default_wait_condition(self):
        config = get_crawl_config()
        assert config.wait_for == PRODUCT_WAIT_CONDITION

    def test_default_page_timeout(self):
        config = get_crawl_config()
        assert config.page_timeout == DEFAULT_PAGE_TIMEOUT

    def test_default_delay(self):
        config = get_crawl_config()
        assert config.delay_before_return_html == DEFAULT_DELAY_BEFORE_RETURN

    def test_custom_wait_until(self):
        config = get_crawl_config(wait_until="domcontentloaded")
        assert config.wait_until == "domcontentloaded"

    def test_custom_page_timeout(self):
        config = get_crawl_config(page_timeout=60000)
        assert config.page_timeout == 60000

    def test_none_wait_for(self):
        config = get_crawl_config(wait_for=None)
        assert config.wait_for is None

    def test_extraction_strategy_passed_through(self):
        from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
        schema = {"baseSelector": ".product", "fields": [{"name": "title", "selector": "h1", "type": "text"}]}
        strategy = JsonCssExtractionStrategy(schema)
        config = get_crawl_config(extraction_strategy=strategy)
        assert config.extraction_strategy is strategy

    def test_deep_crawl_strategy_passed_through(self):
        from unittest.mock import MagicMock
        mock_strategy = MagicMock()
        config = get_crawl_config(deep_crawl_strategy=mock_strategy)
        assert config.deep_crawl_strategy is mock_strategy

    def test_js_code_includes_cookie_dismiss(self):
        """Cookie consent dismiss JS is injected into crawl config."""
        config = get_crawl_config()
        assert config.js_code == DISMISS_COOKIE_JS

    def test_no_max_scroll_steps(self):
        """max_scroll_steps should not be set (crawl4ai ignores it)."""
        config = get_crawl_config()
        # max_scroll_steps defaults to None when not passed
        default_val = getattr(config, "max_scroll_steps", None)
        # If the attribute exists, it should not be 20 (our old value)
        assert default_val != 20 or default_val is None


class TestExtractorsAcceptStealthLevel:
    """Test that all browser-based extractors accept stealth_level parameter."""

    def test_css_extractor_accepts_stealth_level(self):
        from app.extractors.css_extractor import CSSExtractor
        schema = {"baseSelector": ".product", "fields": []}
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STEALTH)
        assert extractor.stealth_level == StealthLevel.STEALTH

    def test_css_extractor_defaults_to_standard(self):
        from app.extractors.css_extractor import CSSExtractor
        schema = {"baseSelector": ".product", "fields": []}
        extractor = CSSExtractor(schema)
        assert extractor.stealth_level == StealthLevel.STANDARD

    def test_smart_css_extractor_accepts_stealth_level(self):
        from unittest.mock import MagicMock
        from crawl4ai import LLMConfig
        from app.extractors.smart_css_extractor import SmartCSSExtractor
        llm_config = LLMConfig(provider="openai/gpt-4o-mini", api_token="test")
        mock_cache = MagicMock()
        extractor = SmartCSSExtractor(llm_config, mock_cache, stealth_level=StealthLevel.UNDETECTED)
        assert extractor.stealth_level == StealthLevel.UNDETECTED

    def test_llm_extractor_accepts_stealth_level(self):
        from crawl4ai import LLMConfig
        from app.extractors.llm_extractor import LLMExtractor
        llm_config = LLMConfig(provider="openai/gpt-4o-mini", api_token="test")
        extractor = LLMExtractor(llm_config, stealth_level=StealthLevel.STEALTH)
        assert extractor.stealth_level == StealthLevel.STEALTH

    def test_url_discovery_accepts_stealth_level(self):
        from app.services.url_discovery import URLDiscoveryService
        service = URLDiscoveryService(stealth_level=StealthLevel.STEALTH)
        assert service.stealth_level == StealthLevel.STEALTH

    def test_url_discovery_defaults_to_standard(self):
        from app.services.url_discovery import URLDiscoveryService
        service = URLDiscoveryService()
        assert service.stealth_level == StealthLevel.STANDARD


class TestHttpxUserAgent:
    """Test single httpx UA (replaces old rotation pool)."""

    def test_httpx_user_agent_is_modern_chrome(self):
        assert "Chrome" in HTTPX_USER_AGENT
        assert "Mozilla/5.0" in HTTPX_USER_AGENT
        assert "Chrome/131" in HTTPX_USER_AGENT

    def test_get_default_user_agent_returns_httpx_ua(self):
        ua = get_default_user_agent()
        assert ua == HTTPX_USER_AGENT


class TestDefaultHeaders:
    """Test shared DEFAULT_HEADERS and get_default_user_agent."""

    def test_default_headers_has_accept_language(self):
        assert DEFAULT_HEADERS["Accept-Language"] == "en-US,en;q=0.9"

    def test_default_headers_has_accept(self):
        assert "Accept" in DEFAULT_HEADERS

    def test_all_stealth_levels_have_headers(self):
        """Every stealth level must include Accept-Language to prevent geo-redirects."""
        for level in StealthLevel:
            config = get_browser_config(level)
            assert "Accept-Language" in config.headers, f"{level} missing Accept-Language"


class TestCrawlConfigNewFeatures:
    """Test scan_full_page, remove_overlay_elements, locale, scroll_delay."""

    def test_default_scan_full_page_enabled(self):
        config = get_crawl_config()
        assert config.scan_full_page is True

    def test_default_remove_overlay_elements_enabled(self):
        config = get_crawl_config()
        assert config.remove_overlay_elements is True

    def test_default_locale_is_de_de(self):
        """Locale defaults to de-DE for German e-commerce (configurable via settings)."""
        config = get_crawl_config()
        assert config.locale == "de-DE"

    def test_default_scroll_delay(self):
        config = get_crawl_config()
        assert config.scroll_delay == 0.5

    def test_scan_full_page_can_be_disabled(self):
        config = get_crawl_config(scan_full_page=False)
        assert config.scan_full_page is False

    def test_default_delay_is_3_seconds(self):
        assert DEFAULT_DELAY_BEFORE_RETURN == 3.0

    def test_wait_condition_no_h1_fallback(self):
        """Wait condition must NOT contain a bare h1 match (fires on every page)."""
        assert 'querySelector("h1")' not in PRODUCT_WAIT_CONDITION


class TestDismissCookieJS:
    """Test cookie consent dismiss JavaScript constant."""

    def test_cookie_js_covers_onetrust(self):
        assert "onetrust-accept-btn-handler" in DISMISS_COOKIE_JS

    def test_cookie_js_covers_cookiebot(self):
        assert "CybotCookiebotDialog" in DISMISS_COOKIE_JS

    def test_cookie_js_covers_german_accept(self):
        assert "Alle akzeptieren" in DISMISS_COOKIE_JS

    def test_cookie_js_is_iife(self):
        """Must be an IIFE to avoid polluting global scope."""
        assert DISMISS_COOKIE_JS.strip().startswith("(function()")
        assert DISMISS_COOKIE_JS.strip().endswith("();")
