"""
Crawl4AI E-commerce Product Extraction - Practical Code Examples
================================================================

This file contains ready-to-use code examples for extracting product data
from various e-commerce platforms using Crawl4AI.

Install requirements:
    pip install crawl4ai
    crawl4ai-setup
"""

import asyncio
import json
from typing import List, Dict, Optional
from datetime import datetime
import xml.etree.ElementTree as ET

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    RateLimiter,
    SemaphoreDispatcher,
    CacheMode
)
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy


# ============================================================================
# 1. SHOPIFY EXTRACTION
# ============================================================================

class ShopifyExtractor:
    """Extract product data from Shopify stores"""

    PRODUCT_SCHEMA = {
        "name": "Shopify Product",
        "baseSelector": "div.product-single, article.product-single",
        "fields": [
            {
                "name": "product_id",
                "selector": "div",
                "type": "attribute",
                "attribute": "data-product-id"
            },
            {
                "name": "title",
                "selector": "h1, h1.product-title, span.product-title",
                "type": "text"
            },
            {
                "name": "price",
                "selector": ".price, span.price, [data-price]",
                "type": "text",
                "transform": "strip"
            },
            {
                "name": "original_price",
                "selector": ".original-price, span.original-price, del, .compare-at-price",
                "type": "text",
                "transform": "strip"
            },
            {
                "name": "url",
                "selector": "a.product-link",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "description",
                "selector": ".product-description, .product-info-main",
                "type": "html"
            },
            {
                "name": "in_stock",
                "selector": ".stock-status, .availability",
                "type": "text"
            },
            {
                "name": "main_image",
                "selector": "img.product-photo, img.feature-image",
                "type": "attribute",
                "attribute": "src"
            },
            {
                "name": "rating_stars",
                "selector": ".rating, span.stars, [data-rating]",
                "type": "text"
            },
            {
                "name": "rating_count",
                "selector": ".review-count, .rating-count",
                "type": "text"
            }
        ]
    }

    async def extract_product_page(self, url: str) -> Dict:
        """Extract data from a single Shopify product page"""

        browser_config = BrowserConfig(
            enable_stealth=True,
            user_agent_mode="random"
        )

        config = CrawlerRunConfig(
            extraction_strategy=JsonCssExtractionStrategy(self.PRODUCT_SCHEMA),
            wait_for=".product-title",
            cache_mode=CacheMode.BYPASS
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=config)

            if result.success and result.extracted_content:
                products = json.loads(result.extracted_content)
                return products[0] if products else {}

        return {}

    async def extract_products_json_api(self, store_url: str) -> List[Dict]:
        """
        Extract products from Shopify's /products.json API endpoint

        Benefits:
        - Faster than scraping individual pages
        - No JavaScript rendering needed
        - Structured data (JSON)
        - Limited to 250 products per request
        """

        all_products = []
        limit = 50
        offset = 0

        async with AsyncWebCrawler() as crawler:
            while True:
                url = f"{store_url}/products.json?limit={limit}&offset={offset}"

                result = await crawler.arun(url=url)

                if not result.success:
                    break

                try:
                    data = json.loads(result.markdown)
                    products = data.get("products", [])

                    if not products:
                        break

                    all_products.extend(products)

                    # Process next batch
                    offset += limit

                except json.JSONDecodeError:
                    break

        return all_products

    async def extract_collection_with_pagination(
        self,
        collection_url: str,
        max_pages: int = 5
    ) -> List[Dict]:
        """Extract products from a Shopify collection with pagination"""

        all_products = []

        for page in range(1, max_pages + 1):
            url = f"{collection_url}?page={page}"

            schema = {
                "name": "ProductList",
                "baseSelector": "div.product-item, li.product-card",
                "fields": [
                    {"name": "title", "selector": ".title, h2", "type": "text"},
                    {"name": "price", "selector": ".price", "type": "text", "transform": "strip"},
                    {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
                    {"name": "image", "selector": "img", "type": "attribute", "attribute": "src"}
                ]
            }

            browser_config = BrowserConfig(enable_stealth=True)
            config = CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema)
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=config)

                if result.success and result.extracted_content:
                    products = json.loads(result.extracted_content)
                    all_products.extend(products)
                else:
                    break

        return all_products


# ============================================================================
# 2. WOOCOMMERCE EXTRACTION
# ============================================================================

