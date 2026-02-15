"""Historical score tracking for eval runs."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from evals.models import EvalReport

logger = logging.getLogger(__name__)

HISTORY_DIR = Path(__file__).parent / "history"
HISTORY_FILE = HISTORY_DIR / "scores.jsonl"


def save_run(reports: list[EvalReport]) -> None:
    """Append current eval run to history file (JSONL format)."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    git_sha = _get_git_sha()
    branch = _get_git_branch()

    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "branch": branch,
        "scores": {},
    }

    for report in reports:
        site_scores = {}
        for tier in report.tier_results:
            if tier.error:
                continue
            site_scores[tier.tier_name] = {
                "avg_score": round(tier.avg_score, 4),
                "overall_score": round(tier.overall_score, 4),
                "products_extracted": tier.products_extracted,
                "completeness": round(tier.completeness_score, 4),
                "duration": round(tier.duration_seconds, 2),
            }
        entry["scores"][report.test_case_name] = site_scores

    with HISTORY_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")

    logger.info("Saved eval run to history (%s)", git_sha[:8] if git_sha else "no-git")


def load_history(last_n: int | None = None) -> list[dict]:
    """Load history entries from JSONL file.

    Args:
        last_n: Only return the last N entries. None for all.
    """
    if not HISTORY_FILE.exists():
        return []

    entries = []
    for line in HISTORY_FILE.read_text().strip().split("\n"):
        if line:
            entries.append(json.loads(line))

    if last_n is not None:
        entries = entries[-last_n:]

    return entries


def format_history(entries: list[dict]) -> str:
    """Format history entries as a readable table."""
    if not entries:
        return "No history entries found."

    lines = []
    lines.append("┌" + "─" * 78 + "┐")
    lines.append("│" + " " * 28 + "EVALUATION HISTORY" + " " * 32 + "│")
    lines.append("└" + "─" * 78 + "┘")
    lines.append("")

    # Table header
    lines.append(f"{'Run':<4} {'Timestamp':<20} {'SHA':<10} {'Branch':<15} {'Sites':<6} {'Avg Score':<10}")
    lines.append("─" * 70)

    for i, entry in enumerate(entries, 1):
        ts = entry.get("timestamp", "")[:19]
        sha = entry.get("git_sha", "")[:8] or "unknown"
        branch = entry.get("branch", "unknown")[:15]
        scores = entry.get("scores", {})
        num_sites = len(scores)

        # Calculate average overall score across all sites and tiers
        all_scores = []
        for site_scores in scores.values():
            for tier_scores in site_scores.values():
                if isinstance(tier_scores, dict) and "overall_score" in tier_scores:
                    all_scores.append(tier_scores["overall_score"])

        avg = f"{sum(all_scores) / len(all_scores) * 100:.1f}%" if all_scores else "N/A"

        lines.append(f"{i:<4} {ts:<20} {sha:<10} {branch:<15} {num_sites:<6} {avg:<10}")

    return "\n".join(lines)


def format_trend(entries: list[dict], site: str | None = None, tier: str | None = None) -> str:
    """Format an ASCII trend chart for a specific site/tier combination.

    Args:
        entries: History entries
        site: Filter to specific site. If None, uses average across all.
        tier: Filter to specific tier. If None, uses best tier per site.
    """
    if not entries:
        return "No history data for trend chart."

    # Extract scores per entry
    data_points = []
    for entry in entries:
        scores = entry.get("scores", {})
        sha = entry.get("git_sha", "")[:6] or "?"

        entry_scores = []
        for site_name, site_scores in scores.items():
            if site and site_name != site:
                continue
            for tier_name, tier_scores in site_scores.items():
                if tier and tier_name != tier:
                    continue
                if isinstance(tier_scores, dict) and "overall_score" in tier_scores:
                    entry_scores.append(tier_scores["overall_score"])

        if entry_scores:
            data_points.append((sha, sum(entry_scores) / len(entry_scores)))

    if not data_points:
        return "No matching data points for trend chart."

    # ASCII chart
    title = "Score Trend"
    if site:
        title += f" ({site})"
    if tier:
        title += f" [{tier}]"

    lines = [title, ""]

    # Scale: 0-100%
    chart_height = 10
    chart_width = min(len(data_points), 40)

    # Sample data if too many points
    if len(data_points) > chart_width:
        step = len(data_points) / chart_width
        sampled = [data_points[int(i * step)] for i in range(chart_width)]
    else:
        sampled = data_points

    for row in range(chart_height, -1, -1):
        threshold = row / chart_height
        label = f"{int(threshold * 100):>3}% │"
        bar = ""
        for _, score in sampled:
            if score >= threshold:
                bar += "██"
            else:
                bar += "  "
        lines.append(f"{label}{bar}")

    lines.append("     └" + "──" * len(sampled))

    # X-axis labels (SHAs)
    label_line = "      "
    for sha, _ in sampled[:20]:  # Only first 20 labels
        label_line += f"{sha:<2}"
    lines.append(label_line)

    return "\n".join(lines)


def _get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _get_git_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""
