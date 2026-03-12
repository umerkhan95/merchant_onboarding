"""Unit tests for MerchantProfileExtractor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from app.extractors.merchant_profile_extractor import (
    MerchantProfileExtractor,
    MerchantProfileResult,
)


@pytest.fixture
def extractor():
    """Create MerchantProfileExtractor instance."""
    return MerchantProfileExtractor()


class TestMerchantProfileExtractorJSONLD:
    """Tests for JSON-LD organization extraction."""

    @pytest.mark.asyncio
    async def test_extract_jsonld_organization(self, extractor):
        """Extract business profile from JSON-LD Organization schema."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "Acme Corp",
                "description": "Leading manufacturer of anvils and ACME products",
                "logo": "https://example.com/logo.png",
                "email": "contact@acme.com",
                "telephone": "+1-555-0123",
                "foundingDate": "1950-01-15",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "123 Anvil Lane",
                    "addressLocality": "Springfield",
                    "addressRegion": "IL",
                    "postalCode": "62701",
                    "addressCountry": "US"
                },
                "sameAs": [
                    "https://facebook.com/acmecorp",
                    "https://twitter.com/acmecorp"
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        assert result.error is None
        assert result.raw_data["jsonld_company_name"] == "Acme Corp"
        assert result.raw_data["jsonld_description"] == "Leading manufacturer of anvils and ACME products"
        assert result.raw_data["jsonld_logo"] == "https://example.com/logo.png"
        assert result.raw_data["jsonld_email"] == "contact@acme.com"
        assert result.raw_data["jsonld_telephone"] == "+1-555-0123"
        assert result.raw_data["founding_date"] == "1950-01-15"
        assert result.raw_data["address_street"] == "123 Anvil Lane"
        assert result.raw_data["address_city"] == "Springfield"
        assert result.raw_data["address_region"] == "IL"
        assert result.raw_data["address_postal_code"] == "62701"
        assert result.raw_data["address_country"] == "US"
        assert len(result.raw_data.get("emails", [])) > 0
        assert "contact@acme.com" in result.raw_data["emails"]

    @pytest.mark.asyncio
    async def test_extract_jsonld_local_business(self, extractor):
        """Extract profile from JSON-LD LocalBusiness schema."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "LocalBusiness",
                "name": "Downtown Bakery",
                "description": "Award-winning bakery with fresh pastries daily",
                "image": "https://example.com/bakery.jpg",
                "email": "hello@bakery.local",
                "telephone": "(555) 123-4567",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "456 Main Street",
                    "addressLocality": "Portland",
                    "addressRegion": "OR",
                    "postalCode": "97201",
                    "addressCountry": "USA"
                }
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://bakery.local", html)

        assert result.error is None
        assert result.raw_data["jsonld_company_name"] == "Downtown Bakery"
        assert result.raw_data["jsonld_description"] == "Award-winning bakery with fresh pastries daily"
        assert result.raw_data["address_city"] == "Portland"

    @pytest.mark.asyncio
    async def test_extract_jsonld_graph(self, extractor):
        """Extract profile from JSON-LD with @graph array pattern."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "WebSite",
                        "url": "https://example.com"
                    },
                    {
                        "@type": "Organization",
                        "name": "Tech Innovations Inc",
                        "description": "Cutting-edge technology solutions",
                        "logo": "https://example.com/logo.svg",
                        "email": "info@techinnovations.com"
                    }
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        assert result.error is None
        assert result.raw_data["jsonld_company_name"] == "Tech Innovations Inc"
        assert result.raw_data["jsonld_logo"] == "https://example.com/logo.svg"


