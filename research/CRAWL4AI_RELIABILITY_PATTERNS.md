# Crawl4AI Reliability Patterns

## Quick Start: Zero-Result Prevention

The **single most important pattern** for your system:

```python
# app/services/extraction_validator.py

from enum import Enum
from typing import Optional
import logging

log = logging.getLogger(__name__)


class ValidationResult(Enum):
    PASS = "pass"
    ZERO_RESULT_DETECTED = "zero_result"
    LOW_CONFIDENCE = "low_confidence"
    INCOMPLETE_DATA = "incomplete_data"
    UNKNOWN_ERROR = "unknown_error"


async def validate_extraction_results(
    products: list[dict],
    shop_url: str,
    extraction_strategy: str,
) -> ValidationResult:
    """
    Validate extracted products BEFORE considering extraction complete.

    Returns: ValidationResult enum + tuple (is_valid, reason, should_escalate)
    """

    if len(products) == 0:
        log.warning(f"Zero-result extraction from {shop_url} via {extraction_strategy}")
        return (False, "zero_result_detected", should_escalate=True)

    # Check required fields
    required_fields = ["title", "price", "product_url"]
    incomplete_count = 0

    for product in products:
        for field in required_fields:
            if field not in product or not product[field]:
                incomplete_count += 1

    if incomplete_count > len(products) * 0.1:  # >10% missing critical fields
        log.warning(f"{incomplete_count} products missing critical fields")
        return (False, "incomplete_data", should_escalate=True)

    # Check confidence scores (if available)
    if "confidence_scores" in products[0]:
        avg_confidence = sum(
            p.get("confidence_scores", {}).get("overall", 0)
            for p in products
        ) / len(products)

        if avg_confidence < 0.70:
            log.warning(f"Low average confidence: {avg_confidence}")
            return (False, "low_confidence", should_escalate=True)

    log.info(f"Extraction validation passed: {len(products)} products from {shop_url}")
    return (True, "extraction_valid", should_escalate=False)
```

---

## Pattern 1: Intelligent Fallback Chain

