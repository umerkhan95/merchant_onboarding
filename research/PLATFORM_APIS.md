# E-commerce Platform Public API Research

## Summary: Which platforms expose public product APIs?

| Platform | Public API? | Endpoint | Auth Required | Products/Request |
|----------|------------|----------|---------------|-----------------|
| **Shopify** | YES | `/products.json` | NO | 250 |
| **WooCommerce** | YES | `/wp-json/wc/store/v1/products` | NO (Store API) | Variable |
| **Magento 2** | YES (default) | `/rest/V1/products` | NO (guest default) | searchCriteria |
| **BigCommerce** | NO | `/v3/catalog/products` | YES (OAuth) | Plan-based |
| **Squarespace** | NO | `/api/v1/commerce/products` | YES (Bearer) | 50 |
| **Wix** | NO | None public | YES (OAuth) | N/A |
| **PrestaShop** | NO | `/api/products` | YES (API key) | Varies |
| **OpenCart** | NO | None (planned) | YES | N/A |
| **Ecwid** | PARTIAL | `/rest/v3/{id}/products` | YES (public token) | Varies |
| **Square Online** | NO | Various | YES (OAuth) | N/A |

## Key Insight

Only 3 platforms offer truly public, unauthenticated product APIs:
1. **Shopify** - Best implementation (Ajax API)
2. **WooCommerce** - Store API (public, customer-facing)
3. **Magento 2** - Guest access enabled by default (admin can disable)

All others require HTML scraping via crawl4ai.

## Platform Detection Methods

| Platform | Detection Method |
|----------|-----------------|
| Shopify | `<meta name="generator" content="Shopify">`, `cdn.shopify.com` in scripts, `X-ShopId` header |
| WooCommerce | `<meta name="generator" content="WordPress">`, `woocommerce` CSS classes, `/wp-content/` paths |
| Magento 2 | `Mage` / `Magento` in HTML comments/headers, `/media/catalog/` paths |
| BigCommerce | `cdn.bigcommerce.com` scripts, "Powered by BigCommerce" footer |
| Squarespace | `squarespace.com` script domains, `<meta name="generator" content="Squarespace">` |
| Wix | `<meta name="generator" content="Wix">`, `wixstatic.com` resources |
| PrestaShop | `/modules/` paths, PrestaShop meta tags |

## Sitemaps

- All e-commerce sites expose `/sitemap.xml` (crucial for product URL discovery)
- Sitemaps include product URLs, `lastmod` dates, change frequency
- Parsing speed: 100-1000+ URLs/sec
- Not rate limited or authenticated
- Shopify's robots.txt does NOT block product sitemaps
