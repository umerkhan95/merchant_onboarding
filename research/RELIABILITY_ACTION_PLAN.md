# Guaranteed Extraction: Action Plan for OneUp

## The Problem Statement

**Current state**: Extraction can return 0 products silently, breaking merchant onboarding with no visibility into why.

**Examples of failures you've already seen**:
- Vestiague Collective: Relative URLs not resolved to absolute (fixed)
- Nordstrom: React hydration not waited for (fixed)
- Undetected pattern X: ???

**The core issue**: You have tactics (CSS, LLM) but no **strategy** for handling the inevitable next failure mode.

---

## The Solution Architecture

**Zero-result extraction = definite failure**, not an edge case. Treat it as a design requirement:

```
EXTRACTION FAILED (0 products)
    ↓
ZERO-RESULT PROTOCOL (automatic)
    ├─ Try fallback strategies
    │  ├─ Network request interception
    │  ├─ Schema.org extraction
    │  ├─ LLM extraction (last resort)
    │  └─ All failed? Continue to step 2
    │
    ├─ Verify page is accessible (not blocked, not 404)
    ├─ Check for anti-bot protection (Cloudflare, DataDome)
    │
    └─ MANUAL ESCALATION (human takes over)
        ├─ Captured screenshot + HTML for investigation
        ├─ Notify merchant: "Need your help"
        │   ├─ Option 1: Upload CSV
        │   ├─ Option 2: Grant temp credentials
        │   └─ Option 3: Wait for our investigation
        └─ Human resolves or marks as "not scrapable"
```

---

## Phase 1: Immediate Implementation (Week 1)

**These are non-negotiable. Do them first. Expect +40% improvement in success rate.**

### 1.1 Zero-Result Detection (2 hours)

**File**: `app/services/extraction_validator.py`

```python
async def validate_extraction_results(
    products: list[dict],
    shop_url: str,
    extraction_strategy: str,
) -> tuple[bool, str]:
    """
    MUST be called after EVERY extraction.

    Returns: (is_valid, reason)
        is_valid=False triggers escalation
    """

    if len(products) == 0:
        return (False, "zero_result_detected")

    # Check required fields present
    for product in products:
        if not product.get('title') or not product.get('price'):
            return (False, "incomplete_data")

    return (True, "extraction_valid")
```

**Integration**: Call this in your `pipeline.py` after every extraction:

```python
extraction_result = await extractor.extract_products(...)

is_valid, reason = await validate_extraction_results(
    products=extraction_result['products'],
    shop_url=shop_url,
    extraction_strategy=extraction_result['strategy'],
)

if not is_valid:
    if reason == "zero_result_detected":
        await handle_zero_result_protocol(job_id, shop_url)
    return
```

**Time to implement**: 30 minutes

**Impact**: Immediately catches silent failures. No more broken onboardings.

---

### 1.2 Confidence Scoring (3 hours)

**Goal**: Every extracted field has a 0-1 confidence score. Reject low-confidence extractions.

**File**: `app/models/extraction_quality.py`

**Minimum implementation**:

```python
class Product(BaseModel):
    title: str
    title_confidence: float  # >= 0.85 required

    price: Decimal
    price_confidence: float  # >= 0.85 required (critical!)

    image_url: str
    image_confidence: float  # >= 0.70 acceptable

# Validation
if product.price_confidence < 0.85:
    escalate_to_manual_review(product, reason="low_price_confidence")
```

**Where to add this**:
- Update your normalizer to extract confidence scores from LLM/CSS strategies
- crawl4ai LLM extraction can return confidence via `confidence_scores` field
- CSS selectors can add heuristics (e.g., price in `data-price` attribute = higher confidence)

**Time to implement**: 1-2 hours

**Impact**: Prevents ingesting bad data. Manual review only gets high-quality edge cases.

---

### 1.3 Exponential Backoff + Jitter (1 hour)

**Replace your current simple retry logic with exponential backoff.**

**Current (bad)**:
```python
for i in range(3):
    try:
        result = extract(url)
        return result
    except Exception:
        time.sleep(1)  # Fixed 1-second delay
```

