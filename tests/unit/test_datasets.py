"""Tests for dataset loaders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.datasets.mave import _create_bundled_sample as create_mave_sample
from evals.datasets.mave import _record_to_product as mave_record_to_product
from evals.datasets.mave import load_mave
from evals.datasets.wdc_pave import _create_bundled_sample as create_wdc_sample
from evals.datasets.wdc_pave import _record_to_product as wdc_record_to_product
from evals.datasets.wdc_pave import load_wdc_pave
from evals.models import TestCase


class TestMAVELoader:
    """Tests for MAVE dataset loader."""

    def test_creates_bundled_sample_when_missing(self, tmp_path: Path):
        """MAVE loader creates bundled sample when no data exists."""
        cache_file = tmp_path / "mave_sample.jsonl"
        assert not cache_file.exists()

        # Load without existing data
        test_cases = load_mave(sample_size=5, data_path=cache_file)

        # Should have created the file
        assert cache_file.exists()
        # Should have loaded some cases
        assert len(test_cases) > 0
        # Should be valid TestCase objects
        assert all(isinstance(tc, TestCase) for tc in test_cases)

    def test_respects_sample_size(self, tmp_path: Path):
        """MAVE loader respects sample_size parameter."""
        cache_file = tmp_path / "mave_sample.jsonl"

        # Create a sample with 20 records
        create_mave_sample(cache_file)

        # Request only 5
        test_cases = load_mave(sample_size=5, data_path=cache_file, seed=42)
        assert len(test_cases) == 5

        # Request more than available - should return all
        test_cases = load_mave(sample_size=100, data_path=cache_file)
        assert len(test_cases) == 20  # Bundled sample has 20 products

    def test_respects_category_filter(self, tmp_path: Path):
        """MAVE loader respects category filter."""
        cache_file = tmp_path / "mave_sample.jsonl"

        # Create bundled sample
        create_mave_sample(cache_file)

        # Filter by category
        test_cases = load_mave(sample_size=100, category="Electronics", data_path=cache_file)

        # All should be Electronics
        for tc in test_cases:
            assert len(tc.products) == 1
            # Check product_type (mapped from category)
            assert tc.products[0].product_type == "Electronics"

        # Should have some Electronics products in bundled sample
        assert len(test_cases) > 0

    def test_record_to_product_conversion(self):
        """MAVE _record_to_product converts correctly."""
        record = {
            "title": "Test Product",
            "category": "Electronics",
            "brand": "TestBrand",
            "price": "99.99",
            "description": "A test product",
            "attributes": [
                {"key": "brand", "value": "TestBrand"},
                {"key": "price", "value": "99.99"},
                {"key": "color", "value": "Blue"},
            ],
        }

        product = mave_record_to_product(record)

        assert product is not None
        assert product.title == "Test Product"
        assert product.vendor == "TestBrand"
        assert product.price == "99.99"
        assert product.product_type == "Electronics"
        assert product.description == "A test product"

    def test_record_to_product_handles_missing_title(self):
        """MAVE _record_to_product returns None for missing title."""
        record = {"category": "Electronics", "price": "99.99"}
        product = mave_record_to_product(record)
        assert product is None

        record_empty_title = {"title": "   ", "price": "99.99"}
        product = mave_record_to_product(record_empty_title)
        assert product is None

    def test_returns_valid_test_cases(self, tmp_path: Path):
        """MAVE loader returns valid TestCase objects."""
        cache_file = tmp_path / "mave_sample.jsonl"
        test_cases = load_mave(sample_size=5, data_path=cache_file)

        assert len(test_cases) > 0

        for tc in test_cases:
            # Check TestCase structure
            assert isinstance(tc, TestCase)
            assert tc.name.startswith("MAVE:")
            assert tc.platform == "generic"
            assert len(tc.products) == 1

            # Check product
            product = tc.products[0]
            assert product.title  # Should have a title
            assert len(product.title) > 0


class TestWDCPAVELoader:
    """Tests for WDC-PAVE dataset loader."""

    def test_creates_bundled_sample_when_missing(self, tmp_path: Path):
        """WDC-PAVE loader creates bundled sample when no data exists."""
        cache_file = tmp_path / "wdc_pave_sample.jsonl"
        assert not cache_file.exists()

        # Load without existing data
        test_cases = load_wdc_pave(sample_size=5, data_path=cache_file)

        # Should have created the file
        assert cache_file.exists()
        # Should have loaded some cases
        assert len(test_cases) > 0
        # Should be valid TestCase objects
        assert all(isinstance(tc, TestCase) for tc in test_cases)

    def test_respects_sample_size(self, tmp_path: Path):
        """WDC-PAVE loader respects sample_size parameter."""
        cache_file = tmp_path / "wdc_pave_sample.jsonl"

        # Create a sample with 10 records
        create_wdc_sample(cache_file)

        # Request only 3
        test_cases = load_wdc_pave(sample_size=3, data_path=cache_file, seed=42)
        assert len(test_cases) == 3

        # Request more than available - should return all
        test_cases = load_wdc_pave(sample_size=100, data_path=cache_file)
        assert len(test_cases) == 10  # Bundled sample has 10 products

    def test_respects_site_filter(self, tmp_path: Path):
        """WDC-PAVE loader respects site filter."""
        cache_file = tmp_path / "wdc_pave_sample.jsonl"

        # Create bundled sample
        create_wdc_sample(cache_file)

        # Filter by site
        test_cases = load_wdc_pave(sample_size=100, site="dyson.com", data_path=cache_file)

        # Should have exactly 1 Dyson product in bundled sample
        assert len(test_cases) == 1
        assert test_cases[0].products[0].vendor == "Dyson"

    def test_record_to_product_conversion(self):
        """WDC-PAVE _record_to_product converts correctly."""
        record = {
            "title": "Test Product",
            "site": "test.com",
            "url": "https://test.com/product",
            "brand": "TestBrand",
            "price": "199.99",
            "currency": "USD",
            "description": "A test product",
            "image": "https://test.com/image.jpg",
        }

        product = wdc_record_to_product(record)

        assert product is not None
        assert product.title == "Test Product"
        assert product.vendor == "TestBrand"
        assert product.price == "199.99"
        assert product.currency == "USD"
        assert product.description == "A test product"
        assert product.image_url == "https://test.com/image.jpg"
        assert product.product_url == "https://test.com/product"

    def test_record_to_product_handles_missing_title(self):
        """WDC-PAVE _record_to_product returns None for missing title."""
        record = {"site": "test.com", "price": "99.99"}
        product = wdc_record_to_product(record)
        assert product is None

        record_empty_title = {"title": "  ", "price": "99.99"}
        product = wdc_record_to_product(record_empty_title)
        assert product is None

    def test_returns_valid_test_cases(self, tmp_path: Path):
        """WDC-PAVE loader returns valid TestCase objects."""
        cache_file = tmp_path / "wdc_pave_sample.jsonl"
        test_cases = load_wdc_pave(sample_size=5, data_path=cache_file)

        assert len(test_cases) > 0

        for tc in test_cases:
            # Check TestCase structure
            assert isinstance(tc, TestCase)
            assert tc.name.startswith("WDC:")
            assert tc.platform == "generic"
            assert len(tc.products) == 1

            # Check product
            product = tc.products[0]
            assert product.title  # Should have a title
            assert len(product.title) > 0

    def test_bundled_sample_has_multiple_sites(self, tmp_path: Path):
        """WDC-PAVE bundled sample represents products from multiple sites."""
        cache_file = tmp_path / "wdc_pave_sample.jsonl"
        create_wdc_sample(cache_file)

        # Read the file and check unique sites
        records = []
        for line in cache_file.read_text().strip().split("\n"):
            if line:
                records.append(json.loads(line))

        sites = {r["site"] for r in records}
        # Should have multiple unique sites
        assert len(sites) >= 5


class TestBundledSamples:
    """Tests for bundled sample creation."""

    def test_mave_bundled_sample_structure(self, tmp_path: Path):
        """MAVE bundled sample has correct structure."""
        cache_file = tmp_path / "mave_sample.jsonl"
        create_mave_sample(cache_file)

        # Read and validate structure
        records = []
        for line in cache_file.read_text().strip().split("\n"):
            if line:
                record = json.loads(line)
                records.append(record)

                # Check required fields
                assert "title" in record
                assert "category" in record
                assert "brand" in record
                assert "price" in record
                assert "attributes" in record
                assert isinstance(record["attributes"], list)

        # Should have multiple records
        assert len(records) >= 10

        # Should have multiple categories
        categories = {r["category"] for r in records}
        assert len(categories) >= 4

    def test_wdc_bundled_sample_structure(self, tmp_path: Path):
        """WDC-PAVE bundled sample has correct structure."""
        cache_file = tmp_path / "wdc_pave_sample.jsonl"
        create_wdc_sample(cache_file)

        # Read and validate structure
        records = []
        for line in cache_file.read_text().strip().split("\n"):
            if line:
                record = json.loads(line)
                records.append(record)

                # Check required fields
                assert "title" in record
                assert "site" in record
                assert "url" in record
                assert "brand" in record
                assert "price" in record
                assert "currency" in record

        # Should have multiple records
        assert len(records) >= 5

        # Should have multiple sites
        sites = {r["site"] for r in records}
        assert len(sites) >= 5


class TestDeterministicSampling:
    """Tests for deterministic sampling with seeds."""

    def test_mave_same_seed_same_results(self, tmp_path: Path):
        """MAVE loader with same seed produces same results."""
        cache_file = tmp_path / "mave_sample.jsonl"
        create_mave_sample(cache_file)

        # Load twice with same seed
        tc1 = load_mave(sample_size=5, data_path=cache_file, seed=42)
        tc2 = load_mave(sample_size=5, data_path=cache_file, seed=42)

        # Should get same products in same order
        assert len(tc1) == len(tc2)
        for i in range(len(tc1)):
            assert tc1[i].products[0].title == tc2[i].products[0].title

    def test_mave_different_seed_different_results(self, tmp_path: Path):
        """MAVE loader with different seeds produces different results."""
        cache_file = tmp_path / "mave_sample.jsonl"
        create_mave_sample(cache_file)

        # Load with different seeds
        tc1 = load_mave(sample_size=5, data_path=cache_file, seed=42)
        tc2 = load_mave(sample_size=5, data_path=cache_file, seed=99)

        # Should get different products (with high probability)
        titles1 = {tc.products[0].title for tc in tc1}
        titles2 = {tc.products[0].title for tc in tc2}
        # Allow some overlap but expect at least some difference
        assert titles1 != titles2
