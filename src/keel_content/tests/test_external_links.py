"""External-link gate: allowlist, rendering, idempotent append (HTTP mocked)."""

from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase

from keel_content.core import external_links as ext
from keel_content.core.external_links import (
    SourceCheck,
    apply_external_sources,
    domain_allowed,
    domain_blocked,
    domain_of,
    is_domain_root,
    render_sources_markdown,
    strip_sources_section,
    verify_sources,
)


class DomainAllowlistTests(SimpleTestCase):
    def test_www_is_stripped(self):
        self.assertEqual(domain_of("https://www.cftc.gov/x"), "cftc.gov")

    def test_allowlisted_domain_and_subdomain(self):
        self.assertTrue(domain_allowed("https://en.wikipedia.org/wiki/Forex"))
        self.assertTrue(domain_allowed("https://www.cftc.gov/Learn"))

    def test_competitor_or_random_domain_blocked(self):
        self.assertFalse(domain_allowed("https://pocketoption.com/promo"))
        self.assertFalse(domain_allowed("https://some-random-blog.example/post"))

    def test_lookalike_suffix_not_allowed(self):
        # "notcftc.gov" must NOT be treated as a subdomain of cftc.gov
        self.assertFalse(domain_allowed("https://notcftc.gov/x"))

    def test_expanded_fast_lane_domains(self):
        # A sample from each category added in the 2026-07 diversity expansion.
        for url in (
            "https://www.cysec.gov.cy/en-GB/entities/investment-firms/",  # intl regulator
            "https://fred.stlouisfed.org/series/DEXUSEU",  # central-bank data (subdomain)
            "https://www.eia.gov/petroleum/",  # macro/stats
            "https://www.euronext.com/en/markets",  # exchange
            "https://help.ctrader.com/ctrader-automate/",  # platform docs
            "https://www.coindesk.com/learn/",  # crypto journalism
            "https://www.reuters.com/markets/",  # non-paywalled newswire
            "https://www.nber.org/papers/w12345",  # research
            "https://www.cfainstitute.org/insights",  # education
        ):
            self.assertTrue(domain_allowed(url), url)

    def test_paywalled_press_and_promoted_partners_stay_off(self):
        # Deliberately absent: hard-paywalled press + brokers/exchanges of any kind.
        for url in (
            "https://www.bloomberg.com/x",
            "https://www.ft.com/x",
            "https://www.wsj.com/x",
            "https://academy.binance.com/en/articles/x",
        ):
            self.assertFalse(domain_allowed(url), url)

    def test_invalid_url(self):
        self.assertFalse(domain_allowed("not a url"))


class DenylistTests(SimpleTestCase):
    def test_url_shortener_is_blocked(self):
        self.assertTrue(domain_blocked("https://bit.ly/abc"))
        self.assertTrue(domain_blocked("https://www.tinyurl.com/x"))

    def test_trusted_and_random_domains_not_blocked(self):
        # The denylist is a small reader-safety floor, not the authority gate.
        self.assertFalse(domain_blocked("https://cftc.gov/x"))
        self.assertFalse(domain_blocked("https://some-random-blog.example/post"))