class TestMerchantProfileExtractorMetaTags:
    """Tests for meta tag extraction."""

    @pytest.mark.asyncio
    async def test_extract_meta_tags(self, extractor):
        """Extract OpenGraph and meta tags."""
        html = """
        <!DOCTYPE html>
        <html lang="en-US">
        <head>
            <title>Premium Online Store | Best Deals</title>
            <meta name="description" content="Shop the finest products online with fast shipping">
            <meta property="og:site_name" content="My Premium Store">
            <meta property="og:description" content="Discover quality products at unbeatable prices">
            <meta property="og:price:currency" content="USD">
            <link rel="icon" href="https://example.com/favicon.ico">
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        assert result.error is None
        assert result.raw_data["title_tag"] == "Premium Online Store | Best Deals"
        assert result.raw_data["meta_description"] == "Shop the finest products online with fast shipping"
        assert result.raw_data["og_site_name"] == "My Premium Store"
        assert result.raw_data["og_description"] == "Discover quality products at unbeatable prices"
        assert result.raw_data["html_lang"] == "en-US"
        assert result.raw_data["currency"] == "USD"
        assert result.raw_data["favicon_url"] == "https://example.com/favicon.ico"

    @pytest.mark.asyncio
    async def test_extract_meta_tags_with_shortcut_icon(self, extractor):
        """Extract favicon using shortcut icon rel."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <link rel="shortcut icon" href="/favicon.png">
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        assert result.raw_data["favicon_url"] == "/favicon.png"


