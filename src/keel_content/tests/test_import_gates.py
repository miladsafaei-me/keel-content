"""Import-time safety gates: internal-link allowlist, intent-gate block, quality rubric."""

from __future__ import annotations

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from keel_content.adapters.signalbots import internal_link_violations
from keel_content.core.quality_rubric import check_bundle, cross_checks
from keel_seo.models import Landing


def _bundle(slug: str, body: str, **extra) -> dict:
    b = {
        "slug": slug,
        "title": "A Plain Heading",
        "h1": "A Plain On-Page Heading",
        "meta_title": "A Plain Heading",
        "meta_description": "A short description.",
        "excerpt": "A short excerpt.",
        "key_takeaways_markdown": "- one\n- two",
        "body_markdown": body,
        "target": "blog",
        "initial_status": "draft",
    }
    b.update(extra)
    return b


class InternalLinkViolationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Synthetic paths only — seed data migrations already populate real landings.
        Landing.objects.create(title="Gate alpha", url="/test-gates/alpha", is_indexable=True)
        # Registry rows may carry a trailing slash (legacy style) — must still match.
        Landing.objects.create(title="Gate beta", url="/test-gates/beta/", is_indexable=True)
        Landing.objects.create(title="Gate hidden", url="/test-gates/hidden", is_indexable=False)

    def _violations(self, body: str) -> list[str]:
        return internal_link_violations(_bundle("t", body))

    def test_allowlisted_link_passes(self):
        self.assertEqual(self._violations("See [alpha](/test-gates/alpha) today."), [])

    def test_trailing_slash_registry_row_matches_slashless_link(self):
        self.assertEqual(self._violations("Our [beta](/test-gates/beta) page."), [])

    def test_offlist_link_blocks(self):
        out = self._violations("See [this](/made-up-page).")
        self.assertEqual(len(out), 1)
        self.assertIn("not in the live indexable allowlist", out[0])

    def test_noindex_landing_blocks(self):
        out = self._violations("See [hidden](/test-gates/hidden).")
        self.assertTrue(any("allowlist" in v for v in out))

    def test_blog_link_blocks(self):
        out = self._violations("Read [a sibling](/blog/some-guess) first.")
        self.assertEqual(len(out), 1)
        self.assertIn("cluster-linking pass", out[0])

    def test_trailing_slash_on_link_blocks(self):
        out = self._violations("See [alpha](/test-gates/alpha/).")
        self.assertTrue(any("trailing slash" in v for v in out))

    def test_duplicate_target_blocks(self):
        out = self._violations(
            "See [alpha](/test-gates/alpha) and later [again](/test-gates/alpha)."
        )
        self.assertTrue(any("one link per distinct target" in v for v in out))

    def test_risk_warning_always_allowed_without_row(self):
        Landing.objects.filter(url__startswith="/risk-warning").delete()
        self.assertEqual(self._violations("Read the [risk warning](/risk-warning)."), [])

    def test_image_and_asset_paths_exempt(self):
        body = "![chart](/media/x.png) and [logo](/static/img/logo.svg)"
        self.assertEqual(self._violations(body), [])

    def test_fragment_and_query_normalized(self):
        self.assertEqual(self._violations("Jump to [alpha](/test-gates/alpha#faq)."), [])


class QualityRubricTests(TestCase):
    def test_fabricated_rating_fails(self):
        r = check_bundle(_bundle("t", "We give it 9.4/10 overall."))
        self.assertTrue(any("R4" in f for f in r["fails"]))

    def test_mt4_5_and_market_hours_do_not_trip_rating(self):
        r = check_bundle(_bundle("t", "MetaTrader 4 / 5 runs 24/5 in FX."))
        self.assertFalse(any("R4" in f for f in r["fails"]))

    def test_risk_trigger_without_link_fails(self):
        r = check_bundle(_bundle("t", "This backtest shows the edge."))
        self.assertTrue(any("R5" in f for f in r["fails"]))

    def test_risk_trigger_with_link_passes(self):
        r = check_bundle(
            _bundle("t", "This backtest shows the edge. See [risk warning](/risk-warning).")
        )
        self.assertFalse(any("R5" in f for f in r["fails"]))

    def test_cold_open_formula_warns(self):
        r = check_bundle(_bundle("t", "Most best-broker lists rank for humans, not bots."))
        self.assertTrue(any("R8" in w for w in r["warns"]))

    def test_shared_h2s_cross_warn(self):
        a = _bundle("a", "## Alpha Setup {#a}\n\nx\n\n## Beta Costs {#b}\n\nx\n\n## Gamma Risks {#c}\n\nx")
        b = _bundle("b", "## Alpha Setup {#a}\n\nx\n\n## Beta Costs {#b}\n\nx\n\n## Gamma Risks {#c}\n\nx")
        results = [check_bundle(a), check_bundle(b)]
        cross_checks([a, b], results)
        self.assertTrue(any("R9" in w for w in results[0]["warns"]))


class ContentImportGateTests(TestCase):
    """End-to-end gating via --dry-run (gates run; nothing is published)."""

    def _run(self, bundle: dict, *flags: str) -> str:
        tmp = Path(tempfile.mkdtemp())
        (tmp / f"{bundle['slug']}.bundle.json").write_text(
            json.dumps(bundle), encoding="utf-8"
        )
        out, err = StringIO(), StringIO()
        call_command("content_import", str(tmp), "--dry-run", *flags, stdout=out, stderr=err)
        return out.getvalue() + err.getvalue()

    def test_unsatisfied_intent_gate_blocks(self):
        bundle = _bundle(
            "gate-blocked-post",
            "Plain body.",
            intent_gate={"satisfied": False, "missing_essential": ["the answer"]},
        )
        output = self._run(bundle)
        self.assertIn("intent gate UNSATISFIED", output)
        self.assertIn("1 gate-blocked", output)

    def test_allow_unsatisfied_overrides(self):
        bundle = _bundle(
            "gate-allowed-post",
            "Plain body.",
            intent_gate={"satisfied": False, "missing_essential": ["the answer"]},
        )
        # --allow-no-figures: these bundles exercise the intent/link gates, not the
        # separate "at least one figure" floor (which would otherwise block them).
        output = self._run(bundle, "--allow-unsatisfied", "--allow-no-figures")
        self.assertIn("would create", output)
        self.assertIn("0 gate-blocked", output)

    def test_offlist_link_blocks_even_with_no_lint(self):
        bundle = _bundle("offlist-post", "See [x](/nowhere-real).")
        output = self._run(bundle, "--no-lint")
        self.assertIn("gate failed", output)
        self.assertIn("1 gate-blocked", output)

    def test_clean_bundle_would_create(self):
        output = self._run(_bundle("clean-post", "Plain body with no links."), "--allow-no-figures")
        self.assertIn("would create", output)
