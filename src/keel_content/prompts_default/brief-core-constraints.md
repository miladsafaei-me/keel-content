# Core constraints — hard rules for any stage that touches the article body

> Generic keel-content default. A host overrides this in `content-pipeline/prompts/` with
> its project-specific compliance, product surfaces, partner rules, and voice.

These bind **every** stage that writes or rewrites the body (author, intent-revise,
editorial-revise). Three kinds: **(A) compliance/safety** — never violate; **(B)
machine-enforced** — the deterministic import gates block these, so follow them but don't
anxiously self-police; **(C) judgment** — only you get these right. Spend attention on (A)
and (C).

## A — Compliance & safety (never violate)

- **Correct language** everywhere in the output (the host declares the target language).
- **Risk / disclosure link:** if the article touches signals / backtests / performance /
  returns, include at least one link to the project's risk-disclosure page (set
  `generation_report.risk_warning_linked`). *(Host: name the exact path.)*
- **No hype in our own voice:** never "guaranteed profit", "risk-free", or "can't lose" —
  use measured framing ("reward-to-risk ratio", "historical win rate", "backtested result").
  Only exception: *quoting to debunk* a scam's claim.
- **No third-party statistics or facts (no-stats policy):** no percentages, sourced numbers,
  market-share/volume figures, dated stats, or attributed third-party quotes — teach through
  original explanation, not borrowed data. **Illustrative hypotheticals are encouraged** when
  clearly framed. No fabricated ratings anywhere — never invent a numeric review score.
- **Trade-semantic colours** (domain law wherever a spec lets you choose): BUY/LONG/UP
  green, SELL/SHORT/DOWN red. Never repurpose for a generic category.

## C — Judgment rules

- **Internal linking — indexable-only.** Link **only** to URLs in the `INDEXABLE_URLS`
  allowlist handed to you (the live indexable pages on the site). Never link a URL not in it.
  **Never link another blog post yourself** — leave `internal_links` unset; the
  cluster-linking pass fills it. **No trailing slash** on any internal link. **≤2** links per
  paragraph, **one link per distinct target** (first/best mention, dedupe), intent-matched
  anchor text. No fixed link count.
- **Never write an outbound partner/affiliate URL** — *naming* a partner in prose is fine
  where the host's rules allow; the platform auto-links partner NAMES at render time. **Never
  dump a bare enumeration of partner names** in one sentence/list (they render as adjacent
  sponsored links — spam). Name each where it genuinely earns a mention.
- **Market / scope integrity (prime directive) — prose AND internal links.** Keep the
  article inside its market/scope: name only same-market entities, and link only
  **same-market** project surfaces — never a different-market surface. *(Host: define your
  markets + surfaces.)*
- **Scope fences — one intent, one post (do NOT broaden).** Treat these spec fields as a hard
  contract:
  - `scope_includes` — the slice that is YOURS: cover it fully, stay inside it.
  - `scope_excludes` — adjacent sub-topics a SIBLING owns: do **not** build a section on
    these; one sentence of context is the ceiling (the cluster-link pass adds the link).
  - `canonical_owner` — for a shared asset reconciled to one owner: if a sibling owns an
    EXPLANATION, do not re-teach it (one sentence + let the link pass point there); if it is
    an interactive TOOL the reader needs in-context, embed the one shared component inline
    (one canonical implementation, not one location) rather than sending the reader away.
  - Empty fields → fall back: stay on your own intent, don't drift into a neighbour's.
- **Product-activation phrasing — one canonical wording.** When the article reaches the point
  of activating one of the project's products, use the host's exact canonical phrase (the
  platform auto-links it at render time). Never invent a pricing/checkout URL. *(Host:
  declare the phrase.)*

## B — Machine-enforced mechanics (follow, don't self-police)

The deterministic import gates catch these — write to them once, don't write defensively:

- `key_takeaways_markdown` = **2–4** bullets.
- Lengths: `title`/`meta_title` **≤65**, `meta_description` **≤160**, `excerpt` **≤200** chars.
- **No inline `style=` and no `on*=` handlers** anywhere; no hand-written visual HTML/CSS/JS.
- Internal links: allowlist-only, no trailing slash, one per target, no cross-post links.
- **cp-component field discipline:** every field value is a **short, complete phrase** (put
  the explanation in surrounding prose). Each field has a strict `maxLength` in the
  component's `manifest.json`; the publisher truncates an over-long value and **flags the
  truncation as a defect** (rubric R2). Use the exact schema field **names** and the exact
  `component_id` in **underscored** form (never the hyphenated folder name).
- **At least one `figure_requests` entry is required** — a bundle with none is import-blocked.
