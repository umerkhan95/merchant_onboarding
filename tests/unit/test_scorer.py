"""Unit tests for the evaluation scorer."""

import pytest

from evals.models import ExpectedProduct, MatchType
from evals.scorer import Scorer


class TestExactMatching:
    """Test exact string matching for fields like currency and sku."""

    def test_exact_match_case_insensitive(self):
        score = Scorer.score_field("currency", "USD", "usd")
        assert score.score == 1.0
        assert score.match_type == MatchType.EXACT

    def test_exact_match_with_whitespace(self):
        score = Scorer.score_field("sku", " ABC123 ", "ABC123")
        assert score.score == 1.0

    def test_exact_mismatch(self):
        score = Scorer.score_field("currency", "USD", "EUR")
        assert score.score == 0.0

    def test_exact_match_empty_strings(self):
        score = Scorer.score_field("sku", "", "")
        assert score.score == 1.0


class TestFuzzyMatching:
    """Test fuzzy string matching for fields like title and vendor."""

    def test_exact_title_match(self):
        score = Scorer._fuzzy_score("Organic Cotton T-Shirt", "Organic Cotton T-Shirt")
        assert score == 1.0

    def test_high_similarity_title(self):
        score = Scorer._fuzzy_score(
            "Organic Cotton T-Shirt",
            "Organic Cotton T-Shirt - Blue",
        )
        assert score > 0.8

    def test_medium_similarity_title(self):
        score = Scorer._fuzzy_score(
            "Organic Cotton T-Shirt",
            "Cotton Shirt",
        )
        assert 0.4 < score < 0.8

    def test_low_similarity_title(self):
        score = Scorer._fuzzy_score(
            "Organic Cotton T-Shirt",
            "Leather Jacket",
        )
        assert score < 0.3

    def test_fuzzy_case_insensitive(self):
        score = Scorer._fuzzy_score("Nike Shoes", "NIKE SHOES")
        assert score == 1.0

    def test_fuzzy_with_extra_whitespace(self):
        score = Scorer._fuzzy_score("  Product Name  ", "Product Name")
        assert score == 1.0


class TestNumericScoring:
    """Test numeric comparison with tolerance for price fields."""

    def test_exact_numeric_match(self):
        score = Scorer._numeric_score("29.99", "29.99")
        assert score == 1.0

    def test_numeric_with_currency_symbols(self):
        score = Scorer._numeric_score("$29.99", "$29.99")
        assert score == 1.0

    def test_numeric_different_currency_formats(self):
        score = Scorer._numeric_score("$29.99", "29.99 USD")
        assert score == 1.0

    def test_numeric_within_tolerance(self):
        # 1% tolerance of 100.00 is 1.00
        score = Scorer._numeric_score("100.00", "100.50")
        assert score == 1.0

    def test_numeric_outside_tolerance(self):
        # 1% tolerance of 100.00 is 1.00, so 102.00 should fail
        score = Scorer._numeric_score("100.00", "102.00")
        assert score == 0.0

    def test_numeric_with_commas(self):
        score = Scorer._numeric_score("1,299.99", "1299.99")
        assert score == 1.0

    def test_numeric_invalid_format(self):
        score = Scorer._numeric_score("invalid", "29.99")
        assert score == 0.0

    def test_numeric_empty_after_stripping(self):
        score = Scorer._numeric_score("$$$", "###")
        assert score == 0.0


