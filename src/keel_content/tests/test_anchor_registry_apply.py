"""Rewriting an adjudicated anchor conflict: what it touches and what it refuses."""

from __future__ import annotations

from django.test import SimpleTestCase

from keel_content.core.anchor_registry import _target_key, normalize_anchor
from keel_content.management.commands.anchor_registry_apply import _rewrite


def _run(body, anchor, loser, winner):
    return _rewrite(body, normalize_anchor(anchor), _target_key(loser), winner)


class RewriteTests(SimpleTestCase):
    def test_a_matching_link_is_repointed(self):
        body, hits = _run("متن [خرید ملک](/sale) ادامه", "خرید ملک", "/sale", "/sale/istanbul")
        self.assertEqual(hits, 1)
        self.assertIn("[خرید ملک](/sale/istanbul)", body)

    def test_a_trailing_slash_is_the_same_target(self):
        _, hits = _run("[x](/sale/)", "x", "/sale", "/sale/istanbul")
        self.assertEqual(hits, 1)

    def test_the_same_anchor_pointing_elsewhere_is_left_alone(self):
        body, hits = _run("[خرید ملک](/rent)", "خرید ملک", "/sale", "/sale/istanbul")
        self.assertEqual((hits, body), (0, "[خرید ملک](/rent)"))

    def test_a_different_anchor_on_the_losing_target_is_left_alone(self):
        body, hits = _run("[چیز دیگر](/sale)", "خرید ملک", "/sale", "/sale/istanbul")
        self.assertEqual((hits, body), (0, "[چیز دیگر](/sale)"))

    def test_an_orthographic_variant_still_matches(self):
        """Persian yeh/kaf encoding differs between authors; the registry folds it."""
        _, hits = _run("[اجاره ی ملك](/rent)", "اجاره ي ملک", "/rent", "/rent/istanbul")
        self.assertEqual(hits, 1)

    def test_a_self_link_is_unwrapped_to_plain_text(self):
        body, hits = _run("مقاله [اجاره ملک](/rent/istanbul) دارد", "اجاره ملک", "/rent/istanbul", None)
        self.assertEqual(hits, 1)
        self.assertEqual(body, "مقاله اجاره ملک دارد")

    def test_every_occurrence_in_one_body_is_rewritten(self):
        body, hits = _run("[a](/x) و [a](/x)", "a", "/x", "/y")
        self.assertEqual(hits, 2)
        self.assertEqual(body.count("(/y)"), 2)

    def test_an_empty_body_is_a_no_op(self):
        self.assertEqual(_run("", "a", "/x", "/y"), ("", 0))
