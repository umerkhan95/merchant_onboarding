# Quick Reference: Extraction Reliability Decision Trees

Use these decision trees when designing extraction logic, choosing strategies, or debugging failures.

---

## Decision Tree 1: When Extraction Returns 0 Products

```
EXTRACTION RETURNED 0 PRODUCTS
│
├─ Is the page actually loaded?
│  ├─ NO → HTTP error / timeout / 404
│  │  └─ Return error to merchant: "Your store is unreachable"
│  │
│  └─ YES → Page loaded but no products found
│     │
│     ├─ Is there a product list visible on the page?
│     │  ├─ NO (blank storefront, maintenance mode, etc.)
│     │  │  └─ Ask merchant to verify products exist
│     │  │
│     │  └─ YES → Products visible but extraction failed
│     │     │
│     │     ├─ Was this the first extraction strategy?
│     │     │  ├─ YES → Try next strategy in fallback chain
│     │     │  │  └─ network → schema.org → opengraph → llm
│     │     │  │
│     │     │  └─ NO (already tried fallbacks)
│     │     │     └─ Escalate to manual review + merchant CSV upload
│     │     │
│     │     └─ Is there anti-bot protection?
│     │        ├─ YES (Cloudflare, DataDome detected)
│     │        │  └─ Try specialist proxy service (Scrape.do, ZenRows)
│     │        │
│     │        └─ NO → Extractor bug, investigate logs
```

---

## Decision Tree 2: Which Extraction Strategy to Use

```
Which strategy should I use?
│
├─ Do I know the platform (Shopify, WooCommerce, Magento)?
│  ├─ YES → Try PLATFORM_API first
│  │  └─ /products.json, /wp-json/wc/store/v1/products, /rest/V1/products
│  │
│  └─ NO → Continue below
│
├─ Is this page a JavaScript SPA (React, Vue, Angular)?
│  ├─ YES → Try NETWORK_INTERCEPTION
│  │  └─ Monitor XHR/Fetch calls, capture product JSON
│  │
│  └─ MAYBE → Try SCHEMA_ORG
│     └─ Look for <script type="application/ld+json">
│
├─ Does the page have meta tags (og:title, og:price)?
│  ├─ YES → Try OPENGRAPH
│  │  └─ Extract social media tags
│  │
│  └─ NO → Continue
│
├─ Is the HTML structure consistent and well-formed?
│  ├─ YES → Try CSS_EXTRACTION (with auto-generated schema)
│  │  └─ Fast, no LLM cost
│  │
│  └─ NO → Try LLM_EXTRACTION
│     └─ Universal fallback, handles anything
│
└─ None of the above worked?
   └─ ESCALATE to manual review + merchant CSV upload
```

---

## Decision Tree 3: Should I Escalate to Manual Review?

```
Should I escalate this extraction?
│
├─ Is extraction_product_count == 0?
│  ├─ YES → ESCALATE
│  │
│  └─ NO → Continue
│
├─ Is avg_extraction_confidence < 0.70?
│  ├─ YES → ESCALATE (low quality)
│  │
│  └─ NO → Continue
│
├─ Are any critical fields missing?
│  │ (title, price, url)
│  ├─ YES → ESCALATE
│  │
│  └─ NO → Continue
│
├─ Is there anomaly in extracted data?
│  │ (e.g., prices dropped 50%, product count variance huge)
│  ├─ YES → ESCALATE for human verification
│  │
│  └─ NO → Continue
│
├─ Do we have required permissions?
│  │ (site requires auth, behind paywall, etc.)
│  ├─ NO → ESCALATE (ask merchant for help)
│  │
│  └─ YES → Continue
│
└─ Data quality looks good → INGEST
```

---

## Decision Tree 4: Retry Logic - When & How to Retry

