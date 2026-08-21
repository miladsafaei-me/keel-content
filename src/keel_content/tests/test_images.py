"""Unit tests for the ``image-nb2`` in-article image contract + budget.

Mirrors the figures pass: deterministic marker/entry matching, integrity gate, and
the whole-post NB2 word-budget (:func:`nb2_cap`). Pure stdlib + Django settings
(no DB), hence ``SimpleTestCase`` with ``override_settings`` for the media copy.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from keel_content.core.images import (
    NB2_MIN_IMAGES,
    apply_images,
    count_words,
    image_violations,
    marker_ids,
    nb2_cap,
    normalize_images,
)

# A fully-valid images entry (everything image_violations checks, minus file-exists).
_OK = {"id": "img-1", "file": "c.images/img-1.webp", "width": 1520, "height": 855,
       "alt": "a scene", "caption": "the point"}


def _entry(i):
    return {**_OK, "id": f"img-{i}", "file": f"c.images/img-{i}.webp"}


class NormalizeTests(SimpleTestCase):
    def test_drops_incomplete_entries(self):
        raw = [_OK, {"id": "", "file": "x.webp"}, {"id": "img-9"}, "nope"]
        out = normalize_images(raw)
        self.assertEqual([e["id"] for e in out], ["img-1"])


class WordCountTests(SimpleTestCase):
    def test_strips_markup_and_markers(self):
        body = "One two three [[IMAGE:img-1]]\n```json\n{\"a\": 1, \"b\": 2}\n``` four"
        # fenced json + marker stripped; "One two three four" = 4 words
        self.assertEqual(count_words(body), 4)

    def test_empty(self):
        self.assertEqual(count_words(""), 0)
        self.assertEqual(count_words(None), 0)


class BudgetTests(SimpleTestCase):
    def test_cap_matches_rule(self):
        # NB2_IMAGES_PER_1000_WORDS per whole 1000 words, then floored at
        # NB2_MIN_IMAGES so even a short post may still carry a couple of photoreal
        # images. This test previously asserted the pre-floor rule (999 -> 0,
        # 0 -> 0, -5 -> 0) and went red when the floor was introduced; the floor is
        # deliberate and documented on nb2_cap, so the expectations move, not the code.
        self.assertEqual(nb2_cap(3900), 6)   # the user's worked example
        self.assertEqual(nb2_cap(1000), 2)
        self.assertEqual(nb2_cap(1999), 2)
        self.assertEqual(nb2_cap(2000), 4)
        # Below one full thousand the floor is what remains.
        self.assertEqual(nb2_cap(999), NB2_MIN_IMAGES)
        self.assertEqual(nb2_cap(0), NB2_MIN_IMAGES)
        self.assertEqual(nb2_cap(-5), NB2_MIN_IMAGES)


class ViolationTests(SimpleTestCase):
    def test_clean_bundle_passes(self):
        self.assertEqual(image_violations({"body_markdown": "just prose"}, bundle_dir=None), [])

    def test_no_images_no_markers_passes(self):
        self.assertEqual(image_violations({"body_markdown": "hi", "images": []}, bundle_dir=None), [])

    def test_marker_without_entry(self):
        b = {"body_markdown": "x\n[[IMAGE:img-1]]\ny", "images": []}
        errs = image_violations(b, bundle_dir=None)
        self.assertTrue(any("has no images entry" in e for e in errs))

    def test_entry_without_marker(self):
        b = {"body_markdown": "no marker here", "images": [_OK]}
        errs = image_violations(b, bundle_dir=None)
        self.assertTrue(any("has no [[IMAGE:img-1]] marker" in e for e in errs))

    def test_missing_alt_caption_dims_and_suffix(self):
        bad = {"id": "img-1", "file": "c.images/img-1.png", "alt": "", "caption": "",
               "width": 0, "height": 0}
        b = {"body_markdown": "[[IMAGE:img-1]]", "images": [bad]}
        errs = image_violations(b, bundle_dir=None)
        joined = " ".join(errs)
        self.assertIn("missing alt text", joined)
        self.assertIn("missing a caption", joined)
        self.assertIn("integer width/height", joined)
        self.assertIn("must be a .webp", joined)

    def test_over_budget_blocks(self):
        # ~1500 words -> cap 2; three valid images -> over budget.
        body = " ".join(["word"] * 1500) + "\n[[IMAGE:img-1]]\n[[IMAGE:img-2]]\n[[IMAGE:img-3]]"
        b = {"body_markdown": body, "images": [_entry(1), _entry(2), _entry(3)]}
        errs = image_violations(b, bundle_dir=None)
        self.assertTrue(any("exceed the budget" in e for e in errs))

    def test_within_budget_passes(self):
        # ~1500 words -> cap 2; two valid images -> OK.
        body = " ".join(["word"] * 1500) + "\n[[IMAGE:img-1]]\n[[IMAGE:img-2]]"
        b = {"body_markdown": body, "images": [_entry(1), _entry(2)]}
        self.assertEqual(image_violations(b, bundle_dir=None), [])


class ApplyTests(SimpleTestCase):
    def test_marker_ids(self):
        self.assertEqual(marker_ids("a\n[[IMAGE:img-2]]\nb\n[[IMAGE:img-5]]\n"), ["img-2", "img-5"])

    def test_apply_swaps_marker_and_copies_file(self):
        with tempfile.TemporaryDirectory() as bundle_dir, tempfile.TemporaryDirectory() as media:
            imgdir = Path(bundle_dir) / "c.images"
            imgdir.mkdir()
            (imgdir / "img-1.webp").write_bytes(b"RIFFfake-webp-bytes")
            body = "Intro.\n[[IMAGE:img-1]]\nOutro."
            entry = {"id": "img-1", "file": "c.images/img-1.webp", "width": 1520,
                     "height": 855, "alt": "a glass scene", "caption": "the takeaway"}
            with override_settings(MEDIA_ROOT=media):
                out, report = apply_images(body, [entry], bundle_dir=Path(bundle_dir), slug="s")
            self.assertNotIn("[[IMAGE:img-1]]", out)
            self.assertIn('class="cp-figure cp-figure--image"', out)
            self.assertIn("the takeaway", out)
            self.assertIn("/media/blog/images/", out)
            self.assertEqual(report.placed, ["img-1"])

    def test_unmatched_marker_is_stripped(self):
        out, report = apply_images("a\n[[IMAGE:img-9]]\nb", [], bundle_dir=None, slug="s")
        self.assertNotIn("[[IMAGE:img-9]]", out)
        self.assertEqual(report.unmatched_markers, ["img-9"])
