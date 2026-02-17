"""Unit tests for ExtractionTracker."""

from __future__ import annotations

from app.services.extraction_tracker import (
    ExtractionAudit,
    ExtractionTracker,
    URLOutcome,
)


class TestExtractionTracker:
    """Tests for ExtractionTracker record/audit functionality."""

    def test_record_success(self):
        tracker = ExtractionTracker()
        tracker.record_success("https://example.com/p1", 3)

        audit = tracker.build_audit()
        assert audit.urls_attempted == 1
        assert audit.urls_with_products == 1
        assert audit.total_products == 3

    def test_record_empty(self):
        tracker = ExtractionTracker()
        tracker.record_empty("https://example.com/p1")

        audit = tracker.build_audit()
        assert audit.urls_attempted == 1
        assert audit.urls_empty == 1
        assert audit.total_products == 0

    def test_record_not_product(self):
        tracker = ExtractionTracker()
        tracker.record_not_product("https://example.com/blog")

        audit = tracker.build_audit()
        assert audit.urls_attempted == 1
        assert audit.urls_not_product == 1

    def test_record_error(self):
        tracker = ExtractionTracker()
        tracker.record_error("https://example.com/p1", "Connection timeout")

        audit = tracker.build_audit()
        assert audit.urls_attempted == 1
        assert audit.urls_errored == 1
        assert audit.records[0].error_message == "Connection timeout"

    def test_record_incomplete(self):
        tracker = ExtractionTracker()
        tracker.record_incomplete("https://example.com/p1", ["price", "image"])

        audit = tracker.build_audit()
        assert audit.urls_attempted == 1
        assert audit.urls_incomplete == 1
        assert audit.records[0].missing_fields == ["price", "image"]

    def test_mixed_outcomes(self):
        tracker = ExtractionTracker()
        tracker.record_success("https://example.com/p1", 2)
        tracker.record_success("https://example.com/p2", 1)
        tracker.record_empty("https://example.com/p3")
        tracker.record_error("https://example.com/p4", "timeout")
        tracker.record_not_product("https://example.com/blog")

        audit = tracker.build_audit()
        assert audit.urls_attempted == 5
        assert audit.urls_with_products == 2
        assert audit.urls_empty == 1
        assert audit.urls_errored == 1
        assert audit.urls_not_product == 1
        assert audit.total_products == 3

    def test_success_rate(self):
        tracker = ExtractionTracker()
        tracker.record_success("https://example.com/p1", 1)
        tracker.record_empty("https://example.com/p2")

        audit = tracker.build_audit()
        assert audit.success_rate == 50.0

    def test_success_rate_zero_attempted(self):
        tracker = ExtractionTracker()
        audit = tracker.build_audit()
        assert audit.success_rate == 0.0

    def test_failed_urls(self):
        tracker = ExtractionTracker()
        tracker.record_error("https://example.com/p1", "err1")
        tracker.record_error("https://example.com/p2", "err2")
        tracker.record_success("https://example.com/p3", 1)

        audit = tracker.build_audit()
        failed = audit.failed_urls
        assert len(failed) == 2
        assert "https://example.com/p1" in failed
        assert "https://example.com/p2" in failed

    def test_incomplete_urls(self):
        tracker = ExtractionTracker()
        tracker.record_incomplete("https://example.com/p1", ["price"])
        tracker.record_success("https://example.com/p2", 1)

        audit = tracker.build_audit()
        incomplete = audit.incomplete_urls
        assert len(incomplete) == 1
        assert incomplete[0] == "https://example.com/p1"


class TestExtractionAuditSummary:
    """Tests for ExtractionAudit.to_summary_dict()."""

    def test_to_summary_dict_basic(self):
        tracker = ExtractionTracker()
        tracker.record_success("https://example.com/p1", 5)
        tracker.record_error("https://example.com/p2", "timeout")

        summary = tracker.build_audit().to_summary_dict()
        assert summary["urls_attempted"] == 2
        assert summary["urls_with_products"] == 1
        assert summary["urls_errored"] == 1
        assert summary["total_products"] == 5
        assert summary["success_rate"] == 50.0
        assert summary["failed_urls"] == ["https://example.com/p2"]

    def test_to_summary_dict_caps_at_50(self):
        tracker = ExtractionTracker()
        for i in range(60):
            tracker.record_error(f"https://example.com/p{i}", "err")

        summary = tracker.build_audit().to_summary_dict()
        assert len(summary["failed_urls"]) == 50

    def test_to_summary_dict_empty(self):
        tracker = ExtractionTracker()
        summary = tracker.build_audit().to_summary_dict()
        assert summary["urls_attempted"] == 0
        assert summary["total_products"] == 0
        assert summary["success_rate"] == 0.0


class TestTagProductsWithSource:
    """Tests for ExtractionTracker.tag_products_with_source()."""

    def test_tags_all_products(self):
        products = [{"title": "A"}, {"title": "B"}]
        result = ExtractionTracker.tag_products_with_source(
            products, "https://example.com/p1"
        )
        assert len(result) == 2
        assert result[0]["_source_url"] == "https://example.com/p1"
        assert result[1]["_source_url"] == "https://example.com/p1"

    def test_tags_empty_list(self):
        result = ExtractionTracker.tag_products_with_source([], "https://example.com/p1")
        assert result == []

    def test_mutates_in_place(self):
        products = [{"title": "A"}]
        ExtractionTracker.tag_products_with_source(products, "https://example.com/p1")
        assert products[0]["_source_url"] == "https://example.com/p1"
