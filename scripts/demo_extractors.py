"""Demo script showing how to use the new extractors.

Run with: python demo_extractors.py
"""

from __future__ import annotations

import asyncio

from app.extractors.css_extractor import CSSExtractor
from app.extractors.opengraph_extractor import OpenGraphExtractor
from app.extractors.schema_org_extractor import SchemaOrgExtractor
from app.extractors.schemas.bigcommerce import BIGCOMMERCE_SCHEMA
from app.extractors.schemas.generic import GENERIC_SCHEMA
from app.extractors.schemas.shopify import SHOPIFY_SCHEMA
from app.extractors.schemas.woocommerce import WOOCOMMERCE_SCHEMA


async def demo_schema_org_extractor():
    """Demo Schema.org JSON-LD extraction."""
    print("\n=== Schema.org Extractor Demo ===")
    extractor = SchemaOrgExtractor()

    # Example: Extract from a page with JSON-LD structured data
    url = "https://example.com/product"
    print(f"Extracting from: {url}")

    results = await extractor.extract(url)
    print(f"Found {len(results)} Product(s)")

    for i, product in enumerate(results, 1):
        print(f"\nProduct {i}:")
        print(f"  Name: {product.get('name')}")
        print(f"  Description: {product.get('description', 'N/A')[:50]}...")
        print(f"  SKU: {product.get('sku', 'N/A')}")
        if "offers" in product:
            print(f"  Price: {product['offers'].get('priceCurrency')} {product['offers'].get('price')}")


async def demo_opengraph_extractor():
    """Demo OpenGraph meta tags extraction."""
    print("\n=== OpenGraph Extractor Demo ===")
    extractor = OpenGraphExtractor()

    url = "https://example.com/product"
    print(f"Extracting from: {url}")

    results = await extractor.extract(url)
    if results:
        og_data = results[0]
        print(f"\nFound {len(og_data)} OpenGraph tags:")
        for key, value in og_data.items():
            print(f"  {key}: {value}")
    else:
        print("No OpenGraph tags found")


async def demo_css_extractor():
    """Demo CSS-based extraction with different schemas."""
    print("\n=== CSS Extractor Demo ===")

    # Demo with Shopify schema
    print("\n--- Shopify Schema ---")
    shopify_extractor = CSSExtractor(SHOPIFY_SCHEMA)
    url = "https://example-store.myshopify.com/products/example"
    print(f"Extracting from: {url}")
    results = await shopify_extractor.extract(url)
    print(f"Found {len(results)} product(s)")

    # Demo with WooCommerce schema
    print("\n--- WooCommerce Schema ---")
    woo_extractor = CSSExtractor(WOOCOMMERCE_SCHEMA)
    url = "https://example.com/shop/product/example"
    print(f"Extracting from: {url}")
    results = await woo_extractor.extract(url)
    print(f"Found {len(results)} product(s)")

    # Demo with BigCommerce schema
    print("\n--- BigCommerce Schema ---")
    bc_extractor = CSSExtractor(BIGCOMMERCE_SCHEMA)
    url = "https://example.bigcommerce.com/example-product"
    print(f"Extracting from: {url}")
    results = await bc_extractor.extract(url)
    print(f"Found {len(results)} product(s)")

    # Demo with Generic schema (fallback)
    print("\n--- Generic Schema (Fallback) ---")
    generic_extractor = CSSExtractor(GENERIC_SCHEMA)
    url = "https://example.com/products/unknown-platform"
    print(f"Extracting from: {url}")
    results = await generic_extractor.extract(url)
    print(f"Found {len(results)} product(s)")


async def demo_combined_extraction():
    """Demo using multiple extractors together for robust extraction."""
    print("\n=== Combined Extraction Strategy Demo ===")

    url = "https://example.com/product"
    print(f"Extracting from: {url}")
    print("Using multiple extraction strategies...\n")

    # Try Schema.org first (most structured)
    schema_org = SchemaOrgExtractor()
    schema_results = await schema_org.extract(url)
    print(f"Schema.org: {len(schema_results)} product(s)")

    # Try OpenGraph (good for basic metadata)
    opengraph = OpenGraphExtractor()
    og_results = await opengraph.extract(url)
    print(f"OpenGraph: {len(og_results)} result(s)")

    # Try CSS extraction as fallback
    generic_css = CSSExtractor(GENERIC_SCHEMA)
    css_results = await generic_css.extract(url)
    print(f"CSS (Generic): {len(css_results)} product(s)")

    print("\nCombined strategy allows fallback when structured data is missing!")


async def main():
    """Run all demos."""
    print("=" * 60)
    print("Product Extractor Demo")
    print("=" * 60)

    # Note: These will fail with real URLs since they're examples
    # In production, replace with actual product URLs

    print("\nThis is a demo showing the extractor interfaces.")
    print("Replace example URLs with real product pages to test extraction.\n")

    # Uncomment to run actual demos (will fail with example URLs)
    # await demo_schema_org_extractor()
    # await demo_opengraph_extractor()
    # await demo_css_extractor()
    # await demo_combined_extraction()

    print("\n" + "=" * 60)
    print("Available Extractors:")
    print("=" * 60)
    print("\n1. SchemaOrgExtractor - Extracts JSON-LD structured data")
    print("2. OpenGraphExtractor - Extracts OpenGraph meta tags")
    print("3. CSSExtractor - Extracts using CSS selectors with platform schemas:")
    print("   - SHOPIFY_SCHEMA")
    print("   - WOOCOMMERCE_SCHEMA")
    print("   - BIGCOMMERCE_SCHEMA")
    print("   - GENERIC_SCHEMA (fallback)")
    print("\nAll extractors return list[dict] with raw data (no normalization)")
    print("All extractors return empty list [] on errors (graceful degradation)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
