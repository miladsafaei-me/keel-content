"""Pipeline markdown → HTML: heading anchors survive, custom blocks pass through."""

from __future__ import annotations

from django.test import SimpleTestCase

from blog.markdown_convert import (
    _inject_heading_anchors,
    prepare_pipeline_content_for_storage,
)


class HeadingAnchorTests(SimpleTestCase):
    def test_h2_anchor_is_promoted_to_id(self):
        html = "<h2>My Section {#sec-1}</h2>"
        out = _inject_heading_anchors(html)
        self.assertEqual(out, '<h2 id="sec-1">My Section</h2>')

    def test_h3_and_h6_anchors_also_promoted(self):
        for tag in ("h3", "h4", "h5", "h6"):
            html = f"<{tag}>X {{#a-{tag}}}</{tag}>"
            out = _inject_heading_anchors(html)
            self.assertIn(f'<{tag} id="a-{tag}">X</{tag}>', out)

    def test_h1_is_not_promoted(self):
        """h1 is reserved for the title — pipeline output should never include one."""
        html = "<h1>Title {#nope}</h1>"
        out = _inject_heading_anchors(html)
        # h1 left alone (text marker remains)
        self.assertIn("{#nope}", out)

    def test_existing_id_attr_is_preserved(self):
        html = '<h2 id="already-there">Heading {#new-id}</h2>'
        out = _inject_heading_anchors(html)
        self.assertIn('id="already-there"', out)
        # Original markup unchanged (no double-id)
        self.assertNotIn('id="new-id"', out)

    def test_invalid_anchor_chars_are_not_matched(self):
        """Anchors must be [a-zA-Z0-9_-]+; spaces or punctuation break the match."""
        html = "<h2>Heading {#has space}</h2>"
        out = _inject_heading_anchors(html)
        self.assertNotIn("id=", out)


class PrepareForStorageTests(SimpleTestCase):
    def test_empty_input_returns_empty_string(self):
        self.assertEqual(prepare_pipeline_content_for_storage(""), "")
        self.assertEqual(prepare_pipeline_content_for_storage("   \n"), "")

    def test_markdown_renders_with_anchors(self):
        md = "## Hello {#hello}\n\nWorld."
        html = prepare_pipeline_content_for_storage(md)
        self.assertIn('<h2 id="hello">Hello</h2>', html)
        self.assertIn("<p>World.</p>", html)

    def test_mermaid_block_survives(self):
        md = (
            "## S {#s}\n\n"
            '<figure class="cp-figure-mermaid">\n'
            '<pre class="mermaid">\nflowchart LR\nA --> B\n</pre>\n'
            "</figure>\n"
        )
        html = prepare_pipeline_content_for_storage(md)
        self.assertIn('<pre class="mermaid">', html)
        self.assertIn("flowchart LR", html)
        self.assertIn('class="cp-figure-mermaid"', html)

    def test_chartjs_canvas_survives(self):
        md = '<canvas data-cp-chart=\'{"type":"bar"}\'></canvas>'
        html = prepare_pipeline_content_for_storage(md)
        self.assertIn("data-cp-chart", html)
        self.assertIn("<canvas", html)


class FigureWrapperBalanceTests(SimpleTestCase):
    """An AI-dropped/mismatched closer on a figure wrapper must never swallow the article."""

    def _trailing_prose(self, html: str) -> str:
        return html[html.rindex("</div>"):]

    def test_unclosed_chart_wrapper_does_not_swallow_following_content(self):
        md = (
            "Intro paragraph.\n\n"
            '<div class="cp-chartjs-wrapper cp-figure">\n'
            "<div><canvas data-cp-chart='{\"type\":\"bar\"}'></canvas></div>\n"
            '<figcaption class="cp-figure-caption">A caption.</figcaption>\n\n'
            "## Next Heading {#next}\n\n"
            "This paragraph must sit OUTSIDE the wrapper."
        )
        html = prepare_pipeline_content_for_storage(md)
        # Balanced, and the heading + paragraph are emitted after the closed wrapper.
        self.assertEqual(html.count("<div"), html.count("</div>"))
        self.assertIn('<h2 id="next">Next Heading</h2>', self._trailing_prose(html))
        self.assertIn("must sit OUTSIDE the wrapper", self._trailing_prose(html))

    def test_mismatched_figure_closer_is_balanced(self):
        # The real bug: opened a <div> wrapper but closed it with </figure>.
        md = (
            '<div class="cp-chartjs-wrapper cp-figure">\n'
            "<div><canvas data-cp-chart='{\"type\":\"bar\"}'></canvas></div>\n"
            "<figcaption>cap</figcaption>\n"
            "</figure>\n\n"
            "Trailing prose."
        )
        html = prepare_pipeline_content_for_storage(md)
        self.assertEqual(html.count("<div"), html.count("</div>"))
        self.assertIn("Trailing prose", self._trailing_prose(html))

    def test_balanced_wrapper_is_left_untouched(self):
        md = (
            '<div class="cp-chartjs-wrapper">\n'
            "<div><canvas data-cp-chart='{\"type\":\"line\"}'></canvas></div>\n"
            "</div>\n\n"
            "After."
        )
        html = prepare_pipeline_content_for_storage(md)
        self.assertEqual(html.count("<div"), html.count("</div>"))
        # No spurious extra closers injected.
        self.assertEqual(html.count("</div>"), 2)
