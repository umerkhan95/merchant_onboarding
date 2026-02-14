"""Schema.org JSON-LD structured data extractor."""

from __future__ import annotations

import json
import logging

import httpx
from bs4 import BeautifulSoup

from app.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class SchemaOrgExtractor(BaseExtractor):
    """Extract JSON-LD structured data from <script type='application/ld+json'> tags."""

    async def extract(self, url: str) -> list[dict]:
        """Extract JSON-LD structured data from page.

        Args:
            url: Product page URL

        Returns:
            List of raw Product JSON-LD dicts. Empty list on error or if no Product found.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text

            soup = BeautifulSoup(html, "html.parser")
            script_tags = soup.find_all("script", type="application/ld+json")

            if not script_tags:
                logger.debug("No JSON-LD script tags found on %s", url)
                return []

            products = []

            for script in script_tags:
                try:
                    data = json.loads(script.string)

                    # Handle single object
                    if isinstance(data, dict):
                        if data.get("@type") == "Product":
                            products.append(data)
                        # Handle @graph array (common pattern)
                        elif "@graph" in data and isinstance(data["@graph"], list):
                            for item in data["@graph"]:
                                if isinstance(item, dict) and item.get("@type") == "Product":
                                    products.append(item)

                    # Handle array of objects
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get("@type") == "Product":
                                products.append(item)

                except json.JSONDecodeError as e:
                    logger.warning("Failed to parse JSON-LD from %s: %s", url, e)
                    continue
                except Exception as e:
                    logger.warning("Error processing JSON-LD script from %s: %s", url, e)
                    continue

            if not products:
                logger.debug("No Product objects found in JSON-LD on %s", url)

            return products

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching %s: %s", url, e)
            return []
        except httpx.RequestError as e:
            logger.error("Request error fetching %s: %s", url, e)
            return []
        except Exception as e:
            logger.exception("Schema.org extraction failed for %s: %s", url, e)
            return []
