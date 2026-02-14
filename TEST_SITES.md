# Test Sites for Pipeline Validation

These are real, live e-commerce stores used to validate each extraction path.

## 1. Shopify — Allbirds
- **URL**: https://www.allbirds.com
- **API**: https://www.allbirds.com/products.json (public, no auth)
- **Tier**: 1 (API-first)
- **Detection**: `cdn.shopify.com` scripts, meta generator `Shopify`
- **Products**: 500+ with variants, images, pricing
- **Verified**: `/products.json` returns `application/json` with full product catalog

## 2. WooCommerce — Ahmad Tea
- **URL**: https://www.ahmadtea.com
- **API**: WooCommerce Store API NOT exposed (no `wc` namespace in `/wp-json/`)
- **Tier**: 2 (Sitemap + CSS scraping)
- **Detection**: `PHPSESSID` cookie, WordPress meta, WooCommerce CSS classes
- **Products**: 100+ teas and accessories
- **Note**: Falls back to sitemap parsing + CSS extraction (good test for Tier 2 path)

## 3. Magento 2 — Magebit Demo
- **URL**: https://magento2-demo.magebit.com
- **API**: `/rest/V1/products` (may require guest access enabled)
- **Tier**: 1 or 2 (API attempt → CSS fallback)
- **Detection**: Magento HTML structure, `/media/catalog/` paths, Luma theme
- **Products**: 50+ demo products
- **Note**: Behind Cloudflare, good test for stealth mode

## 4. BigCommerce — Iconic Electronics Demo
- **URL**: https://iconic-electronics-demo.mybigcommerce.com
- **API**: None public (BigCommerce requires OAuth)
- **Tier**: 2 (Sitemap + CSS scraping)
- **Detection**: `<meta name='platform' content='bigcommerce.stencil'/>`, `cdn.bigcommerce.com`
- **Products**: 50+ electronics
- **Note**: Must use HTML scraping, Stencil theme

## 5. Custom Platform + Anti-Bot — Etsy
- **URL**: https://www.etsy.com
- **API**: None public
- **Tier**: 3 (Schema.org JSON-LD + OpenGraph + CSS heuristics)
- **Detection**: No known platform markers, DataDome anti-bot protection
- **Products**: Millions (marketplace)
- **Note**: Returns 403 from basic curl — tests circuit breaker, anti-bot handling, stealth mode. Has rich Schema.org JSON-LD markup when rendered in browser.

## Test Matrix

| Site | Platform | Tier | API? | Sitemap? | Anti-Bot? | Tests |
|------|----------|------|------|----------|-----------|-------|
| allbirds.com | Shopify | 1 | YES | YES | No | API extraction, pagination |
| ahmadtea.com | WooCommerce | 2 | NO | YES | No | Sitemap parsing, CSS extraction |
| magento2-demo.magebit.com | Magento 2 | 1/2 | Maybe | YES | Cloudflare | API probe, CSS fallback |
| iconic-electronics-demo.mybigcommerce.com | BigCommerce | 2 | NO | NO | No | Platform detection, CSS extraction |
| etsy.com | Custom | 3 | NO | YES | DataDome | Circuit breaker, anti-bot, Schema.org |