class TieredTrustTests(SimpleTestCase):
    """Off-fast-lane hosts survive only when the relevance gate marked them vetted."""

    def _live(self, urls):
        def _http_ok(url, *, session):
            ok = url in urls
            return (ok, 200 if ok else 404, "" if ok else "status 404")
        return _http_ok

    def test_vetted_offlist_domain_kept_when_live(self):
        # A competitor's genuinely-educational page, promoted by the gate.
        sources = [{"url": "https://competitor.example/guide", "anchor": "Competitor — a good explainer", "role": "further_reading", "vetted": True}]
        with mock.patch.object(ext, "_http_ok", self._live({"https://competitor.example/guide"})):
            _, report = apply_external_sources("Body.", sources)
        self.assertEqual(len(report.verified), 1)
        self.assertEqual(report.dropped, [])

    def test_tier_marker_alias_is_honored(self):
        sources = [{"url": "https://pub.example/article", "anchor": "Reputable publication", "role": "further_reading", "tier": "vetted"}]
        with mock.patch.object(ext, "_http_ok", self._live({"https://pub.example/article"})):
            _, report = apply_external_sources("Body.", sources)
        self.assertEqual(len(report.verified), 1)

    def test_unvetted_offlist_domain_dropped(self):
        # No vetted marker → the off-fast-lane host is dropped even though it is live.
        sources = [{"url": "https://randomblog.example/x", "anchor": "Random blog", "role": "further_reading"}]
        with mock.patch.object(ext, "_http_ok", self._live({"https://randomblog.example/x"})):
            _, report = apply_external_sources("Body.", sources)
        self.assertEqual(report.verified, [])
        self.assertEqual(len(report.dropped), 1)

    def test_blocked_domain_beats_vetted_marker(self):
        # A shortener stays dropped even if a bundle claims it is vetted.
        sources = [{"url": "https://bit.ly/abc", "anchor": "Shortened", "role": "further_reading", "vetted": True}]
        with mock.patch.object(ext, "_http_ok", self._live({"https://bit.ly/abc"})):
            _, report = apply_external_sources("Body.", sources)
        self.assertEqual(report.verified, [])
        self.assertEqual(len(report.dropped), 1)


class RenderTests(SimpleTestCase):
    def test_empty_renders_nothing(self):
        self.assertEqual(render_sources_markdown([]), "")

    def test_citations_render_before_further_reading(self):
        verified = [
            SourceCheck("https://a.org/x", "Further A", "further_reading", True),
            SourceCheck("https://cftc.gov/y", "Cite B", "citation", True),
        ]
        out = render_sources_markdown(verified)
        self.assertIn("## Sources & Further Reading {#sources}", out)
        self.assertLess(out.index("Cite B"), out.index("Further A"))
        self.assertIn("- [Cite B](https://cftc.gov/y)", out)

    def test_strip_is_idempotent(self):
        body = "Body text.\n\n## Sources & Further Reading {#sources}\n\nlead\n\n- [x](https://x.org)\n"
        self.assertEqual(strip_sources_section(body), "Body text.")