```
Should I retry this request?
│
├─ What was the error?
│  │
│  ├─ HTTP 429 (rate limit)
│  │  └─ YES, retry with exponential backoff + random proxy
│  │
│  ├─ HTTP 403/401 (auth required)
│  │  └─ NO, ask merchant for credentials
│  │
│  ├─ HTTP 404 (not found)
│  │  └─ NO, product URL doesn't exist
│  │
│  ├─ HTTP 500 (server error)
│  │  └─ YES, retry once (server may recover)
│  │
│  ├─ Timeout (page didn't load in 45s)
│  │  └─ YES, retry with 2x longer timeout
│  │
│  ├─ Parse error (HTML unparseable)
│  │  └─ YES, try different extraction strategy
│  │
│  ├─ Network error (DNS, SSL, connection refused)
│  │  └─ YES, retry with proxy
│  │
│  └─ Logic error (our code bug)
│     └─ NO, fix code and redeploy
│
├─ How many times have we retried already?
│  │
│  ├─ 0-2 times → Retry
│  │  └─ Use exponential backoff (2^attempt seconds + jitter)
│  │
│  ├─ 3-5 times → Retry once more with different strategy
│  │  └─ Try proxy rotation or different extractor
│  │
│  └─ 5+ times → GIVE UP
│     └─ Move to dead letter queue
```

---

## Decision Tree 5: When to Use LLM Extraction vs CSS

```
Should I use LLM or CSS extraction?
│
├─ Do I have CSS selectors that work?
│  ├─ YES → Use CSS
│  │  └─ Faster, cheaper, deterministic
│  │
│  └─ NO → Continue
│
├─ Is the page structure consistent?
│  │ (same selectors work on all pages)
│  ├─ YES → Generate CSS selectors with LLM once, cache
│  │  └─ Cost: $0.01 per domain, reuse forever
│  │
│  └─ NO (structure varies, dynamic) → Use LLM
│
├─ Is the page complex/custom?
│  ├─ YES → Use LLM (handles complexity)
│  │
│  └─ NO → Use CSS
│
└─ Quick decision rule:
   │
   ├─ Known platform (Shopify, WC, etc.)?
   │  └─ CSS + template selectors
   │
   ├─ Generic e-commerce layout?
   │  └─ CSS + generic selectors
   │
   └─ Weird/custom/unique?
      └─ LLM extraction
```

---

## Decision Tree 6: Confidence Score Interpretation

```
What does this confidence score mean?
│
├─ 0.90-1.00 (Very High)
│  └─ Trust this field. Ingest directly.
│
├─ 0.80-0.89 (High)
│  └─ Good enough for non-critical fields. Ingest.
│
├─ 0.70-0.79 (Medium)
│  └─ Some doubt. Flag for human review if critical.
│
├─ 0.50-0.69 (Low)
│  └─ Probably wrong. Escalate to manual review.
│
└─ <0.50 (Very Low)
   └─ Almost certainly wrong. Skip or escalate.

Critical field (title, price, url) minimum:
├─ Must have: ≥ 0.85
├─ Nice to have: ≥ 0.70
└─ Not acceptable: < 0.70

Optional field (description, tags) minimum:
├─ Nice to have: ≥ 0.70
└─ Not acceptable: < 0.50
```

---

## Decision Tree 7: Anti-Bot Protection Detection & Handling

```
Is the site protected?
│
├─ Check for Cloudflare
│  ├─ YES (cf_clearance cookie, _cf_* headers, challenge page)
│  │  └─ Options:
│  │     ├─ Use headless browser (crawl4ai with stealth=True)
│  │     ├─ Use specialist service (Scrape.do, ZenRows, Zyte)
│  │     └─ Rotate residential proxies
│  │
│  └─ NO → Continue
│
├─ Check for DataDome
│  ├─ YES (dd_cookie, _dd_* params, challenge JS)
│  │  └─ Options:
│  │     ├─ Use specialist service (Scrape.do recommended)
│  │     └─ NOT easily bypassed open-source
│  │
│  └─ NO → Continue
│
├─ Check for PerimeterX / Imperva
│  ├─ YES (challenge page, window._px object)
│  │  └─ Use specialist service (Zyte, Bright Data)
│  │
│  └─ NO → Continue
│
├─ Check for rate limiting (HTTP 429)
│  ├─ YES → Rotate proxy, add delays, reduce request rate
│  │
│  └─ NO → Probably not protected
│
└─ If unprotected → Standard crawl should work
```