class TestMerchantProfileExtractorSocialLinks:
    """Tests for social media link extraction."""

    @pytest.mark.asyncio
    async def test_extract_social_links(self, extractor):
        """Extract social media links from anchor tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head></head>
        <body>
            <footer>
                <a href="https://facebook.com/mystore">Follow us on Facebook</a>
                <a href="https://instagram.com/mystore">Instagram</a>
                <a href="https://twitter.com/mystore_official">Twitter</a>
                <a href="https://www.linkedin.com/company/mystore">LinkedIn</a>
                <a href="https://tiktok.com/@mystore">TikTok</a>
                <a href="https://youtube.com/channel/UCmystore">YouTube</a>
                <a href="https://pinterest.com/mystore/">Pinterest</a>
            </footer>
        </body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        assert result.error is None
        social = result.raw_data.get("social_links", {})
        assert social.get("facebook") == "https://facebook.com/mystore"
        assert social.get("instagram") == "https://instagram.com/mystore"
        assert social.get("twitter") == "https://twitter.com/mystore_official"
        assert social.get("linkedin") == "https://www.linkedin.com/company/mystore"
        assert social.get("tiktok") == "https://tiktok.com/@mystore"
        assert social.get("youtube") == "https://youtube.com/channel/UCmystore"
        assert social.get("pinterest") == "https://pinterest.com/mystore/"

    @pytest.mark.asyncio
    async def test_extract_social_links_x_com_twitter(self, extractor):
        """Extract X (formerly Twitter) links."""
        html = """
        <!DOCTYPE html>
        <html>
        <body>
            <a href="https://x.com/mystore">Follow on X</a>
        </body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        social = result.raw_data.get("social_links", {})
        assert social.get("twitter") == "https://x.com/mystore"

    @pytest.mark.asyncio
    async def test_extract_no_duplicate_social_links(self, extractor):
        """Verify social links are not duplicated."""
        html = """
        <!DOCTYPE html>
        <html>
        <body>
            <a href="https://facebook.com/mystore">Facebook 1</a>
            <a href="https://facebook.com/mystore">Facebook 2</a>
            <a href="https://instagram.com/mystore">Instagram</a>
        </body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        social = result.raw_data.get("social_links", {})
        # Should only have one Facebook link even if listed twice
        assert social.get("facebook") == "https://facebook.com/mystore"
        assert social.get("instagram") == "https://instagram.com/mystore"


class TestMerchantProfileExtractorAnalytics:
    """Tests for analytics/tracking tag extraction."""

    @pytest.mark.asyncio
    async def test_extract_analytics_google_analytics(self, extractor):
        """Extract Google Analytics tracking codes (UA and GA4)."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script>
            var ga_id = 'UA-123456-1';
            var ga4_id = 'G-ABCDEF1234';
            gtag('config', 'UA-123456-1');
            gtag('config', 'G-ABCDEF1234');
            </script>
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        analytics = result.raw_data.get("analytics_tags", [])
        ua_tags = [t for t in analytics if "UA" in t.get("tag_type", "")]
        ga4_tags = [t for t in analytics if "GA4" in t.get("tag_type", "")]

        assert len(ua_tags) >= 1
        assert len(ga4_tags) >= 1
        assert any(t["tag_id"] == "UA-123456-1" for t in ua_tags)
        assert any(t["tag_id"] == "G-ABCDEF1234" for t in ga4_tags)

    @pytest.mark.asyncio
    async def test_extract_analytics_gtm(self, extractor):
        """Extract Google Tag Manager container ID."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script>
            (function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
            new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
            j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
            'https://www.googletagmanager.com/gtm.js?id=GTM-K12AB34'+dl;f.parentNode.insertBefore(j,f);
            })(window,document,'script','dataLayer','GTM-K12AB34');
            </script>
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        analytics = result.raw_data.get("analytics_tags", [])
        gtm_tags = [t for t in analytics if "GTM" in t.get("tag_type", "")]

        assert len(gtm_tags) >= 1
        assert any(t["tag_id"] == "GTM-K12AB34" for t in gtm_tags)

    @pytest.mark.asyncio
    async def test_extract_analytics_adsense(self, extractor):
        """Extract Google AdSense publisher ID."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1234567890123456"></script>
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        analytics = result.raw_data.get("analytics_tags", [])
        adsense_tags = [t for t in analytics if "AdSense" in t.get("tag_type", "")]

        assert len(adsense_tags) >= 1
        assert any(t["tag_id"] == "ca-pub-1234567890123456" for t in adsense_tags)

    @pytest.mark.asyncio
    async def test_extract_analytics_facebook_pixel(self, extractor):
        """Extract Facebook Pixel ID."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script>
            !function(f,b,e,v,n,t,s)
            {if(f.fbq)return;n=f.fbq=function(){n.callMethod?
            n.callMethod.apply(n,arguments):n.queue.push(arguments)};
            n.queue=[];t=b.createElement(e);t.async=!0;
            t.src=v;s=b.getElementsByTagName(e)[0];
            s.parentNode.insertBefore(t,s)}(window, document,'script',
            'https://connect.facebook.net/en_US/fbevents.js');
            fbq('init', '1234567890123456');
            fbq('track', 'PageView');
            </script>
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        analytics = result.raw_data.get("analytics_tags", [])
        pixel_tags = [t for t in analytics if "Pixel" in t.get("tag_type", "")]

        assert len(pixel_tags) >= 1
        assert any(t["tag_id"] == "1234567890123456" for t in pixel_tags)

    @pytest.mark.asyncio
    async def test_extract_analytics_multiple(self, extractor):
        """Extract multiple different analytics tags from same page."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script>
            gtag('config', 'UA-111111-1');
            gtag('config', 'G-AAAABBBB00');
            (function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});
            var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';
            j.src='https://www.googletagmanager.com/gtm.js?id=GTM-ABC1234'+dl;f.parentNode.insertBefore(j,f);
            })(window,document,'script','dataLayer','GTM-ABC1234');
            fbq('init', '9876543210987654');
            </script>
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        analytics = result.raw_data.get("analytics_tags", [])

        assert len(analytics) >= 4
        providers = [t["tag_type"] for t in analytics]
        assert "UA" in providers
        assert "GA4" in providers
        assert "GTM" in providers
        assert "Pixel" in providers

    @pytest.mark.asyncio
    async def test_extract_analytics_cdn_detection_via_network(self, extractor):
        """Detect third-party services via network requests when browser crawl is used.

        CDN-based detection (klaviyo, mailchimp, etc.) is now handled by
        _detect_third_party_services() via network request analysis from crawl4ai,
        rather than HTML string scanning. This test verifies the network detection
        path by simulating a crawl result with network requests.
        """
        # Simulate crawl4ai network requests containing third-party CDN domains
        mock_crawl_result = MagicMock()
        mock_crawl_result.success = True
        mock_crawl_result.html = "<html><body></body></html>"
        mock_crawl_result.metadata = {}
        mock_crawl_result.links = {"external": []}
        mock_crawl_result.network_requests = [
            {"url": "https://a.klaviyo.com/onsite/js/klaviyo.js?company_id=ABC123"},
            {"url": "https://chimpstatic.com/mcjs.js?v=2"},
        ]

        services = extractor._detect_third_party_services(mock_crawl_result)
        providers = [s["provider"] for s in services]

        assert "klaviyo" in providers
        assert "mailchimp" in providers
        # Verify service categories
        klaviyo_service = next(s for s in services if s["provider"] == "klaviyo")
        assert klaviyo_service["tag_type"] == "Email Marketing"
        assert klaviyo_service["tag_id"] is None


