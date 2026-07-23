"""Within-cluster blog->blog link insertion: prose-only, deduped, idempotent."""

from __future__ import annotations

from django.test import SimpleTestCase

from keel_content.core.internal_links import (
    apply_internal_links,
    strip_internal_blog_links,
)


def _links(*pairs):
    return [{"anchor": a, "target_url": u} for a, u in pairs]


class StripInternalBlogLinksTests(SimpleTestCase):
    def test_unwraps_relative_blog_link_to_plain_anchor(self):
        body = "See [best cTrader broker](/blog/best-ctrader-brokers) for picks."
        self.assertEqual(
            strip_internal_blog_links(body),
            "See best cTrader broker for picks.",
        )

    def test_leaves_glossary_landing_and_external_links_intact(self):
        body = (
            "A [term](/trading-glossary/copy-trading), a [page](/pricing), "
            "and an [ext](https://example.com/blog/post)."
        )
        # Relative-only: /trading-glossary and /pricing are not /blog, and the external
        # link is absolute (https://…/blog/…) so it is NOT unwrapped — only our own
        # relative /blog/<slug> edges are stripped.
        out = strip_internal_blog_links(body)
        self.assertIn("[term](/trading-glossary/copy-trading)", out)
        self.assertIn("[page](/pricing)", out)
        self.assertIn("[ext](https://example.com/blog/post)", out)

    def test_roundtrip_reset_then_reapply_is_clean(self):
        # A body carrying a WRONG blog link resets to plain text, so a corrected plan
        # can be applied from scratch without stacking on the stale edge.
        wrong = "Our [best cTrader broker](/blog/general-brokers) roundup covers it."
        clean = strip_internal_blog_links(wrong)
        self.assertNotIn("](/blog/", clean)
        out, report = apply_internal_links(clean, _links(("best cTrader broker", "/blog/ctrader")))
        self.assertEqual(len(report.applied), 1)
        self.assertIn("[best cTrader broker](/blog/ctrader)", out)


class ApplyInternalLinksTests(SimpleTestCase):
    def test_empty_plan_leaves_body_untouched(self):
        body = "Some prose about copy trading."
        for plan in (None, [], [{}], [{"anchor": "x"}], [{"target_url": "/blog/y"}]):
            out, report = apply_internal_links(body, plan)
            self.assertEqual(out, body)
            self.assertEqual(report.applied, [])

    def test_inserts_at_first_plain_text_occurrence(self):
        body = "Learn copy trading basics. We compare copy trading platforms below."
        out, report = apply_internal_links(body, _links(("copy trading", "/blog/copy-trading")))
        self.assertEqual(len(report.applied), 1)
        self.assertIn("[copy trading](/blog/copy-trading)", out)
        # only the FIRST occurrence is linked — exactly one link emitted.
        self.assertEqual(out.count("](/blog/copy-trading)"), 1)

    def test_whole_word_only(self):
        # "bot" must not match inside "robotics".
        body = "The field of robotics is broad."
        out, report = apply_internal_links(body, _links(("bot", "/blog/bots")))
        self.assertEqual(out, body)
        self.assertEqual(len(report.skipped), 1)
        self.assertEqual(report.skipped[0].reason, "anchor not found in prose")

    def test_skips_fenced_code_block(self):
        body = "```\ncopy trading config\n```\nReal copy trading prose here."
        out, _ = apply_internal_links(body, _links(("copy trading", "/blog/ct")))
        # the code-fence occurrence is untouched; the prose one is linked.
        self.assertIn("copy trading config", out)
        self.assertIn("[copy trading](/blog/ct)", out)
        self.assertEqual(out.count("](/blog/ct)"), 1)

    def test_skips_html_and_visual_lines(self):
        body = '<div class="cp-card">copy trading widget</div>'
        out, report = apply_internal_links(body, _links(("copy trading", "/blog/ct")))
        self.assertEqual(out, body)  # never touch a line with angle brackets
        self.assertEqual(report.skipped[0].reason, "anchor not found in prose")

    def test_skips_heading_table_blockquote(self):
        for line in ("## Copy trading guide", "| copy trading | yes |", "> copy trading is..."):
            out, report = apply_internal_links(line, _links(("copy trading", "/blog/ct")))
            self.assertEqual(out, line)
            self.assertEqual(report.skipped[0].reason, "anchor not found in prose")

    def test_does_not_nest_when_phrase_only_inside_existing_link(self):
        # "copy trading" appears ONLY as the anchor of an existing link -> no plain
        # text occurrence to link, so it is left alone (never nested).
        body = "See [copy trading](/trading-glossary/copy-trading) for the term."
        out, report = apply_internal_links(body, _links(("copy trading", "/blog/ct")))
        self.assertEqual(out, body)
        self.assertEqual(report.skipped[0].reason, "anchor not found in prose")

    def test_inserts_alongside_an_existing_link_on_the_same_line(self):
        # An author glossary link on the line must NOT block a blog link to a
        # different plain-text phrase on that same line.
        body = "We cover [copy trading](/trading-glossary/copy-trading) and mirror trading too."
        out, report = apply_internal_links(body, _links(("mirror trading", "/blog/mt")))
        self.assertEqual(len(report.applied), 1)
        self.assertIn("[mirror trading](/blog/mt)", out)
        self.assertIn("[copy trading](/trading-glossary/copy-trading)", out)  # untouched

    def test_caps_at_two_links_per_line(self):
        # A line already holding two links gets no third insertion (<=2/paragraph).
        body = "Both [a](/x) and [b](/y) covered, plus mirror trading here."
        out, report = apply_internal_links(body, _links(("mirror trading", "/blog/mt")))
        self.assertEqual(out, body)
        self.assertEqual(report.skipped[0].reason, "anchor not found in prose")

    def test_dedupes_by_target(self):
        body = "copy trading and mirror trading are related."
        plan = _links(("copy trading", "/blog/ct"), ("mirror trading", "/blog/ct"))
        out, report = apply_internal_links(body, plan)
        self.assertEqual(len(report.applied), 1)
        self.assertEqual(out.count("](/blog/ct)"), 1)
        self.assertTrue(any(s.reason == "duplicate target" for s in report.skipped))

    def test_idempotent_when_target_already_linked(self):
        body = "Already [copy trading](/blog/ct) here, and copy trading again."
        out, report = apply_internal_links(body, _links(("copy trading", "/blog/ct")))
        self.assertEqual(out, body)
        self.assertEqual(report.skipped[0].reason, "target already linked")

    def test_reapplying_output_is_stable(self):
        body = "Intro to copy trading and to algo trading."
        plan = _links(("copy trading", "/blog/ct"), ("algo trading", "/blog/algo"))
        once, _ = apply_internal_links(body, plan)
        twice, report = apply_internal_links(once, plan)
        self.assertEqual(once, twice)
        self.assertTrue(all(s.reason == "target already linked" for s in report.skipped))

    def test_max_links_cap(self):
        # one anchor per paragraph (line), so each is independently linkable.
        body = "\n\n".join(f"Paragraph about term{i} here." for i in range(12))
        plan = _links(*[(f"term{i}", f"/blog/t{i}") for i in range(12)])
        out, report = apply_internal_links(body, plan, max_links=3)
        self.assertEqual(len(report.applied), 3)
        self.assertTrue(any(s.reason == "max links reached" for s in report.skipped))

    def test_anchor_not_present_is_skipped(self):
        body = "This article never mentions the phrase."
        out, report = apply_internal_links(body, _links(("nonexistent phrase", "/blog/x")))
        self.assertEqual(out, body)
        self.assertEqual(report.skipped[0].reason, "anchor not found in prose")