class WooCommerceExtractor:
    """Extract product data from WooCommerce stores"""

    PRODUCT_SCHEMA = {
        "name": "WooCommerce Product",
        "baseSelector": "article.type-product, div.product",
        "fields": [
            {
                "name": "title",
                "selector": "h1.product_title, h1.entry-title",
                "type": "text"
            },
            {
                "name": "price",
                "selector": ".woocommerce-Price-amount, .price bdi",
                "type": "text",
                "transform": "strip"
            },
            {
                "name": "original_price",
                "selector": "del .woocommerce-Price-amount",
                "type": "text",
                "transform": "strip"
            },
            {
                "name": "url",
                "selector": "h1.product_title a",
                "type": "attribute",
                "attribute": "href"
            },
            {
                "name": "description",
                "selector": ".woocommerce-product-details__short-description",
                "type": "html"
            },
            {
                "name": "sku",
                "selector": ".sku",
                "type": "text"
            },
            {
                "name": "rating_stars",
                "selector": ".star-rating",
                "type": "text"
            },
            {
                "name": "rating_count",
                "selector": ".woocommerce-review-link",
                "type": "text"
            },
            {
                "name": "stock_status",
                "selector": ".stock",
                "type": "text"
            },
            {
                "name": "image",
                "selector": ".woocommerce-product-gallery img:first",
                "type": "attribute",
                "attribute": "src"
            }
        ]
    }

    async def extract_via_rest_api(
        self,
        site_url: str,
        page: int = 1,
        per_page: int = 100
    ) -> List[Dict]:
        """
        Extract products via WooCommerce REST API

        This is faster and more reliable than scraping HTML

        URL Format: https://example.com/wp-json/wc/v3/products
        """

        url = f"{site_url}/wp-json/wc/v3/products?page={page}&per_page={per_page}"

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)

            if result.success:
                try:
                    return json.loads(result.markdown)
                except json.JSONDecodeError:
                    return []

        return []

    async def extract_all_products_via_api(
        self,
        site_url: str,
        per_page: int = 100
    ) -> List[Dict]:
        """Extract all products from WooCommerce store"""

        all_products = []
        page = 1
        has_more = True

        while has_more:
            products = await self.extract_via_rest_api(
                site_url,
                page=page,
                per_page=per_page
            )

            if not products:
                has_more = False
            else:
                all_products.extend(products)
                page += 1

        return all_products

    async def extract_product_page(self, url: str) -> Dict:
        """Extract data from a single WooCommerce product page"""

        browser_config = BrowserConfig(enable_stealth=True)
        config = CrawlerRunConfig(
            extraction_strategy=JsonCssExtractionStrategy(self.PRODUCT_SCHEMA),
            wait_for=".product_title"
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=config)

            if result.success and result.extracted_content:
                products = json.loads(result.extracted_content)
                return products[0] if products else {}

        return {}

    async def extract_category_products(
        self,
        category_url: str,
        max_pages: int = 5
    ) -> List[Dict]:
        """Extract all products from a WooCommerce category"""

        all_products = []

        for page in range(1, max_pages + 1):
            url = f"{category_url}?page={page}" if "?" not in category_url else f"{category_url}&page={page}"

            schema = {
                "name": "ProductList",
                "baseSelector": "li.product, .product-item",
                "fields": [
                    {"name": "title", "selector": ".woocommerce-loop-product__title", "type": "text"},
                    {"name": "price", "selector": ".price", "type": "text", "transform": "strip"},
                    {"name": "url", "selector": "a.woocommerce-loop-product__link", "type": "attribute", "attribute": "href"},
                    {"name": "image", "selector": "img", "type": "attribute", "attribute": "src"}
                ]
            }

            config = CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema)
            )

            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=config)

                if result.success and result.extracted_content:
                    products = json.loads(result.extracted_content)
                    all_products.extend(products)
                else:
                    break

        return all_products


# ============================================================================
# 3. GENERIC E-COMMERCE EXTRACTION
# ============================================================================

