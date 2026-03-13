"""Unit tests for Pydantic models and enums."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import (
    ExtractionTier,
    JobProgress,
    JobStatus,
    OnboardingRequest,
    OnboardingResponse,
    Platform,
    Product,
    Variant,
)


class TestEnums:
    """Test enum serialization and values."""

    def test_platform_enum_values(self):
        """Test Platform enum has correct values."""
        assert Platform.SHOPIFY == "shopify"
        assert Platform.WOOCOMMERCE == "woocommerce"
        assert Platform.MAGENTO == "magento"
        assert Platform.BIGCOMMERCE == "bigcommerce"
        assert Platform.GENERIC == "generic"

    def test_platform_enum_serialization(self):
        """Test Platform enum serializes to string."""
        assert str(Platform.SHOPIFY) == "shopify"
        assert Platform.SHOPIFY.value == "shopify"

    def test_job_status_enum_values(self):
        """Test JobStatus enum has correct values."""
        assert JobStatus.QUEUED == "queued"
        assert JobStatus.DETECTING == "detecting"
        assert JobStatus.DISCOVERING == "discovering"
        assert JobStatus.EXTRACTING == "extracting"
        assert JobStatus.NORMALIZING == "normalizing"
        assert JobStatus.INGESTING == "ingesting"
        assert JobStatus.COMPLETED == "completed"
        assert JobStatus.FAILED == "failed"

    def test_job_status_enum_serialization(self):
        """Test JobStatus enum serializes to string."""
        assert str(JobStatus.QUEUED) == "queued"
        assert JobStatus.EXTRACTING.value == "extracting"

    def test_extraction_tier_enum_values(self):
        """Test ExtractionTier enum has correct values."""
        assert ExtractionTier.API == "api"
        assert ExtractionTier.SITEMAP_CSS == "sitemap_css"
        assert ExtractionTier.DEEP_CRAWL == "deep_crawl"

    def test_extraction_tier_enum_serialization(self):
        """Test ExtractionTier enum serializes to string."""
        assert str(ExtractionTier.API) == "api"
        assert ExtractionTier.SITEMAP_CSS.value == "sitemap_css"


class TestVariantModel:
    """Test Variant model."""

    def test_variant_creation_with_all_fields(self):
        """Test creating variant with all fields."""
        variant = Variant(
            variant_id="var_123",
            title="Large / Blue",
            price=Decimal("49.99"),
            sku="SHIRT-LG-BLUE",
            in_stock=True,
        )

        assert variant.variant_id == "var_123"
        assert variant.title == "Large / Blue"
        assert variant.price == Decimal("49.99")
        assert variant.sku == "SHIRT-LG-BLUE"
        assert variant.in_stock is True

    def test_variant_creation_without_sku(self):
        """Test creating variant without SKU."""
        variant = Variant(
            variant_id="var_456",
            title="Medium",
            price=Decimal("39.99"),
            sku=None,
            in_stock=False,
        )

        assert variant.variant_id == "var_456"
        assert variant.sku is None
        assert variant.in_stock is False

    def test_variant_price_decimal_precision(self):
        """Test variant price uses Decimal with correct precision."""
        variant = Variant(
            variant_id="var_789",
            title="Small",
            price=Decimal("29.99"),
            in_stock=True,
        )

        assert isinstance(variant.price, Decimal)
        assert variant.price == Decimal("29.99")

    def test_variant_json_serialization(self):
        """Test variant serializes to JSON correctly."""
        variant = Variant(
            variant_id="var_001",
            title="XL / Red",
            price=Decimal("59.99"),
            sku="SHIRT-XL-RED",
            in_stock=True,
        )

        json_data = variant.model_dump()
        assert json_data["variant_id"] == "var_001"
        assert json_data["price"] == Decimal("59.99")


class TestProductModel:
    """Test Product model."""

    def test_product_creation_with_all_fields(self):
        """Test creating product with all fields."""
        variant = Variant(
            variant_id="var_1",
            title="Default",
            price=Decimal("29.99"),
            in_stock=True,
        )

        product = Product(
            external_id="prod_123",
            shop_id="shop_abc",
            platform=Platform.SHOPIFY,
            title="Premium T-Shirt",
            description="High-quality cotton shirt",
            price=Decimal("29.99"),
            compare_at_price=Decimal("49.99"),
            currency="USD",
            image_url="https://example.com/shirt.jpg",
            product_url="https://example.com/products/shirt",
            sku="SHIRT-001",
            vendor="BrandCo",
            product_type="Apparel",
            in_stock=True,
            variants=[variant],
            tags=["cotton", "premium"],
            raw_data={"original": "data"},
            scraped_at=datetime(2026, 2, 14, 12, 0, 0),
        )

        assert product.external_id == "prod_123"
        assert product.shop_id == "shop_abc"
        assert product.platform == Platform.SHOPIFY
        assert product.title == "Premium T-Shirt"
        assert product.price == Decimal("29.99")
        assert product.compare_at_price == Decimal("49.99")
        assert product.currency == "USD"
        assert len(product.variants) == 1
        assert len(product.tags) == 2
        assert product.idempotency_key != ""  # Should be computed

    def test_product_minimal_fields(self):
        """Test creating product with minimal required fields."""
        product = Product(
            external_id="prod_456",
            shop_id="shop_xyz",
            platform=Platform.WOOCOMMERCE,
            title="Simple Product",
            description="A simple product",
            price=Decimal("19.99"),
            currency="EUR",
            image_url="https://example.com/product.jpg",
            product_url="https://example.com/products/simple",
            in_stock=True,
        )

        assert product.external_id == "prod_456"
        assert product.compare_at_price is None
        assert product.sku is None
        assert product.vendor is None
        assert product.product_type is None
        assert product.variants == []
        assert product.tags == []
        assert product.raw_data == {}

    def test_idempotency_key_computation(self):
        """Test idempotency key is computed correctly."""
        product1 = Product(
            external_id="prod_123",
            shop_id="shop_abc",
            platform=Platform.SHOPIFY,
            title="T-Shirt",
            description="A shirt",
            price=Decimal("29.99"),
            currency="USD",
            image_url="https://example.com/shirt.jpg",
            product_url="https://example.com/products/shirt",
            in_stock=True,
        )

        product2 = Product(
            external_id="prod_123",
            shop_id="shop_abc",
            platform=Platform.SHOPIFY,
            title="T-Shirt",
            description="A shirt",
            price=Decimal("29.99"),
            currency="USD",
            image_url="https://example.com/shirt.jpg",
            product_url="https://example.com/products/shirt",
            in_stock=True,
        )

        # Same inputs should produce same idempotency key
        assert product1.idempotency_key == product2.idempotency_key
        assert len(product1.idempotency_key) == 64  # SHA256 hex digest

    def test_idempotency_key_stability(self):
        """Test idempotency key remains stable for same input."""
        product = Product(
            external_id="prod_789",
            shop_id="shop_test",
            platform=Platform.MAGENTO,
            title="Test Product",
            description="Description",
            price=Decimal("99.99"),
            currency="GBP",
            image_url="https://example.com/test.jpg",
            product_url="https://example.com/test",
            in_stock=False,
        )

        # Create another instance with identical stable key fields but different volatile fields
        product2 = Product(
            external_id="prod_789",
            shop_id="shop_test",
            platform=Platform.MAGENTO,
            title="Different Title",  # Different title
            description="Different description",  # Different description
            price=Decimal("149.99"),  # Different price
            currency="GBP",
            image_url="https://example.com/different.jpg",  # Different image
            product_url="https://example.com/test",
            in_stock=True,  # Different stock status
        )

        # Keys should be the same (title, price, image_url, description, in_stock not in key)
        assert product.idempotency_key == product2.idempotency_key

    def test_idempotency_key_changes_with_key_fields(self):
        """Test idempotency key changes when key fields change."""
        product1 = Product(
            external_id="prod_001",
            shop_id="shop_abc",
            platform=Platform.SHOPIFY,
            title="Product A",
            description="Desc",
            price=Decimal("10.00"),
            currency="USD",
            image_url="https://example.com/a.jpg",
            product_url="https://example.com/a",
            in_stock=True,
        )

        product2 = Product(
            external_id="prod_002",  # Different external_id
            shop_id="shop_abc",
            platform=Platform.SHOPIFY,
            title="Product A",
            description="Desc",
            price=Decimal("10.00"),
            currency="USD",
            image_url="https://example.com/a.jpg",
            product_url="https://example.com/a",
            in_stock=True,
        )

        # Keys should be different
        assert product1.idempotency_key != product2.idempotency_key

    def test_currency_code_uppercase_conversion(self):
        """Test currency code is converted to uppercase."""
        product = Product(
            external_id="prod_999",
            shop_id="shop_test",
            platform=Platform.GENERIC,
            title="Test",
            description="Test",
            price=Decimal("10.00"),
            currency="usd",  # lowercase
            image_url="https://example.com/test.jpg",
            product_url="https://example.com/test",
            in_stock=True,
        )

        assert product.currency == "USD"

    def test_currency_code_max_length_validation(self):
        """Test currency code respects 3-character limit."""
        # Valid 3-char currency
        product = Product(
            external_id="prod_999",
            shop_id="shop_test",
            platform=Platform.GENERIC,
            title="Test",
            description="Test",
            price=Decimal("10.00"),
            currency="EUR",
            image_url="https://example.com/test.jpg",
            product_url="https://example.com/test",
            in_stock=True,
        )
        assert product.currency == "EUR"

    def test_product_with_decimal_prices(self):
        """Test product uses Decimal for all price fields."""
        product = Product(
            external_id="prod_decimal",
            shop_id="shop_test",
            platform=Platform.BIGCOMMERCE,
            title="Decimal Test",
            description="Test",
            price=Decimal("123.45"),
            compare_at_price=Decimal("199.99"),
            currency="USD",
            image_url="https://example.com/test.jpg",
            product_url="https://example.com/test",
            in_stock=True,
        )

        assert isinstance(product.price, Decimal)
        assert isinstance(product.compare_at_price, Decimal)
        assert product.price == Decimal("123.45")
        assert product.compare_at_price == Decimal("199.99")


class TestOnboardingRequestModel:
    """Test OnboardingRequest model."""

    def test_valid_https_url(self):
        """Test valid HTTPS URL is accepted."""
        request = OnboardingRequest(url="https://example-store.myshopify.com")
        assert str(request.url) == "https://example-store.myshopify.com/"

    def test_valid_http_url(self):
        """Test valid HTTP URL is accepted."""
        request = OnboardingRequest(url="http://example.com")
        assert "http://example.com" in str(request.url)

    def test_reject_ftp_url(self):
        """Test FTP URLs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            OnboardingRequest(url="ftp://example.com")

        # Pydantic's HttpUrl rejects non-HTTP(S) schemes before our validator
        errors = exc_info.value.errors()
        assert len(errors) > 0
        # The error should indicate scheme validation failure
        assert any("scheme" in str(error).lower() or "url" in str(error).lower() for error in errors)

    def test_reject_private_ip_address(self):
        """Test private IP addresses are rejected."""
        private_ips = [
            "http://192.168.1.1",
            "http://10.0.0.1",
            "http://172.16.0.1",
        ]

        for ip_url in private_ips:
            with pytest.raises(ValidationError) as exc_info:
                OnboardingRequest(url=ip_url)

            error = exc_info.value.errors()[0]
            assert "Private/reserved IP addresses are not allowed" in str(error["ctx"]["error"])

    def test_reject_localhost(self):
        """Test localhost URLs are rejected."""
        localhost_urls = [
            "http://localhost",
            "http://127.0.0.1",
            "http://0.0.0.0",
        ]

        for url in localhost_urls:
            with pytest.raises(ValidationError) as exc_info:
                OnboardingRequest(url=url)

            error = exc_info.value.errors()[0]
            assert "Localhost addresses are not allowed" in str(error["ctx"]["error"])

    def test_accept_public_domain(self):
        """Test public domain names are accepted."""
        valid_urls = [
            "https://www.example.com",
            "https://store.myshopify.com",
            "https://boutique-shop.woocommerce.com",
        ]

        for url in valid_urls:
            request = OnboardingRequest(url=url)
            assert request.url is not None


