"""Deterministic typographic normalization for generation bundles.

Runs at ``content_import`` time, before lint + publish, to strip the typographic
"tells" that vary uncontrollably between LLM runs (curly quotes, the ellipsis
glyph, non-breaking / zero-width spaces, exotic dash code points). Normalizing
these is a cluster-consistency lever, not a style preference: a blind per-article
author cannot keep these uniform across a cluster, so we do it here, once, with
plain rules instead of asking the model.

Pure stdlib + no Django so it is unit-testable and importable anywhere. It only
touches code points, never wording: it does NOT rewrite prose, collapse em-dash
usage, or alter sentence shape — those are the author's.

**Fenced blocks are never normalized.** Folding a curly quote to a straight ASCII
quote is right in prose but catastrophic inside a fenced ``cp-component`` block: a
curly quote an author wrote *inside* a JSON string value is valid data, but folding
it to ``"`` turns it into a structural quote that closes the string early and makes
the whole block invalid JSON — so the visual is silently dropped at render. The body
normalizer therefore protects every fenced block (```` ``` ````…```` ``` ````) and
folds only the prose around them. (Code / mermaid fences are data too, so the same
protection is correct for them.)
"""

from __future__ import annotations

import re

# Code-point → replacement. Each entry kills a typographic tell while preserving
# meaning. En-dash (–) and em-dash (—) are intentionally LEFT ALONE — they are
# legitimate typography; only the rare/aliased dash code points are folded onto em.
_CHAR_MAP = {
    # Curly / typographic double quotes -> straight ASCII
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "«": '"', "»": '"',
    # Curly / typographic single quotes + prime -> straight ASCII apostrophe
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "′": "'",
    # Ellipsis glyph -> three dots
    "…": "...",
    # Non-breaking / narrow / thin / figure spaces -> regular space
    " ": " ", " ": " ", " ": " ", " ": " ",
    # Zero-width + BOM -> removed
    "​": "", "‌": "", "‍": "", "﻿": "",
    # Aliased dashes -> em-dash; true minus -> hyphen-minus
    "‒": "—", "―": "—", "−": "-",
}

_TRANSLATION = {ord(k): v for k, v in _CHAR_MAP.items()}

# Bundle string fields that carry reader-facing prose and should be normalized.
_TEXT_FIELDS = (
    "title", "h1", "meta_title", "meta_description", "excerpt",
    "key_takeaways_markdown", "body_markdown",
)


def normalize_text(value: str) -> str:
    """Return ``value`` with typographic tells folded to canonical ASCII forms."""
    if not value:
        return value
    return value.translate(_TRANSLATION)


# A fenced block of any kind — cp-component (JSON), code, mermaid. Non-greedy so each
# opening fence pairs with its own closing fence.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def normalize_body_markdown(value: str) -> str:
    """Normalize the PROSE of a markdown body but never the inside of a fenced block.

    Folding a curly quote to ``"`` inside a ``cp-component`` JSON block would break
    the JSON and drop the visual (see module docstring), so fenced blocks are copied
    through verbatim and only the prose between them is folded.
    """
    if not value:
        return value
    out: list[str] = []
    last = 0
    for m in _FENCE_RE.finditer(value):
        out.append(normalize_text(value[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(normalize_text(value[last:]))
    return "".join(out)


def normalize_bundle(bundle: dict) -> dict:
    """Normalize a bundle's prose fields in place and return it.

    Touches the top-level text fields plus each external source ``anchor`` (the
    only other reader-facing string). Idempotent.
    """
    for field in _TEXT_FIELDS:
        val = bundle.get(field)
        if isinstance(val, str):
            # body_markdown carries fenced cp-component/code blocks whose contents must
            # not be touched; every other field is pure prose.
            bundle[field] = (
                normalize_body_markdown(val) if field == "body_markdown" else normalize_text(val)
            )
    for src in bundle.get("external_sources") or []:
        if isinstance(src, dict) and isinstance(src.get("anchor"), str):
            src["anchor"] = normalize_text(src["anchor"])
    return bundle
