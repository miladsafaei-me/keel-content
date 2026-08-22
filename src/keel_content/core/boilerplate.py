"""Find the components a page corpus publishes more than once.

A section of a site that ships one page per topic converges on a house style, and
that is wanted: the same section order, the same table columns, the same figure
vocabulary. What is not wanted is the same *text* and the same *drawing*. A reader
who opens three pages in a row and meets the same box and the same chart three
times concludes the pages were generated, and a search engine discounts the
repeated span as boilerplate — so the words are paid for and not counted.

The distinction this module draws is between structure and substance:

* **Repeated structure is fine and is not reported.** Anchors, column headers and
  block *types* are the contract that makes two pages comparable.
* **Repeated substance is reported.** A paragraph, a heading or a rendered figure
  that is byte-identical on more than the allowed number of pages.

It is deliberately business-blind. A caller hands it text it has already extracted
and a fingerprint per figure; this module never parses HTML, never knows what a
page is about, and holds no thresholds of its own beyond the defaults — the
consumer owns what "too many" means, because that is an editorial judgement and it
differs per section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

__all__ = ["PageUnits", "Repeat", "find_repeats", "format_report"]

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Collapse whitespace so a re-wrapped line is not read as a different string."""
    return _SPACE_RE.sub(" ", text).strip()


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


@dataclass(frozen=True)
class PageUnits:
    """One page, reduced to the three things worth comparing across a corpus.

    ``blocks`` are the page's body texts — one entry per paragraph, list item,
    callout, caption or cell, already extracted by the caller. ``headings`` are its
    section headings. ``figures`` are fingerprints: whatever string the caller can
    produce that is equal exactly when two figures would render identically (a hash
    of the geometry, or the parameters that produced it).
    """

    blocks: Sequence[str] = field(default_factory=tuple)
    headings: Sequence[str] = field(default_factory=tuple)
    figures: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class Repeat:
    """One piece of substance published on more pages than allowed."""

    kind: str
    value: str
    pages: tuple[str, ...]
    words: int

    @property
    def count(self) -> int:
        return len(self.pages)


def _collect(
    corpus: Mapping[str, PageUnits],
    attr: str,
    *,
    min_words: int,
) -> dict[str, list[str]]:
    """Map each distinct value to the sorted pages carrying it.

    A value repeated *within* one page counts once for that page: an author who
    uses the same phrase twice on one page has a different problem from one who
    publishes it on twelve.
    """
    seen: dict[str, set[str]] = {}
    for page, units in corpus.items():
        for raw in getattr(units, attr):
            value = _normalize(raw)
            if not value or _word_count(value) < min_words:
                continue
            seen.setdefault(value, set()).add(page)
    return {value: sorted(pages) for value, pages in seen.items()}


def find_repeats(
    corpus: Mapping[str, PageUnits],
    *,
    max_pages: int = 1,
    min_block_words: int = 25,
    max_figure_pages: int | None = None,
    max_heading_pages: int | None = None,
) -> list[Repeat]:
    """Every block, heading and figure appearing on more than the allowed pages.

    ``max_pages`` is the shared default — 1 means "a thing may appear on one page".
    ``max_heading_pages`` and ``max_figure_pages`` override it for those kinds,
    since a section named after a shared contract may legitimately repeat where a
    paragraph never should.

    ``min_block_words`` keeps short fragments out: a table cell reading "2 to 3
    candles" is data, and two pages stating the same measurement are agreeing
    rather than duplicating. Headings and figures carry no word floor — a heading
    is short by nature, and a figure has no words at all.
    """
    heading_cap = max_pages if max_heading_pages is None else max_heading_pages
    figure_cap = max_pages if max_figure_pages is None else max_figure_pages

    plan = (
        ("block", "blocks", min_block_words, max_pages),
        ("heading", "headings", 0, heading_cap),
        ("figure", "figures", 0, figure_cap),
    )

    repeats: list[Repeat] = []
    for kind, attr, floor, cap in plan:
        for value, pages in _collect(corpus, attr, min_words=floor).items():
            if len(pages) > cap:
                repeats.append(
                    Repeat(kind=kind, value=value, pages=tuple(pages),
                           words=_word_count(value))
                )

    repeats.sort(key=lambda r: (-r.count, -r.words, r.kind, r.value))
    return repeats


def format_report(repeats: Iterable[Repeat], *, width: int = 96) -> list[str]:
    """One line per repeat, then one line naming the pages it landed on."""
    lines: list[str] = []
    for r in repeats:
        head = r.value if len(r.value) <= width else r.value[: width - 1] + "…"
        lines.append(f"  {r.kind:7} on {r.count:2} pages ({r.words}w)  {head}")
        lines.append(f"          {', '.join(r.pages)}")
    return lines
