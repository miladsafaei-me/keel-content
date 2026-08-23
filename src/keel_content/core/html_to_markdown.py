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

So this module never trusts the conversion. For each document it pre-cleans,
converts, renders the result back to HTML through the host's own renderer, and
compares. A document is converted only if the round trip is provably faithful;
otherwise it is left exactly as it was and reported. No model is involved at any
point — this is pure, repeatable text processing.

The pre-clean, and why it is not cheating
-----------------------------------------

A WYSIWYG corpus is full of markup that says nothing: spacer paragraphs, bold tags
wrapping a single ``&nbsp;``, a paragraph wrapper inside every table cell. Feeding
that straight to a converter fails the gate for reasons that have nothing to do
with the article — measured 2026-08-23 on 322 unconverted Sarmayeh Media posts,
those three shapes plus ``<thead>`` cells written as ``<td>`` accounted for nearly
all of it.

:func:`preclean` normalises exactly those shapes, and each of its rules is
**structural only** — it may not change a single character of text. That is not a
claim, it is enforced: the cleaned document's normalised text is compared with the
original's, and a rule that moves text disables the whole pre-clean for that
document. The comparison the gate then runs is against the CLEANED HTML, which is
the honest baseline, because the cleaned HTML renders identically to the original
in a browser.

What "faithful" means here, and why each part is in the test:

* **Text is identical** after normalising entities, Unicode form, and whitespace.
  Persian corpora encode ZWNJ both as a literal ``&zwnj;`` entity and as U+200C,
  so a naive comparison reports ~10% loss on text that is in fact untouched.
* **No block-level element is lost** — headings, lists, list items, tables, rows,
  cells, links, images, blockquotes, code, and inline emphasis. A dropped ``<a>``
  or a table cell folded into its neighbour is real damage.
* **Paragraph count may fall only by the number of ``<p>`` still nested inside a
  list item or table cell after the pre-clean.** Those are multi-paragraph cells:
  Markdown has no way to keep the second paragraph, and the pre-clean has already
  unwrapped every single-paragraph one. Any OTHER paragraph loss is a genuine
  layout change and fails the document.
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

# Inline emphasis: Markdown's delimiters must hug their content, so edge whitespace
# has to move out of these before conversion (see _hoist_edge_blanks).
_EMPHASIS_TAGS = ("strong", "b", "em", "i")
# Wrappers a WYSIWYG editor leaves behind that carry nothing when they hold no text.
_EMPTY_DROPPABLE = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "div")
# Elements that are content even with no text of their own.
_VOID_CONTENT = {
    "img", "iframe", "video", "audio", "canvas", "svg", "embed", "object", "table",
    "input", "hr",
}
# A <p> inside one of these cannot survive the round trip: Markdown has no
# paragraph inside a bullet or a table cell.
_CELL_TAGS = ("li", "td", "th")
# Set by the pre-clean on emphasis whose ``**`` form would not parse where it sits
# (see _emphasis_parses); the converter emits raw inline HTML for those instead.
_RAW_ATTR = "data-keel-raw-emphasis"
# A paragraph that opens with one of these reads as a list item, heading or quote
# once it is Markdown, so the paragraph stops being a paragraph (see convert_p).
_BLOCK_MARKER_RE = re.compile(r"^(\s*)(\d{1,9}[.)]|[-+*#>])(\s)")

_TAG_RE = re.compile(r"<([a-zA-Z0-9]+)")
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Zero-width and non-breaking characters a WYSIWYG editor scatters through Persian
# text. None of them is visible, so none of them may decide a fidelity verdict.
_INVISIBLE = ("‌", "‏", "‎", " ", "﻿", "​")
# Whitespace plus the zero-width characters an editor sprinkles at element edges.
_EDGE_BLANK_LEAD = re.compile(r"^[\s​﻿]+")
_EDGE_BLANK_TRAIL = re.compile(r"[\s​﻿]+$")


def normalize_text(markup: str) -> str:
    """Comparable text: tags out, entities decoded, Unicode + invisibles normalised."""
    text = _STRIP_TAGS_RE.sub(" ", markup or "")
    text = _html.unescape(text)
    text = unicodedata.normalize("NFC", text)
    for ch in _INVISIBLE:
        text = text.replace(ch, "")
    return _WS_RE.sub("", text)


def _soup(markup: str):
    from bs4 import BeautifulSoup

    # html.parser, deliberately: it is what markdownify itself parses with, so the
    # pre-clean and the conversion never disagree about the document's shape.
    return BeautifulSoup(markup or "", "html.parser")


def _is_blank(node) -> bool:
    """True when a node contributes no visible text and embeds nothing."""
    from bs4 import NavigableString

    if isinstance(node, NavigableString):
        return normalize_text(str(node)) == ""
    if node.name in _VOID_CONTENT or node.find(list(_VOID_CONTENT)):
        return False
    return normalize_text(node.get_text()) == ""


