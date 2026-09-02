"""Tests for the republish route.

The one that matters most is the anti-bias guarantee: a competitor's visual must
never be able to add a visual need the brief did not already have. That is
structural — the matcher iterates over needs — and these tests pin it there so a
later refactor cannot quietly invert the loop.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from keel_content.republish.brief import (Need, needs_fingerprint, report,
                                          visual_opportunities)
from keel_content.republish.plan import validate_plan


def _needs():
    return [
        Need("v1", "Show that a binary option settles all-or-nothing while an "
                   "option keeps value", shape="contrast_table", section="Structure"),
        Need("v2", "Show the entry, stop and target of one gold setup on an hourly "
                   "chart", shape="price_chart", section="Worked example"),
        Need("v3", "Show the break-even hit rate implied by an eighty percent "
                   "payout", shape="payoff", section="Payout"),
    ]


def _gallery():
    return [
        {"label": "s1#3", "kind": "infographic",
         "alt": "Difference between binary options and options settlement value"},
        {"label": "s1#11", "kind": "chart",
         "alt": "Gold hourly chart with a buy entry zone marked"},
        {"label": "s2#5", "kind": "infographic",
         "alt": "Compounding strategy in binary options with stacks of coins"},
        {"label": "s2#9", "kind": "infographic",
         "alt": "Price action patterns wheel: pin bar, inside bar, head and shoulders"},
    ]


class BriefBiasTests(SimpleTestCase):
    def test_output_has_exactly_one_entry_per_need(self):
        opps = visual_opportunities(_needs(), _gallery())
        self.assertEqual([o.need.id for o in opps], ["v1", "v2", "v3"])

    def test_a_source_visual_matching_no_need_is_never_surfaced(self):
        opps = visual_opportunities(_needs(), _gallery())
        surfaced = {(o.match or {}).get("label") for o in opps if o.match}
        for tempting in ("s2#5", "s2#9"):
            self.assertNotIn(tempting, surfaced)

    def test_an_empty_brief_borrows_nothing_however_rich_the_sources(self):
        self.assertEqual(visual_opportunities([], _gallery()), [])

    def test_a_need_with_no_match_is_still_returned_and_drawn_from_scratch(self):
        opps = {o.need.id: o for o in visual_opportunities(_needs(), _gallery())}
        self.assertFalse(opps["v3"].reproduce)
        self.assertIn("from scratch", opps["v3"].as_dict()["action"])

    def test_a_real_match_is_found_and_scored(self):
        opps = {o.need.id: o for o in visual_opportunities(_needs(), _gallery())}
        self.assertEqual(opps["v1"].match["label"], "s1#3")
        self.assertEqual(opps["v2"].match["label"], "s1#11")
        self.assertGreater(opps["v2"].score, 0)

    def test_no_source_is_used_for_two_needs(self):
        needs = _needs() + [Need("v4", "Show that a binary option settles "
                                       "all-or-nothing while an option keeps value",
                                 shape="contrast_table")]
        opps = visual_opportunities(needs, _gallery())
        used = [(o.match or {}).get("label") for o in opps if o.match]
        self.assertEqual(len(used), len(set(used)))

    def test_kind_mismatch_blocks_a_lexically_close_match(self):
        needs = [Need("v", "Gold hourly chart with buy entry zone",
                      shape="price_chart")]
        flat = [{"label": "x#1", "kind": "infographic",
                 "alt": "Gold hourly chart with buy entry zone"}]
        self.assertFalse(visual_opportunities(needs, flat)[0].reproduce)

    def test_one_shared_word_is_not_a_match(self):
        needs = [Need("v", "Explain the payout ceiling", shape="table")]
        gallery = [{"label": "x#1", "kind": "infographic", "alt": "Payout"}]
        self.assertFalse(visual_opportunities(needs, gallery)[0].reproduce)

    def test_chart_sources_carry_the_do_not_read_numbers_warning(self):
        opps = {o.need.id: o for o in visual_opportunities(_needs(), _gallery())}
        self.assertTrue(any("recover its series" in n for n in opps["v2"].notes))

    def test_every_matched_need_is_told_to_reproduce_understanding_not_artwork(self):
        for opp in visual_opportunities(_needs(), _gallery()):
            if opp.reproduce:
                self.assertTrue(any("never ship" in n for n in opp.notes))

    def test_fingerprint_changes_when_a_need_is_edited(self):
        before = needs_fingerprint(_needs())
        edited = _needs()
        edited[0].comprehension_job = "Show a compounding strategy with coin stacks"
        self.assertNotEqual(before, needs_fingerprint(edited))

    def test_fingerprint_is_stable_for_the_same_needs(self):
        self.assertEqual(needs_fingerprint(_needs()), needs_fingerprint(_needs()))

    def test_report_mentions_only_needs(self):
        text = report(visual_opportunities(_needs(), _gallery()))
        self.assertIn("v1", text)
        self.assertNotIn("s2#5", text)
        self.assertNotIn("s2#9", text)


class PlanValidationTests(SimpleTestCase):
    def _post(self, **over):
        out = {"kind": "post", "slug": "a-slug", "from": ["s1"],
               "bundle": {"title": "T", "meta_title": "M",
                          "meta_description": "D", "excerpt": "E",
                          "key_takeaways_markdown": "- a\n- b",
                          "body_markdown": "body", "facets": {}}}
        out.update(over)
        return out

    def _graft(self, **over):
        out = {"kind": "graft", "target_slug": "s", "graft_id": "g",
               "anchor": {"mode": "after_heading", "text": "H"},
               "visual": {"component_id": "comparison_table", "spec": {}}}
        out.update(over)
        return out

    def test_a_valid_plan_reports_nothing(self):
        self.assertEqual(validate_plan({"outputs": [self._post(), self._graft()]}), [])

    def test_a_plan_needs_at_least_one_output(self):
        self.assertTrue(validate_plan({"outputs": []}))

    def test_a_graft_cannot_carry_both_a_visual_and_a_figure(self):
        bad = self._graft(figure={"builder": "hub_spokes", "alt": "a", "caption": "c"})
        problems = validate_plan({"outputs": [bad]})
        self.assertTrue(any("not both" in p for p in problems))

    def test_a_graft_must_carry_one_of_them(self):
        bad = self._graft()
        bad.pop("visual")
        self.assertTrue(any("needs either" in p for p in validate_plan({"outputs": [bad]})))

    def test_two_posts_cannot_share_a_slug(self):
        problems = validate_plan({"outputs": [self._post(), self._post()]})
        self.assertTrue(any("share the slug" in p for p in problems))

    def test_a_post_output_is_free_to_draw_on_several_sources(self):
        plan = {"outputs": [self._post(**{"from": ["s1", "s2", "s3"]})]}
        self.assertEqual(validate_plan(plan), [])

    def test_one_source_may_feed_several_posts(self):
        plan = {"outputs": [self._post(slug="a"), self._post(slug="b")]}
        self.assertEqual(validate_plan(plan), [])

    def test_the_schema_is_serializable(self):
        from keel_content.republish.plan import PLAN_SCHEMA
        json.dumps(PLAN_SCHEMA)
