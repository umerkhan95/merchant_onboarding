"""MAVE dataset loader for product extraction benchmarks.

MAVE (Multi-source Attribute Value Extraction) contains 2.2M Amazon products
with 3M attribute-value annotations across 1,257 categories.

Source: Google Research, 2022
Available on: Hugging Face (mave-benchmark)
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

from evals.models import ExpectedProduct, TestCase

logger = logging.getLogger(__name__)

# Local cache directory for downloaded data
CACHE_DIR = Path(__file__).parent.parent / "datasets" / "cache"
MAVE_CACHE = CACHE_DIR / "mave_sample.jsonl"


def load_mave(
    sample_size: int = 100,
    category: str | None = None,
    seed: int = 42,
    data_path: Path | None = None,
) -> list[TestCase]:
    """Load MAVE dataset as TestCase fixtures.

    Args:
        sample_size: Number of products to sample (default 100)
        category: Filter to specific category (e.g., "Clothing")
        seed: Random seed for reproducible sampling
        data_path: Path to local MAVE JSONL file. If None, uses cached or bundled sample.

    Returns:
        List of TestCase objects, one per product (each with 1 expected product).
    """
    source = data_path or MAVE_CACHE

    if not source.exists():
        # Create a bundled sample for offline use
        logger.info("No MAVE data found. Creating bundled sample at %s", source)
        _create_bundled_sample(source)

    # Load and parse
    records = []
    for line in source.read_text().strip().split("\n"):
        if not line:
            continue
        record = json.loads(line)

        # Filter by category if specified
        if category and record.get("category", "") != category:
            continue

        records.append(record)

    # Sample
    rng = random.Random(seed)
    if len(records) > sample_size:
        records = rng.sample(records, sample_size)

    # Convert to TestCase format
    test_cases = []
    for record in records:
        product = _record_to_product(record)
        if product:
            tc = TestCase(
                name=f"MAVE: {product.title[:50]}",
                url=record.get("url", "https://www.amazon.com"),
                platform="generic",
                products=[product],
            )
            test_cases.append(tc)

    logger.info("Loaded %d MAVE test cases (sample=%d, category=%s)", len(test_cases), sample_size, category)
    return test_cases


def _record_to_product(record: dict) -> ExpectedProduct | None:
    """Convert a MAVE record to ExpectedProduct."""
    title = record.get("title", "").strip()
    if not title:
        return None

    # Extract known attributes
    attrs = {}
    for attr in record.get("attributes", []):
        key = attr.get("key", "").lower()
        value = attr.get("value", "")
        if key and value:
            attrs[key] = value

    return ExpectedProduct(
        title=title,
        price=attrs.get("price") or record.get("price"),
        vendor=attrs.get("brand") or record.get("brand"),
        description=record.get("description"),
        product_type=record.get("category"),
    )


def _create_bundled_sample(output_path: Path) -> None:
    """Create a small bundled sample for offline use.

    This provides a minimal dataset that works without downloading anything.
    For the full dataset, download from Hugging Face and pass via data_path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Bundled sample — 20 representative Amazon products across categories
    sample_records = [
        {
            "title": "Levi's Men's 501 Original Fit Jeans",
            "category": "Clothing",
            "brand": "Levi's",
            "price": "59.50",
            "attributes": [{"key": "brand", "value": "Levi's"}, {"key": "material", "value": "Cotton"}],
        },
        {
            "title": "Apple AirPods Pro (2nd Generation)",
            "category": "Electronics",
            "brand": "Apple",
            "price": "249.00",
            "attributes": [{"key": "brand", "value": "Apple"}, {"key": "connectivity", "value": "Bluetooth"}],
        },
        {
            "title": "Instant Pot Duo 7-in-1 Electric Pressure Cooker",
            "category": "Kitchen",
            "brand": "Instant Pot",
            "price": "89.95",
            "attributes": [{"key": "brand", "value": "Instant Pot"}, {"key": "capacity", "value": "6 Quart"}],
        },
        {
            "title": "Neutrogena Hydro Boost Water Gel",
            "category": "Beauty",
            "brand": "Neutrogena",
            "price": "19.97",
            "attributes": [{"key": "brand", "value": "Neutrogena"}, {"key": "skin_type", "value": "Dry"}],
        },
        {
            "title": "YETI Rambler 20 oz Tumbler",
            "category": "Sports",
            "brand": "YETI",
            "price": "35.00",
            "attributes": [
                {"key": "brand", "value": "YETI"},
                {"key": "material", "value": "Stainless Steel"},
            ],
        },
        {
            "title": "Bose QuietComfort 45 Headphones",
            "category": "Electronics",
            "brand": "Bose",
            "price": "329.00",
            "attributes": [{"key": "brand", "value": "Bose"}, {"key": "type", "value": "Over-Ear"}],
        },
        {
            "title": "Crocs Classic Clog",
            "category": "Shoes",
            "brand": "Crocs",
            "price": "49.99",
            "attributes": [{"key": "brand", "value": "Crocs"}, {"key": "material", "value": "Croslite"}],
        },
        {
            "title": "Stanley Classic Legendary Bottle 1.5 Qt",
            "category": "Sports",
            "brand": "Stanley",
            "price": "40.00",
            "attributes": [{"key": "brand", "value": "Stanley"}, {"key": "capacity", "value": "1.5 Qt"}],
        },
        {
            "title": "CeraVe Moisturizing Cream",
            "category": "Beauty",
            "brand": "CeraVe",
            "price": "16.08",
            "attributes": [{"key": "brand", "value": "CeraVe"}, {"key": "size", "value": "19 oz"}],
        },
        {
            "title": "Nike Air Force 1 '07",
            "category": "Shoes",
            "brand": "Nike",
            "price": "115.00",
            "attributes": [{"key": "brand", "value": "Nike"}, {"key": "material", "value": "Leather"}],
        },
        {
            "title": "KitchenAid Classic Series 4.5 Quart Stand Mixer",
            "category": "Kitchen",
            "brand": "KitchenAid",
            "price": "279.99",
            "attributes": [{"key": "brand", "value": "KitchenAid"}, {"key": "power", "value": "275 watts"}],
        },
        {
            "title": "Patagonia Better Sweater Fleece Jacket",
            "category": "Clothing",
            "brand": "Patagonia",
            "price": "139.00",
            "attributes": [
                {"key": "brand", "value": "Patagonia"},
                {"key": "material", "value": "Polyester Fleece"},
            ],
        },
        {
            "title": "Samsung Galaxy Buds2 Pro",
            "category": "Electronics",
            "brand": "Samsung",
            "price": "229.99",
            "attributes": [{"key": "brand", "value": "Samsung"}, {"key": "noise_cancelling", "value": "Active"}],
        },
        {
            "title": "Osprey Daylite Plus Daypack",
            "category": "Sports",
            "brand": "Osprey",
            "price": "65.00",
            "attributes": [{"key": "brand", "value": "Osprey"}, {"key": "volume", "value": "20L"}],
        },
        {
            "title": "The Ordinary Niacinamide 10% + Zinc 1%",
            "category": "Beauty",
            "brand": "The Ordinary",
            "price": "5.90",
            "attributes": [{"key": "brand", "value": "The Ordinary"}, {"key": "concern", "value": "Blemishes"}],
        },
        {
            "title": "Lodge Cast Iron Skillet 10.25 Inch",
            "category": "Kitchen",
            "brand": "Lodge",
            "price": "19.90",
            "attributes": [{"key": "brand", "value": "Lodge"}, {"key": "material", "value": "Cast Iron"}],
        },
        {
            "title": "New Balance 574 Core Sneaker",
            "category": "Shoes",
            "brand": "New Balance",
            "price": "89.99",
            "attributes": [{"key": "brand", "value": "New Balance"}, {"key": "style", "value": "Athletic"}],
        },
        {
            "title": "Carhartt Men's Loose Fit Washed Duck Flannel-Lined Active Jacket",
            "category": "Clothing",
            "brand": "Carhartt",
            "price": "99.99",
            "attributes": [{"key": "brand", "value": "Carhartt"}, {"key": "material", "value": "Cotton Duck"}],
        },
        {
            "title": "Kindle Paperwhite (16 GB)",
            "category": "Electronics",
            "brand": "Amazon",
            "price": "149.99",
            "attributes": [{"key": "brand", "value": "Amazon"}, {"key": "display", "value": "6.8 inch"}],
        },
        {
            "title": "Hydro Flask Wide Mouth 32 oz",
            "category": "Sports",
            "brand": "Hydro Flask",
            "price": "44.95",
            "attributes": [{"key": "brand", "value": "Hydro Flask"}, {"key": "insulation", "value": "TempShield"}],
        },
    ]

    with output_path.open("w") as f:
        for record in sample_records:
            f.write(json.dumps(record) + "\n")

    logger.info("Created bundled MAVE sample with %d products", len(sample_records))
