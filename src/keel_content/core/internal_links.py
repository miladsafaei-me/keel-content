"""Deterministic insertion of within-cluster blog->blog internal links.

Blog->blog cross-links are the link graph that makes a topic cluster rank
(pillar<->spoke). They are NOT decided during article generation: at generation
time the parallel author agents each work in a fresh context and cannot see the
sibling articles, so any ``/blog/<slug>`` they guessed would be wrong. Instead a
cluster-linking pass runs once the whole cluster exists and emits, per article, a
structured edge list ``[{"anchor", "target_url"}]``. This module turns that plan
into the published body:

1. **Dedupe** by target URL (one link per distinct target, mirroring the editorial
   "first/best mention only" rule).
2. **Insert** each link at the first *plain-text* occurrence of its ``anchor`` in
   the body, converting ``anchor`` -> ``[anchor](target_url)``. Only prose lines
   are touched: fenced code blocks, raw-HTML / visual blocks (any line containing
   ``<``/``>``), headings, tables, blockquotes and lines that already carry a
   Markdown link are skipped, so the AI-emitted ``<script>``/``<canvas>``/mermaid
   widgets are never corrupted.
3. **Idempotent** — a target already linked anywhere in the body is skipped, so
   re-applying the same plan (or re-importing a bundle with ``--regenerate``)
   yields the same body. The pass is recomputed from the clean bundle body on each
   publish, so it never stacks links.

No LLM and no network here: the relevance judgement and anchor choice were made by
the cluster-linking planner upstream; this module is the deterministic, safe
mechanical insertion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Safety ceiling on links inserted per article. Not a target — the planner is told
# to link only where the cross-reference earns its place; this just caps a runaway
# plan (e.g. a pillar over-linking every spoke inline).
_MAX_LINKS_PER_ARTICLE = 8

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# A complete inline Markdown link, used to (a) find existing-link char spans so we
# never nest a link inside one, and (b) count links per line to honor <=2/paragraph.
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")
# Honor BLOG.md's "<=2 internal links per paragraph". A paragraph in these bodies is
# almost always a single line, so cap inserted+existing links per line at 2.
_MAX_LINKS_PER_LINE = 2
# An actual HTML/markup tag: ``<tag``, ``</tag``, a self-close ``/>`` or a comment.
# Deliberately does NOT match a bare comparison operator in prose ("latency < 10ms",
# "RR > 2") — those are legitimate plain-text lines that must stay link-eligible. A
# real tag never has whitespace right after ``<``, so ``</?[a-zA-Z]`` separates the
# two cases cleanly.
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z]|/>|<!--")

# An inline Markdown link whose target is a RELATIVE blog path (``/blog/<slug>``) —
# the only form the inserter ever emits. Used to reset a body to its clean, unlinked
# state before re-running the cluster-linking plan. Relative-only on purpose: an
# absolute ``https://other-site/blog/...`` external source must never be unwrapped, and
# glossary/landing links (``/trading-glossary/``, ``/pricing`` …) are not ``/blog`` so
# they are untouched too — only our own blog->blog edges are stripped.
_BLOG_LINK_RE = re.compile(r"\[([^\]]+)\]\(/blog/[^)]*\)")


def strip_internal_blog_links(body_markdown: str) -> str:
    """Unwrap every inline blog->blog Markdown link back to its plain anchor text.

    ``[best cTrader broker](/blog/x)`` -> ``best cTrader broker``. Only ``/blog/``
    targets are unwrapped; ``/trading-glossary/``, landing, and external links stay
    intact, and non-link prose is returned unchanged. The relink path calls this to
    return a published body to the same clean state a fresh bundle body is in, so the
    cluster-linking plan can be recomputed from scratch instead of stacking on top of
    stale edges.
    """
    return _BLOG_LINK_RE.sub(r"\1", body_markdown or "")


def _is_prose_line(line: str) -> bool:
    """True for a paragraph / list line safe to insert a Markdown link into.

    Conservative on purpose: a heading, table row, blockquote, or any line carrying a
    real HTML/markup tag is rejected. Pipeline bodies are HTML-heavy (raw
    ``<script>``/``<canvas>``/mermaid visuals), so a tag-bearing line is treated as
    non-prose and never touched — but a bare ``<``/``>`` comparison in prose (e.g. the
    brand's "latency < 10ms") is NOT a tag and stays eligible. Lines that already carry
    a Markdown link ARE eligible — the insertion only ever lands in the plain-text
    portion (see :func:`_insert_outside_links`).
    """
    stripped = line.strip()
    if not stripped:
        return False
    if stripped[0] in "#|>":  # heading, table row, blockquote
        return False
    if _HTML_TAG_RE.search(line):  # raw HTML / visual markup tag
        return False
    return True


def _insert_outside_links(line: str, pattern: re.Pattern, anchor: str, url: str) -> tuple[str, bool]:
    """Link the first ``pattern`` match that lies in plain text (not inside a link).

    Returns ``(new_line, replaced)``. Skips the line if it already holds the
    per-line link cap, so an existing glossary/landing link does not block a blog
    link, but a paragraph never accrues more than two links total.
    """
    spans = [(m.start(), m.end()) for m in _MD_LINK_RE.finditer(line)]
    if len(spans) >= _MAX_LINKS_PER_LINE:
        return line, False
    for m in pattern.finditer(line):
        if any(a <= m.start() < b for a, b in spans):
            continue  # the phrase is the anchor text of an existing link — don't nest
        return f"{line[:m.start()]}[{anchor}]({url}){line[m.end():]}", True
    return line, False


@dataclass
class LinkInsert:
    """Outcome of one planned internal link."""

    anchor: str
    target_url: str
    applied: bool
    reason: str = ""


@dataclass
class InternalLinksReport:
    """Outcome of applying a bundle's internal-link plan to its body."""

    applied: list[LinkInsert] = field(default_factory=list)
    skipped: list[LinkInsert] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return f"{len(self.applied)} inserted, {len(self.skipped)} skipped"


def _normalize(raw) -> tuple[str, str]:
    if not isinstance(raw, dict):
        return "", ""
    anchor = (raw.get("anchor") or "").strip()
    url = (raw.get("target_url") or raw.get("url") or "").strip()
    return anchor, url


def apply_internal_links(
    body_markdown: str,
    links,
    *,
    log: logging.Logger = logger,
    max_links: int = _MAX_LINKS_PER_ARTICLE,
) -> tuple[str, InternalLinksReport]:
    """Insert planned within-cluster links into ``body_markdown``.

    ``links`` is an iterable of dicts ``{"anchor", "target_url"}`` (``url`` accepted
    as an alias). Returns the new body and an :class:`InternalLinksReport`.
    Deterministic and idempotent — see the module docstring.
    """
    report = InternalLinksReport()
    body = body_markdown or ""
    if not links:
        return body, report

    # Dedupe by target, drop malformed, preserve plan order.
    queue: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in links:
        anchor, url = _normalize(raw)
        if not anchor or not url:
            report.skipped.append(LinkInsert(anchor, url, False, "missing anchor/url"))
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            report.skipped.append(LinkInsert(anchor, url, False, "duplicate target"))
            continue
        seen.add(key)
        queue.append((anchor, url))

    lines = body.split("\n")
    applied = 0
    for anchor, url in queue:
        if applied >= max_links:
            report.skipped.append(LinkInsert(anchor, url, False, "max links reached"))
            continue
        # Idempotency: if this target is already linked anywhere, leave it.
        if f"]({url})" in "\n".join(lines):
            report.skipped.append(LinkInsert(anchor, url, False, "target already linked"))
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(anchor) + r"(?!\w)")
        inserted = False
        in_fence = False
        for i, line in enumerate(lines):
            if _FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if in_fence or not _is_prose_line(line):
                continue
            new_line, replaced = _insert_outside_links(line, pattern, anchor, url)
            if replaced:
                lines[i] = new_line
                inserted = True
                applied += 1
                report.applied.append(LinkInsert(anchor, url, True))
                break
        if not inserted:
            report.skipped.append(LinkInsert(anchor, url, False, "anchor not found in prose"))

    for s in report.skipped:
        log.debug("internal_links: skipped %s -> %s (%s)", s.anchor or "(no anchor)", s.target_url or "(no url)", s.reason)
    log.info("internal_links: %s", report.summary)
    return "\n".join(lines), report
