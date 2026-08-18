"""Site-wide anchor registry — detects two different targets claiming the same
anchor phrase across topic clusters.

`internal_links.py` (its sibling in this package) inserts a *given* edge list into
a body deterministically; it has no opinion about whether an anchor phrase is
already spoken for elsewhere on the site. Nothing today stops cluster A's linking
pass from claiming "copy trading" for `/blog/copy-trading` while cluster B's pass,
run independently and blind to A, claims the same phrase for
`/trading-glossary/copy-trading`. That is cannibalization at the internal-link
layer, and it is invisible until a human reads two articles side by side. This
module makes it visible: it scans every published post's body for the internal
links that already exist, groups them by a normalized anchor phrase, and reports
every phrase that resolved to more than one distinct target.

**Report only.** This module never writes to a Post — see
`intent-gate-rollout.md` P1.1. Rewriting anchors already live in published bodies
changes on-page signals and is a separate, separately-approved unit; this one only
tells a human where the collisions are.

No LLM and no network: the whole pass is regex extraction over text already in the
database plus deterministic string normalization, same posture as
`internal_links.py` and `external_links.py`.

The normalizer exists because two of the five consuming projects (Martiland,
Sarmayeh Media) publish Persian, one (SignalBots) publishes English, and the
others mix both — so "same anchor phrase" cannot mean "identical bytes". Each step
below closes one specific way the *same phrase to a human reader* would otherwise
compare unequal as text:

- **NFKC first.** Arabic-script text frequently arrives in more than one
  compatibility form (presentation forms, compatibility ligatures) that render
  identically but are different code points. NFKC folds those before anything
  else looks at the string, the same way it should run first in any Unicode text
  pipeline.
- **`str.lower()`, not `slugify`.** `lower()` is Unicode-aware and works on Persian
  the same as it does nothing-at-all on Persian (Persian has no case, so it is a
  no-op there and a real fold on Latin). `django.utils.text.slugify` is NOT used
  here — it transliterates/strips anything it doesn't recognize as ASCII, which
  means it silently deletes Persian anchors down to an empty string. That would
  make every Persian anchor collide on `""`, the exact opposite of what a registry
  needs.
- **Strip punctuation by Unicode category, not by a hardcoded character list.**
  Arabic/Persian punctuation (`؟ ، ؛ « » ٪` etc.) is a different set of code points
  than ASCII punctuation but the same general-category class (`P*`: `Po`, `Pi`,
  `Pf`, `Pd`, `Pc`, ...). Testing `unicodedata.category(c).startswith("P")` catches
  both alphabets' punctuation with one rule instead of two curated lists that will
  inevitably miss a mark the next script throws at it. Punctuation folds to a
  space (not deleted outright) so `"forex-broker"` and `"forex broker"` still
  compare equal without gluing the two words together.
- **Strip Arabic/Persian diacritics (harakat) and the tatweel.** The harakat
  (U+064B-U+0652, plus U+0670 the superscript alef) are vowel marks that
  professional/WordPress-imported Persian text sometimes carries and casual
  authoring never does — the same word compares unequal purely because one writer
  added fatha marks and another didn't. The tatweel (U+0640) is a pure
  justification/stretching glyph with no semantic content at all; it is deleted,
  not spaced, because it never separated anything to begin with.
- **Normalize the letter variants that differ only by encoding.** Arabic yeh
  (U+064A) vs Farsi yeh (U+06CC), Arabic kaf (U+0643) vs Farsi keh (U+06A9), and
  the three hamza-bearing alef forms (U+0622/U+0623/U+0625) vs bare alef (U+0627)
  are visually near-identical and represent the same letter in Persian text, but
  keyboards, WordPress imports, and hand-typed content mix both encodings within
  the same corpus. Left unmapped, "کارگزاری" typed with an Arabic kaf and the
  identical word typed with a Persian keh would register as two different
  anchors. Canonicalizing onto the Farsi forms (the ones a Persian keyboard
  actually produces) means the registry sees one anchor, not two near-duplicates
  splitting the same signal.
- **Zero-width non-joiner (U+200C) -> space.** ZWNJ is meaningful *inside* a
  compound Persian word (it prevents two letters from joining) but two anchors
  that differ only in whether a ZWNJ sits between two components are the same
  phrase to a reader. Folding it to a space rather than deleting it keeps the
  word boundary a plain-word-boundary regex still recognizes, then whitespace
  collapse cleans up the rest.
- **Collapse whitespace runs to one space.** Punctuation stripping and ZWNJ
  folding both produce new spaces; without a collapse pass `"forex  broker"` (two
  spaces) and `"forex broker"` (one) would compare unequal for a reason that has
  nothing to do with the actual anchor phrase.
- **Strip a leading/trailing English article, Latin-script only.** "the forex
  broker" and "forex broker" are the same anchor to a reader; Persian has no
  equivalent function word to strip, and forcing the same rule onto Persian text
  risks eating a real first/last word that happens to look article-like out of
  context. The check is "does this string contain any Arabic-script code point at
  all" — if it does, the string is left alone; if not, a leading/trailing
  the/a/an is dropped.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from keel_content import host

_ZWNJ = "‌"
_TATWEEL = "ـ"
# Arabic harakat (vowel/gemination/silence marks) + the superscript alef.
_ARABIC_DIACRITICS = tuple(chr(cp) for cp in range(0x064B, 0x0653)) + ("ٰ",)
# Encoding-only letter variants, mapped onto the form a Persian keyboard produces.
_LETTER_VARIANTS = str.maketrans(
    {
        "ي": "ی",  # Arabic yeh -> Farsi yeh
        "ك": "ک",  # Arabic kaf -> Farsi keh
        "آ": "ا",  # alef madda -> bare alef
        "أ": "ا",  # alef + hamza above -> bare alef
        "إ": "ا",  # alef + hamza below -> bare alef
    }
)

_WS_RE = re.compile(r"\s+")
_LEADING_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
_TRAILING_ARTICLE_RE = re.compile(r"\s+(the|a|an)$", re.IGNORECASE)
# Any Arabic-block code point (core block, supplement, presentation forms A/B) —
# used only to decide "is this Latin enough to strip an English article from",
# not as a general script classifier.
_ARABIC_SCRIPT_RE = re.compile(
    r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]"
)


def normalize_anchor(text: str) -> str:
    """Fold an anchor phrase to a canonical, script-aware comparison key.

    See the module docstring for why each step exists. Order matters: NFKC first
    (canonicalize compatibility forms before anything else looks at the string),
    then case-fold, then the Persian-specific folds, then punctuation-as-category
    (which also mops up ASCII punctuation), then whitespace collapse, then —
    Latin-script strings only — a leading/trailing English article.
    """
    if not text:
        return ""
    value = unicodedata.normalize("NFKC", text)
    value = value.lower()
    value = value.replace(_ZWNJ, " ")
    for mark in _ARABIC_DIACRITICS:
        value = value.replace(mark, "")
    value = value.replace(_TATWEEL, "")
    value = value.translate(_LETTER_VARIANTS)
    value = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in value)
    value = _WS_RE.sub(" ", value).strip()
    if not _ARABIC_SCRIPT_RE.search(value):
        value = _LEADING_ARTICLE_RE.sub("", value)
        value = _TRAILING_ARTICLE_RE.sub("", value).strip()
    return value


# A Markdown link whose target may or may not be internal — filtered by the "/"
# prefix check in ``_iter_internal_links``, same division of labor as
# ``internal_links.py``'s own regexes (match broadly, decide narrowly).
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
# An HTML anchor tag; ``href`` may appear anywhere among the attributes, and the
# inner text may itself carry markup (e.g. ``<a href="/x"><strong>Y</strong></a>``)
# which ``_strip_tags`` below cleans off the captured anchor text.
_HTML_A_RE = re.compile(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


def _target_key(path: str) -> str:
    """Normalize a target path so ``/blog/x`` and ``/blog/x/`` are one target."""
    return path.strip().rstrip("/").lower()


def _iter_internal_links(body: str) -> Iterable[tuple[str, str]]:
    """Yield ``(raw_anchor, target_path)`` for every internal link in ``body``.

    Internal means site-relative: the target starts with ``/``. An absolute
    ``http(s)://`` target is external and is never yielded — that is the entire
    filter, applied identically to both link syntaxes. Fenced code/mermaid blocks
    are skipped first (whole blocks, not just their opening/closing lines) so an
    anchor written as a Markdown example inside a fence is never mistaken for a
    real, live link — the same fence-blindness ``internal_links.py`` applies
    before inserting.
    """
    if not body:
        return
    lines = body.split("\n")
    kept: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    text = "\n".join(kept)

    for m in _MD_LINK_RE.finditer(text):
        anchor, target = m.group(1).strip(), m.group(2).strip()
        if target.startswith("/"):
            yield anchor, target
    for m in _HTML_A_RE.finditer(text):
        target, raw_anchor = m.group(1).strip(), _strip_tags(m.group(2))
        if target.startswith("/"):
            yield raw_anchor, target


@dataclass
class AnchorRegistry:
    """The result of scanning a corpus: normalized anchor -> {target: count}.

    Built by :func:`build_registry` (pure, no Django) or :func:`scan_anchor_registry`
    (the DB-touching wrapper). Carries enough provenance — a representative raw
    anchor and the source-post slugs per pairing — that :meth:`conflicts` needs no
    second pass over the corpus to explain itself.
    """

    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    raw_forms: dict[str, str] = field(default_factory=dict)
    sources: dict[str, dict[str, set[str]]] = field(default_factory=dict)

    def claimed_target(self, anchor: str) -> str | None:
        """The one target this anchor is unambiguously claimed for, or ``None``.

        Returns a target only when the normalized anchor maps to exactly one
        distinct target across the whole scanned corpus. An anchor this registry
        has never seen, and a conflicted anchor (mapped to more than one target),
        both return ``None`` — a conflict must never be treated as authoritative
        by a caller deciding whether to propose a new edge.
        """
        norm = normalize_anchor(anchor)
        targets = self.counts.get(norm)
        if not targets or len(targets) != 1:
            return None
        return next(iter(targets))

    def conflicts(self) -> list[dict]:
        """Every normalized anchor claimed by more than one target, as plain dicts.

        Sorted by total occurrence count descending, so the highest-traffic
        collision — the one costing the most cumulative link equity — surfaces
        first. Each entry is self-contained: the normalized anchor, one
        representative raw anchor as it actually appears in prose, every
        competing target with its count, and the source post slugs behind each
        pairing, so a human can act without re-deriving anything from the corpus.
        """
        out = []
        for norm, targets in self.counts.items():
            if len(targets) <= 1:
                continue
            total = sum(targets.values())
            competing = sorted(
                (
                    {
                        "target_path": target,
                        "count": count,
                        "source_slugs": sorted(self.sources.get(norm, {}).get(target, ())),
                    }
                    for target, count in targets.items()
                ),
                key=lambda entry: (-entry["count"], entry["target_path"]),
            )
            out.append(
                {
                    "anchor": norm,
                    "sample_raw_anchor": self.raw_forms.get(norm, norm),
                    "total_count": total,
                    "targets": competing,
                }
            )
        out.sort(key=lambda entry: (-entry["total_count"], entry["anchor"]))
        return out


def build_registry(records: Iterable[tuple[str, str]]) -> AnchorRegistry:
    """Aggregate ``(slug, body)`` records into an :class:`AnchorRegistry`.

    Pure function — no Django import touches this path, no I/O. Kept separate
    from :func:`scan_anchor_registry` so the extraction, normalization and
    conflict logic is unit-testable without a host database, the same split
    ``internal_links.apply_internal_links`` uses relative to the management
    commands that call it.
    """
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    raw_forms: dict[str, str] = {}
    sources: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for slug, body in records:
        for raw_anchor, target in _iter_internal_links(body or ""):
            norm = normalize_anchor(raw_anchor)
            if not norm:
                continue
            key = _target_key(target)
            if not key:
                continue
            counts[norm][key] += 1
            raw_forms.setdefault(norm, raw_anchor)
            sources[norm][key].add(slug)

    return AnchorRegistry(
        counts={anchor: dict(targets) for anchor, targets in counts.items()},
        raw_forms=raw_forms,
        sources={anchor: {t: set(s) for t, s in targets.items()} for anchor, targets in sources.items()},
    )


def scan_anchor_registry(*, cluster: str | None = None) -> AnchorRegistry:
    """Build the site-wide registry from every published post via ``host.py``.

    Reads each post's body as ``content_markdown_source`` falling back to
    ``content_raw`` — the same duck-typed access already used elsewhere in this
    package (``content_outbound_domains``, ``contentplan_rejudge_scope``) to read
    "whichever source-of-truth body field this host's Post model actually has".
    Deliberately does not read ``content_rendered``: that field is a cached
    render that can be stale between a body edit and its next refresh, whereas
    ``content_markdown_source``/``content_raw`` are the fields every write path in
    this package treats as ground truth.

    ``cluster`` optionally limits the scan to one ``TopicCluster.name`` — the
    per-cluster report a linking pass wants when it is only about to touch one
    cluster's articles.
    """
    Post = host.post_model()
    qs = Post.objects.filter(is_deleted=False, status="published")
    if cluster:
        qs = qs.filter(topic_cluster__name=cluster)
    records = (
        (post.slug, getattr(post, "content_markdown_source", "") or getattr(post, "content_raw", "") or "")
        for post in qs.iterator()
    )
    return build_registry(records)


def claimed_target(anchor: str, *, cluster: str | None = None) -> str | None:
    """Convenience wrapper: scan the corpus fresh, then look up ``anchor``.

    Costs one full published-post scan per call — fine for a one-off check, but a
    caller proposing many edges in the same pass (the cross-cluster linking pass
    this registry exists to back) should call :func:`scan_anchor_registry` once
    and reuse its ``.claimed_target`` method instead of re-scanning per anchor.
    """
    return scan_anchor_registry(cluster=cluster).claimed_target(anchor)
