"""Fetch product data from working WooCommerce sites and build eval fixtures.

Usage: python scripts/build_wc_fixtures.py
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

SITES = [
    {
        "name": "Offerman Woodshop",
        "url": "https://www.offermanwoodshop.com",
    },
    {
        "name": "House of Malt",
        "url": "https://www.houseofmalt.co.uk",
    },
    {
        "name": "Sawmill Designs",
        "url": "https://www.sawmilldesigns.com",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def fetch_all_products(client: httpx.AsyncClient, base_url: str) -> list[dict]:
    """Fetch all products via WooCommerce Store API with pagination."""
    all_products = []
    page = 1
    per_page = 100

    while True:
        url = f"{base_url.rstrip('/')}/wp-json/wc/store/v1/products?per_page={per_page}&page={page}"
        resp = await client.get(url, headers=HEADERS, follow_redirects=True)
        if resp.status_code != 200:
            break
        data = resp.json()
        if not isinstance(data, list) or not data:
            break
        all_products.extend(data)
        if len(data) < per_page:
            break
        page += 1

    return all_products


def flatten_wc_product(product: dict) -> dict:
    """Flatten WC Store API product into eval-compatible format."""
    flat = {}

    if product.get("name"):
        flat["title"] = product["name"]
    if product.get("sku"):
        flat["sku"] = product["sku"]
    if product.get("permalink"):
        flat["product_url"] = product["permalink"]

    # Price: stored as integer cents, need to convert
    prices = product.get("prices", {})
    if prices.get("price"):
        minor_unit = prices.get("currency_minor_unit", 2)
        raw_price = int(prices["price"])
        flat["price"] = f"{raw_price / (10 ** minor_unit):.2f}"
    if prices.get("currency_code"):
        flat["currency"] = prices["currency_code"]

    # Image
    images = product.get("images", [])
    if images:
        flat["image_url"] = images[0].get("src", "")

    # Stock
    flat["in_stock"] = product.get("is_in_stock", False)

    # Vendor from brand attribute
    brands = product.get("brands", [])
    if brands:
        flat["vendor"] = brands[0].get("name", "")
    else:
        # Try attributes
        for attr in product.get("attributes", []):
            if attr.get("name", "").lower() in ("brand", "vendor", "manufacturer"):
                terms = attr.get("terms", [])
                if terms:
                    flat["vendor"] = terms[0].get("name", "")
                    break

    # Categories
    categories = product.get("categories", [])
    if categories:
        flat["product_type"] = categories[0].get("name", "")

    return flat


async def main():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for site in SITES:
            print(f"\n{'='*70}")
            print(f"Fetching: {site['name']} ({site['url']})")
            print(f"{'='*70}")

            products = await fetch_all_products(client, site["url"])
            print(f"Total products: {len(products)}")

            if not products:
                print("  SKIP - no products")
                continue

            # Build fixture with 5 sample products
            sample_products = []
            for p in products[:5]:
                flat = flatten_wc_product(p)
                print(f"  Product: {flat.get('title', '?')}")
                print(f"    Price: {flat.get('price', '?')} {flat.get('currency', '?')}")
                print(f"    SKU: {flat.get('sku', 'N/A')}")
                print(f"    In Stock: {flat.get('in_stock', '?')}")
                print(f"    URL: {flat.get('product_url', '?')}")
                print(f"    Image: {flat.get('image_url', '?')[:80]}...")
                sample_products.append(flat)

            # Create fixture JSON
            fixture = {
                "name": site["name"],
                "url": site["url"],
                "platform": "woocommerce",
                "min_products": min(len(products), 20),
                "products": sample_products,
            }

            # Save fixture
            slug = site["name"].lower().replace(" ", "_").replace("'", "")
            filename = f"evals/fixtures/{slug}.json"
            with open(filename, "w") as f:
                json.dump(fixture, f, indent=2)
            print(f"\n  Fixture saved: {filename}")

            # Also dump raw product structure for first product
            print(f"\n  Raw WC Store API response fields: {list(products[0].keys())}")


if __name__ == "__main__":
    asyncio.run(main())