class ApplyTests(SimpleTestCase):
    def _fake_http(self, ok_urls):
        def _http_ok(url, *, session):
            return (url in ok_urls, 200 if url in ok_urls else 404, "" if url in ok_urls else "status 404")
        return _http_ok

    def test_only_allowlisted_and_live_links_survive(self):
        sources = [
            {"url": "https://en.wikipedia.org/wiki/Forex", "anchor": "Wiki Forex", "role": "citation"},
            {"url": "https://pocketoption.com/x", "anchor": "Broker", "role": "citation"},  # blocked domain
            {"url": "https://www.cftc.gov/dead", "anchor": "Dead reg page", "role": "further_reading"},  # 404
        ]
        live = {"https://en.wikipedia.org/wiki/Forex"}
        with mock.patch.object(ext, "_http_ok", self._fake_http(live)):
            body, report = apply_external_sources("Article body.", sources)
        self.assertEqual(len(report.verified), 1)
        self.assertEqual(len(report.dropped), 2)
        self.assertIn("- [Wiki Forex](https://en.wikipedia.org/wiki/Forex)", body)
        self.assertNotIn("pocketoption", body)
        self.assertNotIn("cftc.gov/dead", body)

    def test_reapply_replaces_not_duplicates(self):
        sources = [{"url": "https://en.wikipedia.org/wiki/Forex", "anchor": "Wiki", "role": "citation"}]
        live = {"https://en.wikipedia.org/wiki/Forex"}
        with mock.patch.object(ext, "_http_ok", self._fake_http(live)):
            body1, _ = apply_external_sources("Body.", sources)
            body2, _ = apply_external_sources(body1, sources)
        self.assertEqual(body1, body2)
        self.assertEqual(body2.count("{#sources}"), 1)

    def test_no_verified_leaves_body_clean(self):
        sources = [{"url": "https://pocketoption.com/x", "anchor": "Broker", "role": "citation"}]
        with mock.patch.object(ext, "_http_ok", self._fake_http(set())):
            body, report = apply_external_sources("Body.", sources)
        self.assertEqual(body, "Body.")
        self.assertEqual(report.verified, [])

    def test_dedupe_by_url(self):
        sources = [
            {"url": "https://en.wikipedia.org/wiki/Forex", "anchor": "Wiki 1", "role": "citation"},
            {"url": "https://en.wikipedia.org/wiki/Forex/", "anchor": "Wiki 2", "role": "citation"},
        ]
        live = {"https://en.wikipedia.org/wiki/Forex"}
        with mock.patch.object(ext, "_http_ok", self._fake_http(live)):
            _, report = apply_external_sources("Body.", sources)
        # second is a trailing-slash dupe of the first → only one checked
        self.assertEqual(len(report.verified) + len(report.dropped), 1)

    def test_verify_exempt_domain_kept_on_403(self):
        sources = [{"url": "https://www.investopedia.com/terms/c/copy-trading.asp", "anchor": "Investopedia — Copy trading", "role": "citation"}]
        with mock.patch.object(ext, "_http_ok", lambda url, *, session: (False, 403, "status 403")):
            body, report = apply_external_sources("Body.", sources)
        self.assertEqual(len(report.verified), 1)
        self.assertEqual(report.exempt_kept, 1)
        self.assertIn("https://www.investopedia.com/terms/c/copy-trading.asp", body)

    def test_verify_exempt_domain_dropped_on_404(self):
        # even a trusted bot-blocker is dropped when the page is genuinely gone
        sources = [{"url": "https://www.investopedia.com/terms/x/dead-zzz.asp", "anchor": "Investopedia — dead", "role": "citation"}]
        with mock.patch.object(ext, "_http_ok", lambda url, *, session: (False, 404, "status 404")):
            body, report = apply_external_sources("Body.", sources)
        self.assertEqual(report.verified, [])
        self.assertEqual(len(report.dropped), 1)

    def test_non_exempt_domain_still_dropped_on_403(self):
        # a 403 on a normal allowlisted domain (not a trusted bot-blocker) still drops
        sources = [{"url": "https://www.cftc.gov/some/page", "anchor": "CFTC page", "role": "citation"}]
        with mock.patch.object(ext, "_http_ok", lambda url, *, session: (False, 403, "status 403")):
            body, report = apply_external_sources("Body.", sources)
        self.assertEqual(report.verified, [])
        self.assertEqual(len(report.dropped), 1)


