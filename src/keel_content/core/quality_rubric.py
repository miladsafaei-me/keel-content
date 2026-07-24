"""Deterministic cluster-quality rubric over generation bundles.

The written spec of "a good cluster post", enforced deterministically so the
defects we keep re-discovering by hand can never ship silently again. Every rule
here was a real defect found in the first forex cluster. Pure ``core`` module
(no Django) so it is unit-testable and callable from both the standalone
``content_quality_gate`` command and the ``content_import`` ingest gate.

  HARD (FAIL — blocks import):
   R1 no dropped visual        every cp-component renders (no ``failed``)
   R2 no clamped label         no hero/label field was truncated to fit (``clamped``)
   R3 no empty hero pick       a commercial intent-hero has a non-empty pick name + reason
   R4 no fabricated rating     no invented numeric "9.4 / 10"-style review score anywhere
   R5 risk-warning linked      a signals/performance/leverage post links /risk-warning
   R6 same-market links        a forex/cross-market post never links a crypto/binary surface

  SOFT (WARN — reported, not blocked):
   R7 roundup sources          a best/vs/review post carries >=2 varied further-reading links
   R8 no cold-open formula     the post doesn't open with a stock template ("best-X lists
                               rank for humans" OR "you searched for X, but [the twist]")
   R9 low pairwise overlap     no two posts share too many H2s (cannibalization smell)
   R10 spoke up-links pillar   a non-pillar post carries >=1 outbound blog link
   R11 source-domain diversity <=2 Wikipedia sources (2nd needs another-domain
                               source alongside); >=2 sources never all on one domain
"""

from __future__ import annotations

import re

from ..config import market_link_rule, risk_warning_url
from .components_embed import apply_components
from .text_normalize import normalize_body_markdown

# A fabricated review score: "9.4 / 10", "8/10", "7.5 out of 10", "4.5 out of 5".
# We do not invent ratings (no-stats policy). The slash form is restricted to /10 and
# /100 so it does not mis-fire on "MetaTrader 4 / 5" (MT4/5) or "24/5" market hours;
# genuine star ratings use the spelled "out of 5" form.
_RATING_RE = re.compile(
    r"\b\d(?:\.\d)?\s*(?:/\s*(?:10|100)|out of\s*(?:5|10|100))\b", re.IGNORECASE
)

# The stock AI cold-open formulas the cluster kept collapsing onto. The second group
# ("you searched for X, but [the twist]") is the milder formula the FIRST regeneration
# fell into once the original one was retired — kept here so future clusters flag it too.
_FORMULA_RES = [
    re.compile(r"most\b[^.]{0,40}\bbest[- ]?\w*\b[^.]{0,40}\b(lists|guides|articles)\b", re.I),
    re.compile(r"\brank(?:ed)?\s+for\s+(?:humans|people|a human)\b", re.I),
    re.compile(r"\bbut\s+a\s+bot\s+is\s+(?:a\s+)?different\b", re.I),
    re.compile(r"\byou searched for\b[^.]{0,80}\bbut\b", re.I),
    re.compile(r"\bwhen a human\b[^.]{0,40}\b(picks|chooses|searches for)\b[^.]{0,20}\bbroker\b", re.I),
]

_RISK_TRIGGER_RE = re.compile(
    r"\b(signal|backtest|performance|returns?|win[- ]?rate|leverage|profit|drawdown)\b", re.I
)
_H2_RE = re.compile(r"^##\s+(.+?)(?:\s*\{#[\w-]+\})?\s*$", re.M)
_INTERNAL_LINK_RE = re.compile(r"\]\((/[^)\s]+)\)")


