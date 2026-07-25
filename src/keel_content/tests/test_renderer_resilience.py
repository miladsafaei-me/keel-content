"""Import-resilience tests surfaced by the forex broker cluster run.

Two failure modes must never drop content at import time:
  * a ``markdown2`` library assert on rendered-component HTML (whole article lost), and
  * an over-long component label past its schema ``maxLength`` (whole visual dropped).

Both fixes are pure / DB-free, hence ``SimpleTestCase``.
"""

from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase

from keel_cms import markdown_convert
from keel_ui.renderer import _clamp_to_schema_lengths


class MarkdownFallbackTests(SimpleTestCase):
    def test_pipeline_convert_falls_back_when_markdown2_raises(self):
        """A whole-document markdown2 assert must trigger the block-wise fallback,
        not propagate and fail the import."""
        real = markdown_convert.markdown2.markdown
        calls = {"n": 0}

        def flaky(text, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:  # the library bug: assert on the whole body
                raise AssertionError
            return real(text, **kwargs)

        with mock.patch.object(markdown_convert.markdown2, "markdown", side_effect=flaky):
            out = markdown_convert.prepare_pipeline_content_for_storage(
                '# Title\n\nSome **prose**.\n\n<figure class="cp-figure">x</figure>'
            )

        self.assertIn("Title", out)
        self.assertGreater(calls["n"], 1)  # proved it fell back to per-block conversion


class ClampToSchemaLengthsTests(SimpleTestCase):
    SCHEMA = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "maxLength": 5},
            "nested": {
                "type": "object",
                "properties": {"cta": {"type": "string", "maxLength": 4}},
            },
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "maxLength": 3}},
                },
            },
        },
    }

    def test_truncates_over_length_strings_recursively(self):
        clamped: list[str] = []
        out = _clamp_to_schema_lengths(
            self.SCHEMA,
            {
                "label": "waytoolong",
                "nested": {"cta": "alsolong"},
                "rows": [{"name": "abcdef"}],
                "extra": "unknown-key-left-as-is",
            },
            clamped,
        )
        self.assertLessEqual(len(out["label"]), 5)
        self.assertLessEqual(len(out["nested"]["cta"]), 4)
        self.assertLessEqual(len(out["rows"][0]["name"]), 3)
        # an undeclared key is not our concern here (the prune step handles it)
        self.assertEqual(out["extra"], "unknown-key-left-as-is")
        self.assertTrue(clamped)

    def test_leaves_within_limit_values_untouched(self):
        clamped: list[str] = []
        out = _clamp_to_schema_lengths(self.SCHEMA, {"label": "ok"}, clamped)
        self.assertEqual(out["label"], "ok")
        self.assertEqual(clamped, [])


class EmbedFigureProtectionTests(SimpleTestCase):
    def test_embed_figure_with_blank_lines_is_not_mangled_into_code(self):
        # A rendered component with an internal blank line + indented HTML: markdown2
        # otherwise ends the HTML block at the blank line and turns the indented lines
        # after it into a <pre><code> block (the visual shows as visible source).
        body = (
            "Intro paragraph.\n\n"
            '<figure class="cp-figure cp-figure--embed"><table>\n'
            "  <tr>\n    <td>cell one</td>\n  </tr>\n"
            "\n"  # the blank line that triggers the bug
            "  <tr>\n    <td>cell two</td>\n  </tr>\n</table></figure>\n\n"
            "Outro paragraph."
        )
        out = markdown_convert.prepare_pipeline_content_for_storage(body)
        self.assertNotIn("<pre><code>", out)
        self.assertIn("<table>", out)
        self.assertIn("<td>cell two</td>", out)  # survived verbatim, not as code
        self.assertNotIn("CPEMBED", out)  # placeholder fully restored


class VariantNestingCoercionTests(SimpleTestCase):
    SCHEMA = {
        "type": "object",
        "properties": {
            "variant": {"type": "string"},
            "commercial": {
                "type": "object",
                "properties": {
                    "pick": {"type": "object", "properties": {"name": {"type": "string"}}},
                    "pain": {"type": "string"},
                },
            },
        },
    }

    def test_flattened_variant_fields_are_nested(self):
        from keel_ui.renderer import _coerce_variant_nesting

        # Author put commercial fields at the top level (the empty-EDITOR'S-PICK bug).
        spec = {"variant": "commercial", "pain": "slow fills", "pick": {"name": "IC Markets"}}
        out = _coerce_variant_nesting(self.SCHEMA, spec)
        self.assertEqual(out["commercial"]["pick"]["name"], "IC Markets")
        self.assertEqual(out["commercial"]["pain"], "slow fills")
        self.assertNotIn("pick", out)  # moved under commercial, not left at top level

    def test_correctly_nested_spec_untouched(self):
        from keel_ui.renderer import _coerce_variant_nesting

        spec = {"variant": "commercial", "commercial": {"pick": {"name": "B"}}}
        self.assertEqual(_coerce_variant_nesting(self.SCHEMA, spec), spec)