class GenericEcommerceExtractor:
    """Extract products from any e-commerce site"""

    def build_schema(
        self,
        container_selector: str,
        title_selector: str,
        price_selector: str,
        url_selector: str = None,
        image_selector: str = None
    ) -> Dict:
        """Build a flexible schema for any site"""

        fields = [
            {"name": "title", "selector": title_selector, "type": "text"},
            {"name": "price", "selector": price_selector, "type": "text", "transform": "strip"}
        ]

        if url_selector:
            fields.append({
                "name": "url",
                "selector": url_selector,
                "type": "attribute",
                "attribute": "href"
            })

        if image_selector:
            fields.append({
                "name": "image",
                "selector": image_selector,
                "type": "attribute",
                "attribute": "src"
            })

        return {
            "name": "Product",
            "baseSelector": container_selector,
            "fields": fields
        }

    async def extract_products(
        self,
        url: str,
        container_selector: str,
        title_selector: str,
        price_selector: str,
        url_selector: str = None,
        image_selector: str = None
    ) -> List[Dict]:
        """Extract products with custom selectors"""

        schema = self.build_schema(
            container_selector,
            title_selector,
            price_selector,
            url_selector,
            image_selector
        )

        browser_config = BrowserConfig(enable_stealth=True)
        config = CrawlerRunConfig(
            extraction_strategy=JsonCssExtractionStrategy(schema)
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=config)

            if result.success and result.extracted_content:
                return json.loads(result.extracted_content)

        return []

    async def discover_and_extract(
        self,
        start_url: str,
        max_depth: int = 2
    ) -> List[Dict]:
        """
        Auto-discover product container patterns and extract

        This uses a heuristic approach to identify product containers
        """

        visited = set()
        all_products = []

        async def crawl(url: str, depth: int):
            if depth > max_depth or url in visited:
                return

            visited.add(url)

            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url)

                if not result.success:
                    return

                # Try common patterns
                patterns = [
                    (".product-item", ".title", ".price"),
                    (".product-card", "h2", ".price"),
                    ("article.product", "h1", "span.price"),
                    ("[data-product-id]", "[data-product-name]", "[data-product-price]")
                ]

                for container, title, price in patterns:
                    products = await self.extract_products(
                        url,
                        container,
                        title,
                        price
                    )

                    if products:
                        all_products.extend(products)
                        break

                # Find product links and recurse
                links = result.links.get("internal", [])
                for link in links:
                    href = link.get("href", "")
                    if "/products/" in href or "/product/" in href:
                        await crawl(href, depth + 1)

        await crawl(start_url, 0)
        return all_products


# ============================================================================
# 4. ADVANCED: BATCH CRAWLING WITH RATE LIMITING
# ============================================================================

class BatchProductCrawler:
    """Crawl multiple product URLs with rate limiting and error handling"""

    def __init__(
        self,
        base_delay: tuple = (2.0, 4.0),
        max_concurrent: int = 3
    ):
        self.rate_limiter = RateLimiter(
            base_delay=base_delay,
            max_delay=30.0,
            max_retries=2,
            rate_limit_codes=[429, 503]
        )

        self.dispatcher = SemaphoreDispatcher(
            semaphore_count=max_concurrent,
            rate_limiter=self.rate_limiter
        )

    async def crawl_products(
        self,
        urls: List[str],
        schema: Dict,
        output_file: Optional[str] = None
    ) -> Dict:
        """
        Crawl multiple product URLs with error handling

        Returns:
            {
                "success": [],
                "failed": [],
                "products": []
            }
        """

        browser_config = BrowserConfig(
            enable_stealth=True,
            user_agent_mode="random"
        )

        config = CrawlerRunConfig(
            extraction_strategy=JsonCssExtractionStrategy(schema),
            check_robots_txt=True,
            cache_mode=CacheMode.BYPASS
        )

        result_summary = {
            "success": [],
            "failed": [],
            "products": [],
            "total_urls": len(urls),
            "timestamp": datetime.now().isoformat()
        }

        async with AsyncWebCrawler(config=browser_config) as crawler:
            results = await crawler.arun_many(
                urls=urls,
                config=config,
                dispatcher=self.dispatcher
            )

            for result in results:
                if result.success and result.extracted_content:
                    try:
                        products = json.loads(result.extracted_content)
                        result_summary["products"].extend(products)
                        result_summary["success"].append(result.url)
                        print(f"✓ {result.url}")

                    except json.JSONDecodeError as e:
                        result_summary["failed"].append({
                            "url": result.url,
                            "error": "JSON decode error"
                        })
                        print(f"✗ {result.url} (JSON error)")

                else:
                    result_summary["failed"].append({
                        "url": result.url,
                        "error": result.error_message
                    })
                    print(f"✗ {result.url}: {result.error_message}")

        # Save results
        if output_file:
            with open(output_file, "w") as f:
                json.dump(result_summary, f, indent=2)

        return result_summary


# ============================================================================
# 5. SITEMAP-BASED CRAWLING
# ============================================================================