```python
# app/services/product_extractor.py

from typing import Optional
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.extraction_strategy import (
    JsonCssExtractionStrategy,
    LLMExtractionStrategy,
)
import asyncio
import random
import logging

log = logging.getLogger(__name__)


class ExtractionStrategy:
    """Base class for all extraction strategies."""

    async def extract(self, url: str) -> Optional[list[dict]]:
        raise NotImplementedError


class PlatformAPIStrategy(ExtractionStrategy):
    """Extract via platform-specific APIs (Shopify, WooCommerce, etc)."""

    async def extract(self, url: str) -> Optional[list[dict]]:
        # Delegate to platform-specific extractor
        # Already implemented in your codebase
        pass


class NetworkInterceptionStrategy(ExtractionStrategy):
    """Extract by capturing API responses during page load."""

    async def extract(self, url: str) -> Optional[list[dict]]:
        """Monitor XHR/Fetch calls to capture product data JSON."""

        captured_apis = []

        async def on_response(response):
            # Capture product API responses
            if any(keyword in response.url for keyword in [
                '/api/products', '/api/items', '/api/catalog',
                '/products.json', '/items.json', 'graphql',
            ]):
                try:
                    data = await response.json()
                    captured_apis.append({
                        'url': response.url,
                        'data': data,
                    })
                    log.info(f"Captured API: {response.url}")
                except:
                    pass

        browser_config = BrowserConfig(
            enable_stealth=True,
            headless=True,
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    wait_for="networkidle",
                    timeout=30,
                ),
            )

            if not result.success:
                log.warning(f"Network interception failed for {url}")
                return None

        # Parse captured API responses
        products = self._parse_api_responses(captured_apis)
        return products if products else None

    def _parse_api_responses(self, captured_apis: list[dict]) -> list[dict]:
        """Extract products from captured API responses."""
        products = []

        for api in captured_apis:
            data = api['data']

            # Handle array response
            if isinstance(data, list):
                products.extend(data)

            # Handle object with products key
            elif isinstance(data, dict):
                # Try common product keys
                for key in ['products', 'items', 'data', 'results']:
                    if key in data and isinstance(data[key], list):
                        products.extend(data[key])
                        break

        return products


class SchemaOrgStrategy(ExtractionStrategy):
    """Extract JSON-LD structured data from <script type="application/ld+json">."""

    async def extract(self, url: str) -> Optional[list[dict]]:
        import json
        from bs4 import BeautifulSoup

        browser_config = BrowserConfig(headless=True)

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(timeout=20),
            )

            if not result.success or not result.html:
                return None

        soup = BeautifulSoup(result.html, 'html.parser')
        products = []

        for script in soup.find_all('script', {'type': 'application/ld+json'}):
            try:
                data = json.loads(script.string)

                # Handle different JSON-LD structures
                if self._is_product(data):
                    products.append(data)
                elif self._is_product_collection(data):
                    products.extend(data['itemListElement'] or data.get('products', []))

            except (json.JSONDecodeError, TypeError):
                continue

        return products if products else None

    def _is_product(self, data: dict) -> bool:
        return data.get('@type') in ['Product', ['Product']]

    def _is_product_collection(self, data: dict) -> bool:
        return data.get('@type') in ['ItemList', 'Collection', ['ItemList']]


class CSSExtractionStrategy(ExtractionStrategy):
    """Extract using crawl4ai's JsonCssExtractionStrategy."""

    def __init__(self, css_schema: dict):
        self.css_schema = css_schema

    async def extract(self, url: str) -> Optional[list[dict]]:
        from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

        strategy = JsonCssExtractionStrategy(schema=self.css_schema)

        browser_config = BrowserConfig(
            enable_stealth=True,
            headless=True,
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    extraction_strategy=strategy,
                    wait_for="networkidle",
                    timeout=30,
                ),
            )

            if not result.success or not result.extracted_content:
                return None

        import json
        try:
            data = json.loads(result.extracted_content)
            products = data.get('products', [])
            return products if products else None
        except json.JSONDecodeError:
            return None


class LLMExtractionStrategy(ExtractionStrategy):
    """Universal fallback: LLM-based extraction."""

    def __init__(self, llm_config: dict):
        self.llm_config = llm_config

    async def extract(self, url: str) -> Optional[list[dict]]:
        from crawl4ai.extraction_strategy import LLMExtractionStrategy as CrawlLLM
        from pydantic import BaseModel

        class Product(BaseModel):
            title: str
            price: float
            product_url: str
            image_url: Optional[str] = None
            description: Optional[str] = None

        strategy = CrawlLLM(
            schema=Product.model_json_schema(),
            llm_config=self.llm_config,
            extraction_type="schema",
            input_format="fit_markdown",  # Reduce tokens 40-60%
            chunk_token_threshold=3000,
        )

        browser_config = BrowserConfig(
            enable_stealth=True,
            headless=True,
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    extraction_strategy=strategy,
                    wait_for="networkidle",
                    timeout=30,
                    cache_mode="bypass",  # Don't cache LLM extractions
                ),
            )

            if not result.success or not result.extracted_content:
                return None

        import json
        try:
            data = json.loads(result.extracted_content)

            # Handle array or single object
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'products' in data:
                return data['products']
            else:
                return [data] if data else None

        except json.JSONDecodeError:
            return None


class ProductExtractor:
    """Main orchestrator: tries strategies in fallback order."""

    def __init__(self, llm_config: dict):
        self.llm_config = llm_config

        # CSS schema (generic e-commerce)
        self.generic_css_schema = {
            "products": {
                "selector": (
                    ".product-item, "
                    "[data-product-id], "
                    "[data-product], "
                    ".product, "
                    ".item"
                ),
                "attributes": {
                    "title": {
                        "selector": ".product-title, h2, h3, [data-title], .name",
                        "type": "text",
                    },
                    "price": {
                        "selector": ".price, [data-price], .product-price",
                        "type": "text",
                    },
                    "url": {
                        "selector": "a",
                        "type": "attribute",
                        "attribute": "href",
                    },
                    "image": {
                        "selector": "img",
                        "type": "attribute",
                        "attribute": "src",
                    },
                }
            }
        }

    async def extract_products(
        self,
        url: str,
        shop_url: str,
        platform: str = "generic",
    ) -> dict:
        """
        Extract products with intelligent fallback.

        Returns: {
            'products': list[dict],
            'strategy': str,
            'confidence': float,
            'error': str | None,
        }
        """

        strategies = [
            ("platform_api", self._extract_platform_api),
            ("network_interception", self._extract_network_interception),
            ("schema_org", self._extract_schema_org),
            ("css", self._extract_css),
            ("llm", self._extract_llm),
        ]

        for strategy_name, extract_fn in strategies:
            products = await self._try_strategy(
                strategy_name=strategy_name,
                extract_fn=extract_fn,
                url=url,
                max_retries=2,
            )

            if products and len(products) > 0:
                log.info(f"Extraction successful with {strategy_name}: {len(products)} products")

                # Validate results
                is_valid, reason, should_escalate = await validate_extraction_results(
                    products=products,
                    shop_url=shop_url,
                    extraction_strategy=strategy_name,
                )

                if is_valid:
                    return {
                        'products': products,
                        'strategy': strategy_name,
                        'confidence': self._calculate_confidence(products),
                        'error': None,
                    }

        # All strategies failed
        log.error(f"All extraction strategies failed for {url}")
        return {
            'products': [],
            'strategy': 'none',
            'confidence': 0.0,
            'error': 'All extraction strategies exhausted',
        }

    async def _try_strategy(
        self,
        strategy_name: str,
        extract_fn,
        url: str,
        max_retries: int = 2,
    ) -> Optional[list[dict]]:
        """Try a strategy with exponential backoff + jitter."""

        for attempt in range(max_retries):
            try:
                log.info(f"Attempt {attempt + 1}/{max_retries} with {strategy_name}")

                products = await extract_fn(url)

                if products is None:
                    log.debug(f"{strategy_name} returned None")
                    continue

                if len(products) > 0:
                    log.info(f"{strategy_name}: {len(products)} products extracted")
                    return products

                log.debug(f"{strategy_name} returned empty list")
                continue

            except Exception as e:
                log.error(f"{strategy_name} raised exception: {e}")

                if attempt < max_retries - 1:
                    # Exponential backoff + jitter
                    base_delay = 2 ** attempt
                    jitter = random.uniform(0, base_delay)
                    wait_time = base_delay + jitter

                    log.info(f"Retrying {strategy_name} after {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)

        log.warning(f"{strategy_name} exhausted after {max_retries} attempts")
        return None

    async def _extract_platform_api(self, url: str) -> Optional[list[dict]]:
        """Placeholder: delegate to existing platform detector."""
        # You already have this implemented
        return None

    async def _extract_network_interception(self, url: str) -> Optional[list[dict]]:
        """Extract by capturing API responses."""
        strategy = NetworkInterceptionStrategy()
        return await strategy.extract(url)

    async def _extract_schema_org(self, url: str) -> Optional[list[dict]]:
        """Extract JSON-LD structured data."""
        strategy = SchemaOrgStrategy()
        return await strategy.extract(url)

    async def _extract_css(self, url: str) -> Optional[list[dict]]:
        """Extract using CSS selectors."""
        strategy = CSSExtractionStrategy(self.generic_css_schema)
        return await strategy.extract(url)

    async def _extract_llm(self, url: str) -> Optional[list[dict]]:
        """Extract using LLM (universal fallback)."""
        strategy = LLMExtractionStrategy(self.llm_config)
        return await strategy.extract(url)

    def _calculate_confidence(self, products: list[dict]) -> float:
        """Calculate average confidence across all products."""

        if not products:
            return 0.0

        # If products have confidence scores, use them
        if 'confidence_scores' in products[0]:
            scores = [
                p.get('confidence_scores', {}).get('overall', 0)
                for p in products
            ]
            return sum(scores) / len(scores)

        # Otherwise estimate based on data completeness
        required_fields = ['title', 'price', 'product_url']

        completeness_scores = []
        for product in products:
            found = sum(1 for f in required_fields if product.get(f))
            completeness_scores.append(found / len(required_fields))

        return sum(completeness_scores) / len(completeness_scores)
```