class WikipediaCapTests(SimpleTestCase):
    """At most two Wikipedia links ship per article — and the second only
    alongside at least one non-Wikipedia source; extras drop deterministically."""

    def _all_live(self):
        return lambda url, *, session: (True, 200, "")

    def test_third_wikipedia_link_dropped(self):
        sources = [
            {"url": "https://en.wikipedia.org/wiki/Foreign_exchange_market", "anchor": "Wiki — FX market", "role": "further_reading"},
            {"url": "https://en.wikipedia.org/wiki/Technical_analysis", "anchor": "Wiki — TA", "role": "further_reading"},
            {"url": "https://en.wikipedia.org/wiki/Order_(exchange)", "anchor": "Wiki — Order", "role": "further_reading"},
            {"url": "https://www.cftc.gov/LearnAndProtect", "anchor": "CFTC — Learn & Protect", "role": "further_reading"},
        ]
        with mock.patch.object(ext, "_http_ok", self._all_live()):
            report = verify_sources(sources)
        kept = [c.url for c in report.verified]
        self.assertEqual(len(kept), 3)
        self.assertIn("https://en.wikipedia.org/wiki/Technical_analysis", kept)
        self.assertIn("https://www.cftc.gov/LearnAndProtect", kept)
        self.assertEqual(len(report.dropped), 1)
        self.assertIn("wikipedia cap", report.dropped[0].reason)

    def test_two_wikipedia_ok_alongside_other_domain(self):
        sources = [
            {"url": "https://en.wikipedia.org/wiki/A", "anchor": "Wiki A", "role": "further_reading"},
            {"url": "https://en.wikipedia.org/wiki/B", "anchor": "Wiki B", "role": "further_reading"},
            {"url": "https://www.cftc.gov/x", "anchor": "CFTC", "role": "further_reading"},
        ]
        with mock.patch.object(ext, "_http_ok", self._all_live()):
            report = verify_sources(sources)
        self.assertEqual(len(report.verified), 3)
        self.assertEqual(report.dropped, [])

    def test_all_wikipedia_list_trimmed_to_one(self):
        sources = [
            {"url": "https://en.wikipedia.org/wiki/A", "anchor": "Wiki A", "role": "further_reading"},
            {"url": "https://en.wikipedia.org/wiki/B", "anchor": "Wiki B", "role": "further_reading"},
        ]
        with mock.patch.object(ext, "_http_ok", self._all_live()):
            report = verify_sources(sources)
        self.assertEqual([c.url for c in report.verified], ["https://en.wikipedia.org/wiki/A"])
        self.assertEqual(len(report.dropped), 1)
        self.assertIn("another domain", report.dropped[0].reason)

    def test_cap_not_consumed_by_dead_wiki_link(self):
        # A 404'd first Wikipedia link must not burn the cap for a live second one.
        dead = "https://en.wikipedia.org/wiki/Dead_page"
        live = "https://en.wikipedia.org/wiki/Technical_analysis"
        fake = lambda url, *, session: (url != dead, 404 if url == dead else 200, "" if url != dead else "status 404")  # noqa: E731
        sources = [
            {"url": dead, "anchor": "Wiki — dead", "role": "further_reading"},
            {"url": live, "anchor": "Wiki — TA", "role": "further_reading"},
        ]
        with mock.patch.object(ext, "_http_ok", fake):
            report = verify_sources(sources)
        self.assertEqual([c.url for c in report.verified], [live])

    def test_cap_enforced_when_verify_skipped(self):
        # verify=False still applies both the hard cap and the diversity trim.
        sources = [
            {"url": "https://en.wikipedia.org/wiki/A", "anchor": "Wiki A", "role": "further_reading"},
            {"url": "https://en.wikipedia.org/wiki/B", "anchor": "Wiki B", "role": "further_reading"},
        ]
        report = verify_sources(sources, verify=False)
        self.assertEqual(len(report.verified), 1)
        self.assertEqual(len(report.dropped), 1)
        self.assertIn("wikipedia cap", report.dropped[0].reason)


class DomainRootTests(SimpleTestCase):
    def test_bare_root_and_slash_are_roots(self):
        self.assertTrue(is_domain_root("https://www.fca.org.uk"))
        self.assertTrue(is_domain_root("https://www.fca.org.uk/"))

    def test_deep_page_is_not_a_root(self):
        self.assertFalse(is_domain_root("https://www.fca.org.uk/consumers/leverage"))
        self.assertFalse(is_domain_root("https://en.wikipedia.org/wiki/Forex"))

    def test_query_or_fragment_is_not_a_root(self):
        self.assertFalse(is_domain_root("https://x.example/?q=1"))
        self.assertFalse(is_domain_root("https://x.example/#a"))

    def test_non_http_or_empty_is_not_a_root(self):
        self.assertFalse(is_domain_root("/academy/foo"))
        self.assertFalse(is_domain_root(""))

    def test_verify_sources_drops_fast_lane_homepage(self):
        # Even a trusted fast-lane regulator homepage must be dropped (deep-link or drop).
        sources = [{"url": "https://www.cftc.gov/", "anchor": "CFTC", "role": "further_reading"}]
        with mock.patch.object(ext, "_http_ok", lambda url, *, session: (True, 200, "")):
            report = verify_sources(sources)
        self.assertEqual(report.verified, [])
        self.assertEqual(len(report.dropped), 1)
        self.assertIn("domain root", report.dropped[0].reason)