class SitemapProductCrawler:
    """Discover product URLs from sitemap and crawl them"""

    async def parse_sitemap(self, sitemap_url: str) -> List[str]:
        """Parse XML sitemap and extract URLs"""

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=sitemap_url)

            if not result.success:
                return []

            try:
                root = ET.fromstring(result.html)
                namespace = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

                urls = [
                    elem.text
                    for elem in root.findall('.//sm:loc', namespace)
                    if elem.text
                ]

                return urls

            except ET.ParseError:
                return []

    async def crawl_from_sitemap(
        self,
        sitemap_url: str,
        product_pattern: str = "/product/",
        schema: Optional[Dict] = None,
        max_products: int = None
    ) -> List[Dict]:
        """
        Discover product URLs from sitemap and crawl them

        Args:
            sitemap_url: URL to sitemap.xml
            product_pattern: Pattern to identify product URLs
            schema: Extraction schema
            max_products: Limit number of products to crawl
        """

        if not schema:
            schema = {
                "name": "Product",
                "baseSelector": ".product",
                "fields": [
                    {"name": "title", "selector": ".title", "type": "text"},
                    {"name": "price", "selector": ".price", "type": "text"}
                ]
            }

        # Parse sitemap
        print(f"Parsing sitemap: {sitemap_url}")
        urls = await self.parse_sitemap(sitemap_url)

        # Filter for product URLs
        product_urls = [
            url for url in urls
            if product_pattern in url
        ]

        if max_products:
            product_urls = product_urls[:max_products]

        print(f"Found {len(product_urls)} product URLs")

        # Crawl products
        crawler = BatchProductCrawler()
        results = await crawler.crawl_products(
            product_urls,
            schema,
            output_file="sitemap_products.json"
        )

        return results


# ============================================================================
# 6. USAGE EXAMPLES
# ============================================================================

async def example_shopify():
    """Example: Extract from Shopify store"""

    extractor = ShopifyExtractor()

    # Option 1: Extract from product page
    product = await extractor.extract_product_page(
        "https://example-store.myshopify.com/products/sample-product"
    )
    print("Product:", json.dumps(product, indent=2))

    # Option 2: Use /products.json API (faster)
    products = await extractor.extract_products_json_api(
        "https://example-store.myshopify.com"
    )
    print(f"Found {len(products)} products via API")

    # Option 3: Extract collection with pagination
    products = await extractor.extract_collection_with_pagination(
        "https://example-store.myshopify.com/collections/all",
        max_pages=3
    )
    print(f"Extracted {len(products)} products from collection")


async def example_woocommerce():
    """Example: Extract from WooCommerce store"""

    extractor = WooCommerceExtractor()

    # Option 1: Use REST API (recommended)
    products = await extractor.extract_all_products_via_api(
        "https://example-store.com"
    )
    print(f"Found {len(products)} products via REST API")

    # Option 2: Scrape product page
    product = await extractor.extract_product_page(
        "https://example-store.com/product/sample-product/"
    )
    print("Product:", json.dumps(product, indent=2))


async def example_generic():
    """Example: Extract from generic e-commerce site"""

    extractor = GenericEcommerceExtractor()

    products = await extractor.extract_products(
        url="https://example.com/products",
        container_selector=".product-card",
        title_selector="h2.product-title",
        price_selector="span.price",
        url_selector="a.product-link",
        image_selector="img.product-image"
    )

    print(f"Extracted {len(products)} products")
    print(json.dumps(products[:2], indent=2))


async def example_batch_crawling():
    """Example: Batch crawl with rate limiting"""

    urls = [
        "https://example.com/product/1",
        "https://example.com/product/2",
        "https://example.com/product/3"
    ]

    schema = {
        "name": "Product",
        "baseSelector": ".product",
        "fields": [
            {"name": "title", "selector": ".title", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"}
        ]
    }

    crawler = BatchProductCrawler(base_delay=(2.0, 4.0), max_concurrent=3)
    results = await crawler.crawl_products(
        urls,
        schema,
        output_file="products.json"
    )

    print(f"Success: {len(results['success'])}")
    print(f"Failed: {len(results['failed'])}")
    print(f"Products: {len(results['products'])}")


async def example_sitemap():
    """Example: Crawl from sitemap"""

    crawler = SitemapProductCrawler()

    results = await crawler.crawl_from_sitemap(
        sitemap_url="https://example.com/sitemap.xml",
        product_pattern="/products/",
        max_products=100
    )

    print(f"Crawled {len(results['products'])} products")


# ============================================================================
# MAIN
# ============================================================================

async def main():
    """Run example"""

    # Uncomment example to run
    # await example_shopify()
    # await example_woocommerce()
    # await example_generic()
    # await example_batch_crawling()
    # await example_sitemap()

    print("Choose an example to run by uncommenting in main()")


if __name__ == "__main__":
    asyncio.run(main())