---

## Pattern 2: Zero-Result Recovery Protocol

```python
# app/services/zero_result_handler.py

from typing import Optional
import logging

log = logging.getLogger(__name__)


async def handle_zero_result_extraction(job_id: str, shop_url: str) -> dict:
    """
    When extraction returns 0 products, implement this recovery protocol.
    """

    # 1. Verify page accessibility
    page_status = await check_page_accessibility(shop_url)

    if page_status['http_code'] not in [200, 301, 302]:
        log.error(f"Page unreachable: HTTP {page_status['http_code']}")
        return {
            'status': 'failed',
            'reason': f"Site returned HTTP {page_status['http_code']}",
            'action': 'notify_merchant',
            'message': 'Your store is not accessible from our crawler. Please verify it is publicly visible.',
        }

    # 2. Check for timeout
    if page_status['render_timeout']:
        log.warning(f"Page rendering timed out: {shop_url}")
        return {
            'status': 'needs_retry',
            'reason': 'Page rendering timeout',
            'action': 'retry_with_longer_timeout',
        }

    # 3. Check for anti-bot protection
    if page_status['cloudflare_detected']:
        log.warning(f"Cloudflare detected: {shop_url}")
        return {
            'status': 'escalate',
            'reason': 'Site protected by Cloudflare',
            'action': 'try_antibot_service',
            'message': 'Your site is protected by Cloudflare. We are switching to an advanced crawler.',
        }

    # 4. Try fallback extraction methods
    fallback_results = await try_fallback_strategies(shop_url)

    if fallback_results['product_count'] > 0:
        log.info(f"Recovery successful via {fallback_results['strategy']}")
        return {
            'status': 'recovered',
            'products': fallback_results['products'],
            'strategy': fallback_results['strategy'],
            'message': f"Successfully extracted {fallback_results['product_count']} products using {fallback_results['strategy']}",
        }

    # 5. All fallbacks exhausted - escalate to manual review
    log.error(f"Zero-result recovery failed for {shop_url}")

    escalation = await escalate_to_manual_review(
        job_id=job_id,
        shop_url=shop_url,
        error_reason="All extraction strategies returned 0 products",
        page_screenshot=page_status.get('screenshot'),
        page_html=page_status.get('html'),
    )

    # 6. Notify merchant
    await notify_merchant(
        shop_url=shop_url,
        subject="We need help with your product import",
        body="""
We attempted to automatically extract your products but encountered issues.

This might be due to:
- Your store requiring authentication
- Anti-bot protection blocking our crawler
- Custom HTML structure we don't recognize

Options:
1. UPLOAD A CSV with your products (preferred)
2. GRANT TEMPORARY ACCESS to your admin panel
3. WAIT for our team to investigate (1-2 business days)

Please reply to this email with your preference.
        """
    )

    return {
        'status': 'manual_escalation',
        'escalation_id': escalation['id'],
        'action': 'manual_review_required',
        'message': 'We are escalating to our team for manual investigation. You will receive an email shortly.',
    }


async def check_page_accessibility(url: str) -> dict:
    """Check if page is actually accessible and renderable."""

    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                return {
                    'http_code': response.status,
                    'content': await response.text(),
                    'render_timeout': False,
                    'cloudflare_detected': 'cf_clearance' in response.cookies,
                }
    except asyncio.TimeoutError:
        return {
            'http_code': None,
            'render_timeout': True,
            'cloudflare_detected': False,
        }
    except Exception as e:
        log.error(f"Accessibility check failed: {e}")
        return {
            'http_code': None,
            'error': str(e),
        }


async def try_fallback_strategies(shop_url: str) -> dict:
    """Try additional extraction methods."""

    # This calls your ProductExtractor with all strategies
    # Returns first successful result
    pass


async def escalate_to_manual_review(
    job_id: str,
    shop_url: str,
    error_reason: str,
    page_screenshot: bytes = None,
    page_html: str = None,
) -> dict:
    """Create manual review item in database."""

    # Insert into manual_review_queue table
    # with all context needed for human reviewer
    pass


async def notify_merchant(
    shop_url: str,
    subject: str,
    body: str,
) -> None:
    """Send email to merchant."""
    pass
```

