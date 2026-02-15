"""Universal LLM-based product extractor — works on any website."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, LLMConfig
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.extraction_strategy import LLMExtractionStrategy

from app.extractors.base import BaseExtractor

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Pydantic-compatible JSON schema for product extraction.
# This tells the LLM exactly what fields to extract.
PRODUCT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Product name or title"},
        "price": {"type": "string", "description": "Price as text including currency symbol (e.g. '$29.99')"},
        "description": {"type": "string", "description": "Product description text"},
        "image_url": {"type": "string", "description": "Main product image URL"},
        "sku": {"type": "string", "description": "Product SKU or ID if shown"},
        "currency": {"type": "string", "description": "ISO 4217 currency code (e.g. USD, EUR)"},
        "in_stock": {"type": "boolean", "description": "Whether the product is in stock"},
    },
    "required": ["title"],
}

EXTRACTION_INSTRUCTION = (
    "Extract ALL product information visible on this page. "
    "For each product, extract: title (required), price, description, "
    "image URL, SKU, currency code, and stock status. "
    "If a field is not found, omit it. Return a JSON array of products."
)


class LLMExtractor(BaseExtractor):
    """Universal product extractor using crawl4ai LLMExtractionStrategy.

    Works on ANY website regardless of HTML structure by having the LLM
    read the page content and extract structured product data.
    """

    def __init__(self, llm_config: LLMConfig, temperature: float = 0.2, max_tokens: int = 4000):
        """Initialize LLM extractor.

        Args:
            llm_config: crawl4ai LLMConfig with provider and API key
            temperature: LLM temperature (lower = more deterministic)
            max_tokens: Max output tokens
        """
        self.llm_config = llm_config
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _create_strategy(self) -> LLMExtractionStrategy:
        """Create a fresh LLMExtractionStrategy instance."""
        return LLMExtractionStrategy(
            llm_config=self.llm_config,
            schema=PRODUCT_EXTRACTION_SCHEMA,
            extraction_type="schema",
            instruction=EXTRACTION_INSTRUCTION,
            chunk_token_threshold=3000,
            overlap_rate=0.1,
            apply_chunking=True,
            input_format="fit_markdown",
            verbose=False,
            extra_args={
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
        )

    async def extract(self, url: str) -> list[dict]:
        """Extract products from any page using LLM.

        Args:
            url: Product page URL

        Returns:
            List of raw product dicts. Empty list on error.
        """
        strategy = self._create_strategy()
        try:
            browser_config = BrowserConfig(headless=True, verbose=False, text_mode=True)
            crawler_config = CrawlerRunConfig(
                extraction_strategy=strategy,
                cache_mode="bypass",
                wait_until="domcontentloaded",
                page_timeout=30000,
                delay_before_return_html=2.0,
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=crawler_config)

                if not result.success:
                    logger.error("LLM crawl failed for %s: %s", url, result.error_message)
                    return []

                if not result.extracted_content:
                    logger.warning("LLM extraction returned no content for %s", url)
                    return []

                try:
                    extracted = json.loads(result.extracted_content)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse LLM output for %s: %s", url, e)
                    return []

                # Normalize to list
                if isinstance(extracted, dict):
                    products = [extracted] if extracted.get("title") else []
                elif isinstance(extracted, list):
                    products = [p for p in extracted if isinstance(p, dict) and p.get("title")]
                else:
                    products = []

                logger.info("LLM extracted %d products from %s", len(products), url)
                return products

        except Exception as e:
            logger.exception("LLM extraction failed for %s: %s", url, e)
            return []

    async def extract_batch(self, urls: list[str]) -> list[dict]:
        """Extract products from multiple URLs using a single browser instance.

        Uses arun_many() with MemoryAdaptiveDispatcher to crawl all URLs
        concurrently — eliminates per-URL browser startup overhead.
        """
        if not urls:
            return []

        strategy = self._create_strategy()
        browser_config = BrowserConfig(headless=True, verbose=False, text_mode=True)
        crawler_config = CrawlerRunConfig(
            extraction_strategy=strategy,
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
                        if isinstance(extracted, dict):
                            if extracted.get("title"):
                                all_products.append(extracted)
                        elif isinstance(extracted, list):
                            all_products.extend(
                                p for p in extracted
                                if isinstance(p, dict) and p.get("title")
                            )
                    except json.JSONDecodeError:
                        logger.error("Failed to parse LLM JSON from %s", result.url)
        except Exception as e:
            logger.exception("Batch LLM extraction failed: %s", e)

        return all_products
