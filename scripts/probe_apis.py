"""Probe real WooCommerce and Magento sites for working API endpoints.

Usage: python scripts/probe_apis.py
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

# Real WooCommerce sites (confirmed via BuiltWith/Wappalyzer)
WC_SITES = [
    "https://sodashi.com.au",
    "https://www.offermanwoodshop.com",
    "https://rootscience.com",
    "https://www.thecoolhunter.net",
    "https://jfrench.co.nz",
    "https://www.daelmans.com",
    "https://www.henryjsocks.com",
    "https://www.nutribullet.com",
    "https://www.manscaped.com",
    "https://www.clickmill.co",
    "https://www.underarmour.com",
    "https://www.bluecrate.com",
    "https://www.weber.com",
    "https://www.thenorthface.com",
    "https://www.overstock.com",
    "https://www.ernstbenz.com",
    "https://www.muji.us",
    "https://www.newbalance.com",
    "https://store.spectator.co.uk",
    "https://www.worthpoint.com",
    "https://www.bluestarcoffeeroasters.com",
    "https://www.wildsouls.com.au",
    "https://www.magna-tiles.com",
    "https://www.houseofmalt.co.uk",
    "https://www.sawmilldesigns.com",
]

# Real Magento 2 sites (confirmed)
MAGENTO_SITES = [
    "https://www.hellyhansen.com",
    "https://www.shoebacca.com",
    "https://www.catfootwear.com",
    "https://www.niod.com",
    "https://www.jackjones.com",
    "https://www.sigma-global.com",
    "https://www.landrover.com",
    "https://www.coca-colastore.com",
    "https://www.olympus.com.au",
    "https://www.paulsmith.com",
    "https://www.grfriedrich.com",
    "https://www.liebherr.com",
    "https://www.grainger.com",
    "https://www.hp.com",
    "https://www.monin.com",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def probe_woocommerce(client: httpx.AsyncClient, base_url: str) -> dict:
    """Probe a WooCommerce Store API endpoint."""
    url = f"{base_url.rstrip('/')}/wp-json/wc/store/v1/products?per_page=5"
    try:
        resp = await client.get(url, headers=HEADERS, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return {
                    "url": base_url,
                    "status": "OK",
                    "product_count": len(data),
                    "fields": list(data[0].keys()),
                    "sample": data[0],
                }
        return {"url": base_url, "status": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"url": base_url, "status": f"ERROR: {type(e).__name__}"}


async def probe_magento(client: httpx.AsyncClient, base_url: str) -> dict:
    """Probe a Magento 2 REST API endpoint."""
    url = f"{base_url.rstrip('/')}/rest/V1/products?searchCriteria[pageSize]=5&searchCriteria[currentPage]=1"
    try:
        resp = await client.get(url, headers=HEADERS, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            if items:
                return {
                    "url": base_url,
                    "status": "OK",
                    "total_count": data.get("total_count", 0),
                    "sample_count": len(items),
                    "fields": list(items[0].keys()),
                    "sample": items[0],
                }
        return {"url": base_url, "status": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"url": base_url, "status": f"ERROR: {type(e).__name__}"}


async def main():
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        print("=" * 70)
        print("WOOCOMMERCE STORE API PROBE")
        print("=" * 70)

        wc_tasks = [probe_woocommerce(client, site) for site in WC_SITES]
        wc_results = await asyncio.gather(*wc_tasks, return_exceptions=True)

        wc_working = []
        for result in wc_results:
            if isinstance(result, Exception):
                continue
            if result.get("status") == "OK":
                print(f"  OK   {result['url']}: {result['product_count']} products")
                wc_working.append(result)
            else:
                print(f"  FAIL {result['url']}: {result['status']}")

        print(f"\n  Working: {len(wc_working)}/{len(WC_SITES)}")

        print("\n" + "=" * 70)
        print("MAGENTO 2 REST API PROBE")
        print("=" * 70)

        mg_tasks = [probe_magento(client, site) for site in MAGENTO_SITES]
        mg_results = await asyncio.gather(*mg_tasks, return_exceptions=True)

        mg_working = []
        for result in mg_results:
            if isinstance(result, Exception):
                continue
            if result.get("status") == "OK":
                print(f"  OK   {result['url']}: {result['total_count']} total, {result['sample_count']} sampled")
                mg_working.append(result)
            else:
                print(f"  FAIL {result['url']}: {result['status']}")

        print(f"\n  Working: {len(mg_working)}/{len(MAGENTO_SITES)}")

        # Dump working sample data
        for result in wc_working[:3]:
            print(f"\n{'='*70}")
            print(f"SAMPLE: WooCommerce — {result['url']}")
            print(f"Fields: {result['fields']}")
            print(json.dumps(result["sample"], indent=2, default=str)[:3000])

        for result in mg_working[:3]:
            print(f"\n{'='*70}")
            print(f"SAMPLE: Magento — {result['url']}")
            print(f"Fields: {result['fields']}")
            print(json.dumps(result["sample"], indent=2, default=str)[:3000])


if __name__ == "__main__":
    asyncio.run(main())