---

## Pattern 3: Confidence-Based Filtering

```python
# app/models/extraction_quality.py

from pydantic import BaseModel, Field
from decimal import Decimal
from typing import Optional


class FieldConfidence(BaseModel):
    """Confidence score for a single field."""

    value: str | float | None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str  # "css", "llm", "api", "schema_org", etc.


class ProductExtraction(BaseModel):
    """Extracted product with confidence scores."""

    # Required fields (must have high confidence)
    title: FieldConfidence
    price: FieldConfidence
    product_url: FieldConfidence

    # Optional fields (lower confidence acceptable)
    image_url: Optional[FieldConfidence] = None
    description: Optional[FieldConfidence] = None
    sku: Optional[FieldConfidence] = None
    vendor: Optional[FieldConfidence] = None

    # Metadata
    extraction_source: str
    extraction_timestamp: datetime

    def validate_quality(self) -> tuple[bool, list[str]]:
        """
        Validate that product meets minimum quality standards.

        Returns: (is_valid, error_messages)
        """

        errors = []

        # Critical fields: confidence >= 0.85
        critical_fields = [self.title, self.price, self.product_url]

        for field_name, field in [
            ('title', self.title),
            ('price', self.price),
            ('product_url', self.product_url),
        ]:
            if field.confidence < 0.85:
                errors.append(
                    f"{field_name} confidence too low: {field.confidence:.2f} (< 0.85)"
                )

        # Important fields: confidence >= 0.75
        if self.image_url and self.image_url.confidence < 0.75:
            errors.append(f"image_url confidence too low: {self.image_url.confidence:.2f}")

        # Nice-to-have: confidence >= 0.60
        if self.description and self.description.confidence < 0.60:
            errors.append(f"description confidence too low: {self.description.confidence:.2f}")

        return (len(errors) == 0, errors)

    def get_average_confidence(self) -> float:
        """Calculate average confidence across all fields."""

        fields = [self.title, self.price, self.product_url]

        if self.image_url:
            fields.append(self.image_url)
        if self.description:
            fields.append(self.description)
        if self.sku:
            fields.append(self.sku)
        if self.vendor:
            fields.append(self.vendor)

        if not fields:
            return 0.0

        return sum(f.confidence for f in fields) / len(fields)
```