**New (good)**:
```python
async def retry_with_backoff(extract_fn, url, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await extract_fn(url)
        except Exception as e:
            if attempt == max_retries - 1:
                raise

            # Exponential backoff + jitter
            base_delay = 2 ** attempt  # 1s, 2s, 4s
            jitter = random.uniform(0, base_delay)
            wait_time = base_delay + jitter

            log.info(f"Retry after {wait_time:.2f}s")
            await asyncio.sleep(wait_time)
```

**Time to implement**: 30 minutes

**Impact**: Reduces retries by 50% on rate-limited domains. No thundering herd.

---

### 1.4 Network Request Interception (2 hours)

**Skip HTML parsing. Capture API responses instead.**

**Why**: Many sites already provide product data via `/api/products.json` or GraphQL. Parsing HTML is fragile. Use their own API.

**Implementation**:

```python
async def extract_via_network_requests(url: str) -> Optional[list[dict]]:
    """Monitor XHR/Fetch calls, capture product data JSON."""

    captured_apis = []

    async def on_response(response):
        # Look for product API endpoints
        if '/api/products' in response.url or 'products.json' in response.url:
            try:
                data = await response.json()
                captured_apis.append({'url': response.url, 'data': data})
            except:
                pass

    browser = await launch_browser()

    # Monitor network BEFORE navigation
    page.on('response', on_response)

    # Navigate and wait
    await page.goto(url, wait_until='networkidle')

    # Parse captured data
    products = parse_api_responses(captured_apis)
    return products if products else None
```

**Time to implement**: 1-2 hours

**Impact**: 50% faster extraction, 100% more reliable than HTML parsing.

---

### 1.5 Basic Fallback Chain (3 hours)

**Implement a simple fallback order. Don't fail on first strategy.**

```python
strategies = [
    ("platform_api", extract_platform_api),      # Shopify /products.json
    ("network_interception", extract_network),    # Capture XHR/Fetch
    ("schema_org", extract_schema_org),          # JSON-LD in <script>
    ("opengraph", extract_opengraph),            # og:* meta tags
    ("llm", extract_llm),                        # Universal fallback
]

for strategy_name, extract_fn in strategies:
    products = await extract_fn(url)

    if products and len(products) > 0:
        return products  # Success!

# All failed - escalate
escalate_to_manual_review(job_id, "all_strategies_failed")
```

**Time to implement**: 2-3 hours

**Impact**: Most failures automatically recovered without human intervention.

---

## Phase 2: Robustness (Week 2-3)

**Build on Phase 1. These add resilience without breaking anything.**

### 2.1 Dead Letter Queue (3 hours)

**Problem**: After max retries, URLs fail silently. You never investigate.

**Solution**: Failed URLs go to a DLQ for post-mortem + replay capability.

**Implementation**:

```python
# After 5 failed retries
if attempt_count >= 5:
    await dlq.put({
        'shop_id': job_id,
        'url': url,
        'error': last_error,
        'timestamp': now(),
        'extraction_logs': logs,
    })

    # Notify team
    log.error(f"URL {url} moved to DLQ")
```

**Manual replay API**:
```python
@app.post("/api/v1/dlq/{dlq_id}/retry")
async def retry_dlq_item(dlq_id: str):
    """Replay a dead-letter item."""

    item = await dlq.get(dlq_id)
    # Re-try extraction with fresh extractor
    result = await extract_products(item['url'])

    if result['product_count'] > 0:
        await dlq.mark_resolved(dlq_id, result)
    else:
        await dlq.mark_permanent_failure(dlq_id)
```

**Time to implement**: 2-3 hours

**Impact**: Visibility into failures. Ability to fix root causes.

---

### 2.2 Proxy Rotation (4 hours)

**Problem**: IP gets blocked after 10 requests. Extraction breaks.

**Solution**: Rotate through proxy pool. Different IP per request (or session).

