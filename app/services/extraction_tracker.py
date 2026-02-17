"""Per-URL extraction outcome tracking. In-memory audit trail for pipeline runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Shared key for source URL tagging across tracker, checker, and pipeline.
SOURCE_URL_KEY = "_source_url"


class URLOutcome(StrEnum):
    """Possible outcomes for a URL extraction attempt."""

    SUCCESS = "success"
    EMPTY = "empty"
    NOT_PRODUCT = "not_product"
    ERROR = "error"
    INCOMPLETE = "incomplete"


@dataclass
class URLExtractionRecord:
    """Single URL extraction outcome."""

    url: str
    outcome: URLOutcome
    product_count: int = 0
    error_message: str = ""
    missing_fields: list[str] = field(default_factory=list)


@dataclass
class ExtractionAudit:
    """Aggregated extraction audit summary."""

    urls_attempted: int = 0
    urls_with_products: int = 0
    urls_empty: int = 0
    urls_not_product: int = 0
    urls_errored: int = 0
    urls_incomplete: int = 0
    total_products: int = 0
    records: list[URLExtractionRecord] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Percentage of attempted URLs that yielded products."""
        if self.urls_attempted == 0:
            return 0.0
        return self.urls_with_products / self.urls_attempted * 100

    @property
    def failed_urls(self) -> list[str]:
        """URLs that errored during extraction."""
        return [r.url for r in self.records if r.outcome == URLOutcome.ERROR]

    @property
    def incomplete_urls(self) -> list[str]:
        """URLs that produced products with missing critical fields."""
        return [r.url for r in self.records if r.outcome == URLOutcome.INCOMPLETE]

    def to_summary_dict(self) -> dict:
        """Serialize audit to a summary dict for storage.

        Caps failed/incomplete URL lists at 50 entries.
        """
        return {
            "urls_attempted": self.urls_attempted,
            "urls_with_products": self.urls_with_products,
            "urls_empty": self.urls_empty,
            "urls_not_product": self.urls_not_product,
            "urls_errored": self.urls_errored,
            "urls_incomplete": self.urls_incomplete,
            "total_products": self.total_products,
            "success_rate": round(self.success_rate, 2),
            "failed_urls": self.failed_urls[:50],
            "incomplete_urls": self.incomplete_urls[:50],
        }


class ExtractionTracker:
    """Tracks per-URL extraction outcomes during a pipeline run.

    In-memory only. Created per-job, discarded after audit is built.
    """

    def __init__(self) -> None:
        self._records: list[URLExtractionRecord] = []

    def record_success(self, url: str, product_count: int) -> None:
        """Record a successful extraction from a URL."""
        self._records.append(
            URLExtractionRecord(
                url=url,
                outcome=URLOutcome.SUCCESS,
                product_count=product_count,
            )
        )

    def record_empty(self, url: str) -> None:
        """Record a URL that returned zero products."""
        self._records.append(
            URLExtractionRecord(url=url, outcome=URLOutcome.EMPTY)
        )

    def record_not_product(self, url: str) -> None:
        """Record a URL that was not a product page."""
        self._records.append(
            URLExtractionRecord(url=url, outcome=URLOutcome.NOT_PRODUCT)
        )

    def record_error(self, url: str, error: str) -> None:
        """Record a URL that errored during extraction."""
        self._records.append(
            URLExtractionRecord(
                url=url, outcome=URLOutcome.ERROR, error_message=error
            )
        )

    def record_incomplete(self, url: str, missing_fields: list[str]) -> None:
        """Record a URL that produced products with missing critical fields."""
        self._records.append(
            URLExtractionRecord(
                url=url,
                outcome=URLOutcome.INCOMPLETE,
                missing_fields=missing_fields,
            )
        )

    @staticmethod
    def tag_products_with_source(products: list[dict], source_url: str) -> list[dict]:
        """Stamp _source_url on every product dict.

        Args:
            products: Raw product dicts to tag
            source_url: URL that produced these products

        Returns:
            Same list (mutated in place) with _source_url added
        """
        for product in products:
            product[SOURCE_URL_KEY] = source_url
        return products

    def build_audit(self) -> ExtractionAudit:
        """Build aggregated audit from all recorded outcomes."""
        audit = ExtractionAudit(records=list(self._records))
        audit.urls_attempted = len(self._records)
        for record in self._records:
            if record.outcome == URLOutcome.SUCCESS:
                audit.urls_with_products += 1
                audit.total_products += record.product_count
            elif record.outcome == URLOutcome.EMPTY:
                audit.urls_empty += 1
            elif record.outcome == URLOutcome.NOT_PRODUCT:
                audit.urls_not_product += 1
            elif record.outcome == URLOutcome.ERROR:
                audit.urls_errored += 1
            elif record.outcome == URLOutcome.INCOMPLETE:
                audit.urls_incomplete += 1
        return audit