class TestTokenF1:
    """Test token-level F1 scoring for description fields."""

    def test_identical_descriptions(self):
        desc = "High quality organic cotton shirt"
        score = Scorer._token_f1(desc, desc)
        assert score == 1.0

    def test_partial_overlap(self):
        expected = "High quality organic cotton shirt"
        extracted = "Quality organic shirt with pockets"
        score = Scorer._token_f1(expected, extracted)
        # Overlap: "quality", "organic", "shirt" = 3 tokens
        # Expected: 5 tokens, Extracted: 5 tokens
        # Precision: 3/5, Recall: 3/5, F1: 3/5 = 0.6
        assert score == pytest.approx(0.6, abs=0.01)

    def test_no_overlap(self):
        expected = "Cotton shirt"
        extracted = "Leather jacket"
        score = Scorer._token_f1(expected, extracted)
        assert score == 0.0

    def test_subset_description(self):
        expected = "Organic cotton"
        extracted = "Organic"
        score = Scorer._token_f1(expected, extracted)
        # Precision: 1/1 = 1.0, Recall: 1/2 = 0.5
        # F1: 2 * (1.0 * 0.5) / (1.0 + 0.5) = 0.666...
        assert score == pytest.approx(0.666, abs=0.01)

    def test_empty_strings(self):
        score = Scorer._token_f1("", "Some text")
        assert score == 0.0

    def test_case_insensitive_tokens(self):
        score = Scorer._token_f1("ORGANIC COTTON", "organic cotton")
        assert score == 1.0


class TestBooleanScoring:
    """Test boolean truthiness comparison for in_stock fields."""

    def test_both_true(self):
        score = Scorer._boolean_score("true", "true")
        assert score == 1.0

    def test_both_false(self):
        score = Scorer._boolean_score("false", "out of stock")
        assert score == 1.0

    def test_various_truthy_values(self):
        truthy = ["true", "True", "1", "yes", "YES", "in_stock", "available"]
        for val in truthy:
            score = Scorer._boolean_score("true", val)
            assert score == 1.0, f"Failed for {val}"

    def test_truthy_vs_falsy(self):
        score = Scorer._boolean_score("true", "false")
        assert score == 0.0

    def test_numeric_truthy(self):
        score = Scorer._boolean_score("1", "yes")
        assert score == 1.0

    def test_custom_truthy_values(self):
        score = Scorer._boolean_score("in_stock", "available")
        assert score == 1.0

    def test_instock_without_underscore(self):
        # Schema.org and OpenGraph often use "instock" (no underscore)
        score = Scorer._boolean_score("true", "instock")
        assert score == 1.0

    def test_in_stock_with_space(self):
        score = Scorer._boolean_score("true", "in stock")
        assert score == 1.0

    def test_instock_variations(self):
        # Test all variations of instock
        variations = ["instock", "InStock", "in_stock", "in stock"]
        for val in variations:
            score = Scorer._boolean_score("true", val)
            assert score == 1.0, f"Failed for '{val}'"


class TestURLScoring:
    """Test URL comparison with normalization."""

    def test_exact_url_match(self):
        url = "https://example.com/product/123"
        score = Scorer._url_score(url, url)
        assert score == 1.0

    def test_url_scheme_difference(self):
        expected = "http://example.com/product/123"
        extracted = "https://example.com/product/123"
        score = Scorer._url_score(expected, extracted)
        assert score == 0.9

    def test_url_query_params_ignored(self):
        expected = "https://example.com/product/123"
        extracted = "https://example.com/product/123?ref=email&utm_source=newsletter"
        score = Scorer._url_score(expected, extracted)
        assert score == 1.0

    def test_url_fragment_ignored(self):
        expected = "https://example.com/product/123"
        extracted = "https://example.com/product/123#reviews"
        score = Scorer._url_score(expected, extracted)
        assert score == 1.0

    def test_url_different_path(self):
        expected = "https://example.com/product/123"
        extracted = "https://example.com/product/456"
        score = Scorer._url_score(expected, extracted)
        assert score == 0.0

    def test_url_different_domain(self):
        expected = "https://example.com/product"
        extracted = "https://other.com/product"
        score = Scorer._url_score(expected, extracted)
        assert score == 0.0

    def test_url_trailing_slash(self):
        expected = "https://example.com/product"
        extracted = "https://example.com/product/"
        # URLs with/without trailing slash should be treated as equal after normalization
        score = Scorer._url_score(expected, extracted)
        assert score == 1.0