class TestMerchantProfileExtractorContactInfo:
    """Tests for contact information extraction."""

    @pytest.mark.asyncio
    async def test_extract_contact_info_mailto(self, extractor):
        """Extract email addresses from mailto links."""
        html = """
        <!DOCTYPE html>
        <html>
        <body>
            <a href="mailto:sales@example.com">Email Sales</a>
            <a href="mailto:support@example.com">Support</a>
            <footer>
                Contact: info@example.com
            </footer>
        </body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        emails = result.raw_data.get("emails", [])
        assert "sales@example.com" in emails
        assert "support@example.com" in emails

    @pytest.mark.asyncio
    async def test_extract_contact_info_tel(self, extractor):
        """Extract phone numbers from tel links."""
        html = """
        <!DOCTYPE html>
        <html>
        <body>
            <a href="tel:+1-555-123-4567">Call Us</a>
            <a href="tel:(555)987-6543">Phone</a>
            <footer>
                <p>Main: 555-111-2222</p>
            </footer>
        </body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        phones = result.raw_data.get("phones", [])
        assert len(phones) >= 2
        assert "+1-555-123-4567" in phones
        assert "(555)987-6543" in phones


class TestMerchantProfileExtractorEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_extract_empty_html(self, extractor):
        """Gracefully handle minimal/empty HTML."""
        html = """
        <!DOCTYPE html>
        <html>
        <head></head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        # Should not crash, returns empty/minimal data
        assert result.error is None
        assert isinstance(result.raw_data, dict)
        assert result.confidence == 0.0  # Empty page has no confidence

    @pytest.mark.asyncio
    async def test_extract_malformed_jsonld(self, extractor):
        """Handle malformed JSON-LD gracefully."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "Good Company",
                "broken json here }{
            </script>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "Fallback Company"
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        result = await extractor.extract("https://example.com", html)

        # Should fall back to next JSON-LD block
        assert result.error is None
        assert result.raw_data.get("jsonld_company_name") == "Fallback Company"

    @pytest.mark.asyncio
    async def test_extract_confidence_scoring(self, extractor):
        """Verify confidence score is calculated correctly."""
        html_minimal = "<html><body></body></html>"
        html_full = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>My Store</title>
            <meta name="description" content="Buy quality products">
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "My Store Inc",
                "logo": "https://example.com/logo.png",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "123 Main St",
                    "addressLocality": "Portland"
                }
            }
            </script>
        </head>
        <body>
            <a href="mailto:hello@store.com">Contact</a>
            <a href="https://facebook.com/mystore">Facebook</a>
            <script>gtag('config', 'G-ABC123');</script>
        </body>
        </html>
        """

        result_minimal = await extractor.extract("https://example.com", html_minimal)
        result_full = await extractor.extract("https://example.com", html_full)

        # Minimal page should have lower confidence
        assert result_minimal.confidence < result_full.confidence
        # Full page should have high confidence (multiple fields populated)
        assert result_full.confidence >= 0.6

    @pytest.mark.asyncio
    async def test_extract_with_subpage_mocking(self, extractor):
        """Test extraction with mocked subpage probing."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Store Home</title>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "My Store"
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        # Mock the subpage probing
        with patch.object(extractor, "_probe_subpages") as mock_probe:
            mock_probe.return_value = {
                "pages_crawled": ["https://example.com/about"],
                "about_text": "Founded in 2020, we are committed to excellence.",
                "emails": ["about@example.com"],
                "phones": [],
                "social_links": {},
            }

            result = await extractor.extract("https://example.com", html)

            assert result.error is None
            assert result.raw_data.get("about_text") == "Founded in 2020, we are committed to excellence."
            assert "about@example.com" in result.raw_data.get("emails", [])
            assert "https://example.com/about" in result.pages_crawled


