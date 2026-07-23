"""Unit tests for the asset-request placeholder pass (human-supplied elements).

``apply_asset_requests`` is deterministic and idempotent-by-recompute: markers are
replaced from the bundle on every import. Pure stdlib (no DB), hence
``SimpleTestCase``.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from keel_content.core.asset_requests import (
    apply_asset_requests,
    inject_preview_placeholders,
    normalize_asset_requests,
)


class NormalizeTests(SimpleTestCase):
    def test_drops_incomplete_entries(self):
        raw = [
            {"id": "ar-1", "type": "video", "description": "walkthrough"},
            {"id": "", "description": "no id"},
            {"id": "ar-3"},  # no description
            "not-a-dict",
        ]
        out = normalize_asset_requests(raw)
        self.assertEqual([r["id"] for r in out], ["ar-1"])
        self.assertEqual(out[0]["type"], "video")
        self.assertEqual(out[0]["placement"], "")

    def test_defaults_type(self):
        out = normalize_asset_requests([{"id": "x", "description": "d"}])
        self.assertEqual(out[0]["type"], "asset")


class ApplyTests(SimpleTestCase):
    def test_marker_replaced_with_invisible_anchor(self):
        body = "Intro.\n\n[[ASSET:ar-1]]\n\nOutro."
        reqs = [{"id": "ar-1", "type": "screenshot", "description": "broker panel"}]
        out, normalized, report = apply_asset_requests(body, reqs)
        self.assertIn('class="asset-request-anchor" id="asset-ar-1"', out)
        # The PUBLIC body must never expose the request text or the loud box.
        self.assertNotIn("broker panel", out)
        self.assertNotIn("asset-request-placeholder", out)
        self.assertNotIn("[[ASSET:", out)
        self.assertEqual(report.placed, ["ar-1"])
        self.assertEqual(report.unmatched_markers, [])
        self.assertEqual(report.unplaced_requests, [])
        self.assertEqual(len(normalized), 1)

    def test_unmatched_marker_still_replaced(self):
        out, _, report = apply_asset_requests("[[ASSET:ghost]]", [])
        self.assertNotIn("[[ASSET:", out)
        self.assertIn('id="asset-ghost"', out)
        self.assertEqual(report.unmatched_markers, ["ghost"])

    def test_unplaced_request_reported(self):
        out, normalized, report = apply_asset_requests(
            "No markers here.", [{"id": "ar-9", "type": "video", "description": "d"}]
        )
        self.assertEqual(out, "No markers here.")
        self.assertEqual(report.unplaced_requests, ["ar-9"])
        self.assertEqual(len(normalized), 1)

    def test_inline_marker_not_replaced(self):
        # The marker must stand alone on its own line — inline tokens are left as-is
        # (an author mistake surfaced by the unplaced_requests report).
        body = "Text with [[ASSET:ar-1]] inline."
        out, _, report = apply_asset_requests(
            body, [{"id": "ar-1", "type": "video", "description": "d"}]
        )
        self.assertEqual(out, body)
        self.assertEqual(report.unplaced_requests, ["ar-1"])

    def test_anchor_carries_no_description(self):
        out, _, _ = apply_asset_requests(
            "[[ASSET:a]]", [{"id": "a", "type": "data", "description": "<script>x</script>"}]
        )
        self.assertNotIn("script", out)
        self.assertIn('data-asset-type="data"', out)


class PreviewInjectionTests(SimpleTestCase):
    REQS = [{"id": "ar-1", "type": "screenshot", "description": "broker <b>panel</b>",
             "placement": "inside the 'Setup' H2"}]

    def _anchored_html(self):
        out, _, _ = apply_asset_requests("[[ASSET:ar-1]]", self.REQS)
        return f"<p>before</p>{out}<p>after</p>"

    def test_preview_expands_anchor_into_visible_card(self):
        html_out = inject_preview_placeholders(self._anchored_html(), self.REQS)
        self.assertIn("asset-request-placeholder", html_out)
        self.assertIn("broker &lt;b&gt;panel&lt;/b&gt;", html_out)  # escaped
        self.assertIn("Planned placement:", html_out)
        # The anchor stays so #asset-ar-1 fragment links still land here.
        self.assertIn('id="asset-ar-1"', html_out)

    def test_noop_without_anchors(self):
        self.assertEqual(inject_preview_placeholders("<p>x</p>", self.REQS), "<p>x</p>")

    def test_survives_attribute_reordering(self):
        # blog.views._prepare_body re-serializes the body with BeautifulSoup,
        # which reorders attributes — injection must not depend on adjacency.
        html_out = inject_preview_placeholders(
            '<span class="asset-request-anchor" data-asset-type="screenshot" id="asset-ar-1"></span>',
            self.REQS,
        )
        self.assertIn("asset-request-placeholder", html_out)
        self.assertIn("Planned placement:", html_out)

    def test_unknown_anchor_gets_generic_card(self):
        out, _, _ = apply_asset_requests("[[ASSET:ghost]]", [])
        html_out = inject_preview_placeholders(out, [])
        self.assertIn("no matching asset_requests entry", html_out)
