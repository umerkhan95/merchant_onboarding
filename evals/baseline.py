"""Baseline score storage and regression detection."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from evals.models import EvalReport

logger = logging.getLogger(__name__)

BASELINES_DIR = Path(__file__).parent / "baselines"
BASELINE_FILE = BASELINES_DIR / "baseline.json"


def save_baseline(reports: list[EvalReport]) -> Path:
    """Save current eval scores as the baseline.

    Returns:
        Path to the saved baseline file
    """
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)

    # Get git SHA if available
    git_sha = ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            git_sha = result.stdout.strip()
    except Exception:
        pass

    baseline = {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "results": {},
    }

    for report in reports:
        site_results = {}
        for tier in report.tier_results:
            if tier.error:
                continue
            site_results[tier.tier_name] = {
                "avg_score": tier.avg_score,
                "products_extracted": tier.products_extracted,
                "products_matched": tier.products_matched,
                "field_averages": tier.field_averages,
            }
        baseline["results"][report.test_case_name] = site_results

    BASELINE_FILE.write_text(json.dumps(baseline, indent=2))
    logger.info("Baseline saved to %s (git: %s)", BASELINE_FILE, git_sha[:8] if git_sha else "unknown")
    return BASELINE_FILE


def load_baseline() -> dict | None:
    """Load the saved baseline. Returns None if no baseline exists."""
    if not BASELINE_FILE.exists():
        return None
    return json.loads(BASELINE_FILE.read_text())


def check_regression(
    reports: list[EvalReport],
    threshold: float = 0.05,
    allowed_regressions: list[str] | None = None,
) -> tuple[bool, str]:
    """Check if current scores have regressed vs baseline.

    Args:
        reports: Current eval reports
        threshold: Max allowed score drop (default 5%)
        allowed_regressions: List of "site.tier.field" patterns to ignore

    Returns:
        Tuple of (passed, message). passed=False means regression detected.
    """
    baseline = load_baseline()
    if baseline is None:
        return True, "No baseline found — skipping regression check. Run with --save-baseline first."

    allowed = set(allowed_regressions or [])
    regressions = []
    improvements = []

    for report in reports:
        site = report.test_case_name
        baseline_site = baseline.get("results", {}).get(site, {})

        for tier in report.tier_results:
            if tier.error:
                continue
            baseline_tier = baseline_site.get(tier.tier_name, {})
            if not baseline_tier:
                continue

            baseline_fields = baseline_tier.get("field_averages", {})
            current_fields = tier.field_averages

            for field, current_score in current_fields.items():
                baseline_score = baseline_fields.get(field)
                if baseline_score is None:
                    continue

                key = f"{site}.{tier.tier_name}.{field}"
                delta = current_score - baseline_score

                if delta < -threshold and key not in allowed:
                    regressions.append(
                        f"  REGRESSION: {key}: {baseline_score:.1%} -> {current_score:.1%} ({delta:+.1%})"
                    )
                elif delta > threshold:
                    improvements.append(
                        f"  IMPROVED: {key}: {baseline_score:.1%} -> {current_score:.1%} ({delta:+.1%})"
                    )

    lines = []
    if improvements:
        lines.append("Improvements:")
        lines.extend(improvements)
    if regressions:
        lines.append("Regressions:")
        lines.extend(regressions)

    if not lines:
        return True, "No significant changes vs baseline."

    message = "\n".join(lines)
    passed = len(regressions) == 0
    return passed, message
