"""Unit tests for the deterministic pre-ingest bundle lint — the publish gate.

``bundle_lint`` is the single hard gate that decides whether a generated bundle is
allowed to become a draft Post, so its rules are pinned here. Pure stdlib (no DB),
hence ``SimpleTestCase``.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from keel_content.core.bundle_lint import lint_bundle, lint_bundle_warnings


def _bundle(**over):
    base = {
        "slug": "a-fine-slug",
        "title": "A fine title",
        "h1": "A fine H1",
        "meta_title": "A fine meta title",
        "meta_description": "A fine meta description.",
        "key_takeaways_markdown": "- one\n- two\n- three",
        "body_markdown": "Plain educational prose with no inline styles.",
        "external_sources": [],
    }
    base.update(over)
    return base


class LintBundleHardTests(SimpleTestCase):
    def test_clean_bundle_passes(self):
        self.assertEqual(lint_bundle(_bundle()), [])

    def test_title_over_65_blocks(self):
        self.assertTrue(any("title 66" in v for v in lint_bundle(_bundle(title="T" * 66))))

    def test_h1_over_65_blocks(self):
        self.assertTrue(any("h1 66" in v for v in lint_bundle(_bundle(h1="H" * 66))))

    def test_meta_title_over_65_blocks(self):
        self.assertTrue(any("meta_title 66" in v for v in lint_bundle(_bundle(meta_title="M" * 66))))

    def test_meta_title_exactly_65_passes(self):
        self.assertEqual(lint_bundle(_bundle(meta_title="M" * 65)), [])

    def test_meta_description_over_160_blocks(self):
        self.assertTrue(
            any("meta_description 161" in v for v in lint_bundle(_bundle(meta_description="d" * 161)))
        )

    def test_takeaways_must_be_within_2_to_4(self):
        # out of range -> blocked
        self.assertTrue(lint_bundle(_bundle(key_takeaways_markdown="- one")))
        self.assertTrue(lint_bundle(_bundle(key_takeaways_markdown="- a\n- b\n- c\n- d\n- e")))
        # 2, 3, 4 -> clean
        self.assertEqual(lint_bundle(_bundle(key_takeaways_markdown="- a\n- b")), [])
        self.assertEqual(lint_bundle(_bundle(key_takeaways_markdown="- a\n- b\n- c")), [])
        self.assertEqual(lint_bundle(_bundle(key_takeaways_markdown="- a\n- b\n- c\n- d")), [])

    def test_missing_required_key_blocks(self):
        self.assertTrue(any("slug" in v for v in lint_bundle(_bundle(slug=""))))
        self.assertTrue(any("title" in v for v in lint_bundle(_bundle(title=""))))
        self.assertTrue(any("body_markdown" in v for v in lint_bundle(_bundle(body_markdown=""))))

    def test_malformed_container_blocks(self):
        self.assertTrue(any("facets" in v for v in lint_bundle(_bundle(facets=[]))))
        self.assertTrue(
            any("internal_links[0] missing target" in v
                for v in lint_bundle(_bundle(internal_links=[{"anchor": "x"}])))
        )
        self.assertTrue(
            any("external_sources[0] missing url" in v
                for v in lint_bundle(_bundle(external_sources=[{"anchor": "x"}])))
        )

    def test_inline_style_blocks(self):
        self.assertTrue(
            any("style=" in v for v in lint_bundle(_bundle(body_markdown='<div style="x">hi</div>')))
        )

    def test_lifestyle_word_does_not_trip_style_check(self):
        self.assertEqual(lint_bundle(_bundle(body_markdown="my lifestyle= choices")), [])

    def test_inline_handler_blocks(self):
        self.assertTrue(
            any("on*=" in v for v in lint_bundle(_bundle(body_markdown='<button onclick="x()">go</button>')))
        )

    def test_no_hard_domain_floor(self):
        # No-stats policy: sources are optional further reading, so 0 sources is fine.
        self.assertEqual(lint_bundle(_bundle(external_sources=[])), [])

    def test_cp_component_non_trade_hex_blocks(self):
        body = (
            "intro\n\n```cp-component\n"
            '{"component_id": "chart", "spec": {"series": [{"color": "#123456"}]}}\n'
            "```\n"
        )
        self.assertTrue(any("non-trade hex" in v for v in lint_bundle(_bundle(body_markdown=body))))

    def test_cp_component_trade_hex_passes(self):
        for hexval in ("#3bb273", "#df2c53", "#3bb273ff", "#DF2C53"):
            body = (
                "intro\n\n```cp-component\n"
                f'{{"component_id": "payoff", "spec": {{"up": "{hexval}"}}}}\n'
                "```\n"
            )
            self.assertEqual(lint_bundle(_bundle(body_markdown=body)), [], hexval)

    def test_hex_outside_cp_component_is_ignored(self):
        # A hex mentioned in prose (not a visual spec) is not a visual-correctness bug.
        self.assertEqual(lint_bundle(_bundle(body_markdown="the brand colour is #123456 historically")), [])


class LintBundleWarningTests(SimpleTestCase):
    def test_attributed_statistic_warns(self):
        w = lint_bundle_warnings(_bundle(body_markdown="According to a 2024 study, 73% of traders fail."))
        self.assertTrue(any("third-party statistic" in x for x in w))

    def test_illustrative_hypothetical_does_not_warn(self):
        w = lint_bundle_warnings(_bundle(body_markdown="Suppose you risk 100 dollars at 2 to 1 reward."))
        self.assertEqual(w, [])

    def test_single_domain_sources_warn(self):
        w = lint_bundle_warnings(
            _bundle(external_sources=[
                {"url": "https://en.wikipedia.org/a"},
                {"url": "https://en.wikipedia.org/b"},
            ])
        )
        self.assertTrue(any("single domain" in x for x in w))

    def test_diverse_domains_do_not_warn(self):
        w = lint_bundle_warnings(
            _bundle(external_sources=[
                {"url": "https://en.wikipedia.org/a"},
                {"url": "https://www.cftc.gov/b"},
            ])
        )
        self.assertEqual(w, [])

    def test_single_source_does_not_warn_on_domain(self):
        w = lint_bundle_warnings(_bundle(external_sources=[{"url": "https://en.wikipedia.org/a"}]))
        self.assertFalse(any("single domain" in x for x in w))

    def test_banned_phrase_in_our_voice_warns(self):
        w = lint_bundle_warnings(_bundle(body_markdown="Our bot delivers guaranteed profit every month."))
        self.assertTrue(any("banned phrase" in x and "own voice" in x for x in w))

    def test_banned_phrase_in_debunk_context_warns_softly(self):
        w = lint_bundle_warnings(
            _bundle(body_markdown="Be wary of any bot that promises risk-free returns — it is a scam.")
        )
        self.assertTrue(any("banned phrase" in x and "debunking context" in x for x in w))

    def test_clean_prose_has_no_banned_phrase_warning(self):
        w = lint_bundle_warnings(_bundle(body_markdown="Use a sensible reward-to-risk ratio."))
        self.assertFalse(any("banned phrase" in x for x in w))

    def test_anchor_honesty_dishonest_risk_link_warns(self):
        body = "See the [backtested result](/risk-warning) for details."
        self.assertTrue(any("anchor-honesty" in x for x in lint_bundle_warnings(_bundle(body_markdown=body))))

    def test_anchor_honesty_honest_risk_link_ok(self):
        body = "Read our [risk warning](/risk-warning) before trading."
        self.assertFalse(any("anchor-honesty" in x for x in lint_bundle_warnings(_bundle(body_markdown=body))))

    def test_intent_gate_unsatisfied_warns(self):
        w = lint_bundle_warnings(_bundle(intent_gate={"satisfied": False, "missing_essential": ["fees"]}))
        self.assertTrue(any("intent gate UNSATISFIED" in x for x in w))

    def test_intent_gate_satisfied_does_not_warn(self):
        w = lint_bundle_warnings(_bundle(intent_gate={"satisfied": True}))
        self.assertFalse(any("intent gate" in x for x in w))
