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

    return parser.parse_args()


async def main() -> int:
    """Main CLI entry point."""
    args = parse_args()

    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    logger = logging.getLogger(__name__)

    try:
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
        runner = EvalRunner(tiers=args.tiers)

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
