"""Hero generator invariants -- the scale-safe gate.

The hero generator is deterministic code, so its quality is a property of the
code, not of each (unattended) generation. These tests lock the invariants that
a layout regression would break, across the full style x motif matrix, so a
future style/motif edit can't silently ship a broken hero for thousands of
posts. Two real regressions are pinned here: the isometric label that fell to
the rhombus edge, and the device drawn twice.
"""

from __future__ import annotations

import re

from django.test import SimpleTestCase

from keel_content.core.hero import MOTIFS, STYLES, HeroSpec, build_hero_svg

_HEAD = [[("Two platforms.", None)], [("One real difference.", None)]]


def _spec(style: str, motif: str) -> HeroSpec:
    params = {"labels": ("MT4", "MT5"), "sublabel": "ONE ENGINE"} if motif == "paired" else {}
    return HeroSpec(style, "Test Category", _HEAD, motif, motif_params=params, title="Test")


class HeroMatrixTests(SimpleTestCase):
    def test_every_style_motif_builds_with_headline(self):
        """Every combination renders a non-empty SVG that still carries the headline."""
        for style in STYLES:
            for motif in MOTIFS:
                with self.subTest(style=style, motif=motif):
                    svg = build_hero_svg(_spec(style, motif))
                    self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
                    self.assertIn("One real difference.", svg)
                    self.assertIn("SignalBots", svg)  # brand chrome present

    def test_device_signal_draws_one_device(self):
        """device_signal must not double-draw the device (the phone has the only rx=26)."""
        for style in STYLES:
            with self.subTest(style=style):
                svg = build_hero_svg(_spec(style, "device_signal"))
                self.assertEqual(svg.count('rx="26"'), 1, f"{style}: device drawn != once")

    def test_isometric_paired_label_centered(self):
        """The MT4 label must sit on the tile, not at its bottom edge (regression)."""
        svg = build_hero_svg(_spec("isometric", "paired"))
        m = re.search(r'<text[^>]*\by="([\d.]+)"[^>]*>MT4</text>', svg)
        self.assertIsNotNone(m, "MT4 label missing")
        # tile center y for card (792, 392, 150, 118) is 451; centered label baseline ~458
        self.assertLess(abs(float(m.group(1)) - 451), 24, "MT4 label off the tile center")

    def test_paired_connector_anchored_to_facing_edges(self):
        """The connector must land on the cards' facing edges at their center y, in
        every style -- correct position, source, destination, and length (regression:
        it floated above the gap at y=431 with rect-edge x's in the isometric style)."""
        # cards are (792,392,150,118) and (978,392,150,118): center y = 451.
        # Flat styles meet the rect edges (942 -> 978); isometric meets the tile
        # vertices (cx +/- w, w = 150*0.46 = 69): 936 -> 984.
        expected = {
            "minimal": (942, 978), "glow": (942, 978),
            "network": (942, 978), "infographic": (942, 978),
            "isometric": (936, 984),
        }
        line_re = re.compile(r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)" stroke="#41FFA0" stroke-width="2.5"/>')
        for style, (ex1, ex2) in expected.items():
            with self.subTest(style=style):
                svg = build_hero_svg(_spec(style, "paired"))
                m = line_re.search(svg)
                self.assertIsNotNone(m, f"{style}: connector line missing")
                x1, y1, x2, y2 = (float(v) for v in m.groups())
                self.assertEqual((y1, y2), (451, 451), f"{style}: connector not at card center y")
                self.assertLess(x1, x2, f"{style}: connector reversed")
                self.assertAlmostEqual(x1, ex1, delta=1, msg=f"{style}: source x off the edge")
                self.assertAlmostEqual(x2, ex2, delta=1, msg=f"{style}: destination x off the edge")


class HeroBriefTests(SimpleTestCase):
    def test_long_title_autosizes_within_text_zone(self):
        """A very long title must shrink so the headline never overflows the text zone."""
        from keel_content.core.hero.pipeline import derive_spec

        spec = derive_spec(
            title="A Very Long Title That Would Otherwise Overflow The Hero Text Zone Badly Indeed",
            category="Trading Bots & Automation",
            slug="a-very-long-title",
        )
        longest = max(sum(len(t) for t, _ in line) for line in spec.headline_lines)
        # ExtraBold advance ~0.62em; text zone is ~620px wide
        self.assertLessEqual(longest * (spec.head_size or 62) * 0.62, 660)

    def test_og_image_prefers_webp_sibling(self):
        """og:image resolves an SVG hero to its .webp sibling, or None when absent
        (caller then uses the brand default card -- never an SVG og:image)."""
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        from core.media_urls import featured_image_absolute_url

        class _Req:
            def build_absolute_uri(self, u):
                return "https://signalbots.ai" + u

        rel = "blog/featured/2026/06/post.abc12345"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "blog/featured/2026/06").mkdir(parents=True)
            with override_settings(MEDIA_ROOT=d, MEDIA_URL="/media/"):
                stored = f"/media/{rel}.svg"
                self.assertIsNone(featured_image_absolute_url(_Req(), stored))  # no raster yet
                (Path(d) / f"{rel}.webp").write_bytes(b"RIFF....WEBP")
                self.assertEqual(
                    featured_image_absolute_url(_Req(), stored),
                    f"https://signalbots.ai/media/{rel}.webp",
                )

    def test_motif_inferred_from_concept(self):
        from keel_content.core.hero.pipeline import derive_spec

        cases = {
            "What Is Copy Trading & How Does It Work?": "hub_spokes",
            "MetaTrader Explained: What Is MT4 & MT5?": "paired",
            "Best Forex Brokers for Algorithmic Trading": "ranked",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                spec = derive_spec(title=title, category="X", slug=title.lower().replace(" ", "-"))
                self.assertEqual(spec.motif, expected)