class TestOnboardingResponseModel:
    """Test OnboardingResponse model."""

    def test_onboarding_response_creation(self):
        """Test creating onboarding response."""
        response = OnboardingResponse(
            job_id="job_123abc",
            status=JobStatus.QUEUED,
            progress_url="/api/v1/jobs/job_123abc/progress",
        )

        assert response.job_id == "job_123abc"
        assert response.status == JobStatus.QUEUED
        assert response.progress_url == "/api/v1/jobs/job_123abc/progress"

    def test_onboarding_response_json_serialization(self):
        """Test response serializes correctly."""
        response = OnboardingResponse(
            job_id="job_xyz",
            status=JobStatus.DETECTING,
            progress_url="/progress",
        )

        json_data = response.model_dump()
        assert json_data["job_id"] == "job_xyz"
        assert json_data["status"] == "detecting"  # Enum serializes to string


class TestJobProgressModel:
    """Test JobProgress model."""

    def test_job_progress_with_explicit_percentage(self):
        """Test job progress with explicit percentage."""
        progress = JobProgress(
            job_id="job_123",
            processed=50,
            total=100,
            percentage=50.0,
            status=JobStatus.EXTRACTING,
            current_step="Extracting products",
        )

        assert progress.job_id == "job_123"
        assert progress.processed == 50
        assert progress.total == 100
        assert progress.percentage == 50.0
        assert progress.status == JobStatus.EXTRACTING
        assert progress.error is None

    def test_job_progress_percentage_calculation(self):
        """Test percentage is calculated from processed/total."""
        progress = JobProgress(
            job_id="job_456",
            processed=75,
            total=150,
            percentage=None,  # Should be computed
            status=JobStatus.NORMALIZING,
            current_step="Normalizing data",
        )

        assert progress.percentage == 50.0  # 75/150 * 100

    def test_job_progress_zero_total(self):
        """Test percentage calculation with zero total."""
        progress = JobProgress(
            job_id="job_789",
            processed=0,
            total=0,
            percentage=None,
            status=JobStatus.QUEUED,
            current_step="Initializing",
        )

        assert progress.percentage == 0.0

    def test_job_progress_with_error(self):
        """Test job progress with error message."""
        progress = JobProgress(
            job_id="job_error",
            processed=10,
            total=100,
            percentage=10.0,
            status=JobStatus.FAILED,
            current_step="Failed during extraction",
            error="Connection timeout",
        )

        assert progress.status == JobStatus.FAILED
        assert progress.error == "Connection timeout"

    def test_job_progress_percentage_rounding(self):
        """Test percentage is rounded to 2 decimal places."""
        progress = JobProgress(
            job_id="job_round",
            processed=1,
            total=3,
            percentage=None,
            status=JobStatus.INGESTING,
            current_step="Ingesting to database",
        )

        # 1/3 * 100 = 33.333... should round to 33.33
        assert progress.percentage == 33.33

    def test_job_progress_completed_status(self):
        """Test job progress with completed status."""
        progress = JobProgress(
            job_id="job_done",
            processed=200,
            total=200,
            percentage=100.0,
            status=JobStatus.COMPLETED,
            current_step="All products processed",
        )

        assert progress.percentage == 100.0
        assert progress.status == JobStatus.COMPLETED


