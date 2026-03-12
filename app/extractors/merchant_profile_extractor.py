"""Merchant profile extractor — extracts business identity and technology tags from website HTML."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import MAX_RESPONSE_SIZE
from app.extractors.browser_config import (
    DEFAULT_HEADERS,
    get_default_user_agent,
)
from app.security.url_validator import URLValidator

logger = logging.getLogger(__name__)


@dataclass
class MerchantProfileResult:
    """Result from merchant profile extraction.

    Different from ExtractorResult — returns a single dict (merchant profile)
    rather than a list of dicts (products). Used by platform onboarding pipeline
    to capture business identity, social links, contact info, and analytics tags.
    """

    raw_data: dict = field(default_factory=dict)
    pages_crawled: list[str] = field(default_factory=list)
    confidence: float = 0.0
    error: str | None = None


class MerchantProfileExtractor:
    """Extracts merchant business profile from website HTML.

    Does NOT inherit BaseExtractor — different contract (single dict, not product list).
    Uses crawl4ai browser crawl to capture metadata, external links, and network
    requests (third-party service detection). Falls back to httpx + BeautifulSoup
    when browser crawl fails or is unavailable.
    Probes additional pages (/about, /contact) via lightweight httpx.

    Extracts:
    - Business identity: company name, logo, description, founding date, industry
    - Contact info: emails, phone numbers from mailto: and tel: links
    - Social links: Facebook, Instagram, Twitter, LinkedIn, TikTok, YouTube, Pinterest
    - Address: street, city, region, postal code, country (from JSON-LD)
    - Meta tags: og:site_name, og:description, meta description, title, language, favicon
    - Analytics tags: Google Analytics UA/GA4, GTM, AdSense, Facebook Pixel, Hotjar, TikTok Pixel, etc.
    - Third-party services: detected via network requests (payments, reviews, chat, etc.)
    - About text: extracted from /about or /about-us pages
    """

    _SUBPAGE_PATHS = [
        "/about",
        "/about-us",
        "/pages/about",
        "/pages/about-us",
        "/contact",
        "/contact-us",
        "/pages/contact",
    ]

    _SOCIAL_PATTERNS = {
        "facebook": ["facebook.com/", "fb.com/"],
        "instagram": ["instagram.com/"],
        "twitter": ["twitter.com/", "x.com/"],
        "linkedin": ["linkedin.com/company/", "linkedin.com/in/"],
        "tiktok": ["tiktok.com/@"],
        "youtube": ["youtube.com/", "youtu.be/"],
        "pinterest": ["pinterest.com/"],
    }

    # Regex patterns for analytics tags: (pattern, tag_type, case_sensitive)
    # For patterns with capture groups, the first group is the tag_id
    # For patterns without capture groups, the full match is the tag_id
    # case_sensitive=True means no re.IGNORECASE (GA4/GTM IDs are always uppercase)
    _ANALYTICS_PATTERNS = {
        "google_analytics_ua": (r"UA-\d{4,10}-\d{1,4}", "UA", False),
        "google_analytics_ga4": (r"G-[A-Z0-9]{6,}", "GA4", True),
        "google_tag_manager": (r"GTM-[A-Z0-9]{6,}", "GTM", True),
        "google_adsense": (r"ca-pub-\d{10,}", "AdSense", False),
        "facebook_pixel": (r"fbq\s*\(\s*['\"]init['\"]\s*,\s*['\"](\d{10,})['\"]", "Pixel", False),
        "hotjar": (r"hj\s*\(\s*['\"]init['\"]\s*,\s*(\d+)", "Hotjar", False),
        "tiktok_pixel": (r"ttq\.load\s*\(\s*['\"]([A-Z0-9]+)['\"]", "TikTok", False),
        "pinterest_tag": (r"pintrk\s*\(\s*['\"]load['\"]\s*,\s*['\"](\d+)['\"]", "Pinterest", False),
        "microsoft_clarity": (r"clarity\s*\(\s*['\"]set['\"].*?['\"]([a-z0-9]{7,})['\"]", "Clarity", False),
    }

    # Third-party service domains detected via network requests.
    # Maps domain substring -> (provider_name, service_category).
    _THIRD_PARTY_DOMAINS = {
        # Analytics & Tracking
        "google-analytics.com": ("google_analytics", "Analytics"),
        "googletagmanager.com": ("google_tag_manager", "Tag Manager"),
        "googlesyndication.com": ("google_adsense", "AdSense"),
        "connect.facebook.net": ("facebook_pixel", "Pixel"),
        "static.hotjar.com": ("hotjar", "Hotjar"),
        "analytics.tiktok.com": ("tiktok_pixel", "TikTok"),
        "ct.pinterest.com": ("pinterest_tag", "Pinterest"),
        "clarity.ms": ("microsoft_clarity", "Clarity"),
        "snap.licdn.com": ("linkedin_insight", "LinkedIn"),
        "bat.bing.com": ("bing_ads", "Bing Ads"),
        "cdn.segment.com": ("segment", "Segment"),
        "cdn.amplitude.com": ("amplitude", "Amplitude"),
        "cdn.heapanalytics.com": ("heap", "Heap"),
        "static.criteo.net": ("criteo", "Criteo"),
        "js.adsrvr.org": ("tradedesk", "TradeDesk"),
        "tag.simpli.fi": ("simplifi", "Simpli.fi"),
        # Email & SMS Marketing
        "klaviyo.com": ("klaviyo", "Email Marketing"),
        "chimpstatic.com": ("mailchimp", "Email Marketing"),
        "omnisrc.com": ("omnisend", "Email Marketing"),
        "attentive.com": ("attentive", "SMS Marketing"),
        "attn.tv": ("attentive", "SMS Marketing"),
        "postscript.io": ("postscript", "SMS Marketing"),
        "privy.com": ("privy", "Email Popups"),
        # Reviews & UGC
        "widget.trustpilot.com": ("trustpilot", "Reviews"),
        "staticw2.yotpo.com": ("yotpo", "Reviews"),
        "cdn.judge.me": ("judge_me", "Reviews"),
        "stamped.io": ("stamped", "Reviews"),
        "loox.io": ("loox", "Reviews"),
        "okendo.io": ("okendo", "Reviews"),
        "bazaarvoice.com": ("bazaarvoice", "Reviews"),
        # Support & Chat
        "static.zdassets.com": ("zendesk", "Support"),
        "js.intercomcdn.com": ("intercom", "Support"),
        "widget.drift.com": ("drift", "Chat"),
        "code.tidio.co": ("tidio", "Chat"),
        "gorgias.chat": ("gorgias", "Support"),
        # Payments & BNPL
        "js.stripe.com": ("stripe", "Payments"),
        "js.klarna.com": ("klarna", "BNPL"),
        "js-cdn.afterpay.com": ("afterpay", "BNPL"),
        "cdn.sezzle.com": ("sezzle", "BNPL"),
        "cdn1.affirm.com": ("affirm", "BNPL"),
        "paypalobjects.com": ("paypal", "Payments"),
        "pay.shopify.com": ("shop_pay", "Payments"),
        "shop.app": ("shop_pay", "Payments"),
        # Subscriptions & Loyalty
        "rechargecdnprod.azureedge.net": ("recharge", "Subscriptions"),
        "smile.io": ("smile_io", "Loyalty"),
        "loyaltylion.com": ("loyaltylion", "Loyalty"),
        "ordergroove.com": ("ordergroove", "Subscriptions"),
        # Search & Merchandising
        "cdn.searchspring.net": ("searchspring", "Search"),
        "cdn.rebuyengine.com": ("rebuy", "Merchandising"),
        "connect.nosto.com": ("nosto", "Merchandising"),
        # Cookie Consent
        "cdn.cookielaw.org": ("onetrust", "Cookie Consent"),
        "cdn.osano.com": ("osano", "Cookie Consent"),
        # A/B Testing
        "cdn.optimizely.com": ("optimizely", "A/B Testing"),
        # Push Notifications
        "cdn.onesignal.com": ("onesignal", "Push Notifications"),
        # Fonts & CDN (informational)
        "fonts.googleapis.com": ("google_fonts", "Fonts"),
        "use.typekit.net": ("adobe_fonts", "Fonts"),
    }

    _SUBPAGE_TIMEOUT = 5.0
    _MAX_ABOUT_TEXT_LENGTH = 5000

    def __init__(self, client: httpx.AsyncClient | None = None):
        """Initialize extractor with optional shared httpx client.

        Args:
            client: Shared httpx.AsyncClient for request pooling (optional).
                    If None, creates temporary client for each request.
        """
        self._client = client

    async def extract(
        self, shop_url: str, homepage_html: str | None = None
    ) -> MerchantProfileResult:
        """Extract merchant profile from homepage HTML + subpage probes.

        Uses crawl4ai browser crawl when possible to capture metadata, external links,
        and network requests. Falls back to httpx + BeautifulSoup when browser crawl
        fails or when homepage_html is pre-provided.

        Args:
            shop_url: The merchant's base URL
            homepage_html: Pre-fetched homepage HTML (from PlatformDetector).
                          If None, fetches it. Avoids redundant requests when
                          already fetched during platform detection.

        Returns:
            MerchantProfileResult with raw_data dict containing all extracted fields.
            On error, returns result with error message and partial data extracted so far.
        """
        pages_crawled = []
        raw_data = {}

        try:
            # Attempt browser crawl for metadata, links, and network requests.
            # Skip browser crawl when homepage_html is already provided — the caller
            # (e.g., PlatformDetector) already fetched it, and we only need the
            # browser for network request capture and richer metadata.
            crawl_result = None
            if homepage_html is None:
                crawl_result = await self._browser_crawl(shop_url)

            # Determine HTML source: crawl4ai > provided > httpx fallback
            html = None
            if crawl_result and crawl_result.success:
                html = crawl_result.html
            if not html:
                html = homepage_html
            if not html:
                html = await self._fetch_page(shop_url)
            if not html:
                logger.warning("Failed to fetch homepage for %s", shop_url)
                return MerchantProfileResult(error="Failed to fetch homepage")

            pages_crawled.append(shop_url)
            soup = BeautifulSoup(html, "html.parser")

            # Use crawl4ai results when available, BeautifulSoup fallback otherwise
            if crawl_result and crawl_result.success:
                meta_data = self._extract_meta_from_crawl_result(crawl_result)
                social_data = self._extract_social_from_crawl_result(crawl_result)
                network_services = self._detect_third_party_services(crawl_result)
            else:
                meta_data = self._extract_meta_tags(soup)
                social_data = self._extract_social_links(soup)
                network_services = []

            # Always use custom code for these (crawl4ai doesn't provide)
            jsonld_data = self._extract_jsonld_organization(soup)
            analytics_data = self._extract_analytics_tags(html)
            contact_data = self._extract_contact_info(soup)

            # Merge network-detected services into analytics tags
            analytics_data = self._merge_network_services(analytics_data, network_services)

            # Merge all homepage data
            raw_data.update(
                {
                    # JSON-LD fields (prefixed to avoid collisions)
                    "jsonld_company_name": jsonld_data.get("company_name"),
                    "jsonld_logo": jsonld_data.get("logo"),
                    "jsonld_description": jsonld_data.get("description"),
                    "jsonld_email": jsonld_data.get("email"),
                    "jsonld_telephone": jsonld_data.get("telephone"),
                    "founding_date": jsonld_data.get("founding_date"),
                    "industry": jsonld_data.get("industry"),
                    "jsonld_address": jsonld_data.get("address"),
                    "jsonld_same_as": jsonld_data.get("same_as", []),
                    # Meta tags
                    "og_site_name": meta_data.get("og_site_name"),
                    "og_description": meta_data.get("og_description"),
                    "meta_description": meta_data.get("meta_description"),
                    "title_tag": meta_data.get("title_tag"),
                    "html_lang": meta_data.get("html_lang"),
                    "favicon_url": meta_data.get("favicon_url"),
                    "currency": meta_data.get("currency"),
                    # Social links
                    "social_links": social_data,
                    # Analytics tags
                    "analytics_tags": analytics_data,
                    # Contact info
                    "emails": contact_data.get("emails", []),
                    "phones": contact_data.get("phones", []),
                }
            )

            # Merge JSON-LD address into flat fields
            jsonld_addr = jsonld_data.get("address", {})
            if isinstance(jsonld_addr, dict):
                raw_data["address_street"] = jsonld_addr.get("streetAddress")
                raw_data["address_city"] = jsonld_addr.get("addressLocality")
                raw_data["address_region"] = jsonld_addr.get("addressRegion")
                raw_data["address_postal_code"] = jsonld_addr.get("postalCode")
                raw_data["address_country"] = jsonld_addr.get("addressCountry")

            # Merge JSON-LD sameAs into social links
            for url in jsonld_data.get("same_as", []):
                if isinstance(url, str):
                    self._classify_social_url(url, raw_data.setdefault("social_links", {}))

            # Add JSON-LD email/phone to contact lists
            if jsonld_data.get("email"):
                emails = raw_data.get("emails", [])
                if jsonld_data["email"] not in emails:
                    emails.append(jsonld_data["email"])
                raw_data["emails"] = emails
            if jsonld_data.get("telephone"):
                phones = raw_data.get("phones", [])
                if jsonld_data["telephone"] not in phones:
                    phones.append(jsonld_data["telephone"])
                raw_data["phones"] = phones

            # Probe subpages for additional data
            subpage_data = await self._probe_subpages(shop_url)
            if subpage_data.get("pages_crawled"):
                pages_crawled.extend(subpage_data["pages_crawled"])
            if subpage_data.get("about_text"):
                raw_data["about_text"] = subpage_data["about_text"]

            # Merge additional emails/phones from subpages (avoid duplicates)
            for email in subpage_data.get("emails", []):
                if email not in raw_data.get("emails", []):
                    raw_data.setdefault("emails", []).append(email)
            for phone in subpage_data.get("phones", []):
                if phone not in raw_data.get("phones", []):
                    raw_data.setdefault("phones", []).append(phone)

            # Merge additional social links from subpages (don't overwrite homepage links)
            for platform, url in subpage_data.get("social_links", {}).items():
                if platform not in raw_data.get("social_links", {}):
                    raw_data.setdefault("social_links", {})[platform] = url

            raw_data["pages_crawled"] = pages_crawled

            # Calculate confidence score
            confidence = self._calculate_confidence(raw_data)
            raw_data["confidence"] = confidence

            logger.info(
                "Merchant profile extracted from %s: %d pages crawled, confidence %.2f, "
                "crawl4ai=%s, network_services=%d",
                shop_url,
                len(pages_crawled),
                confidence,
                bool(crawl_result and crawl_result.success),
                len(network_services),
            )

            return MerchantProfileResult(
                raw_data=raw_data,
                pages_crawled=pages_crawled,
                confidence=confidence,
            )

        except Exception as e:
            logger.exception("Merchant profile extraction failed for %s", shop_url)
            return MerchantProfileResult(
                raw_data=raw_data,
                pages_crawled=pages_crawled,
                confidence=0.0,
                error=str(e),
            )

    async def _browser_crawl(self, url: str):
        """Crawl homepage via browser to capture metadata, links, and network requests.

        Uses crawl4ai AsyncWebCrawler with network request capture enabled.
        Short timeout — profile extraction is non-blocking and should not delay
        the pipeline if the browser is slow or unavailable.

        Args:
            url: The homepage URL to crawl

        Returns:
            CrawlResult on success, None on failure or if crawl4ai is unavailable.
        """
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

            browser_config = BrowserConfig(headless=True, verbose=False)
            crawl_config = CrawlerRunConfig(
                capture_network_requests=True,
                wait_until="domcontentloaded",
                page_timeout=15000,
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=crawl_config)
                if result and result.success:
                    logger.debug(
                        "Browser crawl succeeded for %s: %d network requests captured",
                        url,
                        len(getattr(result, "network_requests", []) or []),
                    )
                    return result
                else:
                    logger.debug("Browser crawl returned unsuccessful result for %s", url)
                    return None

        except ImportError:
            logger.debug("crawl4ai not available, skipping browser crawl")
            return None
        except Exception as e:
            logger.debug("Browser crawl failed for %s: %s", url, e)
            return None

    def _extract_meta_from_crawl_result(self, crawl_result) -> dict:
        """Extract meta tags from crawl4ai CrawlResult metadata.

        Maps crawl4ai metadata keys to expected raw_data keys. Falls back to
        BeautifulSoup for html_lang, currency, and favicon_url which are not
        available in crawl4ai metadata.

        Args:
            crawl_result: crawl4ai CrawlResult object

        Returns:
            Dict with keys: og_site_name, og_description, meta_description,
            title_tag, html_lang, favicon_url, currency
        """
        result = {}
        metadata = getattr(crawl_result, "metadata", {}) or {}

        # Map crawl4ai metadata to expected keys
        if metadata.get("title"):
            result["title_tag"] = metadata["title"]
        if metadata.get("description"):
            result["meta_description"] = metadata["description"]
        if metadata.get("og:site_name"):
            result["og_site_name"] = metadata["og:site_name"]
        if metadata.get("og:description"):
            result["og_description"] = metadata["og:description"]

        # html_lang, currency, favicon_url are not in crawl4ai metadata —
        # parse from HTML with BeautifulSoup (just these 3 fields)
        html = getattr(crawl_result, "html", None)
        if html:
            soup = BeautifulSoup(html, "html.parser")

            # html lang
            html_tag = soup.find("html")
            if html_tag and html_tag.get("lang"):
                result["html_lang"] = html_tag["lang"].strip()[:10]

            # Currency from meta tags
            currency_meta = soup.find("meta", property="og:price:currency")
            if not currency_meta:
                currency_meta = soup.find("meta", property="product:price:currency")
            if currency_meta and currency_meta.get("content"):
                result["currency"] = currency_meta["content"].strip()[:3]

            # Favicon
            favicon = soup.find(
                "link",
                rel=lambda x: x and "icon" in x if isinstance(x, list) else x == "icon",
            )
            if not favicon:
                favicon = soup.find("link", rel="shortcut icon")
            if favicon and favicon.get("href"):
                result["favicon_url"] = favicon["href"].strip()

        return result

    def _extract_social_from_crawl_result(self, crawl_result) -> dict:
        """Extract social media links from crawl4ai CrawlResult external links.

        Uses crawl_result.links["external"] instead of BeautifulSoup anchor parsing.
        Classifies each external link via the existing _classify_social_url() method.

        Args:
            crawl_result: crawl4ai CrawlResult object

        Returns:
            Dict mapping platform name to URL (e.g., {"facebook": "https://...", ...})
        """
        social = {}
        links = getattr(crawl_result, "links", {}) or {}
        external_links = links.get("external", [])

        for link in external_links:
            href = None
            if isinstance(link, dict):
                href = link.get("href")
            elif isinstance(link, str):
                href = link

            if href and isinstance(href, str):
                self._classify_social_url(href, social)

        return social

    def _detect_third_party_services(self, crawl_result) -> list[dict]:
        """Detect third-party services from network requests captured by crawl4ai.

        Parses each network request URL domain and checks against the
        _THIRD_PARTY_DOMAINS mapping to identify analytics, payment, review,
        chat, and other services the merchant uses.

        Args:
            crawl_result: crawl4ai CrawlResult object with network_requests

        Returns:
            List of dicts: [{"provider": "stripe", "tag_id": None, "tag_type": "Payments"}, ...]
        """
        services = []
        seen_providers = set()
        network_requests = getattr(crawl_result, "network_requests", []) or []

        for request in network_requests:
            # Network requests can be dicts with "url" key or objects with url attribute
            request_url = None
            if isinstance(request, dict):
                request_url = request.get("url")
            elif hasattr(request, "url"):
                request_url = request.url

            if not request_url or not isinstance(request_url, str):
                continue

            try:
                parsed = urlparse(request_url)
                domain = parsed.netloc.lower()
            except Exception:
                continue

            for domain_pattern, (provider, category) in self._THIRD_PARTY_DOMAINS.items():
                if domain_pattern in domain and provider not in seen_providers:
                    seen_providers.add(provider)
                    services.append(
                        {
                            "provider": provider,
                            "tag_id": None,
                            "tag_type": category,
                        }
                    )

        return services

    def _merge_network_services(
        self, analytics_tags: list[dict], network_services: list[dict]
    ) -> list[dict]:
        """Merge network-detected services into analytics tags.

        If a provider already exists with a tag_id from regex extraction, keeps
        the regex version (it has the actual tracking ID). Only adds network-detected
        entries for NEW providers not already found by regex.

        Args:
            analytics_tags: Existing analytics tags from regex extraction
            network_services: Services detected via network requests

        Returns:
            Merged list of analytics tag dicts
        """
        existing_providers = {tag["provider"] for tag in analytics_tags}

        for service in network_services:
            if service["provider"] not in existing_providers:
                analytics_tags.append(service)
                existing_providers.add(service["provider"])

        return analytics_tags

    def _extract_jsonld_organization(self, soup: BeautifulSoup) -> dict:
        """Parse JSON-LD for Organization, LocalBusiness, Store, etc.

        Looks for schema.org structured data in <script type="application/ld+json"> tags.
        Handles single objects, @graph arrays, and root-level arrays.
        Takes the first matching organization type found.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Dict with keys: company_name, logo, description, email, telephone,
            founding_date, industry, address (dict), same_as (list)
        """
        org_types = {
            "Organization",
            "LocalBusiness",
            "Store",
            "OnlineStore",
            "Corporation",
            "Restaurant",
            "WebSite",
            "AutoDealer",
            "MedicalBusiness",
            "LegalService",
            "FinancialService",
        }
        result = {}

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = []

                if isinstance(data, dict):
                    if "@graph" in data and isinstance(data["@graph"], list):
                        # @graph container: only traverse children, not the root wrapper
                        items.extend(data["@graph"])
                    else:
                        items.append(data)
                elif isinstance(data, list):
                    items.extend(data)

                # Prefer the first org-type node that has a name field.
                # Fall back to the first org-type node if none have a name.
                # This handles @graph lists where a lightweight WebSite node
                # appears before a richer Organization node.
                fallback_item: dict | None = None
                fallback_type_str: str = ""

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    type_val = item.get("@type", "")
                    type_str = (
                        str(type_val)
                        if not isinstance(type_val, list)
                        else " ".join(str(t) for t in type_val)
                    )

                    # Check if any org type matches
                    if any(t in type_str for t in org_types):
                        if item.get("name"):
                            # Best match: org type with a name — use immediately
                            fallback_item = item
                            fallback_type_str = type_str
                            break
                        elif fallback_item is None:
                            # Record first org-type match as fallback in case
                            # no named node is found
                            fallback_item = item
                            fallback_type_str = type_str

                if fallback_item is not None:
                    item = fallback_item
                    type_str = fallback_type_str
                    result["company_name"] = item.get("name")
                    result["logo"] = item.get("logo")
                    result["description"] = item.get("description")
                    result["founding_date"] = item.get("foundingDate")
                    result["email"] = item.get("email")
                    result["telephone"] = item.get("telephone")
                    result["industry"] = type_str

                    same_as = item.get("sameAs", [])
                    if isinstance(same_as, str):
                        same_as = [same_as]
                    result["same_as"] = same_as

                    addr = item.get("address", {})
                    if isinstance(addr, dict):
                        result["address"] = addr
                    elif isinstance(addr, str):
                        result["address"] = {"streetAddress": addr}

            except json.JSONDecodeError as e:
                logger.debug("Failed to parse JSON-LD: %s", e)
                continue
            except Exception as e:
                logger.debug("Error processing JSON-LD: %s", e)
                continue

        return result

    def _extract_meta_tags(self, soup: BeautifulSoup) -> dict:
        """Extract og:site_name, meta description, language, favicon, currency.

        Parses standard meta tags including OpenGraph and product-specific tags.
        Used as fallback when crawl4ai browser crawl is unavailable.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Dict with keys: og_site_name, og_description, meta_description,
            title_tag, html_lang, favicon_url, currency
        """
        result = {}

        # og:site_name
        og_site = soup.find("meta", property="og:site_name")
        if og_site and og_site.get("content"):
            result["og_site_name"] = og_site["content"].strip()

        # og:description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            result["og_description"] = og_desc["content"].strip()

        # meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            result["meta_description"] = meta_desc["content"].strip()

        # title tag
        title = soup.find("title")
        if title and title.string:
            result["title_tag"] = title.string.strip()

        # html lang
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            result["html_lang"] = html_tag["lang"].strip()[:10]

        # Favicon (multiple possible rel values)
        favicon = soup.find(
            "link", rel=lambda x: x and "icon" in x if isinstance(x, list) else x == "icon"
        )
        if not favicon:
            favicon = soup.find("link", rel="shortcut icon")
        if favicon and favicon.get("href"):
            result["favicon_url"] = favicon["href"].strip()

        # Currency from meta tags
        currency_meta = soup.find("meta", property="og:price:currency")
        if not currency_meta:
            currency_meta = soup.find("meta", property="product:price:currency")
        if currency_meta and currency_meta.get("content"):
            result["currency"] = currency_meta["content"].strip()[:3]

        return result

    def _extract_social_links(self, soup: BeautifulSoup) -> dict:
        """Extract social media links from anchor tags.

        Prioritizes links found in header, footer, and nav elements.
        Falls back to full page scan only if priority areas yield nothing.
        Used as fallback when crawl4ai browser crawl is unavailable.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Dict mapping platform name to URL (e.g., {"facebook": "https://...", ...})
        """
        social = {}

        # Priority: header, footer, nav elements first
        priority_areas = soup.find_all(["header", "footer", "nav", "aside"])
        for area in priority_areas:
            for a in area.find_all("a", href=True):
                href = a["href"]
                if href and isinstance(href, str):
                    self._classify_social_url(href, social)

        # If we found links in priority areas, return them
        if social:
            return social

        # Fallback: scan all <a> tags
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href and isinstance(href, str):
                self._classify_social_url(href, social)

        return social

    def _classify_social_url(self, url: str, social: dict) -> None:
        """Classify a URL as a social media link if it matches known patterns.

        Modifies the social dict in place, adding the URL if it matches any platform.

        Args:
            url: The URL to classify
            social: Dict to add classified URL to
        """
        url_lower = url.lower()
        for platform, patterns in self._SOCIAL_PATTERNS.items():
            if platform not in social:
                for pat in patterns:
                    if pat in url_lower:
                        social[platform] = url
                        break

    def _extract_analytics_tags(self, html: str) -> list[dict]:
        """Regex-scan raw HTML for tracking/analytics tag IDs.

        Extracts analytics provider IDs via regex patterns.
        Deduplicates results using (provider, tag_id) key.

        Args:
            html: Raw HTML content

        Returns:
            List of dicts: [{"provider": "google_analytics_ga4", "tag_id": "G-...", "tag_type": "GA4"}, ...]
        """
        # Strip HTML comments to avoid matching inactive/commented-out tags
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

        tags = []
        seen = set()

        # Regex-based extraction
        for provider, (pattern, tag_type, case_sensitive) in self._ANALYTICS_PATTERNS.items():
            flags = 0 if case_sensitive else re.IGNORECASE
            matches = re.findall(pattern, html, flags)
            for match in matches:
                tag_id = match if isinstance(match, str) else match
                key = f"{provider}:{tag_id}"
                if key not in seen:
                    seen.add(key)
                    tags.append(
                        {
                            "provider": provider,
                            "tag_id": tag_id,
                            "tag_type": tag_type,
                        }
                    )

        return tags

    def _extract_contact_info(self, soup: BeautifulSoup) -> dict:
        """Extract emails from mailto: and phones from tel: links.

        Also looks for email patterns in footer/address elements via regex.
        Deduplicates results.

        Args:
            soup: BeautifulSoup parsed HTML

        Returns:
            Dict with keys: emails (list), phones (list)
        """
        emails = set()
        phones = set()

        # Extract from mailto: and tel: links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not isinstance(href, str):
                continue

            if href.startswith("mailto:"):
                email = href[7:].split("?")[0].strip()
                if email and "@" in email and "." in email:
                    emails.add(email.lower())
            elif href.startswith("tel:"):
                phone = href[4:].strip()
                if phone:
                    phones.add(phone)

        # Look for email patterns in text near footer/contact sections
        # (conservative — only in <footer> or <address> elements)
        email_pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        phone_pattern = re.compile(
            r"(?:\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9})"
            r"|"
            r"(?:\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4})"
        )

        for elem in soup.find_all(["footer", "address"]):
            text = elem.get_text()
            for match in email_pattern.findall(text):
                if not match.endswith((".png", ".jpg", ".gif", ".css", ".js")):
                    emails.add(match.lower())
            for match in phone_pattern.findall(text):
                cleaned = match.strip()
                digit_count = sum(c.isdigit() for c in cleaned)
                if digit_count >= 7 and digit_count <= 15:
                    phones.add(cleaned)

        return {
            "emails": list(emails),
            "phones": list(phones),
        }

    async def _probe_subpages(self, base_url: str) -> dict:
        """Fetch /about, /contact pages and extract additional data.

        Attempts to crawl common about/contact page paths. Extracts text content
        from about pages and contact info from all probed pages.

        Args:
            base_url: The merchant's base URL

        Returns:
            Dict with keys: pages_crawled (list), about_text (str or None),
            emails (list), phones (list), social_links (dict)
        """
        result = {
            "pages_crawled": [],
            "about_text": None,
            "emails": [],
            "phones": [],
            "social_links": {},
        }

        client = self._client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=self._SUBPAGE_TIMEOUT,
                headers={**DEFAULT_HEADERS, "User-Agent": get_default_user_agent()},
            )

        try:
            base = base_url.rstrip("/")

            for path in self._SUBPAGE_PATHS:
                url = f"{base}{path}"
                try:
                    # SSRF validation before fetching
                    is_valid, reason = await URLValidator.validate_async(url)
                    if not is_valid:
                        logger.debug("SSRF validation failed for subpage %s: %s", url, reason)
                        continue

                    response = await client.get(url, timeout=self._SUBPAGE_TIMEOUT)
                    if response.status_code != 200:
                        continue

                    # Check content-length header before parsing
                    try:
                        content_length = int(response.headers.get("content-length", 0))
                    except (ValueError, TypeError):
                        content_length = 0
                    if content_length > MAX_RESPONSE_SIZE:
                        logger.debug(
                            "Subpage %s too large (%d bytes), skipping", url, content_length
                        )
                        continue

                    html = response.text
                    if len(html) > MAX_RESPONSE_SIZE:
                        logger.debug(
                            "Subpage %s response body too large (%d chars), skipping",
                            url,
                            len(html),
                        )
                        continue

                    result["pages_crawled"].append(url)
                    soup = BeautifulSoup(html, "html.parser")

                    # Extract about text from about pages
                    if "about" in path and not result["about_text"]:
                        main_content = soup.find("main") or soup.find("article")
                        if not main_content:
                            main_content = soup.find(
                                "div", class_=re.compile(r"content|main|about", re.I)
                            )
                        if main_content:
                            about_text = main_content.get_text(separator=" ", strip=True)
                            if about_text and len(about_text) > 50:
                                result["about_text"] = about_text[
                                    : self._MAX_ABOUT_TEXT_LENGTH
                                ]

                    # Extract contact info from all subpages
                    contact = self._extract_contact_info(soup)
                    result["emails"].extend(contact.get("emails", []))
                    result["phones"].extend(contact.get("phones", []))

                    # Extract social links from subpages
                    social = self._extract_social_links(soup)
                    for platform, link_url in social.items():
                        if platform not in result["social_links"]:
                            result["social_links"][platform] = link_url

                except httpx.TimeoutException:
                    logger.debug("Subpage probe timed out for %s", url)
                except httpx.HTTPStatusError as e:
                    logger.debug("HTTP %d for subpage %s", e.response.status_code, url)
                except Exception as e:
                    logger.debug("Subpage probe failed for %s: %s", url, e)
                    continue

        finally:
            if owns_client:
                await client.aclose()

        # Deduplicate
        result["emails"] = list(set(result["emails"]))
        result["phones"] = list(set(result["phones"]))

        return result

    def _calculate_confidence(self, raw_data: dict) -> float:
        """Calculate extraction confidence based on populated fields.

        Scoring (cumulative):
        - company_name present: +0.25
        - description present: +0.10
        - at least 1 email or phone: +0.15
        - at least 1 social link: +0.15
        - at least 1 analytics tag: +0.10
        - logo present: +0.10
        - address present: +0.10
        - about text present: +0.05
        - third-party services detected via network: +0.05

        Args:
            raw_data: The extracted raw data dict

        Returns:
            Confidence score from 0.0 to 1.0
        """
        score = 0.0

        if (
            raw_data.get("jsonld_company_name")
            or raw_data.get("og_site_name")
            or raw_data.get("title_tag")
        ):
            score += 0.25
        if (
            raw_data.get("jsonld_description")
            or raw_data.get("meta_description")
            or raw_data.get("og_description")
        ):
            score += 0.10
        if raw_data.get("emails") or raw_data.get("phones"):
            score += 0.15
        if raw_data.get("social_links"):
            score += 0.15
        if raw_data.get("analytics_tags"):
            score += 0.10
        if raw_data.get("jsonld_logo") or raw_data.get("favicon_url"):
            score += 0.10
        if raw_data.get("address_street") or raw_data.get("address_city"):
            score += 0.10
        if raw_data.get("about_text"):
            score += 0.05

        # Bonus for third-party services detected via network requests
        analytics_tags = raw_data.get("analytics_tags", [])
        has_network_services = any(
            tag.get("tag_id") is None and tag.get("tag_type") not in ("UA", "GA4", "GTM", "AdSense", "Pixel", "Hotjar", "TikTok", "Pinterest", "Clarity")
            for tag in analytics_tags
        )
        if has_network_services:
            score += 0.05

        return min(score, 1.0)

    async def _fetch_page(self, url: str) -> str | None:
        """Fetch a page via httpx with size and status checks.

        Uses provided client if available, otherwise creates temporary client.
        Respects MAX_RESPONSE_SIZE limit.

        Args:
            url: The URL to fetch

        Returns:
            HTML content on success, None on error
        """
        client = self._client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=10.0,
                headers={**DEFAULT_HEADERS, "User-Agent": get_default_user_agent()},
            )
        try:
            response = await client.get(url)
            if response.status_code < 400:
                try:
                    content_length = int(response.headers.get("content-length", 0))
                except (ValueError, TypeError):
                    content_length = 0
                if content_length > MAX_RESPONSE_SIZE:
                    logger.warning(
                        "Response from %s too large (%d bytes), skipping",
                        url,
                        content_length,
                    )
                    return None
                html = response.text
                if len(html) > MAX_RESPONSE_SIZE:
                    logger.warning(
                        "Response body from %s too large (%d chars), skipping",
                        url,
                        len(html),
                    )
                    return None
                return html
            else:
                logger.warning("HTTP %d fetching %s", response.status_code, url)
        except httpx.TimeoutException:
            logger.warning("Timeout fetching %s", url)
        except httpx.RequestError as e:
            logger.warning("Request error fetching %s: %s", url, e)
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)
        finally:
            if owns_client:
                await client.aclose()
        return None