class TestSSRFProtection:
    """Tests for SSRF protection on subpage probing."""

    @pytest.mark.asyncio
    async def test_subpage_ssrf_validation_called(self):
        """Test that subpage URLs are validated against SSRF."""
        extractor = MerchantProfileExtractor()

        with patch("app.extractors.merchant_profile_extractor.URLValidator") as mock_validator:
            mock_validator.validate_async = AsyncMock(return_value=(True, "Valid"))

            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_client.get = AsyncMock(return_value=mock_response)

            extractor._client = mock_client
            await extractor._probe_subpages("https://example.com")

            # Should have called validate_async for each subpage path
            assert mock_validator.validate_async.call_count > 0


class TestContentLengthEdgeCases:
    """Tests for safe content-length parsing."""

    @pytest.mark.asyncio
    async def test_malformed_content_length_handled(self):
        """Test that malformed content-length doesn't crash."""
        extractor = MerchantProfileExtractor()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-length": "not-a-number"}
        mock_response.text = "<html><body>test</body></html>"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        extractor._client = mock_client
        # Should not raise
        result = await extractor._fetch_page("https://example.com")
        assert result is not None


class TestAnalyticsCommentStripping:
    """Tests for analytics tag extraction with HTML comments."""

    def test_analytics_in_comments_not_extracted(self):
        """Test that analytics tags inside HTML comments are ignored."""
        extractor = MerchantProfileExtractor()

        html = """
        <!-- Old analytics: UA-123456-1 -->
        <script>
        // Active tag
        gtag('config', 'G-ACTIVE123');
        </script>
        """

        tags = extractor._extract_analytics_tags(html)
        tag_ids = [t["tag_id"] for t in tags]

        assert "UA-123456-1" not in tag_ids
        assert "G-ACTIVE123" in tag_ids


class TestGA4FalsePositives:
    """Tests for GA4/GTM case-sensitive matching."""

    def test_css_class_names_not_matched_as_ga4(self):
        """CSS class names like g-recaptcha, g-tables should not match GA4 pattern."""
        extractor = MerchantProfileExtractor()

        html = """
        <div class="g-recaptcha" data-sitekey="xyz"></div>
        <div class="g-tables g-boards g-content"></div>
        <script>gtag('config', 'G-Q39M3TMSTY');</script>
        """

        tags = extractor._extract_analytics_tags(html)
        ga4_tags = [t for t in tags if t["tag_type"] == "GA4"]

        assert len(ga4_tags) == 1
        assert ga4_tags[0]["tag_id"] == "G-Q39M3TMSTY"

    def test_lowercase_gtm_not_matched(self):
        """Lowercase gtm- prefixes should not match GTM pattern."""
        extractor = MerchantProfileExtractor()

        html = """
        <div class="gtm-manager gtm-element"></div>
        <script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC1234"></script>
        """

        tags = extractor._extract_analytics_tags(html)
        gtm_tags = [t for t in tags if t["tag_type"] == "GTM"]

        assert len(gtm_tags) == 1
        assert gtm_tags[0]["tag_id"] == "GTM-ABC1234"


class TestNonAsciiHandling:
    """Tests for non-ASCII character handling."""

    def test_unicode_company_name_in_jsonld(self):
        """Test extraction of Unicode company names from JSON-LD."""
        extractor = MerchantProfileExtractor()

        html = """<html><head>
        <script type="application/ld+json">
        {"@type": "Organization", "name": "Ünïcödé Störe GmbH"}
        </script>
        </head><body></body></html>"""

        soup = BeautifulSoup(html, "html.parser")
        result = extractor._extract_jsonld_organization(soup)
        assert result.get("company_name") == "Ünïcödé Störe GmbH"

    def test_unicode_in_meta_description(self):
        """Test extraction of Unicode meta descriptions."""
        extractor = MerchantProfileExtractor()

        html = """<html><head>
        <meta name="description" content="Bäckerei & Café — frische Brötchen täglich">
        </head><body></body></html>"""

        soup = BeautifulSoup(html, "html.parser")
        result = extractor._extract_meta_tags(soup)
        assert "Bäckerei" in result.get("meta_description", "")


