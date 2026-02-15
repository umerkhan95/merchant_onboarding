"""Scoring engine for product extraction evaluation."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from evals.models import (
    FIELD_ALIASES,
    FIELD_MATCH_TYPES,
    ExpectedProduct,
    FieldScore,
    MatchType,
    ProductScore,
)


class Scorer:
    """Scores extracted product data against ground truth."""

    @staticmethod
    def score_field(field_name: str, expected: str | None, extracted: str | None) -> FieldScore:
        """Score a single field comparison.

        Args:
            field_name: Name of the field being scored
            expected: Ground truth value (None means no ground truth)
            extracted: Extracted value (None means not found)

        Returns:
            FieldScore with match type and score 0.0-1.0
        """
        match_type = FIELD_MATCH_TYPES.get(field_name, MatchType.EXACT)

        # No ground truth to compare against
        if expected is None:
            return FieldScore(
                field_name=field_name,
                match_type=match_type,
                score=1.0,
                expected=expected,
                extracted=extracted,
            )

        # Extracted value is missing
        if extracted is None:
            return FieldScore(
                field_name=field_name,
                match_type=match_type,
                score=0.0,
                expected=expected,
                extracted=extracted,
            )

        # Delegate to appropriate scoring method
        if match_type == MatchType.EXACT:
            score = 1.0 if expected.strip().lower() == extracted.strip().lower() else 0.0
        elif match_type == MatchType.FUZZY:
            score = Scorer._fuzzy_score(expected, extracted)
        elif match_type == MatchType.NUMERIC:
            score = Scorer._numeric_score(expected, extracted)
        elif match_type == MatchType.TOKEN_F1:
            score = Scorer._token_f1(expected, extracted)
        elif match_type == MatchType.BOOLEAN:
            score = Scorer._boolean_score(expected, extracted)
        elif match_type == MatchType.URL:
            score = Scorer._url_score(expected, extracted)
        else:
            score = 0.0

        return FieldScore(
            field_name=field_name,
            match_type=match_type,
            score=score,
            expected=expected,
            extracted=extracted,
        )

    @staticmethod
    def _fuzzy_score(expected: str, extracted: str) -> float:
        """Fuzzy string similarity using sequence matching.

        Args:
            expected: Ground truth string
            extracted: Extracted string

        Returns:
            Similarity ratio 0.0-1.0
        """
        expected_clean = expected.strip().lower()
        extracted_clean = extracted.strip().lower()
        return SequenceMatcher(None, expected_clean, extracted_clean).ratio()

    @staticmethod
    def _numeric_score(expected: str, extracted: str) -> float:
        """Numeric comparison with tolerance.

        Strips currency symbols and compares as float with 1% tolerance.

        Args:
            expected: Ground truth numeric string (may include currency)
            extracted: Extracted numeric string (may include currency)

        Returns:
            1.0 if within tolerance, 0.0 otherwise
        """
        # Strip currency symbols and commas
        expected_num = re.sub(r'[^\d.]', '', expected)
        extracted_num = re.sub(r'[^\d.]', '', extracted)

        try:
            exp_val = float(expected_num)
            ext_val = float(extracted_num)
        except ValueError:
            return 0.0

        # 1% tolerance
        tolerance = abs(exp_val) * 0.01
        return 1.0 if abs(exp_val - ext_val) <= tolerance else 0.0

    @staticmethod
    def _token_f1(expected: str, extracted: str) -> float:
        """Token-level F1 score.

        Splits on whitespace, computes precision and recall on token sets.

        Args:
            expected: Ground truth text
            extracted: Extracted text

        Returns:
            F1 score 0.0-1.0
        """
        expected_tokens = set(expected.lower().split())
        extracted_tokens = set(extracted.lower().split())

        if not expected_tokens or not extracted_tokens:
            return 0.0

        overlap = expected_tokens & extracted_tokens

        precision = len(overlap) / len(extracted_tokens)
        recall = len(overlap) / len(expected_tokens)

        if precision + recall == 0:
            return 0.0

        # Harmonic mean
        return 2 * (precision * recall) / (precision + recall)

    @staticmethod
    def _boolean_score(expected: str, extracted: str) -> float:
        """Boolean truthiness comparison.

        Args:
            expected: Ground truth boolean string
            extracted: Extracted boolean string

        Returns:
            1.0 if same truthiness, 0.0 otherwise
        """
        truthy_values = {"true", "1", "yes", "in_stock", "available"}

        expected_truthy = expected.strip().lower() in truthy_values
        extracted_truthy = extracted.strip().lower() in truthy_values

        return 1.0 if expected_truthy == extracted_truthy else 0.0

    @staticmethod
    def _url_score(expected: str, extracted: str) -> float:
        """URL comparison with normalization.

        Compares scheme+netloc+path, ignoring query and fragment.

        Args:
            expected: Ground truth URL
            extracted: Extracted URL

        Returns:
            1.0 for exact match, 0.9 for same path/different scheme, 0.0 otherwise
        """
        exp_parsed = urlparse(expected.strip())
        ext_parsed = urlparse(extracted.strip())

        # Normalize: compare scheme, netloc, path (ignore query/fragment)
        exp_normalized = (exp_parsed.scheme.lower(), exp_parsed.netloc.lower(), exp_parsed.path)
        ext_normalized = (ext_parsed.scheme.lower(), ext_parsed.netloc.lower(), ext_parsed.path)

        # Exact match
        if exp_normalized == ext_normalized:
            return 1.0

        # Same netloc+path but different scheme (http vs https)
        if exp_normalized[1:] == ext_normalized[1:]:
            return 0.9

        return 0.0

    @staticmethod
    def score_product(expected: ExpectedProduct, extracted: dict) -> ProductScore:
        """Score all fields of an extracted product against expected.

        Uses field aliases to find values in extracted dict.

        Args:
            expected: Ground truth product
            extracted: Raw extracted product dict

        Returns:
            ProductScore with per-field scores
        """
        scorable = expected.scorable_fields()
        field_scores = []

        for field_name, expected_value in scorable.items():
            # Try to get value from extracted dict
            extracted_value = extracted.get(field_name)

            # If not found, try aliases
            if extracted_value is None and field_name in FIELD_ALIASES:
                for alias in FIELD_ALIASES[field_name]:
                    extracted_value = extracted.get(alias)
                    if extracted_value is not None:
                        break

            # Flatten JSON-LD nested objects (e.g. {"@type": "Brand", "name": "Nike"} → "Nike")
            if isinstance(extracted_value, dict):
                extracted_value = extracted_value.get("name") or extracted_value.get("value") or str(extracted_value)

            # Convert to string for comparison (except None)
            if extracted_value is not None:
                extracted_value = str(extracted_value)

            field_score = Scorer.score_field(field_name, expected_value, extracted_value)
            field_scores.append(field_score)

        extracted_title = extracted.get("title") or extracted.get("og:title") or extracted.get("name")
        return ProductScore(
            expected_title=expected.title,
            extracted_title=extracted_title,
            field_scores=field_scores,
        )

    @staticmethod
    def match_products(
        expected: list[ExpectedProduct],
        extracted: list[dict],
    ) -> list[ProductScore]:
        """Match extracted products to expected by title similarity.

        Uses greedy best-match algorithm. Unmatched products get score 0.0.

        Args:
            expected: List of ground truth products
            extracted: List of raw extracted product dicts

        Returns:
            List of ProductScore, one per expected product
        """
        product_scores = []
        remaining_extracted = extracted.copy()

        for exp_product in expected:
            best_match = None
            best_score = 0.0
            best_idx = -1

            # Find best matching extracted product by title similarity
            for idx, ext_dict in enumerate(remaining_extracted):
                ext_title = ext_dict.get("title") or ext_dict.get("og:title") or ext_dict.get("name", "")
                if not ext_title:
                    continue

                exp_lower = exp_product.title.lower()
                ext_lower = str(ext_title).lower()

                # Use the higher of: SequenceMatcher ratio, or containment check.
                # Long OG titles like "Product - Description | Brand" tank SequenceMatcher
                # but the expected title "Product" is clearly contained.
                seq_score = SequenceMatcher(None, exp_lower, ext_lower).ratio()

                # Containment: if expected is a substring of extracted (or vice versa),
                # score based on length ratio of shorter/longer
                if exp_lower in ext_lower:
                    containment_score = len(exp_lower) / len(ext_lower)
                    # Boost: contained match should score at least 0.6
                    containment_score = max(containment_score, 0.6)
                elif ext_lower in exp_lower:
                    containment_score = len(ext_lower) / len(exp_lower)
                    containment_score = max(containment_score, 0.6)
                else:
                    containment_score = 0.0

                title_similarity = max(seq_score, containment_score)

                # Threshold 0.5 for a match
                if title_similarity >= 0.5 and title_similarity > best_score:
                    best_score = title_similarity
                    best_match = ext_dict
                    best_idx = idx

            if best_match is not None:
                # Score the matched product
                product_score = Scorer.score_product(exp_product, best_match)
                product_scores.append(product_score)
                # Remove from pool
                remaining_extracted.pop(best_idx)
            else:
                # No match found - score 0.0 for all fields
                scorable = exp_product.scorable_fields()
                field_scores = [
                    FieldScore(
                        field_name=field_name,
                        match_type=FIELD_MATCH_TYPES.get(field_name, MatchType.EXACT),
                        score=0.0,
                        expected=expected_value,
                        extracted=None,
                    )
                    for field_name, expected_value in scorable.items()
                ]
                product_scores.append(
                    ProductScore(
                        expected_title=exp_product.title,
                        extracted_title=None,
                        field_scores=field_scores,
                    )
                )

        return product_scores