def _hoist_edge_blanks(tag) -> None:
    """Move leading/trailing blank characters OUT of an inline emphasis element.

    ``<strong>text&nbsp;</strong>`` converts to ``**text **``, which is not emphasis
    at all — the reader sees literal asterisks and the bold is gone. The blank
    belongs between the elements, not inside the delimiters, and moving it there
    changes no text: it stays in the same position in the document's character
    stream.
    """
    from bs4 import NavigableString

    strings = [s for s in tag.descendants if isinstance(s, NavigableString)]
    if not strings:
        return
    lead = _EDGE_BLANK_LEAD.match(str(strings[0]))
    if lead:
        first = strings[0]
        rest = str(first)[lead.end():]
        first.replace_with(NavigableString(rest))
        tag.insert_before(NavigableString(lead.group(0)))
    strings = [s for s in tag.descendants if isinstance(s, NavigableString)]
    if not strings:
        return
    trail = _EDGE_BLANK_TRAIL.search(str(strings[-1]))
    if trail:
        last = strings[-1]
        head = str(last)[: trail.start()]
        last.replace_with(NavigableString(head))
        tag.insert_after(NavigableString(trail.group(0)))


def _is_punct(ch: str) -> bool:
    return bool(ch) and unicodedata.category(ch)[0] in "PS"


def _is_blank_char(ch: str) -> bool:
    """A missing neighbour counts as whitespace: it is a line boundary."""
    return not ch or ch.isspace() or ch in "​﻿"


def _neighbour_chars(tag) -> tuple[str, str]:
    """The visible characters immediately before and after ``tag`` in its block."""

    def edge(node, last: bool) -> str:
        while node is not None:
            text = node if isinstance(node, str) else node.get_text()
            if text:
                return text[-1] if last else text[0]
            node = node.previous_sibling if last else node.next_sibling
        return ""

    return edge(tag.previous_sibling, True), edge(tag.next_sibling, False)


def _emphasis_parses(inner: str, prev_char: str, next_char: str) -> bool:
    """Would ``**inner**`` still be emphasis at this spot, or just literal asterisks?

    Markdown's delimiters are not free-standing: a run only opens when it is
    left-flanking and only closes when it is right-flanking. Bold text ending in an
    opening bracket — ``<strong>رگوله‌شده (</strong>مطابق`` — produces ``**x (**م``,
    whose closing run is preceded by punctuation and followed by a letter, so it
    closes nothing. The reader then sees the asterisks and loses the bold. Emphasis
    that fails this test is emitted as inline HTML instead, which every renderer
    passes through unchanged.
    """
    if not inner:
        return True
    opens = not _is_punct(inner[0]) or _is_blank_char(prev_char) or _is_punct(prev_char)
    closes = not _is_punct(inner[-1]) or _is_blank_char(next_char) or _is_punct(next_char)
    return opens and closes


def preclean(source_html: str) -> str:
    """Normalise editor artifacts that no converter can carry, without moving text.

    Five rules, each provably structural:

    1. A ``<td>`` inside ``<thead>`` becomes ``<th>``. A cell in a header row IS a
       header cell, and Markdown tables have no other kind in row one.
    2. Emphasis holding no visible text (``<strong>&#8203;</strong>``) is unwrapped,
       and blank characters at the edges of emphasis are moved outside it.
    3. A ``<p>``/``<div>``/heading holding no text and embedding nothing is dropped.
       These are the editor's spacer artifacts (``<p>&nbsp;</p>``).
    4. A ``<p>`` that is the entire content of a list item or table cell is
       unwrapped. No converter can keep it, and unwrapping it up front makes the
       gate's paragraph accounting exact instead of approximate.
    5. Emphasis whose ``**`` form would not parse where it sits is marked for raw
       inline HTML (see :func:`_emphasis_parses`). Nothing is added or removed —
       only the notation the converter will use for it.

    Returns the original markup unchanged if any rule moved text — that would be a
    bug in this function, and the safe response is to convert nothing.
    """
    if not source_html:
        return source_html or ""
    soup = _soup(source_html)

    for thead in soup.find_all("thead"):
        for cell in thead.find_all("td"):
            cell.name = "th"

    # Hoist first, THEN drop what is left empty: emphasis holding nothing but a
    # zero-width space is emptied BY the hoist, and an empty <strong> the converter
    # then drops is a lost block element as far as the gate is concerned.
    for tag in soup.find_all(_EMPHASIS_TAGS):
        _hoist_edge_blanks(tag)
    for tag in soup.find_all(_EMPHASIS_TAGS):
        if _is_blank(tag):
            tag.unwrap()

    # Dropping an empty wrapper can empty its parent, so run to a fixpoint rather
    # than once: <div><p>&nbsp;</p></div> is two passes, not one.
    for _ in range(3):
        doomed = [t for t in soup.find_all(_EMPTY_DROPPABLE) if _is_blank(t)]
        if not doomed:
            break
        for tag in doomed:
            tag.decompose()

    for cell in soup.find_all(_CELL_TAGS):
        kids = [c for c in cell.contents if not _is_blank(c)]
        if len(kids) == 1 and getattr(kids[0], "name", None) == "p":
            kids[0].unwrap()

    for tag in soup.find_all(_EMPHASIS_TAGS):
        prev_char, next_char = _neighbour_chars(tag)
        if not _emphasis_parses(tag.get_text(), prev_char, next_char):
            tag[_RAW_ATTR] = "1"

    cleaned = str(soup)
    if normalize_text(cleaned) != normalize_text(source_html):
        return source_html
    return cleaned


