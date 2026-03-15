"""CSS-based product data extractor using crawl4ai."""

from __future__ import annotations

import json
import logging

from crawl4ai import AsyncWebCrawler
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import (
    StealthLevel,
    get_browser_config,
    get_crawl_config,
    get_crawler_strategy,
)

logger = logging.getLogger(__name__)


class CSSExtractor(BaseExtractor):
    """Extract product data using CSS selectors via crawl4ai JsonCssExtractionStrategy."""

    _ESCALATION_ORDER = [StealthLevel.STANDARD, StealthLevel.STEALTH, StealthLevel.UNDETECTED]

    def __init__(self, schema: dict, stealth_level: StealthLevel = StealthLevel.STANDARD):
        self.schema = schema
        self.stealth_level = stealth_level

    @staticmethod
    def _parse_extracted_content(url: str, result) -> list[dict]:
        """Parse extracted content from a crawl result into product dicts."""
        if not result.success:
            logger.error("Crawl failed for %s: %s", url, result.error_message)
            return []

        if not result.extracted_content:
            logger.warning("No content extracted from %s", url)
            return []

        try:
            extracted_data = json.loads(result.extracted_content)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse extracted JSON from %s: %s", url, e)
            return []

        if isinstance(extracted_data, dict):
            return [extracted_data] if extracted_data else []
        elif isinstance(extracted_data, list):
            return extracted_data
        else:
            logger.warning("Unexpected extracted data type from %s: %s", url, type(extracted_data))
            return []

    async def _crawl_single(self, url: str, stealth_level: StealthLevel) -> list[dict]:
        """Core crawl logic for a single URL at a given stealth level.

        Creates its own browser instance. Used as fallback when the shared-browser
        extract() path fails.
        """
        try:
            browser_config = get_browser_config(stealth_level)
            extraction_strategy = JsonCssExtractionStrategy(self.schema, verbose=False)
            crawler_config = get_crawl_config(
                stealth_level=stealth_level,
                extraction_strategy=extraction_strategy,
            )

            crawler_strategy = get_crawler_strategy(stealth_level, browser_config)
            async with AsyncWebCrawler(
                config=browser_config,
                crawler_strategy=crawler_strategy,
            ) as crawler:
                result = await crawler.arun(
                    url=url,
                    config=crawler_config,
                )
                return self._parse_extracted_content(url, result)

        except Exception as e:
            logger.exception("CSS extraction failed for %s: %s", url, e)
            return []

    async def extract(self, url: str) -> ExtractorResult:
        """Extract product data using crawl4ai JsonCssExtractionStrategy with stealth escalation.

        Creates ONE browser instance and retries with different CrawlerRunConfig
        params for each stealth level, avoiding the cost of spawning a new
        browser per escalation step.
        """
        start_idx = self._ESCALATION_ORDER.index(self.stealth_level)
        levels = self._ESCALATION_ORDER[start_idx:]

        if not levels:
            return ExtractorResult(products=[], complete=False, error="No stealth levels to try")

        # Use the highest stealth level for the browser config (superset of lower levels)
        max_level = levels[-1]
        browser_config = get_browser_config(max_level)
        crawler_strategy = get_crawler_strategy(max_level, browser_config)

        try:
            async with AsyncWebCrawler(
                config=browser_config,
                crawler_strategy=crawler_strategy,
            ) as crawler:
                for level in levels:
                    if level != self.stealth_level:
                        logger.info("Escalating stealth level to %s for %s", level.value, url)

                    extraction_strategy = JsonCssExtractionStrategy(self.schema, verbose=False)
                    crawler_config = get_crawl_config(
                        stealth_level=level,
                        extraction_strategy=extraction_strategy,
                    )

                    try:
                        result = await crawler.arun(url=url, config=crawler_config)
                        products = self._parse_extracted_content(url, result)
                        if products:
                            return ExtractorResult(products=products)
                    except Exception as e:
                        logger.warning("CSS crawl (%s) error for %s: %s", level.value, url, e)
                        continue
        except Exception as e:
            logger.exception("CSS browser startup failed for %s: %s", url, e)

        return ExtractorResult(products=[], complete=False, error="All stealth levels exhausted with 0 products")

    async def extract_batch(self, urls: list[str]) -> ExtractorResult:
        """Extract products from multiple URLs using a single browser instance."""
        if not urls:
            return ExtractorResult(products=[])

        browser_config = get_browser_config(self.stealth_level)
        extraction_strategy = JsonCssExtractionStrategy(self.schema, verbose=False)
        crawler_config = get_crawl_config(
            stealth_level=self.stealth_level,
            extraction_strategy=extraction_strategy,
        )
        dispatcher = MemoryAdaptiveDispatcher(
            max_session_permit=5,
            memory_threshold_percent=70.0,
        )

        all_products = []
        error: str | None = None
        try:
            crawler_strategy = get_crawler_strategy(self.stealth_level, browser_config)
            async with AsyncWebCrawler(
                config=browser_config,
                crawler_strategy=crawler_strategy,
            ) as crawler:
                results = await crawler.arun_many(
                    urls=urls,
                    config=crawler_config,
                    dispatcher=dispatcher,
                )
                for result in results:
                    if not result.success or not result.extracted_content:
                        continue
                    try:
                        extracted = json.loads(result.extracted_content)
                        if isinstance(extracted, list):
                            all_products.extend(extracted)
                        elif isinstance(extracted, dict) and extracted:
                            all_products.append(extracted)
                    except json.JSONDecodeError:
                        logger.error("Failed to parse JSON from %s", result.url)
        except Exception as e:
            logger.exception("Batch CSS extraction failed: %s", e)
            error = str(e)

        return ExtractorResult(products=all_products, complete=error is None, error=error)
