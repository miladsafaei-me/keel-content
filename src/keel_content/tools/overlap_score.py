#!/usr/bin/env python3
"""Deterministic Layer-4 overlap scorer for a just-generated blog bundle batch.

Replaces the Opus overlap-audit agent (TOKEN-OPTIMIZATION-PLAN.md §1) for the bulk
of the work: near-duplicate detection between article bodies is almost entirely
computable, so it is scored here with zero LLM tokens. Only pairs that land in a
"gray band" straddling the 75 block line are handed to a single Sonnet agent
downstream for a confirm/override read.

Usage:
    python3 overlap_score.py <bundle_dir> [slug ...]

Reads every ``*.bundle.json`` in ``bundle_dir`` (keyed by the ``slug`` field inside
each — bundles are ``<content_id>.bundle.json`` on disk, but pairs are reported by
slug, exactly like the LLM audit it replaces). If explicit slugs are passed, only
those are compared; otherwise every bundle in the dir is compared pairwise.

Writes ``<bundle_dir>/overlap-audit.json`` in the SCHEMA ``content_import`` consumes:

    {"pairs":[{"a","b","score","block","signals","reason"}], "flagged":[<score>=60>]}

sorted by score descending. ``block: true`` is set for every pair scoring >= 75
(the same threshold ``content_import`` hard-blocks at). Prints a one-line SUMMARY
JSON on stdout so the runner agent can report pair / block / gray-band counts.
"""
from __future__ import annotations

import json
import re
import sys
from itertools import combinations
from pathlib import Path

# Block line shared with content_import (_OVERLAP_BLOCK_AT). A pair >= this hard-
# blocks BOTH its articles at import.
BLOCK_AT = 75
# Gray band straddling the block line: a Sonnet agent re-reads only these pairs to
# confirm/override `block`. Pairs outside it are trusted deterministically.
GRAY_LO, GRAY_HI = 65, 84

# Signal weights (sum = 1.0). Structural section overlap (shared H2s) is the
# strongest near-duplicate signal; the intro formula is next; repeated distinctive
# stats and re-implemented widgets round it out. Tunable — the gray-band Sonnet pass
# is the calibration safety net around the block line.
W_SHARED_H2 = 0.55
W_INTRO = 0.25
W_STATS = 0.10
W_WIDGET = 0.10

_H2_RE = re.compile(r"^##\s+(.+?)\s*#*\s*$", re.MULTILINE)
_H2_ONLY = re.compile(r"^##(?!#)")  # a line that is H2, not H3+
_COMPONENT_FENCE_RE = re.compile(r"```cp-component[^\n]*\n(.*?)\n```", re.DOTALL)
_WORD_RE = re.compile(r"[a-z0-9]+")
# Distinctive numeric tokens: percentages, decimals, multi-digit integers,
# money/pip figures. Single digits (0-9) are too common to be a duplicate signal.
_NUM_RE = re.compile(r"\d+(?:\.\d+)?%|\$\d[\d,]*(?:\.\d+)?|\b\d{2,}(?:\.\d+)?\b")

_STOP = {
    "the", "and", "for", "with", "that", "this", "your", "you", "are", "how",
    "what", "why", "from", "have", "has", "can", "will", "into", "onto", "over",
    "a", "an", "of", "to", "in", "on", "is", "it", "as", "at", "or", "by", "be",
}


def _norm_heading(h: str) -> str:
    toks = [t for t in _WORD_RE.findall(h.lower()) if t not in _STOP]
    return " ".join(toks)


def _h2_set(body: str) -> set[str]:
    out = set()
    for m in _H2_RE.finditer(body):
        line = body[m.start():m.start() + 3]
        if not _H2_ONLY.match(line):
            continue
        norm = _norm_heading(m.group(1))
        if norm:
            out.add(norm)
    return out


def _shingles(text: str, n: int = 3) -> set[str]:
    toks = _WORD_RE.findall(text.lower())
    if len(toks) < n:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def _component_ids(body: str) -> list[str]:
    ids: list[str] = []
    for m in _COMPONENT_FENCE_RE.finditer(body):
        try:
            item = json.loads(m.group(1))
        except Exception:
            continue
        cid = item.get("component_id") if isinstance(item, dict) else None
        if cid:
            ids.append(str(cid))
    return ids