---

## Decision Tree 8: When to Ask Merchant for Help

```
When should I escalate to merchant?
│
├─ Store requires authentication
│  └─ "Please provide temporary admin credentials or a CSV export"
│
├─ Store is behind paywall
│  └─ "Your store requires purchase. Please provide a CSV export or public URL"
│
├─ Store is private (password-protected)
│  └─ "Your store is password-protected. Please provide credentials or CSV"
│
├─ Extraction failed completely
│  └─ "We couldn't extract your products. Options: 1) CSV upload 2) Grant access 3) Wait"
│
├─ Low extraction confidence
│  └─ "We extracted ${count} products but low confidence. Please review:"
│
├─ Store is down / unreachable
│  └─ "Your store is currently unreachable. Please verify it's online"
│
└─ Unusual structure
   └─ "Your store uses unusual HTML. Please provide CSV export or API credentials"
```

---

## Decision Tree 9: Fallback Chain Order

```
What order should I try extraction strategies?
│
├─ First: PLATFORM_API
│  └─ Only works for known platforms, but extremely reliable
│
├─ Second: NETWORK_INTERCEPTION
│  └─ SPAs (React, Vue) use APIs. Capture them.
│  └─ Cost: Free. Speed: Fast.
│
├─ Third: SCHEMA_ORG
│  └─ ~60% of modern sites have JSON-LD. No cost.
│
├─ Fourth: OPENGRAPH
│  └─ ~80% of sites with social sharing. No cost.
│
├─ Fifth: CSS_EXTRACTION (auto-generated)
│  └─ LLM generates selectors once, caches. Cost: ~$0.01 per domain.
│
├─ Sixth: LLM_EXTRACTION
│  └─ Universal fallback. Works on anything.
│  └─ Cost: ~$0.01-$0.10 per page (expensive but reliable).
│
└─ Seventh: MANUAL_ESCALATION
   └─ Ask merchant for CSV or credentials.
```

**Rationale**: Fast → Cheap → Reliable → Expensive → Human

---

## Decision Tree 10: Choosing Between Proxy Services

```
Which proxy service should I use?
│
├─ Budget: $0 / month
│  └─ Use residential proxies with self-rotation (hard to maintain)
│
├─ Budget: $50-100 / month
│  └─ ScraperAPI (simple, good for moderate volume)
│  └─ or Bright Data entry tier
│
├─ Budget: $200-500 / month
│  └─ Scrapy Cloud (if you're already using Scrapy)
│  └─ or Bright Data mid-tier
│  └─ or Zyte
│
├─ Budget: $1000+ / month
│  └─ Bright Data residential proxies (best reliability)
│  └─ or Zyte enterprise
│
├─ Specific need: CloudFlare + DataDome bypass
│  └─ Scrape.do (99.98% success, but expensive per request)
│  └─ or ZenRows
│  └─ or Zyte API
│
└─ Specific need: JavaScript rendering + anti-bot
   └─ Use headless browser + stealth mode (crawl4ai)
   └─ Or use crawl4ai + residential proxies combo
```

---

## Quick Decision: CSS vs LLM Cost Analysis

```
Which is cheaper: CSS or LLM extraction?
│
├─ Scenario 1: Extract 1,000 pages, same domain
│  │
│  ├─ CSS approach:
│  │  └─ Generate schema: 1 LLM call = $0.005
│  │  └─ Extract 1000 pages: $0
│  │  └─ Total: $0.005 (winner)
│  │
│  └─ LLM approach:
│     └─ Extract 1000 pages: 1000 × $0.01 = $10
│     └─ Total: $10
│
├─ Scenario 2: Extract 1 page from 1000 different domains
│  │
│  ├─ CSS approach:
│  │  └─ Generate 1000 schemas: 1000 × $0.005 = $5
│  │  └─ Extract 1 per domain: $0
│  │  └─ Total: $5
│  │
│  └─ LLM approach:
│     └─ Extract 1000 pages: 1000 × $0.01 = $10
│     └─ Total: $10
│
└─ For your use case (many merchants):
   └─ Use CSS first (cached per domain)
   └─ Fall back to LLM only if CSS fails
   └─ Cost: ~$0.01-$0.02 per merchant
```

