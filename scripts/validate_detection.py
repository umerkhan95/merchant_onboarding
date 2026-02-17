"""Validate platform detection works for our WooCommerce test sites.

Usage: python scripts/validate_detection.py
"""

from __future__ import annotations

import asyncio

from app.services.platform_detector import PlatformDetector


async def main():
    detector = PlatformDetector()

    sites = [
        ("https://www.offermanwoodshop.com", "woocommerce"),
        ("https://www.houseofmalt.co.uk", "woocommerce"),
        ("https://www.sawmilldesigns.com", "woocommerce"),
        # Also verify Shopify sites still detect correctly
        ("https://www.allbirds.com", "shopify"),
        ("https://www.skullcandy.com", "shopify"),
    ]

    for url, expected in sites:
        result = await detector.detect(url)
        status = "OK" if result.platform.value == expected else "MISMATCH"
        print(
            f"  {status:8s} {url:45s} → {result.platform.value:15s} "
            f"(confidence: {result.confidence:.0%}, expected: {expected})"
        )
        if result.signals:
            for signal in result.signals[:3]:
                print(f"           signal: {signal}")


if __name__ == "__main__":
    asyncio.run(main())
