"""Let a brief borrow from competitor visuals without being led by them.

The obvious way to use a harvested competitor page during briefing is to look at
what it drew and write the brief around that. It produces a brief that feels
well-researched and is, in fact, a reproduction of a competitor's outline with
better styling — a worse outcome than having no source at all, because it looks
like work.

So the order is fixed and the code enforces it rather than asking politely:

1. The brief writes its **own** visual needs from its **own** outline, before
   any competitor visual is looked at. Each need says what the reader should
   understand, not what a picture should contain.
2. :func:`visual_opportunities` is then handed those needs and the harvested
   gallery. It iterates over **needs**, never over the gallery. A competitor
   visual that matches no need is never surfaced, so it cannot suggest itself.
3. Whatever matched gets reproduced by the republish route in our own components
   or as our own drawn figure. Nothing of the source's ships.

The structural guarantee is that last detail: because the loop is over needs,
there is no code path by which "the competitor had a nice chart" becomes a
reason to add a visual. The worst this function can do is fail to find a match,
which costs nothing — the need is drawn from scratch instead.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

#: Words that appear in almost every trading-adjacent alt text and carry no
#: matching signal. Kept small on purpose: an over-eager stop list hides real
#: matches, and a missed match is cheap while a false one is not.
_STOP = {
    "the", "a", "an", "of", "in", "on", "for", "and", "or", "to", "with", "by",
    "is", "are", "how", "what", "why", "vs", "versus", "between", "from", "at",
    "image", "picture", "chart", "graph", "diagram", "infographic", "illustration",
    "trading", "trade", "trader", "market", "markets", "options", "option",
    # Every need begins with one of these, so they carry no matching signal.
    "show", "shows", "showing", "explain", "explains", "illustrate", "display",
    "compare", "comparison", "reader", "understand", "one",
}

_WORD = re.compile(r"[a-z0-9]+")

#: However well the ratio scores, one word in common is a coincidence.
_MIN_SHARED_TOKENS = 2

#: Which harvested image kinds can plausibly answer which kind of need. A need
#: for a price chart is not answered by a flat infographic, however well the
#: words line up.
_KIND_FIT = {
    "price_chart": {"chart", "screenshot", "photo"},
    "candles": {"chart", "screenshot", "photo"},
    "screenshot": {"screenshot", "photo", "chart"},
    "hub_spokes": {"infographic", "unknown"},
    "process_chain": {"infographic", "unknown"},
    "quadrant": {"infographic", "unknown"},
    "contrast_table": {"infographic", "unknown"},
    "table": {"infographic", "unknown", "screenshot"},
    "comparison": {"infographic", "unknown"},
}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower())
            if len(w) > 2 and w not in _STOP}


@dataclass
class Need:
    """One visual the brief decided it wants, written before looking at sources."""

    id: str
    comprehension_job: str          # what the reader should understand afterwards
    shape: str = ""                 # hub_spokes, table, price_chart, ... (optional)
    section: str = ""

    def tokens(self) -> set[str]:
        return _tokens(f"{self.comprehension_job} {self.section}")


@dataclass
class Opportunity:
    """A need, and whether anything harvested happens to answer it."""

    need: Need
    match: dict | None = None
    score: float = 0.0
    format: str = ""
    builder: str | None = None
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def reproduce(self) -> bool:
        return self.match is not None

    def as_dict(self) -> dict:
        return {
            "need_id": self.need.id,
            "comprehension_job": self.need.comprehension_job,
            "shape": self.need.shape,
            "section": self.need.section,
            "format": self.format,
            "builder": self.builder,
            "format_reason": self.reason,
            "source_visual": (self.match or {}).get("label"),
            "source_kind": (self.match or {}).get("kind"),
            "match_score": round(self.score, 3),
            "action": ("reproduce from the source visual, rebuilt as ours"
                       if self.reproduce else "draw from scratch — no source covers it"),
            "notes": self.notes,
        }


def needs_fingerprint(needs) -> str:
    """A hash of the needs exactly as written, before any source was consulted.

    Store it with the brief. If the needs are later edited to match what a
    competitor happened to have, the fingerprint no longer agrees, and the
    ordering rule this module exists to protect has visibly been broken.
    """
    payload = json.dumps(
        [{"id": n.id, "comprehension_job": n.comprehension_job, "shape": n.shape}
         for n in needs], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _score(need: Need, visual: dict) -> float:
    """How well a harvested visual answers a need. 0 means "not at all"."""
    want = need.tokens()
    if not want:
        return 0.0
    have = _tokens(f"{visual.get('alt', '')} {visual.get('caption', '')}")
    if not have:
        return 0.0
    if need.shape:
        allowed = _KIND_FIT.get(need.shape)
        if allowed and visual.get("kind") not in allowed:
            return 0.0
    shared = want & have
    # Two independent guards. Containment (over the SHORTER side) is the right
    # measure because a need is a sentence and an alt is a phrase, so dividing
    # by the need's length alone would reject every real match. The absolute
    # floor then stops a two-word alt scoring 1.0 off a single coincidence.
    if len(shared) < _MIN_SHARED_TOKENS:
        return 0.0
    return len(shared) / min(len(want), len(have))


def visual_opportunities(needs, gallery, *, threshold: float = 0.40,
                         decide_format=None) -> list[Opportunity]:
    """For each need the brief already declared, is there a source visual for it?

    Iterates over ``needs``. A gallery entry matching nothing is never returned,
    which is what makes it impossible for a competitor's visual to add a job the
    brief did not already want.

    ``threshold`` is the share of the need's meaningful words a visual must
    share before it counts. Set it high rather than low: a missed match costs a
    figure drawn from scratch, while a false match costs a visual that answers
    the wrong question.
    """
    if decide_format is None:
        from page_extract.policy import decide as decide_format

    gallery = list(gallery or [])
    used: set[str] = set()
    out: list[Opportunity] = []

    for need in needs:
        decision = decide_format(need.shape or "unknown")
        opp = Opportunity(need=need, format=decision.format,
                          builder=decision.builder, reason=decision.reason)

        best, best_score = None, 0.0
        for visual in gallery:
            label = visual.get("label") or visual.get("src") or ""
            if label in used:
                continue
            s = _score(need, visual)
            if s > best_score:
                best, best_score = visual, s

        if best is not None and best_score >= threshold:
            opp.match, opp.score = best, best_score
            used.add(best.get("label") or best.get("src") or "")
            if best.get("kind") in ("chart", "screenshot", "photo"):
                opp.notes.append(
                    "Chart-like source: recover its series with page-extract "
                    "chart rather than reading numbers off the picture.")
            opp.notes.append(
                "Reproduce the UNDERSTANDING, not the artwork — the source's "
                "layout, palette and watermark never ship.")
        else:
            opp.notes.append(
                "No source visual answers this need. Draw it from scratch; do "
                "not substitute a different competitor visual because it is there.")
        out.append(opp)

    return out


def report(opportunities) -> str:
    """A brief-ready summary. Only needs appear — never an unmatched source."""
    lines = ["## Visual plan", ""]
    reproduced = sum(1 for o in opportunities if o.reproduce)
    lines.append(f"{len(opportunities)} visual need(s); {reproduced} have something "
                 f"in the harvested sources worth reproducing, "
                 f"{len(opportunities) - reproduced} drawn from scratch.")
    lines.append("")
    for o in opportunities:
        d = o.as_dict()
        head = f"- **{d['need_id']}** — {d['comprehension_job']}"
        lines.append(head)
        lines.append(f"    format: {d['format']}"
                     + (f" ({d['builder']})" if d["builder"] else "")
                     + f" — {d['format_reason']}")
        if d["source_visual"]:
            lines.append(f"    source: `{d['source_visual']}` "
                         f"({d['source_kind']}, match {d['match_score']})")
        for n in d["notes"]:
            lines.append(f"    note: {n}")
    return "\n".join(lines)