class TestHTMLEntityHandling:
    """Tests for HTML entity handling in extraction."""

    def test_html_entities_in_email(self):
        """Test that HTML entities in mailto links are decoded."""
        extractor = MerchantProfileExtractor()

        html = '<html><body><a href="mailto:info&#64;example.com">Contact</a></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        result = extractor._extract_contact_info(soup)
        assert len(result["emails"]) >= 1


class TestExtractMetaFromCrawlResult:
    """Tests for _extract_meta_from_crawl_result (crawl4ai metadata path)."""

    def test_maps_crawl4ai_metadata_keys(self):
        """Map crawl4ai metadata fields to expected raw_data keys."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.metadata = {
            "title": "My Store — Best Products",
            "description": "We sell quality stuff",
            "og:site_name": "My Store",
            "og:description": "OG description text",
        }
        mock_result.html = "<html lang='de'><head></head><body></body></html>"

        meta = extractor._extract_meta_from_crawl_result(mock_result)

        assert meta["title_tag"] == "My Store — Best Products"
        assert meta["meta_description"] == "We sell quality stuff"
        assert meta["og_site_name"] == "My Store"
        assert meta["og_description"] == "OG description text"
        assert meta["html_lang"] == "de"

    def test_extracts_currency_and_favicon_from_html(self):
        """Currency and favicon are parsed from HTML since crawl4ai doesn't expose them."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.metadata = {}
        mock_result.html = """
        <html>
        <head>
            <meta property="og:price:currency" content="EUR">
            <link rel="icon" href="/favicon.ico">
        </head>
        <body></body>
        </html>
        """

        meta = extractor._extract_meta_from_crawl_result(mock_result)

        assert meta["currency"] == "EUR"
        assert meta["favicon_url"] == "/favicon.ico"

    def test_handles_empty_metadata(self):
        """Return empty dict when metadata is None or empty."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.metadata = None
        mock_result.html = None

        meta = extractor._extract_meta_from_crawl_result(mock_result)
        assert meta == {}

    def test_product_price_currency_fallback(self):
        """Fall back to product:price:currency when og:price:currency is missing."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.metadata = {}
        mock_result.html = """
        <html><head>
            <meta property="product:price:currency" content="GBP">
        </head><body></body></html>
        """

        meta = extractor._extract_meta_from_crawl_result(mock_result)
        assert meta["currency"] == "GBP"


class TestExtractSocialFromCrawlResult:
    """Tests for _extract_social_from_crawl_result (crawl4ai external links path)."""

    def test_classifies_external_links_as_social(self):
        """Classify crawl4ai external links into social media platforms."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.links = {
            "external": [
                {"href": "https://facebook.com/mystore"},
                {"href": "https://instagram.com/mystore"},
                {"href": "https://x.com/mystore"},
                {"href": "https://www.example.com/unrelated"},
            ]
        }

        social = extractor._extract_social_from_crawl_result(mock_result)

        assert social.get("facebook") == "https://facebook.com/mystore"
        assert social.get("instagram") == "https://instagram.com/mystore"
        assert social.get("twitter") == "https://x.com/mystore"
        assert "example.com" not in str(social.values())

    def test_handles_string_links(self):
        """Handle links as plain strings (not dicts)."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.links = {
            "external": [
                "https://youtube.com/channel/UCtest",
                "https://tiktok.com/@mystore",
            ]
        }

        social = extractor._extract_social_from_crawl_result(mock_result)

        assert social.get("youtube") == "https://youtube.com/channel/UCtest"
        assert social.get("tiktok") == "https://tiktok.com/@mystore"

    def test_handles_empty_links(self):
        """Return empty dict when no external links."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.links = None

        social = extractor._extract_social_from_crawl_result(mock_result)
        assert social == {}

    def test_deduplicates_social_links(self):
        """First link wins when multiple links match the same platform."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.links = {
            "external": [
                {"href": "https://facebook.com/first"},
                {"href": "https://facebook.com/second"},
            ]
        }

        social = extractor._extract_social_from_crawl_result(mock_result)
        assert social.get("facebook") == "https://facebook.com/first"