def _stat_set(body: str) -> set[str]:
    return {s.replace(",", "") for s in _NUM_RE.findall(body)}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _widget_overlap(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    # Proportion of the smaller widget set that is duplicated in the other article.
    return len(sa & sb) / min(len(sa), len(sb))


class Doc:
    __slots__ = ("slug", "h2", "shingles", "components", "stats")

    def __init__(self, slug: str, body: str):
        self.slug = slug
        self.h2 = _h2_set(body)
        self.shingles = _shingles(body[:600], 3)
        self.components = _component_ids(body)
        self.stats = _stat_set(body)


def score_pair(x: Doc, y: Doc) -> tuple[int, list[str]]:
    s_h2 = _jaccard(x.h2, y.h2)
    s_intro = _jaccard(x.shingles, y.shingles)
    s_stats = _jaccard(x.stats, y.stats)
    s_widget = _widget_overlap(x.components, y.components)
    raw = (W_SHARED_H2 * s_h2 + W_INTRO * s_intro
           + W_STATS * s_stats + W_WIDGET * s_widget)
    score = int(round(100 * raw))
    signals: list[str] = []
    if s_h2 >= 0.34:
        signals.append("shared_h2")
    if s_intro >= 0.34:
        signals.append("intro_similarity")
    if s_stats >= 0.34:
        signals.append("repeated_stats")
    if s_widget >= 0.5:
        signals.append("duplicate_widget")
    return score, signals


def _reason(x: Doc, y: Doc, signals: list[str]) -> str:
    if not signals:
        return "low structural overlap"
    shared_h2 = sorted(x.h2 & y.h2)
    bits = []
    if "shared_h2" in signals:
        bits.append(f"{len(shared_h2)} shared section(s)"
                    + (f' (e.g. "{shared_h2[0]}")' if shared_h2 else ""))
    if "intro_similarity" in signals:
        bits.append("near-identical intro formula")
    if "repeated_stats" in signals:
        bits.append("repeated distinctive stats")
    if "duplicate_widget" in signals:
        bits.append("re-implemented widget(s)")
    return "; ".join(bits)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: overlap_score.py <bundle_dir> [slug ...]", file=sys.stderr)
        return 2
    bundle_dir = Path(argv[0])
    want = set(argv[1:])
    if not bundle_dir.is_dir():
        print(f"not a directory: {bundle_dir}", file=sys.stderr)
        return 2

    docs: list[Doc] = []
    for p in sorted(bundle_dir.glob("*.bundle.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = data.get("slug")
        body = data.get("body_markdown") or data.get("final_markdown") or ""
        if not slug or not body.strip():
            continue
        if want and slug not in want:
            continue
        docs.append(Doc(slug, body))

    pairs = []
    for x, y in combinations(docs, 2):
        score, signals = score_pair(x, y)
        a, b = sorted((x.slug, y.slug))
        # Keep signal/reason oriented consistently with the sorted (a, b).
        xa, yb = (x, y) if x.slug == a else (y, x)
        pairs.append({
            "a": a,
            "b": b,
            "score": score,
            "block": score >= BLOCK_AT,
            "signals": signals,
            "reason": _reason(xa, yb, signals),
        })

    pairs.sort(key=lambda p: p["score"], reverse=True)
    flagged = [p for p in pairs if p["score"] >= 60]
    out = {"pairs": pairs, "flagged": flagged}
    (bundle_dir / "overlap-audit.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    gray = [p for p in pairs if GRAY_LO <= p["score"] <= GRAY_HI]
    summary = {
        "written": True,
        "bundles": len(docs),
        "pairs": len(pairs),
        "blocked": sum(1 for p in pairs if p["block"]),
        "flagged": len(flagged),
        "gray_band": len(gray),
        "top_score": pairs[0]["score"] if pairs else 0,
    }
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