---

## Implementation Priority Matrix

```
Implement these in order (high-impact first):

CRITICAL (do first):
├─ [ ] Zero-result detection
├─ [ ] Confidence scoring
├─ [ ] Exponential backoff + jitter
└─ [ ] Fallback chain

HIGH IMPACT (do second):
├─ [ ] Network request interception
├─ [ ] Manual escalation protocol
└─ [ ] Dead letter queue

MEDIUM (do third):
├─ [ ] Proxy rotation
├─ [ ] Browser pool optimization
├─ [ ] CSV upload fallback
└─ [ ] Metrics dashboard

NICE TO HAVE (do later):
├─ [ ] Self-healing extraction
├─ [ ] Vision-based extraction
├─ [ ] Alerting rules
└─ [ ] Advanced monitoring
```

---

## When to Escalate vs Retry vs Fail

```
                    ESCALATE   RETRY   INGEST   FAIL
                    --------   -----   ------   ----
Zero products       YES        -       NO       -
Low confidence      YES        -       -        -
HTTP 429            -          YES     -        -
HTTP 401/403        YES        -       -        -
HTTP 404            -          -       -        YES
HTTP 500            -          YES     -        -
Timeout             -          YES     -        -
Parse error         -          YES*    -        -
  (*try alt strategy)
Network error       -          YES     -        -
Data incomplete     YES        -       -        -
Anomalies detected  YES        -       -        -
Everything okay     -          -       YES      -
All retries failed  YES        -       -        -
```

---

## Cost Estimation

```
Cost per merchant extraction (rough):

Base case (1000 products, 1 domain):
├─ Platform API: $0 (free)
├─ Schema.org / OG: $0 (free)
├─ CSS (auto-gen): $0.005 + $0 = $0.005
├─ Network monitor: $0 (free)
└─ Total: < $0.01

Problematic case (no API, needs LLM):
├─ LLM extraction: 5-10 API calls = $0.05-$0.10
└─ Total: $0.05-$0.10

With proxies (site blocks):
├─ Proxy service: ~$0.20 per 100 requests
├─ + LLM: + $0.05-$0.10
└─ Total: $0.25-$0.30

Manual review (escalation):
├─ Human time: ~15 minutes = ~$5-10
├─ Merchant communication: ~5 min = ~$2-3
└─ Total: $7-13

Ideal outcome:
- 95% automated ($0.005-$0.10 each)
- 5% escalation ($7-13 each)
- Blended: ~$0.40-$0.70 per merchant
```

---

## Testing Checklist

**Test these scenarios before going live**:

```
Zero-result handling:
[ ] Extraction returns 0 → escalates
[ ] Fallback chain tried in order
[ ] All fallbacks fail → manual queue

Confidence filtering:
[ ] Low-confidence products flagged
[ ] High-confidence products ingested
[ ] Thresholds enforced correctly

Retry logic:
[ ] Exponential backoff working (1s, 2s, 4s delays)
[ ] Jitter prevents synchronized retries
[ ] Max retries limit respected

Proxy rotation:
[ ] Different IP on each request (if enabled)
[ ] Fallback to new proxy on block

Dead letter queue:
[ ] Failed URLs moved to DLQ after max retries
[ ] Can be replayed via API
[ ] Human can investigate and resolve

Manual review:
[ ] Escalations created with full context
[ ] Merchants notified
[ ] CSV upload accepted and validated

Metrics:
[ ] Success rate calculated correctly
[ ] Confidence scores tracked
[ ] Cost per merchant estimated
```

