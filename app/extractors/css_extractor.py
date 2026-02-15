"""CSS-based product data extractor using crawl4ai."""

from __future__ import annotations

import json
import logging

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

from app.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class CSSExtractor(BaseExtractor):
    """Extract product data using CSS selectors via crawl4ai JsonCssExtractionStrategy."""

    def __init__(self, schema: dict):
        """Initialize with a CSS selector schema.

        Args:
            schema: Dictionary with 'name', 'baseSelector', and 'fields' keys
                    matching crawl4ai JsonCssExtractionStrategy format
        """
        self.schema = schema

    async def extract(self, url: str) -> list[dict]:
        """Extract product data using crawl4ai JsonCssExtractionStrategy.

        Args:
            url: Product page URL to scrape

        Returns:
            List of raw extracted product dicts. Empty list on error.
        """
        try:
            # Configure browser with stealth mode
            browser_config = BrowserConfig(
                headless=True,
                verbose=False,
                text_mode=True,
            )

            # Configure extraction strategy
            extraction_strategy = JsonCssExtractionStrategy(self.schema, verbose=False)

            # Configure crawler run
            crawler_config = CrawlerRunConfig(
                extraction_strategy=extraction_strategy,
                cache_mode="bypass",
                wait_until="domcontentloaded",
                page_timeout=30000,
                delay_before_return_html=2.0,
            )

            # Execute crawl
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(
                    url=url,
                    config=crawler_config,
                )

                if not result.success:
                    logger.error("Crawl failed for %s: %s", url, result.error_message)
                    return []

                if not result.extracted_content:
                    logger.warning("No content extracted from %s", url)
                    return []

                # Parse JSON from extracted_content string
                try:
                    extracted_data = json.loads(result.extracted_content)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse extracted JSON from %s: %s", url, e)
                    return []

                # Handle both single dict and list of dicts
                if isinstance(extracted_data, dict):
                    return [extracted_data] if extracted_data else []
                elif isinstance(extracted_data, list):
                    return extracted_data
                else:
                    logger.warning("Unexpected extracted data type from %s: %s", url, type(extracted_data))
                    return []

        except Exception as e:
            logger.exception("CSS extraction failed for %s: %s", url, e)
            return []

    async def extract_batch(self, urls: list[str]) -> list[dict]:
        """Extract products from multiple URLs using a single browser instance.

        Uses arun_many() with MemoryAdaptiveDispatcher to crawl all URLs
        concurrently within one browser — eliminates per-URL browser startup.
        """
        if not urls:
            return []

        browser_config = BrowserConfig(headless=True, verbose=False, text_mode=True)
        extraction_strategy = JsonCssExtractionStrategy(self.schema, verbose=False)
        crawler_config = CrawlerRunConfig(
            extraction_strategy=extraction_strategy,
            cache_mode="bypass",
            wait_until="domcontentloaded",
            page_timeout=30000,
            delay_before_return_html=2.0,
        )
        dispatcher = MemoryAdaptiveDispatcher(
            max_session_permit=5,
            memory_threshold_percent=70.0,
        )

        all_products = []
        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
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

        return all_products