def check_bundle(b: dict) -> dict:
    """Run the per-post R1–R8 + R10/R11 checks on one bundle dict.

    Returns ``{"slug", "fails", "warns", "_h2"}`` — ``_h2`` feeds ``cross_checks``.
    """
    slug = b.get("slug") or b.get("content_id") or "(unknown)"
    fails: list[str] = []
    warns: list[str] = []
    if b.get("_load_error"):
        return {"slug": slug, "fails": [f"unreadable bundle: {b['_load_error']}"], "warns": [], "_h2": []}

    body = b.get("body_markdown") or ""
    facets = b.get("facets") or {}
    markets = [str(m).lower() for m in (facets.get("markets") or [])]
    role = str(facets.get("role") or "")
    title = str(b.get("title") or "")

    # Mirror content_import: typographic normalization runs before render, so gate
    # against the normalized body to catch any normalize-induced breakage too.
    rendered, rep = apply_components(normalize_body_markdown(body))

    # R1 / R2 — no dropped visual, no clamped label.
    for msg in rep.get("failed", []) or []:
        fails.append(f"R1 component dropped: {msg}")
    for msg in rep.get("clamped", []) or []:
        fails.append(f"R2 label truncated (write it shorter): {msg}")

    # R3 — commercial intent-hero must have a non-empty pick.
    if 'cp-ihero--commercial' in rendered:
        name = re.search(r'cp-ihero__name">([^<]*)', rendered)
        has_reason = 'cp-ihero__reasons">' in rendered and '<li>' in (
            rendered.split('cp-ihero__reasons">', 1)[-1].split('</ul>', 1)[0]
        )
        if not (name and name.group(1).strip()):
            fails.append("R3 commercial hero has an empty pick name")
        elif not has_reason:
            fails.append("R3 commercial hero pick has no reasons")

    # R4 — no fabricated numeric rating (check both source specs and rendered HTML).
    for hay, where in ((body, "body/spec"), (rendered, "rendered")):
        m = _RATING_RE.search(hay)
        if m:
            fails.append(f"R4 fabricated numeric rating '{m.group(0).strip()}' ({where})")
            break

    # R5 — risk-warning link on any risk-bearing post, when the host defines a
    # risk-warning URL (a non-trading host sets none, disabling this rule). The link
    # often comes from a risk_warning_callout component, so check the RENDERED output,
    # not just the raw body.
    risk_url = risk_warning_url()
    if risk_url and _RISK_TRIGGER_RE.search(body) and risk_url not in body and risk_url not in rendered:
        fails.append(f"R5 signals/performance content with no {risk_url} link")

    # R6 — same-market internal links only, when the host defines a market-integrity
    # rule (unset disables it — the package carries no market vocabulary of its own).
    # Fires on a post that is on the "same side" and does not itself cover an off-market,
    # if it links a surface matching the off-market URL pattern.
    rule = market_link_rule()
    if rule:
        same_side = {str(m).lower() for m in rule.get("same_side_markets", [])}
        off_markets = {str(m).lower() for m in rule.get("off_market_markets", [])}
        off_re = rule.get("off_market_url_re")
        on_same_side = (not markets) or any(m in same_side for m in markets)
        covers_off = any(m in off_markets for m in markets)
        if off_re and on_same_side and not covers_off:
            off_market_re = re.compile(off_re)
            for link in _INTERNAL_LINK_RE.findall(body):
                if off_market_re.search(link):
                    fails.append(f"R6 off-market internal link on a same-market post: {link}")
                    break

    # R7 — roundup sources (soft).
    is_roundup = role == "pillar" or bool(
        re.search(r"\b(best|top|vs\.?|versus|review|compare)\b", title, re.I)
    )
    if is_roundup:
        srcs = b.get("external_sources") or []
        domains = {re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", s.get("url", "")) for s in srcs}
        if len(srcs) < 2 or len(domains) < 2:
            warns.append(
                f"R7 roundup has thin further-reading ({len(srcs)} link(s), "
                f"{len(domains)} domain(s)) — aim for >=2 varied authoritative sources"
            )

    # R8 — no stock cold-open formula (soft).
    opening = body[:1200]
    if any(rx.search(opening) for rx in _FORMULA_RES):
        warns.append("R8 opens with a stock cold-open formula (e.g. 'best-X lists rank for humans' / 'you searched for X, but…')")

    # R11 — source-domain diversity on EVERY post (soft). Wikipedia was carrying
    # ~70% of all outbound links; the import gate hard-caps it at 1 per article,
    # and this warns at generation time so the author fixes it before import drops
    # a link silently. Also flag a multi-source list that leans on a single host.
    srcs_all = b.get("external_sources") or []
    src_domains = [
        re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", s.get("url", "")) for s in srcs_all
    ]
    wiki_n = sum(1 for d in src_domains if d.endswith("wikipedia.org"))
    if wiki_n > 2:
        warns.append(
            f"R11 {wiki_n} Wikipedia sources — import keeps at most 2 (and a 2nd only "
            "alongside another domain); replace extras with varied authoritative domains"
        )
    if len(srcs_all) >= 2 and len(set(src_domains)) == 1:
        warns.append(
            f"R11 all {len(srcs_all)} sources on one domain ({src_domains[0]}) — vary source domains"
        )

    # R10 — a spoke should carry at least one outbound blog link (up to the pillar).
    # The cluster-linking pass occasionally leaves a single-post regen with none.
    if role and role != "pillar" and not (b.get("internal_links") or []):
        warns.append("R10 no outbound blog link (a spoke should up-link the pillar) — re-run cluster-linking")

    return {"slug": slug, "fails": fails, "warns": warns, "_h2": _H2_RE.findall(body)}


def cross_checks(bundles: list[dict], results: list[dict]) -> None:
    """R9 — flag any pair of posts that share too many H2 headings (in-place)."""
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()  # noqa: E731
    h2sets = []
    for r in results:
        h2sets.append({norm(h) for h in r.get("_h2", []) if norm(h) not in ("faq", "sources  further reading", "")})
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            a, b = h2sets[i], h2sets[j]
            if not a or not b:
                continue
            shared = a & b
            jacc = len(shared) / len(a | b)
            if len(shared) >= 3 or jacc >= 0.5:
                msg = (
                    f"R9 shares {len(shared)} H2(s) with '{results[j]['slug']}' "
                    f"(jaccard {jacc:.0%}) — cannibalization smell: {sorted(shared)[:4]}"
                )
                results[i]["warns"].append(msg)
                results[j]["warns"].append(
                    f"R9 shares {len(shared)} H2(s) with '{results[i]['slug']}'"
                )
