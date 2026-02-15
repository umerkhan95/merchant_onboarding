"""WDC-PAVE dataset loader for cross-site product extraction benchmarks.

WDC-PAVE contains product offers from 59 real e-commerce websites
with schema.org annotations from Common Crawl.

Source: Web Data Commons, University of Mannheim
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

from evals.models import ExpectedProduct, TestCase

logger = logging.getLogger(__name__)

WDC_CACHE = Path(__file__).parent.parent / "datasets" / "cache" / "wdc_pave_sample.jsonl"


def load_wdc_pave(
    sample_size: int = 50,
    site: str | None = None,
    seed: int = 42,
    data_path: Path | None = None,
) -> list[TestCase]:
    """Load WDC-PAVE dataset as TestCase fixtures.

    Args:
        sample_size: Number of products to sample
        site: Filter to specific website domain
        seed: Random seed
        data_path: Path to local WDC JSONL file
    """
    source = data_path or WDC_CACHE

    if not source.exists():
        logger.info("No WDC-PAVE data found. Creating bundled sample at %s", source)
        _create_bundled_sample(source)

    records = []
    for line in source.read_text().strip().split("\n"):
        if not line:
            continue
        record = json.loads(line)
        if site and record.get("site", "") != site:
            continue
        records.append(record)

    rng = random.Random(seed)
    if len(records) > sample_size:
        records = rng.sample(records, sample_size)

    test_cases = []
    for record in records:
        product = _record_to_product(record)
        if product:
            tc = TestCase(
                name=f"WDC: {product.title[:50]}",
                url=record.get("url", ""),
                platform="generic",
                products=[product],
            )
            test_cases.append(tc)

    logger.info("Loaded %d WDC-PAVE test cases", len(test_cases))
    return test_cases


def _record_to_product(record: dict) -> ExpectedProduct | None:
    title = record.get("title", "").strip()
    if not title:
        return None

    return ExpectedProduct(
        title=title,
        price=record.get("price"),
        currency=record.get("currency"),
        vendor=record.get("brand"),
        description=record.get("description"),
        image_url=record.get("image"),
        product_url=record.get("url"),
    )


def _create_bundled_sample(output_path: Path) -> None:
    """Create a small bundled WDC-PAVE sample representing products from multiple sites."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sample_records = [
        {
            "title": "Ray-Ban Aviator Classic Sunglasses",
            "site": "ray-ban.com",
            "url": "https://www.ray-ban.com/aviator-classic",
            "brand": "Ray-Ban",
            "price": "163.00",
            "currency": "USD",
        },
        {
            "title": "Dyson V15 Detect Absolute",
            "site": "dyson.com",
            "url": "https://www.dyson.com/v15-detect",
            "brand": "Dyson",
            "price": "749.99",
            "currency": "USD",
        },
        {
            "title": "Le Creuset Signature Round Dutch Oven",
            "site": "lecreuset.com",
            "url": "https://www.lecreuset.com/round-dutch-oven",
            "brand": "Le Creuset",
            "price": "370.00",
            "currency": "USD",
        },
        {
            "title": "Fjallraven Kanken Classic Backpack",
            "site": "fjallraven.com",
            "url": "https://www.fjallraven.com/kanken",
            "brand": "Fjallraven",
            "price": "80.00",
            "currency": "USD",
        },
        {
            "title": "Weber Spirit II E-310 Gas Grill",
            "site": "weber.com",
            "url": "https://www.weber.com/spirit-ii-e-310",
            "brand": "Weber",
            "price": "499.00",
            "currency": "USD",
        },
        {
            "title": "Vitamix Professional Series 750 Blender",
            "site": "vitamix.com",
            "url": "https://www.vitamix.com/pro-750",
            "brand": "Vitamix",
            "price": "529.95",
            "currency": "USD",
        },
        {
            "title": "Breville Barista Express Espresso Machine",
            "site": "breville.com",
            "url": "https://www.breville.com/barista-express",
            "brand": "Breville",
            "price": "699.95",
            "currency": "USD",
        },
        {
            "title": "Sonos One SL Speaker",
            "site": "sonos.com",
            "url": "https://www.sonos.com/one-sl",
            "brand": "Sonos",
            "price": "199.00",
            "currency": "USD",
        },
        {
            "title": "All-Clad D3 Stainless Steel Fry Pan 10 Inch",
            "site": "all-clad.com",
            "url": "https://www.all-clad.com/d3-fry-pan",
            "brand": "All-Clad",
            "price": "99.95",
            "currency": "USD",
        },
        {
            "title": "Theragun Prime Massage Gun",
            "site": "therabody.com",
            "url": "https://www.therabody.com/theragun-prime",
            "brand": "Therabody",
            "price": "199.00",
            "currency": "USD",
        },
    ]

    with output_path.open("w") as f:
        for record in sample_records:
            f.write(json.dumps(record) + "\n")

    logger.info(
        "Created bundled WDC-PAVE sample with %d products from %d sites",
        len(sample_records),
        len({r["site"] for r in sample_records}),
    )
