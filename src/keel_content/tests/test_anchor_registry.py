"""Site-wide anchor registry: normalizer, link extraction, conflict detection.

Pure stdlib (no DB) — ``build_registry`` takes plain ``(slug, body)`` records
instead of touching ``host.post_model()``, the same split
``internal_links.apply_internal_links`` uses relative to its callers. Hence
``SimpleTestCase``.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from keel_content.core.anchor_registry import build_registry, normalize_anchor


class NormalizeAnchorTests(SimpleTestCase):
    def test_persian_yeh_variant_normalizes_equal(self):
        # Arabic yeh (ي, U+064A) vs Farsi yeh (ی, U+06CC) in the same word.
        arabic_yeh = "کارگزاري"
        farsi_yeh = "کارگزاری"
        self.assertEqual(normalize_anchor(arabic_yeh), normalize_anchor(farsi_yeh))

    def test_persian_keh_variant_normalizes_equal(self):
        # Arabic kaf (ك, U+0643) vs Farsi keh (ک, U+06A9).
        arabic_kaf = "كپی تریدینگ"
        farsi_keh = "کپی تریدینگ"
        self.assertEqual(normalize_anchor(arabic_kaf), normalize_anchor(farsi_keh))

    def test_zwnj_normalizes_equal_to_plain_space(self):
        with_zwnj = "می‌خواهم"  # zero-width non-joiner between the two parts
        with_space = "می خواهم"
        self.assertEqual(normalize_anchor(with_zwnj), normalize_anchor(with_space))

    def test_diacritics_normalize_equal(self):
        with_harakat = "الْفَوْرِكس"  # same word with harakat marks added
        without = "الفورکس"
        self.assertEqual(normalize_anchor(with_harakat), normalize_anchor(without))

    def test_persian_punctuation_stripped(self):
        self.assertEqual(normalize_anchor("رمزارز؟"), normalize_anchor("رمزارز"))
        self.assertEqual(normalize_anchor("«فارکس»"), normalize_anchor("فارکس"))

    def test_latin_leading_article_stripped(self):
        self.assertEqual(
            normalize_anchor("The Best Forex Broker"),
            normalize_anchor("best forex broker"),
        )

    def test_latin_trailing_article_stripped(self):
        self.assertEqual(normalize_anchor("Copy Trading a"), normalize_anchor("copy trading"))

    def test_article_not_stripped_from_persian_string(self):
        # Persian has no equivalent function word; the Latin-only guard must not
        # eat a real leading/trailing Persian word by accident.
        self.assertEqual(normalize_anchor("بهترین بروکر"), "بهترین بروکر")

    def test_case_and_whitespace_fold(self):
        self.assertEqual(
            normalize_anchor("  Copy   TRADING  "),
            normalize_anchor("copy trading"),
        )

    def test_hyphen_becomes_word_boundary_not_glue(self):
        self.assertEqual(normalize_anchor("forex-broker"), "forex broker")

    def test_empty_input(self):
        self.assertEqual(normalize_anchor(""), "")
        self.assertEqual(normalize_anchor(None), "")


class BuildRegistryLinkExtractionTests(SimpleTestCase):
    def test_external_https_link_ignored(self):
        body = 'See [external guide](https://example.com/guide) for more.'
        registry = build_registry([("post-a", body)])
        self.assertEqual(registry.counts, {})

    def test_markdown_and_html_link_to_same_path_counted_together(self):
        body_a = "See [copy trading](/blog/copy-trading) for picks."
        body_b = 'Read about <a href="/blog/copy-trading/">copy trading</a> too.'
        registry = build_registry([("post-a", body_a), ("post-b", body_b)])
        norm = normalize_anchor("copy trading")
        self.assertEqual(registry.counts[norm], {"/blog/copy-trading": 2})
        self.assertEqual(
            registry.sources[norm]["/blog/copy-trading"], {"post-a", "post-b"}
        )

    def test_html_anchor_with_nested_markup_strips_tags(self):
        body = '<a href="/blog/mirror-trading"><strong>mirror trading</strong></a> is related.'
        registry = build_registry([("post-a", body)])
        norm = normalize_anchor("mirror trading")
        self.assertEqual(registry.counts[norm], {"/blog/mirror-trading": 1})

    def test_link_inside_fenced_code_block_ignored(self):
        body = "```\n[copy trading](/blog/copy-trading)\n```\nReal prose has no link here."
        registry = build_registry([("post-a", body)])
        self.assertEqual(registry.counts, {})

    def test_trailing_slash_and_case_collapse_to_one_target(self):
        body_a = "[Forex Guide](/blog/Forex-Guide/)"
        body_b = "[forex guide](/blog/forex-guide)"
        registry = build_registry([("post-a", body_a), ("post-b", body_b)])
        norm = normalize_anchor("forex guide")
        self.assertEqual(registry.counts[norm], {"/blog/forex-guide": 2})


class ConflictDetectionTests(SimpleTestCase):
    def test_single_target_used_fifty_times_is_not_a_conflict(self):
        records = [
            (f"post-{i}", "See [copy trading](/blog/copy-trading) here.")
            for i in range(50)
        ]
        registry = build_registry(records)
        self.assertEqual(registry.conflicts(), [])
        self.assertEqual(registry.claimed_target("copy trading"), "/blog/copy-trading")

    def test_two_target_conflict_detected_and_reported(self):
        records = [
            ("post-a", "See [copy trading](/blog/copy-trading) here."),
            ("post-b", 'See <a href="/trading-glossary/copy-trading">copy trading</a> here.'),
        ]
        registry = build_registry(records)
        conflicts = registry.conflicts()
        self.assertEqual(len(conflicts), 1)
        entry = conflicts[0]
        self.assertEqual(entry["anchor"], normalize_anchor("copy trading"))
        self.assertEqual(entry["total_count"], 2)
        targets = {t["target_path"]: t for t in entry["targets"]}
        self.assertEqual(set(targets), {"/blog/copy-trading", "/trading-glossary/copy-trading"})
        self.assertEqual(targets["/blog/copy-trading"]["source_slugs"], ["post-a"])
        self.assertEqual(
            targets["/trading-glossary/copy-trading"]["source_slugs"], ["post-b"]
        )

    def test_claimed_target_returns_none_for_conflicted_anchor(self):
        records = [
            ("post-a", "See [copy trading](/blog/copy-trading) here."),
            ("post-b", 'See <a href="/trading-glossary/copy-trading">copy trading</a> here.'),
        ]
        registry = build_registry(records)
        self.assertIsNone(registry.claimed_target("copy trading"))

    def test_claimed_target_returns_none_for_unknown_anchor(self):
        registry = build_registry([("post-a", "No links here at all.")])
        self.assertIsNone(registry.claimed_target("nonexistent phrase"))

    def test_conflicts_sorted_by_total_count_descending(self):
        records = [
            ("post-a", "[low volume](/blog/x)"),
            ("post-b", "[low volume](/blog/y)"),
            ("post-c", "[high volume](/blog/p)"),
            ("post-d", "[high volume](/blog/q)"),
            ("post-e", "[high volume](/blog/p)"),
            ("post-f", "[high volume](/blog/q)"),
        ]
        registry = build_registry(records)
        conflicts = registry.conflicts()
        self.assertEqual(len(conflicts), 2)
        self.assertEqual(conflicts[0]["anchor"], "high volume")
        self.assertEqual(conflicts[0]["total_count"], 4)
        self.assertEqual(conflicts[1]["anchor"], "low volume")
        self.assertEqual(conflicts[1]["total_count"], 2)

    def test_persian_anchor_variants_collide_into_one_conflict(self):
        # Two spellings of the same term (Arabic vs Farsi yeh), each claiming a
        # different target, must still be recognized as ONE conflicting anchor.
        records = [
            ("post-a", "بیشتر در [کارگزاري](/blog/broker-a) بخوانید."),
            ("post-b", "بیشتر در [کارگزاری](/blog/broker-b) بخوانید."),
        ]
        registry = build_registry(records)
        conflicts = registry.conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["total_count"], 2)
        self.assertEqual(
            {t["target_path"] for t in conflicts[0]["targets"]},
            {"/blog/broker-a", "/blog/broker-b"},
        )