class TestDetectThirdPartyServices:
    """Tests for _detect_third_party_services (network request analysis)."""

    def test_detects_multiple_service_categories(self):
        """Detect services across different categories from network requests."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.network_requests = [
            {"url": "https://js.stripe.com/v3/"},
            {"url": "https://widget.trustpilot.com/scripts/loader.js"},
            {"url": "https://static.zdassets.com/zendesk/widget.js"},
            {"url": "https://cdn.cookielaw.org/consent/abc/init.js"},
            {"url": "https://fonts.googleapis.com/css2?family=Roboto"},
        ]

        services = extractor._detect_third_party_services(mock_result)
        providers = {s["provider"] for s in services}

        assert "stripe" in providers
        assert "trustpilot" in providers
        assert "zendesk" in providers
        assert "onetrust" in providers
        assert "google_fonts" in providers

        # Verify categories
        stripe = next(s for s in services if s["provider"] == "stripe")
        assert stripe["tag_type"] == "Payments"
        assert stripe["tag_id"] is None

    def test_deduplicates_by_provider(self):
        """Same provider from multiple URLs should appear only once."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.network_requests = [
            {"url": "https://js.stripe.com/v3/"},
            {"url": "https://js.stripe.com/v3/fingerprinted-abc.js"},
            {"url": "https://js.stripe.com/v2/checkout.js"},
        ]

        services = extractor._detect_third_party_services(mock_result)
        assert len(services) == 1
        assert services[0]["provider"] == "stripe"

    def test_handles_empty_network_requests(self):
        """Return empty list when no network requests."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.network_requests = None

        services = extractor._detect_third_party_services(mock_result)
        assert services == []

    def test_handles_malformed_urls(self):
        """Skip malformed URLs without crashing."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.network_requests = [
            {"url": "not-a-url"},
            {"url": ""},
            {"url": None},
            {},
            {"url": "https://js.stripe.com/v3/"},
        ]

        services = extractor._detect_third_party_services(mock_result)
        assert len(services) == 1
        assert services[0]["provider"] == "stripe"

    def test_handles_attentive_duplicate_domains(self):
        """Attentive has two domain patterns — both map to same provider."""
        extractor = MerchantProfileExtractor()

        mock_result = MagicMock()
        mock_result.network_requests = [
            {"url": "https://cdn.attentive.com/sdk.js"},
            {"url": "https://events.attn.tv/v1/track"},
        ]

        services = extractor._detect_third_party_services(mock_result)
        attentive = [s for s in services if s["provider"] == "attentive"]
        assert len(attentive) == 1


class TestMergeNetworkServices:
    """Tests for _merge_network_services (dedup by provider, keep regex IDs)."""

    def test_adds_new_network_services(self):
        """Add network-detected services not found by regex."""
        extractor = MerchantProfileExtractor()

        analytics_tags = [
            {"provider": "google_analytics_ga4", "tag_id": "G-ABC123", "tag_type": "GA4"},
        ]
        network_services = [
            {"provider": "stripe", "tag_id": None, "tag_type": "Payments"},
            {"provider": "klaviyo", "tag_id": None, "tag_type": "Email Marketing"},
        ]

        merged = extractor._merge_network_services(analytics_tags, network_services)

        assert len(merged) == 3
        providers = {t["provider"] for t in merged}
        assert "stripe" in providers
        assert "klaviyo" in providers

    def test_preserves_regex_extracted_ids(self):
        """When regex already found a provider, keep the regex version (has tag_id)."""
        extractor = MerchantProfileExtractor()

        analytics_tags = [
            {"provider": "google_analytics_ga4", "tag_id": "G-ABC123", "tag_type": "GA4"},
        ]
        network_services = [
            {"provider": "google_analytics_ga4", "tag_id": None, "tag_type": "Analytics"},
        ]

        merged = extractor._merge_network_services(analytics_tags, network_services)

        assert len(merged) == 1
        assert merged[0]["tag_id"] == "G-ABC123"

    def test_empty_inputs(self):
        """Handle empty analytics_tags and network_services."""
        extractor = MerchantProfileExtractor()

        assert extractor._merge_network_services([], []) == []
        assert len(extractor._merge_network_services([], [
            {"provider": "stripe", "tag_id": None, "tag_type": "Payments"}
        ])) == 1


