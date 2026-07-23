"""Unit tests for deterministic typographic normalization. Pure stdlib (no DB)."""

from __future__ import annotations

from django.test import SimpleTestCase

from keel_content.core.text_normalize import normalize_bundle, normalize_text


class NormalizeTextTests(SimpleTestCase):
    def test_curly_quotes_folded(self):
        self.assertEqual(normalize_text("“hi” and ‘yo’"), '"hi" and \'yo\'')

    def test_ellipsis_glyph_folded(self):
        self.assertEqual(normalize_text("wait…"), "wait...")

    def test_nbsp_folded_to_space(self):
        self.assertEqual(normalize_text("a b"), "a b")

    def test_zero_width_and_bom_removed(self):
        # Zero-width space + BOM are dropped, so the surrounding letters join.
        self.assertEqual(normalize_text("b​c﻿"), "bc")

    def test_em_and_en_dash_preserved(self):
        s = "alpha — beta – gamma"
        self.assertEqual(normalize_text(s), s)

    def test_aliased_dash_and_minus_folded(self):
        # Horizontal-bar (U+2015) -> em-dash; true minus (U+2212) -> hyphen-minus.
        self.assertEqual(normalize_text("a―b − c"), "a—b - c")

    def test_idempotent(self):
        once = normalize_text("“x”…")
        self.assertEqual(normalize_text(once), once)

    def test_empty_safe(self):
        self.assertEqual(normalize_text(""), "")


class NormalizeBundleTests(SimpleTestCase):
    def test_normalizes_prose_fields_and_source_anchors(self):
        bundle = {
            "title": "“Title”",
            "body_markdown": "body…",
            "external_sources": [{"url": "https://x", "anchor": "‘Anchor’"}],
            "slug": "keep-me",
        }
        out = normalize_bundle(bundle)
        self.assertEqual(out["title"], '"Title"')
        self.assertEqual(out["body_markdown"], "body...")
        self.assertEqual(out["external_sources"][0]["anchor"], "'Anchor'")
        self.assertEqual(out["slug"], "keep-me")
