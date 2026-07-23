"""Normalized token matching for glossary terms.

Shared by the gap analyzer (``glossary_gap``) and the suggestion backlog
(``glossary_backlog``) so "is this term already covered / already queued" is
decided one way everywhere. Pure Python — no Django, no Anthropic — so either
caller can import it without dragging in the API client.
"""

from __future__ import annotations

import re
from typing import Any


def tokens(s: str) -> frozenset[str]:
    """Normalize a term to its lowercase alphanumeric token set (separator-insensitive)."""
    return frozenset(t for t in re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split() if t)


def existing_token_sets(terms: list[dict[str, Any]]) -> list[frozenset[str]]:
    """Token sets for every existing name / abbreviation / aka alias (deduped, non-empty)."""
    sets: set[frozenset[str]] = set()
    for t in terms:
        for label in (t.get("name"), t.get("abbreviation"), *(t.get("aka") or [])):
            toks = tokens(label or "")
            if toks:
                sets.add(toks)
    return list(sets)


def already_covered(term: str, existing_sets: list[frozenset[str]]) -> bool:
    """True if ``existing_sets`` already covers ``term``.

    A term is a duplicate when its tokens equal an existing term's, or when it
    merely qualifies one (an existing term's tokens are a subset of the term's —
    e.g. existing "Backtest" ⊆ "Backtest / Backtesting", or existing "Drawdown" ⊆
    "Maximum Drawdown"). Used both to drop LLM suggestions the glossary already
    defines and to dedupe a new suggestion against ones already in the backlog.
    """
    toks = tokens(term)
    if not toks:
        return True
    return any(e <= toks for e in existing_sets)
