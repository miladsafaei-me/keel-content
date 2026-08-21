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

from django.test import SimpleTestCase, override_settings

from keel_content.core.hero import MOTIFS, STYLES, HeroSpec, build_hero_svg
from keel_content.core.hero.tokens import GREEN
from keel_content.host import featured_image_absolute_url

_HEAD = [[("Two platforms.", None)], [("One real difference.", None)]]


# ``featured_image_absolute_url`` resolves a DOTTED PATH, so the test's local closure
# has to be reachable by name. ``_install_hook`` parks it here for the duration.
_HOOK = None


def _hook_target(*args, **kwargs):
    return _HOOK(*args, **kwargs)


def _install_hook(fn):
    global _HOOK
    _HOOK = fn



def _spec(style: str, motif: str) -> HeroSpec:
    params = {"labels": ("MT4", "MT5"), "sublabel": "ONE ENGINE"} if motif == "paired" else {}
    return HeroSpec(style, "Test Category", _HEAD, motif, motif_params=params, title="Test")


class HeroMatrixTests(SimpleTestCase):
    def test_every_style_motif_builds_with_headline(self):
        """Every combination renders a non-empty SVG that still carries the headline
        and the HOST's wordmark — not a wordmark of the package's own."""
        # The wordmark comes from KEEL_CONTENT["brand"] (config._DEFAULT_BRAND leaves
        # it empty). This assertion used to read `assertIn("SignalBots", svg)`, true
        # only while the engine lived in SignalBots; after extraction the lockup
        # renders nothing unless a host paints one, so the literal never appeared and
        # every style x motif combination failed.
        with override_settings(KEEL_CONTENT={"brand": {"wordmark": "ExampleHost"}}):
            for style in STYLES:
                for motif in MOTIFS:
                    with self.subTest(style=style, motif=motif):
                        svg = build_hero_svg(_spec(style, motif))
                        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
                        self.assertIn("One real difference.", svg)
                        self.assertIn("ExampleHost", svg)  # host brand chrome present

    def test_no_brand_configured_renders_no_lockup(self):
        """A host that paints no brand gets no wordmark — the package owns no identity."""
        with override_settings(KEEL_CONTENT={}):
            svg = build_hero_svg(_spec(next(iter(STYLES)), next(iter(MOTIFS))))
            self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
            self.assertIn("One real difference.", svg)
            self.assertNotIn("ExampleHost", svg)
            self.assertNotIn("SignalBots", svg)

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
        # The stroke is the host's brand accent. This regex used to hardcode
        # "#41FFA0" — SignalBots' accent, valid only while the engine lived there.
        # Read the resolved token instead of pinning a colour: hero.tokens binds the
        # palette at IMPORT time, so override_settings cannot change it after the
        # fact (see TODO.md — chrome.py resolves the same brand dict per call, and
        # that inconsistency is a real finding, not something this test should paper
        # over). The geometry, not the colour, is what this test is about.
        line_re = re.compile(
            r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)" '
            r'stroke="' + re.escape(GREEN) + r'" stroke-width="2.5"/>'
        )
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

    def test_og_image_url_is_delegated_to_the_host(self):
        """``featured_image_absolute_url`` dispatches; it holds no policy of its own.

        This replaces ``test_og_image_prefers_webp_sibling``, which asserted a
        POLICY — "an SVG hero resolves to its .webp sibling, or None when absent" —
        that lives in whichever host the hook points at, not in this package. Run
        under Binary Option Trading's settings it failed, because Binary's
        ``core.media_urls`` implements a different rule; that made the package suite
        red for a host difference the package does not own. The webp-sibling rule
        belongs in SignalBots' own tests. What IS the package's contract, and what
        this test pins, is that the hook is resolved from settings and called.
        """
        called = {}

        def _hook(request, stored):
            called["args"] = (request, stored)
            return "https://example.test/media/x.webp"

        with override_settings(KEEL_CONTENT={"featured_image_url_hook": f"{__name__}._hook_target"}):
            _install_hook(_hook)
            self.assertEqual(
                featured_image_absolute_url("REQ", "/media/x.svg"),
                "https://example.test/media/x.webp",
            )
        self.assertEqual(called["args"], ("REQ", "/media/x.svg"))
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
