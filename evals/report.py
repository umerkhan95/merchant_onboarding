"""Format evaluation results for terminal output."""

from __future__ import annotations

import json

from evals.models import EvalReport, TierResult


class ReportFormatter:
    """Formats evaluation results for terminal display."""

    @staticmethod
    def format_report(report: EvalReport) -> str:
        """Format a single test case report with all tier results."""
        lines = []

        # Header
        lines.append("┌" + "─" * 78 + "┐")
        lines.append(f"│ Test Case: {report.test_case_name:<63} │")
        lines.append(f"│ URL: {report.url:<70} │")
        lines.append(f"│ Platform: {report.platform:<67} │")
        lines.append("└" + "─" * 78 + "┘")
        lines.append("")

        # Tier results
        for tier in report.tier_results:
            lines.append(ReportFormatter.format_tier(tier))
            lines.append("")

        # Footer with best tier
        best = report.best_tier
        if best:
            avg_score = best.avg_score * 100
            lines.append(f"Best tier: {best.tier_name} (avg score: {avg_score:.1f}%)")
        else:
            lines.append("No successful tier results.")

        return "\n".join(lines)

    @staticmethod
    def format_tier(tier: TierResult) -> str:
        """Format results for a single extraction tier."""
        lines = []

        # Tier header
        lines.append(f"═══ {tier.tier_name.upper()} ═══")

        if tier.error:
            lines.append(f"ERROR: {tier.error}")
            return "\n".join(lines)

        if not tier.product_scores:
            lines.append("No products extracted.")
            return "\n".join(lines)

        # Field scores table
        field_avgs = tier.field_averages

        if field_avgs:
            lines.append("")
            lines.append("┌" + "─" * 15 + "┬" + "─" * 7 + "┬" + "─" * 30 + "┬" + "─" * 30 + "┐")
            lines.append("│ Field          │ Score  │ Expected                      │ Extracted                     │")
            lines.append("├" + "─" * 15 + "┼" + "─" * 7 + "┼" + "─" * 30 + "┼" + "─" * 30 + "┤")

            for field_name in sorted(field_avgs.keys()):
                score = field_avgs[field_name]
                score_pct = f"{score * 100:5.1f}%"

                # Get sample expected/extracted values from first product
                expected_val = ""
                extracted_val = ""
                for ps in tier.product_scores:
                    for fs in ps.field_scores:
                        if fs.field_name == field_name:
                            expected_val = ReportFormatter._truncate(fs.expected or "", 30)
                            extracted_val = ReportFormatter._truncate(fs.extracted or "", 30)
                            break
                    if expected_val:
                        break

                lines.append(f"│ {field_name:<14} │ {score_pct:>6} │ {expected_val:<29} │ {extracted_val:<29} │")

            lines.append("└" + "─" * 15 + "┴" + "─" * 7 + "┴" + "─" * 30 + "┴" + "─" * 30 + "┘")

        # Summary line
        avg_score = tier.avg_score * 100
        summary = (
            f"Products: {tier.products_extracted} extracted, {tier.products_matched} matched | "
            f"Avg: {avg_score:.1f}% | Time: {tier.duration_seconds:.1f}s"
        )
        lines.append("")
        lines.append(summary)

        return "\n".join(lines)

    @staticmethod
    def format_summary(reports: list[EvalReport]) -> str:
        """Format summary table across multiple test cases."""
        if not reports:
            return "No evaluation reports to summarize."

        lines = []
        lines.append("┌" + "─" * 78 + "┐")
        lines.append("│" + " " * 30 + "EVALUATION SUMMARY" + " " * 30 + "│")
        lines.append("└" + "─" * 78 + "┘")
        lines.append("")

        # Table header
        lines.append("┌" + "─" * 25 + "┬" + "─" * 12 + "┬" + "─" * 15 + "┬" + "─" * 8 + "┬" + "─" * 10 + "┐")
        lines.append("│ Site                     │ Platform    │ Best Tier      │ Score   │ Products  │")
        lines.append("├" + "─" * 25 + "┼" + "─" * 12 + "┼" + "─" * 15 + "┼" + "─" * 8 + "┼" + "─" * 10 + "┤")

        total_score = 0.0
        total_count = 0

        for report in reports:
            site_name = ReportFormatter._truncate(report.test_case_name, 25)
            platform = ReportFormatter._truncate(report.platform, 12)

            best = report.best_tier
            if best:
                tier_name = ReportFormatter._truncate(best.tier_name, 15)
                score_pct = f"{best.avg_score * 100:5.1f}%"
                products = f"{best.products_matched}/{best.products_extracted}"

                total_score += best.avg_score
                total_count += 1
            else:
                tier_name = "N/A"
                score_pct = "  N/A"
                products = "0/0"

            lines.append(f"│ {site_name:<24} │ {platform:<11} │ {tier_name:<14} │ {score_pct:>7} │ {products:>9} │")

        lines.append("└" + "─" * 25 + "┴" + "─" * 12 + "┴" + "─" * 15 + "┴" + "─" * 8 + "┴" + "─" * 10 + "┘")

        # Overall average
        if total_count > 0:
            overall_avg = (total_score / total_count) * 100
            lines.append("")
            lines.append(f"Overall average score: {overall_avg:.1f}%")

        return "\n".join(lines)

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """Truncate text to max length with ellipsis."""
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + "..."

    @staticmethod
    def to_json(report: EvalReport) -> str:
        """Convert report to JSON string."""
        data = {
            "test_case_name": report.test_case_name,
            "url": report.url,
            "platform": report.platform,
            "tier_results": [
                {
                    "tier_name": tier.tier_name,
                    "products_extracted": tier.products_extracted,
                    "products_matched": tier.products_matched,
                    "avg_score": tier.avg_score,
                    "field_averages": tier.field_averages,
                    "duration_seconds": tier.duration_seconds,
                    "error": tier.error,
                }
                for tier in report.tier_results
            ],
        }
        if report.best_tier:
            data["best_tier"] = {
                "name": report.best_tier.tier_name,
                "avg_score": report.best_tier.avg_score,
            }
        return json.dumps(data, indent=2)
