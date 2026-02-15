"""Load evaluation test fixtures from JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from evals.models import ExpectedProduct, TestCase

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(path: Path) -> TestCase:
    """Load a single test fixture from a JSON file."""
    data = json.loads(path.read_text())
    products = [ExpectedProduct(**p) for p in data.get("products", [])]
    return TestCase(
        name=data["name"],
        url=data["url"],
        platform=data["platform"],
        products=products,
        min_products=data.get("min_products"),
    )


def load_all_fixtures(directory: Path | None = None) -> list[TestCase]:
    """Load all JSON fixtures from the fixtures directory."""
    fixture_dir = directory or FIXTURES_DIR
    return [load_fixture(p) for p in sorted(fixture_dir.glob("*.json"))]
