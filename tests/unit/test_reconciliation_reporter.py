"""Unit tests for ReconciliationReporter and ReconciliationReport."""

import json

from app.services.reconciliation_reporter import ReconciliationReport, ReconciliationReporter


class TestReconciliationReporter:
    def setup_method(self):
        self.reporter = ReconciliationReporter()

    def test_full_coverage(self):
        discovered_urls = [
            "https://example.com/product/1",
            "https://example.com/product/2",
            "https://example.com/product/3",
            "https://example.com/product/4",
            "https://example.com/product/5",
        ]
        audit_summary = {
            "urls_attempted": 5,
            "urls_with_products": 5,
            "urls_errored": 0,
            "total_products": 5,
            "failed_urls": [],
        }

        report = self.reporter.generate(
            discovered_urls=discovered_urls,
            audit_summary=audit_summary,
            products_normalized=5,
        )

        assert report.urls_discovered == 5
        assert report.urls_attempted == 5
        assert report.urls_with_products == 5
        assert report.coverage_percentage == 100.0
        assert report.gap_count == 0

    def test_partial_coverage(self):
        discovered_urls = [f"https://example.com/product/{i}" for i in range(10)]
        audit_summary = {
            "urls_attempted": 8,
            "urls_with_products": 5,
            "urls_errored": 3,
            "total_products": 20,
            "failed_urls": [],
        }

        report = self.reporter.generate(
            discovered_urls=discovered_urls,
            audit_summary=audit_summary,
            products_normalized=18,
        )

        assert report.urls_discovered == 10
        assert report.urls_attempted == 8
        assert report.urls_with_products == 5
        # 5 / 10 * 100 = 50.0
        assert report.coverage_percentage == 50.0
        # 5 / 8 * 100 = 62.5
        assert report.extraction_success_rate == 62.5
        assert report.gap_count == 5

    def test_zero_discovered_no_division_error(self):
        audit_summary = {
            "urls_attempted": 0,
            "urls_with_products": 0,
            "urls_errored": 0,
            "total_products": 0,
            "failed_urls": [],
        }

        report = self.reporter.generate(
            discovered_urls=[],
            audit_summary=audit_summary,
            products_normalized=0,
        )

        assert report.urls_discovered == 0
        assert report.coverage_percentage == 0.0

    def test_zero_attempted_no_division_error(self):
        discovered_urls = [
            "https://example.com/product/1",
            "https://example.com/product/2",
        ]
        audit_summary = {
            "urls_attempted": 0,
            "urls_with_products": 0,
            "urls_errored": 0,
            "total_products": 0,
            "failed_urls": [],
        }

        report = self.reporter.generate(
            discovered_urls=discovered_urls,
            audit_summary=audit_summary,
            products_normalized=0,
        )

        assert report.urls_discovered == 2
        assert report.urls_attempted == 0
        assert report.extraction_success_rate == 0.0

    def test_gap_count(self):
        discovered_urls = [f"https://example.com/product/{i}" for i in range(20)]
        audit_summary = {
            "urls_attempted": 20,
            "urls_with_products": 15,
            "urls_errored": 5,
            "total_products": 45,
            "failed_urls": [],
        }

        report = self.reporter.generate(
            discovered_urls=discovered_urls,
            audit_summary=audit_summary,
            products_normalized=40,
        )

        assert report.gap_count == 5

    def test_failed_urls_from_audit(self):
        discovered_urls = [
            "https://example.com/product/1",
            "https://example.com/product/2",
            "https://example.com/url1",
            "https://example.com/url2",
        ]
        audit_summary = {
            "urls_attempted": 4,
            "urls_with_products": 2,
            "urls_errored": 2,
            "total_products": 10,
            "failed_urls": ["https://example.com/url1", "https://example.com/url2"],
        }

        report = self.reporter.generate(
            discovered_urls=discovered_urls,
            audit_summary=audit_summary,
            products_normalized=8,
        )

        assert "https://example.com/url1" in report.failed_urls
        assert "https://example.com/url2" in report.failed_urls
        assert len(report.failed_urls) == 2

    def test_failed_urls_capped_at_100(self):
        discovered_urls = [f"https://example.com/product/{i}" for i in range(200)]
        failed_urls = [f"https://example.com/fail/{i}" for i in range(150)]
        audit_summary = {
            "urls_attempted": 200,
            "urls_with_products": 50,
            "urls_errored": 150,
            "total_products": 100,
            "failed_urls": failed_urls,
        }

        report = self.reporter.generate(
            discovered_urls=discovered_urls,
            audit_summary=audit_summary,
            products_normalized=90,
        )

        assert len(report.failed_urls) == 100
        # The cap preserves order — first 100 entries should match
        assert report.failed_urls == failed_urls[:100]

    def test_products_normalized_passed_through(self):
        discovered_urls = [
            "https://example.com/product/1",
            "https://example.com/product/2",
        ]
        audit_summary = {
            "urls_attempted": 2,
            "urls_with_products": 2,
            "urls_errored": 0,
            "total_products": 50,
            "failed_urls": [],
        }

        report = self.reporter.generate(
            discovered_urls=discovered_urls,
            audit_summary=audit_summary,
            products_normalized=42,
        )

        assert report.products_normalized == 42


class TestReconciliationReportJson:
    def _make_report(self, **kwargs) -> ReconciliationReport:
        defaults = {
            "urls_discovered": 10,
            "urls_attempted": 8,
            "urls_with_products": 5,
            "urls_failed": 2,
            "products_extracted": 20,
            "products_normalized": 18,
            "coverage_percentage": 50.0,
            "extraction_success_rate": 62.5,
            "gap_count": 5,
            "failed_urls": ["https://example.com/fail1", "https://example.com/fail2"],
        }
        defaults.update(kwargs)
        return ReconciliationReport(**defaults)

    def test_to_json_valid(self):
        report = self._make_report()
        result = report.to_json()
        data = json.loads(result)

        assert data["urls_discovered"] == 10
        assert data["urls_attempted"] == 8
        assert data["urls_with_products"] == 5
        assert data["urls_failed"] == 2
        assert data["products_extracted"] == 20
        assert data["products_normalized"] == 18
        assert data["coverage_percentage"] == 50.0
        assert data["extraction_success_rate"] == 62.5
        assert data["gap_count"] == 5
        assert data["failed_urls"] == [
            "https://example.com/fail1",
            "https://example.com/fail2",
        ]

    def test_to_json_rounds_floats(self):
        # 1/3 * 100 = 33.333...
        report = self._make_report(coverage_percentage=100 / 3)
        result = report.to_json()
        data = json.loads(result)

        assert data["coverage_percentage"] == 33.33
