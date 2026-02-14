"""Auto-generating CSS extractor — uses LLM once per domain to create selectors, then reuses."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, LLMConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

from app.extractors.base import BaseExtractor

if TYPE_CHECKING:
    from app.extractors.schema_cache import SchemaCache

logger = logging.getLogger(__name__)

SCHEMA_GENERATION_QUERY = (
    "Extract product listing data: product title/name, price, description, "
    "image URL, SKU, and availability/stock status. "
    "Use stable CSS selectors (prefer class names and data attributes over nth-child)."
)


class SmartCSSExtractor(BaseExtractor):
    """Auto-generates CSS selectors per domain via LLM, caches and reuses them.

    First call for a domain: fetches page HTML, calls generate_schema() with LLM, caches result.
    Subsequent calls: loads cached schema, uses JsonCssExtractionStrategy (zero LLM cost).
    """

    def __init__(self, llm_config: LLMConfig, schema_cache: SchemaCache):
        """Initialize SmartCSS extractor.

        Args:
            llm_config: crawl4ai LLMConfig for schema generation
            schema_cache: Redis-backed schema cache
        """
        self.llm_config = llm_config
        self.cache = schema_cache

    async def _fetch_html(self, url: str) -> str | None:
        """Fetch page HTML for schema generation."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.error("Failed to fetch HTML for schema generation from %s: %s", url, e)
            return None

    async def _generate_schema(self, html: str) -> dict | None:
        """Generate CSS extraction schema from sample HTML using LLM."""
        try:
            schema = JsonCssExtractionStrategy.generate_schema(
                html=html,
                schema_type="CSS",
                query=SCHEMA_GENERATION_QUERY,
                llm_config=self.llm_config,
            )
            if not schema or not schema.get("baseSelector") or not schema.get("fields"):
                logger.warning("LLM generated invalid schema (missing baseSelector or fields)")
                return None
            logger.info("Generated CSS schema with baseSelector='%s' and %d fields",
                        schema.get("baseSelector"), len(schema.get("fields", [])))
            return schema
        except Exception as e:
            logger.error("Schema generation failed: %s", e)
            return None

    async def _get_or_generate_schema(self, url: str) -> dict | None:
        """Get cached schema or generate a new one."""
        # Try cache first
        schema = await self.cache.get(url)
        if schema:
            return schema

        # Generate from HTML
        html = await self._fetch_html(url)
        if not html:
            return None

        schema = await self._generate_schema(html)
        if not schema:
            return None

        # Cache for reuse
        await self.cache.set(url, schema)
        return schema

    async def extract(self, url: str) -> list[dict]:
        """Extract products using auto-generated CSS selectors.

        Args:
            url: Product page URL

        Returns:
            List of raw product dicts. Empty list on error.
        """
        schema = await self._get_or_generate_schema(url)
        if not schema:
            return []

        try:
            browser_config = BrowserConfig(headless=True, verbose=False)
            extraction_strategy = JsonCssExtractionStrategy(schema, verbose=False)
            crawler_config = CrawlerRunConfig(
                extraction_strategy=extraction_strategy,
                cache_mode="bypass",
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=crawler_config)

                if not result.success:
                    logger.error("SmartCSS crawl failed for %s: %s", url, result.error_message)
                    return []

                if not result.extracted_content:
                    logger.warning("SmartCSS returned no content for %s", url)
                    return []

                try:
                    extracted = json.loads(result.extracted_content)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse SmartCSS output for %s: %s", url, e)
                    return []

                if isinstance(extracted, dict):
                    products = [extracted] if extracted else []
                elif isinstance(extracted, list):
                    products = [p for p in extracted if isinstance(p, dict)]
                else:
                    products = []

                # If cached schema produced 0 results, invalidate and retry once
                if not products:
                    cached = await self.cache.get(url)
                    if cached:
                        logger.info("SmartCSS cached schema produced 0 results for %s, invalidating", url)
                        await self.cache.invalidate(url)
                    return []

                logger.info("SmartCSS extracted %d products from %s", len(products), url)
                return products

        except Exception as e:
            logger.exception("SmartCSS extraction failed for %s: %s", url, e)
            return []