class TestFieldScoring:
    """Test the main score_field method with various scenarios."""

    def test_score_field_with_none_expected(self):
        score = Scorer.score_field("title", None, "Some Product")
        assert score.score == 1.0
        assert score.expected is None

    def test_score_field_with_none_extracted(self):
        score = Scorer.score_field("title", "Expected Product", None)
        assert score.score == 0.0
        assert score.extracted is None

    def test_score_field_delegates_correctly(self):
        # Test that it uses the right match type
        price_score = Scorer.score_field("price", "$29.99", "29.99")
        assert price_score.match_type == MatchType.NUMERIC
        assert price_score.score == 1.0

        title_score = Scorer.score_field("title", "Product", "Product Name")
        assert title_score.match_type == MatchType.FUZZY
        assert title_score.score > 0.0


class TestProductScoring:
    """Test scoring a full product against expected."""

    def test_score_product_all_fields_match(self):
        expected = ExpectedProduct(
            title="Organic T-Shirt",
            price="29.99",
            currency="USD",
            sku="TS001",
        )
        extracted = {
            "title": "Organic T-Shirt",
            "price": "$29.99",
            "currency": "usd",
            "sku": "TS001",
        }
        result = Scorer.score_product(expected, extracted)

        assert result.expected_title == "Organic T-Shirt"
        assert result.extracted_title == "Organic T-Shirt"
        assert len(result.field_scores) == 4
        assert all(fs.score >= 0.9 for fs in result.field_scores)

    def test_score_product_with_alias_resolution(self):
        expected = ExpectedProduct(
            title="Product",
            vendor="Nike",
            image_url="https://example.com/image.jpg",
        )
        extracted = {
            "title": "Product",
            "brand": "Nike",  # alias for vendor
            "image": "https://example.com/image.jpg",  # alias for image_url
        }
        result = Scorer.score_product(expected, extracted)

        # Should find vendor via "brand" alias
        vendor_score = next(fs for fs in result.field_scores if fs.field_name == "vendor")
        assert vendor_score.score == 1.0
        assert vendor_score.extracted == "Nike"

        # Should find image_url via "image" alias
        image_score = next(fs for fs in result.field_scores if fs.field_name == "image_url")
        assert image_score.score == 1.0

    def test_score_product_missing_fields(self):
        expected = ExpectedProduct(
            title="Product",
            price="29.99",
            sku="ABC123",
        )
        extracted = {
            "title": "Product",
            # price and sku missing
        }
        result = Scorer.score_product(expected, extracted)

        title_score = next(fs for fs in result.field_scores if fs.field_name == "title")
        assert title_score.score == 1.0

        price_score = next(fs for fs in result.field_scores if fs.field_name == "price")
        assert price_score.score == 0.0
        assert price_score.extracted is None

        sku_score = next(fs for fs in result.field_scores if fs.field_name == "sku")
        assert sku_score.score == 0.0
        assert sku_score.extracted is None

    def test_score_product_only_title_required(self):
        expected = ExpectedProduct(title="Basic Product")
        extracted = {"title": "Basic Product"}

        result = Scorer.score_product(expected, extracted)
        assert len(result.field_scores) == 1
        assert result.field_scores[0].field_name == "title"
        assert result.field_scores[0].score == 1.0