def _tag_counts(markup: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tag in _TAG_RE.findall(markup or ""):
        tag = tag.lower()
        if tag in _BLOCK_TAGS:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def _paragraphs(markup: str) -> tuple[int, int]:
    """``(total <p>, <p> nested inside a list item or table cell)``.

    Counted with the parser rather than a regex because the regex counted only the
    FIRST ``<p>`` after each cell's opening tag, so a cell holding three paragraphs
    was allowed to lose one and failed on the other two for no stated reason.
    """
    soup = _soup(markup)
    paras = soup.find_all("p")
    nested = sum(1 for p in paras if p.find_parent(_CELL_TAGS) is not None)
    return len(paras), nested


def _converter():
    """markdownify, plus the one rule it has no option for.

    Emphasis marked by the pre-clean is emitted as inline HTML rather than ``**``,
    because at that spot the asterisks would be read as literal text. Every method
    forwards through ``*args`` so the subclass survives markdownify's signature
    changing between majors.
    """
    from markdownify import MarkdownConverter

    class _EmphasisSafeConverter(MarkdownConverter):
        def convert_p(self, el, text, *args, **kwargs):
            """Keep a paragraph a paragraph.

            ``<p>3. آیا بیت‌کوین امن است؟</p>`` converts to ``3. آیا ...``, which any
            Markdown renderer reads as an ordered-list item — the paragraph becomes a
            bullet and the numbering restarts. markdownify's ``escape_misc`` fixes it
            globally, but escaping every ``*``, ``_`` and ``.`` in the body makes the
            prose stop matching the anchor phrases a linking pass was shown. So the
            escape is applied here only, and only to the one character that changes
            the block's type.
            """
            out = super().convert_p(el, text, *args, **kwargs)
            lead = len(out) - len(out.lstrip("\n"))
            head, body = out[:lead], out[lead:]
            return head + _BLOCK_MARKER_RE.sub(
                lambda m: f"{m.group(1)}{m.group(2)[:-1]}\\{m.group(2)[-1]}{m.group(3)}"
                if m.group(2)[-1] in ".)"
                else f"{m.group(1)}\\{m.group(2)}{m.group(3)}",
                body,
                count=1,
            )

        def _raw(self, el, text, tag, sup, *args, **kwargs):
            if el.get(_RAW_ATTR) and text:
                return f"<{tag}>{text}</{tag}>"
            return sup(el, text, *args, **kwargs)

        def convert_strong(self, el, text, *args, **kwargs):
            return self._raw(el, text, "strong", super().convert_strong, *args, **kwargs)

        def convert_b(self, el, text, *args, **kwargs):
            return self._raw(el, text, "strong", super().convert_b, *args, **kwargs)

        def convert_em(self, el, text, *args, **kwargs):
            return self._raw(el, text, "em", super().convert_em, *args, **kwargs)

        def convert_i(self, el, text, *args, **kwargs):
            return self._raw(el, text, "em", super().convert_i, *args, **kwargs)

    return _EmphasisSafeConverter(**_MARKDOWNIFY_OPTS)


def to_markdown(source_html: str) -> str:
    """HTML -> Markdown. Deterministic; no fidelity judgement of its own."""
    return _converter().convert(source_html or "")


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
    cleaned = preclean(source_html)
    markdown = to_markdown(cleaned)
    try:
        round_tripped = render(markdown)
    except Exception as exc:  # a renderer that throws is a failed document, not a crash
        return markdown, False, {"error": f"render failed: {exc}"}

    similarity = difflib.SequenceMatcher(
        None, normalize_text(cleaned), normalize_text(round_tripped)
    ).ratio()

    before, after = _tag_counts(cleaned), _tag_counts(round_tripped)
    lost = {
        tag: (count, after.get(tag, 0))
        for tag, count in before.items()
        if after.get(tag, 0) < count
    }

    p_before, p_nested = _paragraphs(cleaned)
    p_after, _ = _paragraphs(round_tripped)
    paragraphs_ok = p_after >= p_before - p_nested

    report = {
        "similarity": round(similarity, 5),
        "lost_tags": lost,
        "paragraphs": {"before": p_before, "after": p_after, "nested_allowance": p_nested},
        "precleaned": cleaned != source_html,
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
