"""Reconciliation reporting. Compares discovered URLs vs extraction results for coverage analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ReconciliationReport:
    urls_discovered: int = 0
    urls_attempted: int = 0
    urls_with_products: int = 0
    urls_failed: int = 0
    products_extracted: int = 0
    products_normalized: int = 0
    coverage_percentage: float = 0.0
    extraction_success_rate: float = 0.0
    gap_count: int = 0
    failed_urls: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "urls_discovered": self.urls_discovered,
            "urls_attempted": self.urls_attempted,
            "urls_with_products": self.urls_with_products,
            "urls_failed": self.urls_failed,
            "products_extracted": self.products_extracted,
            "products_normalized": self.products_normalized,
            "coverage_percentage": round(self.coverage_percentage, 2),
            "extraction_success_rate": round(self.extraction_success_rate, 2),
            "gap_count": self.gap_count,
            "failed_urls": self.failed_urls,
        })


class ReconciliationReporter:
    def generate(
        self,
        discovered_urls: list[str],
        audit_summary: dict,
        products_normalized: int,
    ) -> ReconciliationReport:
        urls_discovered = len(discovered_urls)
        urls_attempted = audit_summary.get("urls_attempted", 0)
        urls_with_products = audit_summary.get("urls_with_products", 0)
        urls_failed = audit_summary.get("urls_errored", 0)
        products_extracted = audit_summary.get("total_products", 0)
        coverage_percentage = (
            urls_with_products / urls_discovered * 100
            if urls_discovered > 0
            else 0.0
        )
        extraction_success_rate = (
            urls_with_products / urls_attempted * 100
            if urls_attempted > 0
            else 0.0
        )
        gap_count = urls_discovered - urls_with_products
        failed_urls = audit_summary.get("failed_urls", [])[:100]

        return ReconciliationReport(
            urls_discovered=urls_discovered,
            urls_attempted=urls_attempted,
            urls_with_products=urls_with_products,
            urls_failed=urls_failed,
            products_extracted=products_extracted,
            products_normalized=products_normalized,
            coverage_percentage=coverage_percentage,
            extraction_success_rate=extraction_success_rate,
            gap_count=gap_count,
            failed_urls=failed_urls,
        )