---

## Pattern 4: Monitoring & Alerting

```python
# app/infra/extraction_metrics.py

from datetime import datetime, timedelta
import logging

log = logging.getLogger(__name__)


class ExtractionMetrics:
    """Track extraction success, quality, and failure patterns."""

    def __init__(self, redis_client):
        self.redis = redis_client

    async def record_extraction(
        self,
        shop_id: str,
        shop_url: str,
        strategy: str,
        product_count: int,
        confidence: float,
        duration_seconds: float,
        error: str = None,
    ) -> None:
        """Record one extraction attempt."""

        # Record in Redis for 7-day retention
        key = f"extraction_metrics:{datetime.now().strftime('%Y-%m-%d')}"

        await self.redis.hincrby(key, "total_attempts", 1)

        if product_count > 0:
            await self.redis.hincrby(key, "successful", 1)
        else:
            await self.redis.hincrby(key, "zero_result", 1)

        if confidence >= 0.85:
            await self.redis.hincrby(key, "high_quality", 1)
        elif confidence >= 0.70:
            await self.redis.hincrby(key, "medium_quality", 1)
        else:
            await self.redis.hincrby(key, "low_quality", 1)

        # Track strategy usage
        await self.redis.hincrby(key, f"strategy_{strategy}", 1)

        # Track errors
        if error:
            await self.redis.hincrby(key, f"error_{error}", 1)

        # Set expiry (7 days)
        await self.redis.expire(key, 7 * 24 * 60 * 60)

    async def get_success_rate(self, days: int = 1) -> float:
        """Get extraction success rate for last N days."""

        total = 0
        successful = 0

        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            key = f"extraction_metrics:{date}"

            total += await self.redis.hget(key, "total_attempts") or 0
            successful += await self.redis.hget(key, "successful") or 0

        if total == 0:
            return 0.0

        return successful / total

    async def check_alerts(self) -> list[dict]:
        """Check if any alerting thresholds are breached."""

        alerts = []

        # Alert 1: Success rate dropped
        current_rate = await self.get_success_rate(days=1)
        previous_rate = await self.get_success_rate(days=2)

        if previous_rate > 0.95 and current_rate < 0.80:
            alerts.append({
                'severity': 'critical',
                'message': f"Success rate dropped from {previous_rate:.1%} to {current_rate:.1%}",
                'action': 'page_oncall',
            })

        # Alert 2: Zero-result rate increasing
        zero_result_key = f"extraction_metrics:{datetime.now().strftime('%Y-%m-%d')}"
        zero_result_count = await self.redis.hget(zero_result_key, "zero_result") or 0

        if zero_result_count > 100:
            alerts.append({
                'severity': 'warning',
                'message': f"Zero-result extractions: {zero_result_count} in last 24 hours",
                'action': 'notify_slack',
            })

        return alerts
```

