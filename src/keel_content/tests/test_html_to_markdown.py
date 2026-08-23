"""HTML -> Markdown: the pre-clean's rules, and what the fidelity gate refuses.

The round-trip assertions render through ``keel_cms.markdown_convert`` — the same
renderer a keel-cms host's publish path uses — because a gate that passed against a
reference implementation and failed against the real one would be worthless.
"""

from __future__ import annotations

from django.test import SimpleTestCase
from keel_cms.markdown_convert import markdown_to_blog_html as render

from keel_content.core.html_to_markdown import (
    _emphasis_parses,
    convert_checked,
    normalize_text,
    preclean,
    to_markdown,
)

ZWSP = "​"
NBSP = " "


class PrecleanTests(SimpleTestCase):
    def test_header_row_cells_become_header_cells(self):
        out = preclean("<table><thead><tr><td>A</td><td>B</td></tr></thead>"
                       "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>")
        self.assertEqual(out.count("<th>"), 2)
        # Only the header row is promoted; the body row keeps its data cells.
        self.assertEqual(out.count("<td>"), 2)

    def test_spacer_paragraph_is_dropped(self):
        out = preclean(f"<p>real</p><p>{NBSP}</p><p></p>")
        self.assertEqual(out, "<p>real</p>")

    def test_paragraph_holding_only_an_image_survives(self):
        out = preclean('<p><img src="/x.png"/></p>')
        self.assertIn("<img", out)

    def test_empty_emphasis_is_unwrapped(self):
        self.assertEqual(preclean(f"<h2>Q{ZWSP}<strong></strong></h2>"), f"<h2>Q{ZWSP}</h2>")

    def test_emphasis_emptied_by_the_hoist_is_also_unwrapped(self):
        """The hoist can empty a tag; the unwrap has to run after it, not before."""
        self.assertNotIn("<strong>", preclean(f"<p>a<strong>{ZWSP}</strong>b</p>"))

    def test_trailing_nbsp_moves_outside_the_emphasis(self):
        out = preclean(f"<p><strong>bold{NBSP}</strong>rest</p>")
        self.assertEqual(out, f"<p><strong>bold</strong>{NBSP}rest</p>")

    def test_sole_paragraph_in_a_cell_or_bullet_is_unwrapped(self):
        self.assertEqual(preclean("<td><p>x</p></td>"), "<td>x</td>")
        self.assertEqual(preclean("<li><p>x</p></li>"), "<li>x</li>")

    def test_two_paragraphs_in_a_cell_are_left_alone(self):
        """Only the unambiguous single-paragraph wrapper is removed."""
        self.assertEqual(preclean("<td><p>a</p><p>b</p></td>").count("<p>"), 2)

    def test_paragraph_in_a_blockquote_is_left_alone(self):
        """A blockquote round-trips WITH its paragraph, so unwrapping it would hurt."""
        self.assertIn("<p>", preclean("<blockquote><p>x</p></blockquote>"))

    def test_nested_empty_wrappers_are_dropped_to_a_fixpoint(self):
        self.assertEqual(preclean(f"<div><div><p>{NBSP}</p></div></div><p>keep</p>"), "<p>keep</p>")

    def test_preclean_never_changes_text(self):
        source = (
            "<div><p>&nbsp;</p></div>"
            "<table><thead><tr><td><p>سر&zwnj;ستون</p></td></tr></thead>"
            "<tbody><tr><td><p>خانه&nbsp;</p></td></tr></tbody></table>"
            f"<p><strong>پررنگ{NBSP}</strong>ادامه<em>{ZWSP}</em></p>"
        )
        self.assertEqual(normalize_text(preclean(source)), normalize_text(source))

    def test_empty_input_is_returned_unchanged(self):
        self.assertEqual(preclean(""), "")


class EmphasisFlankingTests(SimpleTestCase):
    def test_ordinary_emphasis_parses(self):
        self.assertTrue(_emphasis_parses("bold", " ", " "))

    def test_emphasis_ending_in_an_open_bracket_before_a_letter_does_not(self):
        # **رگوله‌شده (**مطابق -> the closing run cannot close, asterisks leak.
        self.assertFalse(_emphasis_parses("رگوله (", " ", "م"))

    def test_emphasis_ending_in_a_period_before_a_space_still_parses(self):
        self.assertTrue(_emphasis_parses("done.", " ", " "))

    def test_unparseable_emphasis_is_emitted_as_inline_html(self):
        md = to_markdown(preclean("<p><strong>regulated (</strong>per the rules)</p>"))
        self.assertIn("<strong>regulated (</strong>", md)
        self.assertNotIn("**", md)

    def test_ordinary_emphasis_still_uses_asterisks(self):
        self.assertIn("**bold**", to_markdown(preclean("<p><strong>bold</strong> rest</p>")))

    def test_the_html_form_round_trips_to_a_strong_element(self):
        md = to_markdown(preclean("<p><strong>regulated (</strong>per the rules)</p>"))
        self.assertIn("<strong>regulated (</strong>", render(md))


class ParagraphBlockMarkerTests(SimpleTestCase):
    def test_numbered_paragraph_stays_a_paragraph(self):
        md = to_markdown(preclean("<p>3. Is bitcoin safe?</p>"))
        self.assertIn("3\\.", md)
        self.assertIn("<p>", render(md))
        self.assertNotIn("<ol>", render(md))

    def test_dash_led_paragraph_stays_a_paragraph(self):
        self.assertNotIn("<ul>", render(to_markdown(preclean("<p>- not a bullet</p>"))))

    def test_a_real_list_is_still_a_list(self):
        self.assertIn("<ol>", render(to_markdown(preclean("<ol><li>one</li><li>two</li></ol>"))))

    def test_ordinary_paragraph_is_untouched(self):
        self.assertNotIn("\\", to_markdown(preclean("<p>plain sentence.</p>")))


class ConvertCheckedTests(SimpleTestCase):
    def test_a_clean_article_converts(self):
        html = "<h2>Heading</h2><p>Body text.</p><ul><li>one</li><li>two</li></ul>"
        markdown, faithful, report = convert_checked(html, render)
        self.assertTrue(faithful, report)
        self.assertIn("## Heading", markdown)

    def test_an_editor_flavoured_article_converts_after_the_preclean(self):
        html = (
            f"<p>{NBSP}</p><h2>عنوان</h2>"
            f"<p><strong>پررنگ{NBSP}</strong>ادامه دارد.</p>"
            "<table><thead><tr><td><p>ستون</p></td></tr></thead>"
            "<tbody><tr><td><p>مقدار</p></td></tr></tbody></table>"
        )
        _, faithful, report = convert_checked(html, render)
        self.assertTrue(faithful, report)
        self.assertTrue(report["precleaned"])

    def test_a_list_nested_in_a_table_cell_is_refused(self):
        html = "<table><tbody><tr><td><ul><li>a</li><li>b</li></ul></td></tr></tbody></table>"
        _, faithful, report = convert_checked(html, render)
        self.assertFalse(faithful)
        self.assertIn("block elements lost", report["reason"])

    def test_a_renderer_that_throws_fails_the_document_rather_than_the_run(self):
        def boom(_markdown):
            raise RuntimeError("nope")

        _, faithful, report = convert_checked("<p>x</p>", boom)
        self.assertFalse(faithful)
        self.assertIn("render failed", report["error"])

    def test_a_multi_paragraph_cell_is_within_the_nested_allowance(self):
        html = "<table><tbody><tr><td><p>a</p><p>b</p></td></tr></tbody></table>"
        _, _, report = convert_checked(html, render)
        self.assertEqual(report["paragraphs"]["nested_allowance"], 2)
