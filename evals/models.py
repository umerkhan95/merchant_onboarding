"""Data models for the evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MatchType(StrEnum):
    """How to compare an extracted field against ground truth."""

    EXACT = "exact"
    FUZZY = "fuzzy"
    NUMERIC = "numeric"
    TOKEN_F1 = "token_f1"
    BOOLEAN = "boolean"
    URL = "url"


# Scoring method per product field.
FIELD_MATCH_TYPES: dict[str, MatchType] = {
    "title": MatchType.FUZZY,
    "price": MatchType.NUMERIC,
    "currency": MatchType.EXACT,
    "description": MatchType.TOKEN_F1,
    "image_url": MatchType.URL,
    "vendor": MatchType.FUZZY,
    "in_stock": MatchType.BOOLEAN,
    "sku": MatchType.EXACT,
    "product_type": MatchType.FUZZY,
    "product_url": MatchType.URL,
}

# Common field name aliases in raw extraction data.
FIELD_ALIASES: dict[str, str] = {
    "vendor": "brand",
    "image_url": "image",
    "product_url": "url",
    "product_type": "category",
    "in_stock": "availability",
}


@dataclass
class ExpectedProduct:
    """Ground truth product data for a single product."""

    title: str
    price: str | None = None
    currency: str | None = None
    description: str | None = None
    image_url: str | None = None
    vendor: str | None = None
    in_stock: bool | None = None
    sku: str | None = None
    product_type: str | None = None
    product_url: str | None = None

    def scorable_fields(self) -> dict[str, str | None]:
        """Return dict of fields that have ground-truth values."""
        raw = {
            "title": self.title,
            "price": self.price,
            "currency": self.currency,
            "description": self.description,
            "image_url": self.image_url,
            "vendor": self.vendor,
            "in_stock": str(self.in_stock).lower() if self.in_stock is not None else None,
            "sku": self.sku,
            "product_type": self.product_type,
            "product_url": self.product_url,
        }
        return {k: v for k, v in raw.items() if v is not None}


@dataclass
class TestCase:
    """A single evaluation test case: one shop URL + expected products."""

    name: str
    url: str
    platform: str
    products: list[ExpectedProduct]
    min_products: int | None = None
    html_file: str | None = None  # Relative path to HTML snapshot in fixtures/snapshots/


@dataclass
class FieldScore:
    """Score for a single field comparison."""

    field_name: str
    match_type: MatchType
    score: float  # 0.0 to 1.0
    expected: str | None
    extracted: str | None


@dataclass
class ProductScore:
    """Score for a single extracted product matched against expected."""

    expected_title: str
    extracted_title: str | None
    field_scores: list[FieldScore]

    @property
    def avg_score(self) -> float:
        if not self.field_scores:
            return 0.0
        return sum(f.score for f in self.field_scores) / len(self.field_scores)

    @property
    def fields_matched(self) -> int:
        return sum(1 for f in self.field_scores if f.score >= 0.8)

    @property
    def fields_total(self) -> int:
        return len(self.field_scores)


@dataclass
class TierResult:
    """Evaluation result for a single extraction tier on one test case."""

    tier_name: str
    products_extracted: int
    products_matched: int
    product_scores: list[ProductScore]
    duration_seconds: float
    error: str | None = None
    min_products: int | None = None  # Expected minimum from test case
    peak_memory_mb: float | None = None  # Peak memory during extraction
    tokens_used: int | None = None  # LLM tokens used (Tier 4-5 only)
    estimated_cost_usd: float | None = None  # Estimated cost (LLM tiers)

    @property
    def avg_score(self) -> float:
        if not self.product_scores:
            return 0.0
        return sum(p.avg_score for p in self.product_scores) / len(self.product_scores)

    @property
    def field_averages(self) -> dict[str, float]:
        """Average score per field across all matched products."""
        field_totals: dict[str, list[float]] = {}
        for ps in self.product_scores:
            for fs in ps.field_scores:
                field_totals.setdefault(fs.field_name, []).append(fs.score)
        return {
            name: sum(scores) / len(scores)
            for name, scores in field_totals.items()
        }

    @property
    def completeness_score(self) -> float:
        """How many products were found vs expected minimum."""
        if not self.min_products or self.min_products <= 0:
            return 1.0  # No expectation set
        return min(1.0, self.products_extracted / self.min_products)

    @property
    def overall_score(self) -> float:
        """Weighted combination of accuracy and completeness.

        60% field accuracy + 40% completeness.
        """
        return (self.avg_score * 0.6) + (self.completeness_score * 0.4)


@dataclass
class EvalReport:
    """Full evaluation report for one test case across all tiers."""

    test_case_name: str
    url: str
    platform: str
    tier_results: list[TierResult] = field(default_factory=list)

    @property
    def best_tier(self) -> TierResult | None:
        scorable = [t for t in self.tier_results if t.product_scores]
        if not scorable:
            return None
        return max(scorable, key=lambda t: t.overall_score)