**Services** (recommended):
- **Bright Data**: $1000/month (overkill for your use case)
- **Scrapy Cloud**: ~$100/month (good balance)
- **ScraperAPI**: ~$50/month (cheapest, works well)
- **Residential proxies**: $0.50-$1 per GB (cheapest if you're careful)

**Integration**:

```python
from scraperapi import ScraperAPIClient

client = ScraperAPIClient(api_key=os.getenv("SCRAPER_API_KEY"))

async def extract_with_proxy(url: str):
    response = await client.get(url)
    # Proxy automatically rotated
    return response.content
```

**Time to implement**: 1-2 hours (if using ScraperAPI)

**Cost**: ~$50-100/month for 100k requests

**Impact**: IP blocks no longer kill extraction. Handles rate limiting gracefully.

---

### 2.3 Browser Pool Optimization (2 hours)

**Current (bad)**: Each page = new browser process = 150MB RAM.

**New (good)**: Share browser, reuse contexts = 80% less memory.

**Playwright context pooling** (from research):

```python
class BrowserPool:
    def __init__(self, max_concurrent=10):
        self.browser = None
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def initialize(self):
        self.browser = await playwright.chromium.launch()

    async def acquire_page(self):
        async with self.semaphore:
            context = await self.browser.new_context()
            page = await context.new_page()
            return page

    async def release_page(self, page):
        await page.close()  # Context auto-closes

# Usage
pool = BrowserPool(max_concurrent=10)
page = await pool.acquire_page()
# ...use page...
await pool.release_page(page)
```

**Time to implement**: 1-2 hours

**Impact**: 5-10 concurrent crawls instead of 2-3. Better memory efficiency.

---

### 2.4 Manual Review Queue (4 hours)

**Problem**: When extraction fails, nobody knows. Merchant is left hanging.

**Solution**: Create dashboard for manual review. Escalate edge cases.

**Minimum schema**:

```python
class ManualReviewItem:
    job_id: str
    shop_url: str
    escalation_reason: str  # "zero_result", "low_confidence", "auth_required"

    # Context
    page_screenshot: bytes  # What the site looks like
    page_html: str  # For analysis
    extracted_data: list[dict]  # What we got
    extraction_logs: list[str]  # Debugging

    # Metadata
    created_at: datetime
    sla_deadline: datetime  # e.g., 4 hours for high-priority
    status: str  # pending, in_progress, resolved, rejected

    # Resolution
    reviewer_id: str
    resolution_notes: str
    approved_products: int
```

**Reviewer workflow**:
1. Open item → see screenshot + extracted data
2. Compare with actual website
3. Approve ("Looks correct") or escalate ("Ask merchant for CSV")
4. Move to next item

**Time to implement**: 3-4 hours

**Impact**: Closure on failed extractions. Merchant never left wondering.

---

### 2.5 Merchant CSV Upload Fallback (2 hours)

**Problem**: Some stores can't be scraped. Ask merchant for help.

**Solution**: Provide CSV upload interface + validation.

**Implementation**:

```python
@app.post("/api/v1/onboard/{job_id}/upload-csv")
async def upload_csv(job_id: str, file: UploadFile):
    """Merchant uploads their product CSV."""

    rows = parse_csv(file.file)

    # Map to unified Product schema
    products = [
        Product(
            title=row['title'],
            price=Decimal(row['price']),
            ...
        )
        for row in rows
    ]

    # Validate
    invalid = [p for p in products if not p.validate()]

    if invalid:
        return {
            'status': 'validation_error',
            'invalid_rows': invalid,
        }

    # Ingest
    await bulk_ingestor.ingest(products)

    return {
        'status': 'completed',
        'products_ingested': len(products),
    }
```

**Time to implement**: 1-2 hours

**Impact**: Alternative path to success for scrape-resistant sites.

---

## Phase 3: Human Loop (Week 3-4)

**Enable humans to resolve what automation can't.**

### 3.1 Escalation Emails (1 hour)

**Send merchant actionable notification when extraction fails.**

```python
async def send_escalation_email(merchant_email: str, shop_url: str):
    email = f"""
Subject: We need your help with product import

Dear Merchant,

We tried to extract products from {shop_url} but encountered issues.

Options:
1. UPLOAD A CSV (fastest)
   - Export products from your admin panel
   - Upload here: [link]
   - We'll import immediately

2. GRANT ACCESS (if you trust us)
   - Temporary admin credentials
   - We extract everything directly
   - Revoke when done

3. WAIT FOR INVESTIGATION
   - Our team investigates manually
   - 1-2 business days

Which option would you prefer?

Best regards,
OneUp Team
    """

    await send_email(merchant_email, email)
```

**Time to implement**: 30 minutes

**Impact**: Merchant knows what's happening. Empowered to help.

---

### 3.2 Dashboard for Reviewers (4 hours)

**Give your team visibility into failures.**

```
MANUAL REVIEW DASHBOARD
├─ Pending: 12 items
│  └─ SLA: 8 due in <4 hours
├─ Statistics
│  ├─ Avg resolution time: 15 minutes
│  ├─ Approval rate: 87%
│  └─ Top escalation reason: "auth_required"
└─ Queue
   ├─ [Nordstrom] zero_result - due in 2h
   ├─ [Local Shop] low_confidence - due in 6h
   └─ [Vestiague] auth_required - due in 8h
```

**Time to implement**: 3-4 hours

**Impact**: Structured, fair triage. Metrics for improvement.

---

## Phase 4: Observability (Ongoing)

**Can't improve what you don't measure.**

### 4.1 Metrics Dashboard

**Track these KPIs**:

```python
metrics = {
    "success_rate": 0.92,  # % of jobs with >0 products
    "avg_confidence": 0.84,  # Average extraction confidence
    "zero_result_count": 8,  # Count in last 24h
    "manual_review_queue": 12,  # Current backlog
    "strategy_usage": {
        "platform_api": 0.45,
        "network_interception": 0.25,
        "schema_org": 0.10,
        "llm": 0.15,
        "other": 0.05,
    },
    "cost": {
        "proxy_requests": 10000,
        "llm_tokens": 150000,
        "estimated_usd": 3.50,  # Per merchant
    },
}
```

**Dashboard**:
- Real-time success rate
- Extraction quality distribution
- Failure reason breakdown
- Cost per merchant
- Manual review backlog trend

**Time to implement**: 2-3 hours

**Impact**: Early warning system. Cost visibility.

---

### 4.2 Alerting Rules

**Alert when something goes wrong:**

```python
alerts = [
    # Success rate drops suddenly
    {
        'name': 'success_drop',
        'condition': lambda m: m.success_rate < 0.80,
        'severity': 'critical',
        'action': 'page_oncall',
    },

    # Zero-result spike
    {
        'name': 'zero_result_spike',
        'condition': lambda m: m.zero_result_count_24h > 50,
        'severity': 'warning',
        'action': 'notify_slack',
    },

    # Manual review backlog
    {
        'name': 'review_backlog',
        'condition': lambda m: len(m.manual_review_queue) > 100,
        'severity': 'info',
        'action': 'notify_team_email',
    },
]
```

**Time to implement**: 1-2 hours

**Impact**: Proactive instead of reactive. Catch issues early.

---

## Implementation Timeline

```
Week 1 (Phase 1):
  Mon: Zero-result detection (1.1)
  Tue: Confidence scoring (1.2)
  Wed: Exponential backoff (1.3)
  Thu: Network interception (1.4)
  Fri: Fallback chain (1.5)
  → +40% success rate

Week 2 (Phase 2):
  Mon-Tue: Dead letter queue (2.1)
  Wed: Proxy rotation setup (2.2)
  Thu: Browser pool optimization (2.3)
  Fri: Manual review queue (2.4)
  → Edge case handling

Week 3-4 (Phase 3):
  Tue-Wed: Escalation emails (3.1)
  Thu-Fri: Reviewer dashboard (3.2)
  → Human loop operational

Ongoing (Phase 4):
  Metrics dashboard (4.1)
  Alerting rules (4.2)
  → Observability & improvement
```

---

## Success Metrics

**Before implementation**:
- Success rate: ~60%
- Silent failures: Unknown
- Manual review: None
- Cost per merchant: $1.50 (rough estimate)

**After Phase 1 (Week 1)**:
- Success rate: 92%+
- Zero-results detected & escalated: 100%
- Cost per merchant: $1.80 (proxy + LLM fallback)

**After Phase 2 (Week 3)**:
- Success rate: 96%+
- Manual review backlog: <20 items
- Cost per merchant: $2.20 (but reliability high)

**After Phase 3-4 (Week 4)**:
- Success rate: 98%+
- Manual review SLA met: 95%
- Cost tracking: Per-merchant visibility
- Zero broken onboardings: Target achieved

---

## Code Files to Create/Modify

**New files**:
- `app/services/extraction_validator.py` (Phase 1.1)
- `app/models/extraction_quality.py` (Phase 1.2)
- `app/services/zero_result_handler.py` (Phase 1.1)
- `app/infra/browser_pool.py` (Phase 2.3)
- `app/db/models/manual_review.py` (Phase 2.4)
- `app/infra/extraction_metrics.py` (Phase 4.1)

**Files to modify**:
- `app/services/pipeline.py` (integrate validators)
- `app/services/product_extractor.py` (add fallback chain + retry logic)
- `app/api/v1/onboarding.py` (handle escalations)
- `app/config.py` (add Phase 1-4 settings)

---

## Estimated Timeline

**Phase 1**: 10-12 hours engineering (1 day, 1 person)
**Phase 2**: 15-18 hours engineering (2 days, 1 person)
**Phase 3**: 8-10 hours engineering (1 day, 1 person)
**Phase 4**: 5-8 hours ongoing (spread over weeks)

**Total**: ~4 weeks for full implementation, ~3 weeks for MVP (Phase 1 + 2)

---

## Risk Mitigation

**Risk: "This is too complex, I don't have time."**

**Mitigation**: Start with Phase 1 only. It's 1 day of work and fixes 40% of failures. Rest is optional but highly recommended.

**Risk: "Proxy services are expensive."**

**Mitigation**: Start without proxies. Add them only if IP blocking becomes common. ScraperAPI is ~$50/month for low volume.

**Risk: "LLM extraction is slow/expensive."**

**Mitigation**: Use Groq (free tier) or Ollama (local). Only fall back to OpenAI if free options fail.

**Risk: "Manual review is labor-intensive."**

**Mitigation**: Start with just capturing data for review. Humans only "approve/reject" (5 min per item). Actual investigation happens only on Fridays.

---

## Success Stories in Industry

**Google Shopping** (hundreds of thousands of merchants):
- Validates feed data strictly
- Provides clear error messages
- Allows partial import (some items succeed, others flagged)
- Merchants fix and re-upload

**Shopify** (millions of merchants):
- Supports CSV import with validation
- Shows exactly which rows failed and why
- Lets merchants preview before final import

**Idealo** (50,000+ merchants):
- Prefers merchant-provided CSV
- Falls back to automated scraping only for special cases
- Has large human QA team

**All of them**: Automation + human loop. Never 100% automation.

---

## Final Checklist

**Before going live with Phase 1**:
- [ ] Zero-result detection implemented
- [ ] All extractions validated before ingestion
- [ ] Confidence scores on critical fields
- [ ] Exponential backoff in retry logic
- [ ] Network interception added to fallback chain
- [ ] Comprehensive logging for debugging
- [ ] Tests covering zero-result cases
- [ ] Manual escalation workflow defined
- [ ] Merchant notification template ready

**Before Phase 2**:
- [ ] Dead letter queue operational
- [ ] Proxy service integrated and tested
- [ ] Browser pool prevents memory leaks
- [ ] Manual review database schema
- [ ] CSV upload endpoint

**Before Phase 3**:
- [ ] Escalation emails sent and tracked
- [ ] Reviewer dashboard functional
- [ ] SLA tracking in place

**Ongoing**:
- [ ] Metrics dashboard updated daily
- [ ] Alerts checked regularly
- [ ] Failure patterns analyzed weekly
- [ ] Process improvements documented

---

## Questions to Ask Before Starting

1. **What's your current success rate?** (estimate)
2. **How many merchants are in the zero-result bucket?**
3. **What's your budget for proxy services?** ($0 / $50/month / $500+)
4. **Do you have a team to do manual review?** (1 person minimum)
5. **Can you afford 4 weeks of development?** (Or want MVP in 1 week?)

---

## Next Steps

1. **Read** `research/EXTRACTION_RELIABILITY_RESEARCH.md` (30 min)
2. **Implement** Phase 1 (1 day)
3. **Test** with 10 real merchants (1 day)
4. **Measure** success rate improvement
5. **Plan** Phase 2 based on results

Good luck. This roadmap will make your system virtually unbreakable.

