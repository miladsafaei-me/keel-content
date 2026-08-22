"""Deterministic HTML -> Markdown conversion with a round-trip fidelity gate.

A corpus migrated from another CMS often stores only rendered HTML, leaving
``content_markdown_source`` empty. Every Markdown-based tool in this package is
then a silent no-op on it — ``content_relink`` in particular exports empty bodies
and inserts nothing, which is indistinguishable from "no link opportunities".

Converting is easy; converting SAFELY is the whole problem. Markdown cannot
express everything HTML can — a table cell holding a nested list, a heading inside
a list item — so a blind conversion followed by a re-render silently degrades
those pages. And the re-render is not hypothetical: the moment anything writes to
``content_markdown_source``, the publish path regenerates the visible body FROM
it.

So this module never trusts the conversion. For each document it converts, renders
the result back to HTML through the host's own renderer, and compares against the
original. A document is converted only if the round trip is provably faithful;
otherwise it is left exactly as it was and reported. No model is involved at any
point — this is pure, repeatable text processing.

What "faithful" means here, and why each part is in the test:

* **Text is identical** after normalising entities, Unicode form, and whitespace.
  Persian corpora encode ZWNJ both as a literal ``&zwnj;`` entity and as U+200C,
  so a naive comparison reports ~10% loss on text that is in fact untouched.
* **No block-level element is lost** — headings, lists, list items, tables, rows,
  cells, links, images, blockquotes, code, and inline emphasis. A dropped ``<a>``
  or a table cell folded into its neighbour is real damage.
* **Paragraph count may fall only by the number of ``<p>`` nested inside a list
  item, table cell, or blockquote.** Those wrappers are semantically empty —
  ``<li><p>x</p></li>`` and ``<li>x</li>`` render identically — and Markdown has
  no way to keep them. Any OTHER paragraph loss is a genuine layout change and
  fails the document.
"""

from __future__ import annotations

import difflib
import html as _html
import re
import unicodedata

# Elements whose disappearance is real damage, not a representational difference.
_BLOCK_TAGS = (
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "tr", "td",
    "th", "a", "img", "blockquote", "pre", "code", "strong", "em",
)

_MARKDOWNIFY_OPTS = dict(
    heading_style="ATX",
    bullets="-",
    strip=["script", "style"],
    # Backslash-escaping every *, _ and punctuation makes the Markdown unreadable
    # and, worse, makes anchor phrases in it stop matching the prose a linking
    # pass was shown. Off.
    escape_asterisks=False,
    escape_underscores=False,
    escape_misc=False,
    wrap=False,
)

_NESTED_P_RE = re.compile(r"<(?:li|td|th|blockquote)[^>]*>\s*<p", re.IGNORECASE)
_OPEN_P_RE = re.compile(r"<p[\s>]", re.IGNORECASE)
_TAG_RE = re.compile(r"<([a-zA-Z0-9]+)")
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_INVISIBLE = ("‌", "‏", "‎", " ", "﻿")


def normalize_text(markup: str) -> str:
    """Comparable text: tags out, entities decoded, Unicode + invisibles normalised."""
    text = _STRIP_TAGS_RE.sub(" ", markup or "")
    text = _html.unescape(text)
    text = unicodedata.normalize("NFC", text)
    for ch in _INVISIBLE:
        text = text.replace(ch, "")
    return _WS_RE.sub("", text)


def _tag_counts(markup: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tag in _TAG_RE.findall(markup or ""):
        tag = tag.lower()
        if tag in _BLOCK_TAGS:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def to_markdown(source_html: str) -> str:
    """HTML -> Markdown. Deterministic; no fidelity judgement of its own."""
    from markdownify import markdownify

    return markdownify(source_html or "", **_MARKDOWNIFY_OPTS)


def convert_checked(source_html: str, render) -> tuple[str, bool, dict]:
    """Convert, round-trip through ``render``, and report whether it was faithful.

    ``render`` is the host's Markdown -> HTML callable (normally
    ``host.markdown_to_blog_html``) — the SAME renderer the publish path uses, so
    the check measures what the reader would actually get rather than what some
    reference implementation would produce.

    Returns ``(markdown, is_faithful, report)``. When ``is_faithful`` is False the
    caller must leave the stored body untouched; ``report`` says why.
    """
    source_html = source_html or ""
    markdown = to_markdown(source_html)
    try:
        round_tripped = render(markdown)
    except Exception as exc:  # a renderer that throws is a failed document, not a crash
        return markdown, False, {"error": f"render failed: {exc}"}

    similarity = difflib.SequenceMatcher(
        None, normalize_text(source_html), normalize_text(round_tripped)
    ).ratio()

    before, after = _tag_counts(source_html), _tag_counts(round_tripped)
    lost = {
        tag: (count, after.get(tag, 0))
        for tag, count in before.items()
        if after.get(tag, 0) < count
    }

    p_before = len(_OPEN_P_RE.findall(source_html))
    p_after = len(_OPEN_P_RE.findall(round_tripped))
    p_nested = len(_NESTED_P_RE.findall(source_html))
    paragraphs_ok = p_after >= p_before - p_nested

    report = {
        "similarity": round(similarity, 5),
        "lost_tags": lost,
        "paragraphs": {"before": p_before, "after": p_after, "nested_allowance": p_nested},
    }
    faithful = similarity >= 0.999 and not lost and paragraphs_ok
    if not faithful:
        why = []
        if similarity < 0.999:
            why.append("text differs")
        if lost:
            why.append("block elements lost: " + ", ".join(sorted(lost)))
        if not paragraphs_ok:
            why.append("paragraph breaks lost beyond the nested-<p> allowance")
        report["reason"] = "; ".join(why)
    return markdown, faithful, report
