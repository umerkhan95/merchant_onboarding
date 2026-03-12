"""Unit tests for browser_config module."""

from __future__ import annotations

from app.extractors.browser_config import get_crawl_config, StealthLevel


class TestGetCrawlConfig:
    """Test get_crawl_config factory function."""

    def test_check_robots_txt_default_true(self):
        """check_robots_txt should default to True."""
        config = get_crawl_config()
        assert config.check_robots_txt is True

    def test_check_robots_txt_can_be_disabled(self):
        """check_robots_txt can be set to False."""
        config = get_crawl_config(check_robots_txt=False)
        assert config.check_robots_txt is False

    def test_check_robots_txt_with_stealth_level(self):
        """check_robots_txt should work with all stealth levels."""
        for level in StealthLevel:
            config = get_crawl_config(stealth_level=level, check_robots_txt=True)
            assert config.check_robots_txt is True