class TestModelIntegration:
    """Test model integration and JSON serialization."""

    def test_product_with_variants_serialization(self):
        """Test product with variants serializes correctly."""
        variants = [
            Variant(
                variant_id="v1",
                title="Small",
                price=Decimal("19.99"),
                in_stock=True,
            ),
            Variant(
                variant_id="v2",
                title="Large",
                price=Decimal("24.99"),
                in_stock=False,
            ),
        ]

        product = Product(
            external_id="prod_multi",
            shop_id="shop_test",
            platform=Platform.SHOPIFY,
            title="Multi-Variant Product",
            description="Product with variants",
            price=Decimal("19.99"),
            currency="USD",
            image_url="https://example.com/multi.jpg",
            product_url="https://example.com/multi",
            in_stock=True,
            variants=variants,
        )

        json_data = product.model_dump()
        assert len(json_data["variants"]) == 2
        assert json_data["variants"][0]["title"] == "Small"
        assert json_data["platform"] == "shopify"  # Enum serializes to string

    def test_all_enums_serialize_to_strings(self):
        """Test all enum types serialize to strings in JSON."""
        product = Product(
            external_id="enum_test",
            shop_id="shop_test",
            platform=Platform.MAGENTO,
            title="Enum Test",
            description="Test",
            price=Decimal("10.00"),
            currency="USD",
            image_url="https://example.com/test.jpg",
            product_url="https://example.com/test",
            in_stock=True,
        )

        progress = JobProgress(
            job_id="enum_test",
            processed=1,
            total=1,
            percentage=100.0,
            status=JobStatus.COMPLETED,
            current_step="Done",
        )

        product_json = product.model_dump()
        progress_json = progress.model_dump()

        # Platform enum serializes to string
        assert isinstance(product_json["platform"], str)
        assert product_json["platform"] == "magento"

        # JobStatus enum serializes to string
        assert isinstance(progress_json["status"], str)
        assert progress_json["status"] == "completed"
