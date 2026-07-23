"""Deterministic pre-ingest lint for generation bundles.

Runs at ``content_import`` time, before a bundle is published, to catch the
violations the author/gate prompts are supposed to prevent but occasionally let
slip. Pure stdlib + no Django so it is unit-testable and importable anywhere.

A bundle with any HARD violation is skipped by ``content_import`` (reported, not
published) unless ``--no-lint`` is passed — the fix belongs in the generator, not
in a hand-edit of a shipped draft. ``lint_bundle`` returns the hard-violation
strings (empty = clean); ``lint_bundle_warnings`` returns non-blocking warnings.

Hard violations (block import):
  - structural: required keys present + optional containers well-shaped
    (delegated to ``bundle_schema.validate_bundle_structure``)
  - title / h1 / meta_title ≤ 65 chars, meta_description ≤ 160 chars (project SEO rule)
  - 2–4 key-takeaway bullets
  - no inline ``style=`` / ``on*=`` handlers in the body (cp-* classes only)
  - a ``cp-component`` visual spec hardcodes a raw hex colour other than the two
    trade-semantic colours (the component templates theme via tokens — an author
    must emit DATA, never colours; a stray hex bypasses brand theming + buy/sell
    semantics and risks dark/light contrast)

Warnings (reported, never block — under the no-stats editorial policy external
sources are optional "further reading", not fact-citations, so domain diversity
is advisory rather than a gate):
  - body pairs a number / percentage with a third-party attribution (possible stat)
  - if sources ARE supplied, they lean on a single registrable domain
  - a compliance "banned phrase" appears (flagged for a human; legitimate when
    quoting-to-debunk, so warn rather than block)
  - an in-body link to ``/risk-warning`` carries an anchor that does not describe a
    risk warning (anchor-honesty: the reader expects the page the anchor promises)
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .bundle_schema import validate_bundle_structure

TITLE_MAX = 65
META_TITLE_MAX = 65
META_DESCRIPTION_MAX = 160
MIN_TAKEAWAYS = 2
MAX_TAKEAWAYS = 4
SINGLE_DOMAIN_WARN_AT = 2  # warn once this many sources collapse to < 2 domains

_INLINE_HANDLER_RE = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
# Attribute-aware: matches a real ``style=`` attribute, not the word "lifestyle=".
_INLINE_STYLE_RE = re.compile(r"(?<![\w-])style\s*=")
# No-stats policy: flag a line that pairs a number/percentage with a third-party
# attribution — the fabricated-statistic pattern. Warn-only, because illustrative
# hypotheticals legitimately use numbers and must never be blocked.
_ATTRIBUTION_RE = re.compile(
    r"\b(according to|study (found|by|of|shows)|survey (found|by|of)|"
    r"report (found|by|shows)|statistics show|data (from|by)|research (shows|by|from)|"
    r"BIS|IMF|OECD|World Bank|BLS)\b",
    re.IGNORECASE,
)
_NUMBERISH_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d{2,}\b")

# Visual-correctness gate: a cp-component spec must carry DATA, not colours. The two
# trade-semantic colours are domain law and allowed; any other raw hex is a bypass of
# token theming. ``cpTheme.palette()`` lives in the component templates, not the spec.
_CP_BLOCK_RE = re.compile(r"```cp-component\b(.*?)```", re.DOTALL | re.IGNORECASE)
_HEX_RE = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_ALLOWED_HEX = {"3bb273", "df2c53"}  # BUY / SELL — see CLAUDE.md Trade-Semantic Colors


def _hex6(token: str) -> str:
    """Normalize a 3/6/8-digit hex body to its comparable 6-digit lowercase form."""
    t = token.lower()
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    return t[:6]


# Compliance banned phrases. Warn-only: naming a red-flag phrase to debunk it is
# explicitly allowed (BLOG.md / agent brief), so a human verifies the context.
_BANNED_PHRASE_RE = re.compile(
    r"\b(guaranteed\s+(?:profits?|returns?|wins?|income)|risk[-\s]?free|"
    r"can'?t\s+lose|can\s?not\s+lose|cannot\s+lose|100%\s+win|never\s+loses?|"
    r"no[-\s]risk|sure\s+(?:thing|profit|win))\b",
    re.IGNORECASE,
)
_DEBUNK_MARKER_RE = re.compile(
    r"\b(avoid|bewar|wary|myth|scam|fraud|red[-\s]?flag|promis|claim|"
    r"don'?t\s+fall|never\s+trust|too\s+good\s+to\s+be\s+true|warning\s+sign|"
    r"debunk|illusion|false|no\s+such\s+thing|hype|trap)\b",
    re.IGNORECASE,
)
# In-body link to /risk-warning whose anchor must honestly describe a risk warning.
_RISK_LINK_RE = re.compile(r"\[([^\]]+)\]\((/risk-warning[^)]*)\)")
_RISK_ANCHOR_OK_RE = re.compile(r"\b(risk|warning|disclaim|caution|lose|loss)\b", re.IGNORECASE)


def _registrable_domain(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower().lstrip(".")
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


_TOP_BULLET_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")


def _count_takeaways(md: str) -> int:
    # Count only TOP-LEVEL list items. A nested sub-bullet (indented >=2 spaces) is
    # part of its parent takeaway, not a fourth one, and must not inflate the count
    # past the gate. Accept any common Markdown marker (-, *, + or an ordered "1."/
    # "1)") and tolerate a single leading space so a slightly-indented but non-nested
    # block of clean takeaways is not mis-counted as 0 and hard-blocked.
    count = 0
    for ln in (md or "").splitlines():
        indent = len(ln) - len(ln.lstrip(" "))
        if indent <= 1 and _TOP_BULLET_RE.match(ln.lstrip(" ")):
            count += 1
    return count


def lint_bundle(bundle: dict) -> list[str]:
    """Return a list of HARD lint violations for one bundle (empty = clean)."""
    violations: list[str] = list(validate_bundle_structure(bundle))

    for field in ("title", "h1"):
        val = bundle.get(field) or ""
        if len(val) > TITLE_MAX:
            violations.append(f"{field} {len(val)} chars > {TITLE_MAX}")

    mt = bundle.get("meta_title") or ""
    if len(mt) > META_TITLE_MAX:
        violations.append(f"meta_title {len(mt)} chars > {META_TITLE_MAX}")

    md = bundle.get("meta_description") or ""
    if len(md) > META_DESCRIPTION_MAX:
        violations.append(f"meta_description {len(md)} chars > {META_DESCRIPTION_MAX}")

    kt = _count_takeaways(bundle.get("key_takeaways_markdown") or "")
    if not (MIN_TAKEAWAYS <= kt <= MAX_TAKEAWAYS):
        violations.append(
            f"key_takeaways has {kt} bullets (must be {MIN_TAKEAWAYS}-{MAX_TAKEAWAYS})"
        )

    body = bundle.get("body_markdown") or ""
    if _INLINE_STYLE_RE.search(body):
        violations.append("body contains inline style= (use cp-* classes)")
    if _INLINE_HANDLER_RE.search(body):
        violations.append("body contains inline on*= handler (use external JS)")

    for block in _CP_BLOCK_RE.findall(body):
        bad = sorted(
            {f"#{m.group(1).lower()}" for m in _HEX_RE.finditer(block)
             if _hex6(m.group(1)) not in _ALLOWED_HEX}
        )
        if bad:
            violations.append(
                "cp-component spec hardcodes non-trade hex "
                f"{bad} (emit data; the template themes via tokens)"
            )

    return violations


def lint_bundle_warnings(bundle: dict) -> list[str]:
    """Return non-blocking warnings for one bundle (empty = none).

    These never block import — they surface editorial smells a human reviewer
    should glance at: a likely third-party statistic (the no-stats policy bans
    those) and a single-domain source list when sources are supplied at all.
    """
    warnings: list[str] = []

    sources = bundle.get("external_sources") or []
    domains = {d for d in (_registrable_domain(s.get("url", "")) for s in sources) if d}
    if len(sources) >= SINGLE_DOMAIN_WARN_AT and len(domains) < 2:
        warnings.append(
            f"external_sources lean on a single domain {sorted(domains)} — vary the sources"
        )

    body = bundle.get("body_markdown") or ""
    for ln in body.splitlines():
        if _ATTRIBUTION_RE.search(ln) and _NUMBERISH_RE.search(ln):
            warnings.append(
                f"possible third-party statistic (no-stats policy): {ln.strip()[:90]}"
            )
        m = _BANNED_PHRASE_RE.search(ln)
        if m:
            context = (
                "debunking context — verify it reads as a warning"
                if _DEBUNK_MARKER_RE.search(ln)
                else "appears in our own voice — likely a compliance violation"
            )
            warnings.append(f"banned phrase {m.group(0)!r} ({context}): {ln.strip()[:90]}")

    for anchor, target in _RISK_LINK_RE.findall(body):
        if not _RISK_ANCHOR_OK_RE.search(anchor):
            warnings.append(
                f"anchor-honesty: {anchor.strip()[:60]!r} -> {target} reads as a "
                "risk-warning link but the anchor promises something else"
            )

    gate = bundle.get("intent_gate")
    if isinstance(gate, dict) and gate.get("satisfied") is False:
        missing = gate.get("missing_essential") or []
        scope = gate.get("scope_violations") or []
        warnings.append(
            "intent gate UNSATISFIED — "
            f"missing essentials: {missing or '—'}; scope violations: {scope or '—'} "
            f"({gate.get('notes', '')})".strip()
        )

    return warnings
