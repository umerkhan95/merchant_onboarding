"""CLI for running product extraction evaluations."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from evals.loader import FIXTURES_DIR, load_all_fixtures, load_fixture
from evals.report import ReportFormatter
from evals.runner import EvalRunner


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run product extraction evaluations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--fixture",
        type=str,
        help="Run only one fixture by name (without .json extension)",
    )

    parser.add_argument(
        "--tier",
        type=str,
        action="append",
        dest="tiers",
        help="Run only specific tier(s). Can be repeated. Example: --tier schema_org --tier opengraph",
    )

    parser.add_argument(
        "--all-tiers",
        action="store_true",
        help="Run all 5 extraction tiers (including smart_css and llm). Requires LLM_API_KEY.",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted table",
    )

    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Save current scores as baseline",
    )

    parser.add_argument(
        "--check-regression",
        action="store_true",
        help="Check for regressions vs saved baseline",
    )

    parser.add_argument(
        "--regression-threshold",
        type=float,
        default=0.05,
        help="Max allowed score drop (default: 0.05)",
    )

    parser.add_argument(
        "--allow-regression",
        action="append",
        dest="allowed_regressions",
        help="Allow regression for specific field (site.tier.field)",
    )

    parser.add_argument(
        "--profile",
        action="store_true",
        help="Enable memory profiling (slower)",
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help="Force offline mode (fail if snapshot missing)",
    )

    parser.add_argument(
        "--live",
        action="store_true",
        help="Force live mode (ignore snapshots)",
    )

    # Create subparsers for snapshot command
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    snapshot_parser = subparsers.add_parser("snapshot", help="Capture HTML snapshots")
    snapshot_parser.add_argument(
        "--url",
        required=True,
        help="URL to capture",
    )
    snapshot_parser.add_argument(
        "--output",
        type=str,
        help="Output file path (relative to snapshots dir or absolute)",
    )

    return parser.parse_args()


async def main() -> int:
    """Main CLI entry point."""
    args = parse_args()

    # Set up logging
    log_level = logging.DEBUG if hasattr(args, "verbose") and args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    logger = logging.getLogger(__name__)

    try:
        # Handle snapshot command
        if args.command == "snapshot":
            from pathlib import Path
            from evals.snapshot import capture_snapshot

            output_path = None
            if args.output:
                output_path = Path(args.output)
                if not output_path.is_absolute():
                    # Relative to snapshots dir
                    from evals.snapshot import SNAPSHOTS_DIR
                    output_path = SNAPSHOTS_DIR / output_path

            saved_path = await capture_snapshot(args.url, output_path)
            logger.info("Snapshot saved successfully: %s", saved_path)
            print(f"Snapshot saved: {saved_path}")
            return 0
        # Load fixtures
        if args.fixture:
            fixture_path = FIXTURES_DIR / f"{args.fixture}.json"
            logger.info("Loading fixture: %s", args.fixture)
            if not fixture_path.exists():
                logger.error("Fixture not found: %s", fixture_path)
                return 1
            fixtures = [load_fixture(fixture_path)]
        else:
            logger.info("Loading all fixtures")
            fixtures = load_all_fixtures()

        if not fixtures:
            logger.error("No fixtures loaded")
            return 1

        logger.info("Loaded %d fixture(s)", len(fixtures))

        # Create runner with tier filter
        if args.all_tiers:
            tiers = EvalRunner.ALL_TIERS
        elif args.tiers:
            tiers = args.tiers
        else:
            tiers = None  # Use default

        runner = EvalRunner(
            tiers=tiers,
            profile=args.profile,
            force_offline=args.offline,
            force_live=args.live,
        )

        # Run evaluations
        logger.info("Starting evaluations...")
        reports = await runner.run_all(fixtures)

        if not reports:
            logger.error("No evaluation reports generated")
            return 1

        # Print results
        if args.json:
            # JSON output mode
            for report in reports:
                print(ReportFormatter.to_json(report))
                print()  # Blank line between reports
        else:
            # Formatted table output
            for report in reports:
                print(ReportFormatter.format_report(report))
                print()  # Blank line between reports

            # Summary if multiple reports
            if len(reports) > 1:
                print()
                print(ReportFormatter.format_summary(reports))

        # Save baseline if requested
        if args.save_baseline:
            from evals.baseline import save_baseline
            baseline_path = save_baseline(reports)
            print(f"\nBaseline saved to {baseline_path}")

        # Check regression if requested
        if args.check_regression:
            from evals.baseline import check_regression
            passed, message = check_regression(
                reports,
                threshold=args.regression_threshold,
                allowed_regressions=args.allowed_regressions,
            )
            print(f"\n{message}")
            if not passed:
                return 1  # Exit code 1 for CI

        logger.info("Evaluations complete")
        return 0

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1


def entrypoint():
    """Entry point that calls main and exits with appropriate code."""
    sys.exit(asyncio.run(main()))
