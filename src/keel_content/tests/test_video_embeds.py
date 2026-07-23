"""Unit tests for the video-embed pass (LLM-sourced, deterministically verified).

Run with ``verify=False`` so no network is touched; the oEmbed check itself is
exercised in production (and failures degrade to asset requests, never crash).
"""

from __future__ import annotations

from django.test import SimpleTestCase

from keel_content.core.video_embeds import (
    apply_video_embeds,
    extract_video_id,
    normalize_video_embeds,
)


class ExtractIdTests(SimpleTestCase):
    def test_url_forms(self):
        for url in (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?t=1&v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        ):
            self.assertEqual(extract_video_id(url), "dQw4w9WgXcQ", url)

    def test_non_youtube_rejected(self):
        self.assertEqual(extract_video_id("https://vimeo.com/12345"), "")


class NormalizeTests(SimpleTestCase):
    def test_drops_bad_entries(self):
        raw = [
            {"id": "v1", "url": "https://youtu.be/dQw4w9WgXcQ", "title": "t"},
            {"id": "", "url": "https://youtu.be/dQw4w9WgXcQ"},
            {"id": "v3", "url": "https://example.com/video"},
        ]
        out = normalize_video_embeds(raw)
        self.assertEqual([e["id"] for e in out], ["v1"])


class ApplyTests(SimpleTestCase):
    def test_marker_becomes_nocookie_embed(self):
        body = "Intro.\n\n[[VIDEO:v1]]\n\nOutro."
        embeds = [{"id": "v1", "url": "https://youtu.be/dQw4w9WgXcQ",
                   "title": "Setup walkthrough", "channel": "MetaQuotes"}]
        out, fallbacks, report = apply_video_embeds(body, embeds, verify=False)
        self.assertIn("youtube-nocookie.com/embed/dQw4w9WgXcQ", out)
        self.assertIn('class="video-embed"', out)
        self.assertIn("Setup walkthrough — MetaQuotes", out)
        self.assertNotIn("[[VIDEO:", out)
        self.assertEqual(report.embedded, ["v1"])
        self.assertEqual(fallbacks, [])

    def test_unmatched_marker_downgrades_to_asset(self):
        out, fallbacks, report = apply_video_embeds("[[VIDEO:ghost]]", [], verify=False)
        self.assertIn("[[ASSET:video-ghost]]", out)
        self.assertEqual(report.unmatched_markers, ["ghost"])
        self.assertEqual(fallbacks[0]["id"], "video-ghost")
        self.assertEqual(fallbacks[0]["type"], "video")

    def test_inline_marker_untouched(self):
        body = "Watch [[VIDEO:v1]] inline."
        out, fallbacks, _ = apply_video_embeds(
            body, [{"id": "v1", "url": "https://youtu.be/dQw4w9WgXcQ"}], verify=False
        )
        self.assertEqual(out, body)
        self.assertEqual(fallbacks, [])