---

## Recommended Crawl4AI Settings

```python
# app/config.py (or separate file)

CRAWL4AI_CONFIG = {
    "browser": {
        "enable_stealth": True,  # Avoid basic bot detection
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ],
    },
    "crawler": {
        "memory_threshold_percent": 70,  # Pause at 70% RAM
        "max_concurrent_pages": 10,  # Don't overload
    },
    "run_config": {
        "wait_for": "networkidle",  # Wait for all network activity
        "cache_mode": "bypass",  # Don't cache extractions
        "timeout": 45,  # 45 second timeout (higher for slow sites)
        "fit_markdown": True,  # For LLM extraction
    },
    "llm": {
        "provider": "openai/gpt-4o-mini",  # or groq, ollama
        "chunk_token_threshold": 3000,
        "overlap_rate": 0.1,
    },
}
```

---

## Complete Integration Example

```python
# app/services/pipeline.py (updated)

from typing import Optional
from decimal import Decimal
import logging

log = logging.getLogger(__name__)


class MerchantOnboardingPipeline:
    """Main orchestrator for merchant onboarding."""

    def __init__(self, extractor: ProductExtractor, metrics: ExtractionMetrics):
        self.extractor = extractor
        self.metrics = metrics

    async def onboard_merchant(self, job_id: str, shop_url: str) -> dict:
        """
        Complete onboarding flow with reliability patterns.
        """

        try:
            # 1. Detect platform
            platform = await self.platform_detector.detect(shop_url)

            # 2. Extract products (with fallback chain)
            start_time = time.time()

            extraction_result = await self.extractor.extract_products(
                url=shop_url,
                shop_url=shop_url,
                platform=platform,
            )

            duration_seconds = time.time() - start_time

            # 3. Record metrics
            await self.metrics.record_extraction(
                shop_id=job_id,
                shop_url=shop_url,
                strategy=extraction_result['strategy'],
                product_count=len(extraction_result['products']),
                confidence=extraction_result['confidence'],
                duration_seconds=duration_seconds,
                error=extraction_result.get('error'),
            )

            # 4. Handle zero-result case
            if len(extraction_result['products']) == 0:
                zero_result_protocol = await handle_zero_result_extraction(
                    job_id=job_id,
                    shop_url=shop_url,
                )

                return {
                    'status': zero_result_protocol['status'],
                    'job_id': job_id,
                    'message': zero_result_protocol.get('message'),
                    'escalation_id': zero_result_protocol.get('escalation_id'),
                }

            # 5. Normalize products
            normalized_products = [
                await self.normalizer.normalize(p)
                for p in extraction_result['products']
            ]

            # 6. Validate quality
            valid_products = []
            escalated_products = []

            for product in normalized_products:
                is_valid, errors = product.validate_quality()

                if is_valid:
                    valid_products.append(product)
                else:
                    escalated_products.append({
                        'product': product,
                        'errors': errors,
                    })

            # 7. Ingest valid products
            await self.bulk_ingestor.ingest(valid_products)

            # 8. Escalate low-quality products
            if escalated_products:
                await self.escalate_to_manual_review(
                    job_id=job_id,
                    reason="quality_issues",
                    products=escalated_products,
                )

            # 9. Return success
            return {
                'status': 'completed',
                'job_id': job_id,
                'products_ingested': len(valid_products),
                'products_escalated': len(escalated_products),
                'strategy': extraction_result['strategy'],
                'avg_confidence': extraction_result['confidence'],
                'duration_seconds': duration_seconds,
            }

        except Exception as e:
            log.error(f"Onboarding failed: {e}", exc_info=True)

            await self.escalate_to_manual_review(
                job_id=job_id,
                reason="unhandled_exception",
                error=str(e),
            )

            return {
                'status': 'failed',
                'job_id': job_id,
                'error': str(e),
                'escalation_required': True,
            }
```