class TestBrowserCrawlFallback:
    """Tests for extract() browser crawl vs BeautifulSoup fallback."""

    @pytest.mark.asyncio
    async def test_uses_crawl_result_when_no_html_provided(self):
        """When homepage_html is None, attempts browser crawl."""
        extractor = MerchantProfileExtractor()

        mock_crawl_result = MagicMock()
        mock_crawl_result.success = True
        mock_crawl_result.html = """
        <html lang="en">
        <head>
            <title>Browser Crawled Store</title>
            <meta property="og:site_name" content="Crawled Store">
        </head>
        <body>
            <a href="https://facebook.com/crawled">FB</a>
        </body>
        </html>
        """
        mock_crawl_result.metadata = {
            "title": "Browser Crawled Store",
            "og:site_name": "Crawled Store",
        }
        mock_crawl_result.links = {
            "external": [{"href": "https://facebook.com/crawled"}]
        }
        mock_crawl_result.network_requests = [
            {"url": "https://js.stripe.com/v3/"},
        ]

        with patch.object(extractor, "_browser_crawl", return_value=mock_crawl_result):
            with patch.object(extractor, "_probe_subpages", return_value={
                "pages_crawled": [], "about_text": None,
                "emails": [], "phones": [], "social_links": {},
            }):
                result = await extractor.extract("https://example.com", homepage_html=None)

        assert result.error is None
        assert result.raw_data["title_tag"] == "Browser Crawled Store"
        assert result.raw_data["og_site_name"] == "Crawled Store"
        social = result.raw_data.get("social_links", {})
        assert social.get("facebook") == "https://facebook.com/crawled"
        # Stripe detected via network
        analytics = result.raw_data.get("analytics_tags", [])
        stripe_tags = [t for t in analytics if t["provider"] == "stripe"]
        assert len(stripe_tags) == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_beautifulsoup_when_html_provided(self):
        """When homepage_html is provided, skips browser crawl entirely."""
        extractor = MerchantProfileExtractor()

        html = """
        <html>
        <head><title>Provided HTML Store</title></head>
        <body>
            <a href="https://instagram.com/provided">IG</a>
        </body>
        </html>
        """

        with patch.object(extractor, "_browser_crawl") as mock_crawl:
            with patch.object(extractor, "_probe_subpages", return_value={
                "pages_crawled": [], "about_text": None,
                "emails": [], "phones": [], "social_links": {},
            }):
                result = await extractor.extract("https://example.com", homepage_html=html)

        # Browser crawl should NOT have been called
        mock_crawl.assert_not_called()
        assert result.error is None
        assert result.raw_data["title_tag"] == "Provided HTML Store"
        social = result.raw_data.get("social_links", {})
        assert social.get("instagram") == "https://instagram.com/provided"

    @pytest.mark.asyncio
    async def test_falls_back_to_httpx_when_browser_crawl_fails(self):
        """When browser crawl returns None, falls back to httpx fetch."""
        extractor = MerchantProfileExtractor()

        with patch.object(extractor, "_browser_crawl", return_value=None):
            with patch.object(extractor, "_fetch_page", return_value="<html><head><title>Fetched</title></head><body></body></html>"):
                with patch.object(extractor, "_probe_subpages", return_value={
                    "pages_crawled": [], "about_text": None,
                    "emails": [], "phones": [], "social_links": {},
                }):
                    result = await extractor.extract("https://example.com", homepage_html=None)

        assert result.error is None
        assert result.raw_data["title_tag"] == "Fetched"