class TestProductMatching:
    """Test matching extracted products to expected by title similarity."""

    def test_match_products_exact_titles(self):
        expected = [
            ExpectedProduct(title="Product A", price="10.00"),
            ExpectedProduct(title="Product B", price="20.00"),
        ]
        extracted = [
            {"title": "Product A", "price": "10.00"},
            {"title": "Product B", "price": "20.00"},
        ]
        results = Scorer.match_products(expected, extracted)

        assert len(results) == 2
        assert results[0].expected_title == "Product A"
        assert results[0].extracted_title == "Product A"
        assert results[1].expected_title == "Product B"
        assert results[1].extracted_title == "Product B"

    def test_match_products_fuzzy_titles(self):
        expected = [
            ExpectedProduct(title="Organic Cotton T-Shirt"),
        ]
        extracted = [
            {"title": "Organic Cotton T-Shirt - Blue Size M"},
        ]
        results = Scorer.match_products(expected, extracted)

        assert len(results) == 1
        assert results[0].extracted_title == "Organic Cotton T-Shirt - Blue Size M"
        # Should match due to high similarity

    def test_match_products_best_match_greedy(self):
        # Greedy matching processes expected products in order
        # First expected product gets best available match
        expected = [
            ExpectedProduct(title="Cotton Shirt"),
            ExpectedProduct(title="Organic Cotton T-Shirt"),
        ]
        extracted = [
            {"title": "Organic Cotton T-Shirt - Blue"},
            {"title": "Cotton Shirt Basic"},
        ]
        results = Scorer.match_products(expected, extracted)

        # First expected matches to best available
        first_result = results[0]
        assert first_result.expected_title == "Cotton Shirt"
        # Should have matched to something
        assert first_result.extracted_title is not None

        # Second expected gets remaining matches
        second_result = results[1]
        assert second_result.expected_title == "Organic Cotton T-Shirt"
        assert second_result.extracted_title is not None

    def test_match_products_unmatched_expected(self):
        expected = [
            ExpectedProduct(title="Product A", price="10.00"),
            ExpectedProduct(title="Product B", price="20.00"),
        ]
        extracted = [
            {"title": "Product A", "price": "10.00"},
            # Product B not extracted
        ]
        results = Scorer.match_products(expected, extracted)

        assert len(results) == 2

        product_a_result = next(r for r in results if r.expected_title == "Product A")
        assert product_a_result.extracted_title == "Product A"
        assert all(fs.score > 0 for fs in product_a_result.field_scores)

        product_b_result = next(r for r in results if r.expected_title == "Product B")
        assert product_b_result.extracted_title is None
        assert all(fs.score == 0.0 for fs in product_b_result.field_scores)

    def test_match_products_no_extracted(self):
        expected = [ExpectedProduct(title="Product A")]
        extracted = []
        results = Scorer.match_products(expected, extracted)

        assert len(results) == 1
        assert results[0].extracted_title is None
        assert all(fs.score == 0.0 for fs in results[0].field_scores)

    def test_match_products_below_threshold(self):
        expected = [
            ExpectedProduct(title="Leather Jacket"),
        ]
        extracted = [
            {"title": "Cotton T-Shirt"},  # Very different, below 0.5 threshold
        ]
        results = Scorer.match_products(expected, extracted)

        assert len(results) == 1
        assert results[0].extracted_title is None
        assert all(fs.score == 0.0 for fs in results[0].field_scores)

    def test_match_products_empty_lists(self):
        results = Scorer.match_products([], [])
        assert len(results) == 0

    def test_match_products_missing_titles_in_extracted(self):
        expected = [ExpectedProduct(title="Product A")]
        extracted = [
            {"price": "10.00"},  # No title field
        ]
        results = Scorer.match_products(expected, extracted)

        assert len(results) == 1
        assert results[0].extracted_title is None


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_score_field_both_none(self):
        score = Scorer.score_field("title", None, None)
        assert score.score == 1.0  # No ground truth = automatic pass

    def test_score_field_empty_strings(self):
        score = Scorer.score_field("title", "", "")
        assert score.score == 1.0

    def test_fuzzy_score_unicode(self):
        score = Scorer._fuzzy_score("Café au lait", "Café au lait")
        assert score == 1.0

    def test_numeric_score_zero_values(self):
        score = Scorer._numeric_score("0.00", "0.00")
        assert score == 1.0

    def test_numeric_score_negative_values(self):
        score = Scorer._numeric_score("-10.00", "-10.00")
        assert score == 1.0

    def test_token_f1_single_token(self):
        score = Scorer._token_f1("Product", "Product")
        assert score == 1.0

    def test_url_score_with_whitespace(self):
        score = Scorer._url_score(
            "  https://example.com/product  ",
            "https://example.com/product",
        )
        assert score == 1.0

    def test_product_score_with_non_string_values(self):
        expected = ExpectedProduct(title="Product", price="29.99")
        extracted = {
            "title": "Product",
            "price": 29.99,  # Numeric instead of string
        }
        result = Scorer.score_product(expected, extracted)

        price_score = next(fs for fs in result.field_scores if fs.field_name == "price")
        # Should convert to string and compare
        assert price_score.score == 1.0