---

## Testing Your Patterns

```python
# tests/test_extraction_reliability.py

import pytest
from app.services.product_extractor import ProductExtractor


@pytest.mark.asyncio
async def test_zero_result_detection():
    """Verify zero-result detection triggers escalation."""

    extractor = ProductExtractor(llm_config={})

    # Mock a site that returns 0 products
    result = await extractor.extract_products(
        url="https://no-products-here.example.com",
        shop_url="https://no-products-here.example.com",
    )

    assert result['products'] == []
    assert result['strategy'] in ['none', 'fallback_exhausted']


@pytest.mark.asyncio
async def test_fallback_chain_order():
    """Verify fallback strategies are tried in correct order."""

    call_order = []

    async def mock_api(url):
        call_order.append('api')
        return None

    async def mock_network(url):
        call_order.append('network')
        return [{'title': 'Test Product', 'price': 10}]

    # First strategy fails, second succeeds
    # Should not call strategies after success

    assert call_order == ['api', 'network']


@pytest.mark.asyncio
async def test_confidence_filtering():
    """Verify low-confidence products are escalated."""

    product_low = ProductExtraction(
        title=FieldConfidence(value="Title", confidence=0.5),
        price=FieldConfidence(value=10.0, confidence=0.5),
        product_url=FieldConfidence(value="https://...", confidence=0.5),
    )

    is_valid, errors = product_low.validate_quality()

    assert not is_valid
    assert len(errors) > 0


@pytest.mark.asyncio
async def test_exponential_backoff():
    """Verify retry logic uses exponential backoff."""

    import time

    call_times = []

    async def failing_strategy(url):
        call_times.append(time.time())
        raise Exception("Simulated failure")

    extractor = ProductExtractor(llm_config={})

    # This will fail and retry with backoff
    result = await extractor._try_strategy(
        strategy_name="test",
        extract_fn=failing_strategy,
        url="https://test.com",
        max_retries=3,
    )

    # Verify delays increased exponentially
    if len(call_times) > 2:
        delay_1 = call_times[1] - call_times[0]
        delay_2 = call_times[2] - call_times[1]

        # Second delay should be longer than first
        assert delay_2 > delay_1
```

---

## Summary

**Critical patterns to implement immediately**:

1. **Zero-result detection** → Route to escalation/fallback
2. **Confidence scoring** → Filter low-quality extractions
3. **Multi-strategy fallback** → API → Network → Schema.org → CSS → LLM
4. **Exponential backoff + jitter** → Retry failures smartly
5. **Manual escalation** → For edge cases automation can't handle

These five patterns together eliminate the "silent failure" problem where extraction returns 0 products and the merchant is left wondering why.

