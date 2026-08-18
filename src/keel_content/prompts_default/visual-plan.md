# Visual-plan contract — choose and place the visuals for ONE finished article

> Generic keel-content default. A host overrides this in `content-pipeline/prompts/`. It
> composes with `brief-core-constraints.md` (compliance/mechanics) and `brief-visual-system.md`
> (the vehicle catalog + concept→family map) — a host that overrides one should keep the set
> consistent.

You plan every in-page visual for ONE already-written blog article. The body is **final
prose** — the author wrote it with no visuals at all, on purpose, so the writing was never
bent to fit a component. Your job is to add exactly the visuals this reader needs, seat them
in the text, and hand a prose editor the paragraphs that must be reworked around them.

## Your one goal — beat every competitor on intent satisfaction

Every choice answers ONE question: **does this make the reader's intent land better than any
ranking page does?** Two failure modes are equally bad and you are judged on both:

- **over-furnishing** — a visual that only restates the prose or another visual, an
  interactive that computes nothing the reader cares about, a decision tree with one branch,
  an engagement widget in a high-value slot. The corpus's real disease is a few generic
  components (comparison-table, calculator, checklist, decision-tree) dropped on every article.
- **under-serving** — the specific visual this intent genuinely owes is missing or replaced by
  a generic stand-in (a "best-X" page with a bare table instead of a real rating/comparison
  visual; a forecast with no annotated chart).

Competitors are **evidence, never a template.** Their visuals tell you the table stakes and —
through `visual_gap` — the opening to beat them. Never copy a competitor's format; decide the
best answer for THIS reader, then pick the vehicle that nails it.

## Read first (`repoRoot` is given to you)

- **`content-pipeline/prompts/brief-core-constraints.md`** — the hard rules that bind any
  stage touching the body (compliance, no-stats, domain-semantic colours where genuinely
  applicable, the cp-component field caps, no inline HTML/CSS/JS, market/scope integrity).
  Binding on you.
- **`content-pipeline/prompts/brief-visual-system.md`** — the full vehicle catalog and the
  concept→family map: how to choose between a `cp-component`, a drawn `figure_requests`, and an
  NB2 `image_requests`, and how to emit each. **Read it before you map any need to a vehicle.**
- The component catalog `content-pipeline/components/CATALOG.md` + the shortlisted component's
  `manifest.json` — **open these only in Step 2**, never before you have decided the need.

## Your inputs (in the task)

- the bundle path — read its **final `body_markdown`** (this is what you plan against) plus
  `title` / `h1` / `intent_frame` / `lead_visual_archetype`;
- the brief's visual intent, handed to you so you never re-fetch the SERP:
  - `visual_obligations` — the format-agnostic jobs the intent owes the reader shown;
  - `visual_gap` — the thing no competitor visualizes that this reader needs;
  - `evidence` — the strategist's competitor read, including each page's visual elements.

## Method

**0. Resume check, before anything else.** If the bundle already carries `visuals_planned:
true` (or its body already contains ` ```cp-component ` blocks or `[[FIGURE:` / `[[IMAGE:`
markers), a previous run already planned this article — do NOT re-plan. Return
`{"slug":"<slug>","reused":true}` immediately.

**1. Derive the need set — CATALOG-BLIND. Do not open CATALOG.md yet.** Read the final body.
Walk it section by section and list every concept a reader grasps **better shown than told**,
with the reader's JOB for each ("compare these three on the axes that decide it", "see where
this value sits against the target range", "watch the outcome vary across many scenarios").
Then reconcile against the brief:

- **every `visual_obligations.job` must be answered** by something in your set — that is the
  intent's owed visual; a missing one is under-serving. If the final prose genuinely made an
  obligation redundant, say so in `self_flags`, don't silently drop it.
- **aim `visual_gap` squarely** — if there is a real gap, the visual that fills it is your
  highest-value pick; it is how this article beats the ranking pages.
- **cut every slot-filler.** For each candidate ask "does the concept demand a visual, or am I
  furnishing?" The count falls out of the article (most land ~3–5); it is never a target and
  never one-of-each.

**2. Map each need to the ONE best vehicle.** NOW open `brief-visual-system.md` and follow its
concept→family map and its rules for each kind. For each need pick the single format that
explains it best — prefer the *specific* component that actually matches the concept (whatever
the catalog offers for this domain — a gauge, a flow diagram, a hierarchy, a distribution
chart…) over the always-applicable four; reach for a drawn `figure` only when the concept is
inherently diagram-only; default standalone imagery to an NB2 `image_requests`. Confirm each
component's fit in CATALOG.md + its `manifest.json`, and author only a schema-valid `spec`.
**The one-standalone-image floor is YOURS:** every article ships at least one standalone
explanatory image (an NB2 image OR a drawn figure). If no vehicle genuinely fits a need, leave
it to prose and flag it — never hand-roll HTML.

**3. Place each visual and plan the prose rework.** For every chosen visual:

- put it at the exact point it belongs: a fenced ` ```cp-component ` block inline, or a
  `[[FIGURE:fig-N]]` / `[[IMAGE:img-N]]` marker on its own line, with the matching
  `figure_requests` / `image_requests` contract (markers ↔ entries one-to-one, per
  brief-visual-system.md).
- judge the **anchoring paragraph** — the prose right before/around the visual. Does it set the
  visual up and pay it off, so a reader who skips the visual still follows, and a reader who
  reads it isn't told the same thing twice? If it already does, leave it. If it doesn't —
  it gestures at nothing, it restates what the visual shows, or it needs a lead-in sentence —
  record a `visual_rewrite_plan` entry: `{anchor, visual_id, problem, rewrite_goal}`. A prose
  editor fixes these next; you never rewrite body prose yourself (you only insert the blocks/
  markers). Keep the list to genuine needs — an unnecessary rewrite costs a full prose-authoring
  pass.

**4. Compliance + integrity.** `brief-core-constraints.md` binds here exactly as it did the
body it belongs to: its compliance-and-safety rules (domain-semantic colours only for their
genuine meaning, no fabricated stats/ratings in any spec, market/scope integrity) and its
cp-component field-discipline rule (every field a short, complete phrase under its
`manifest.json` cap) apply to every spec you author.

## Output — patch the bundle, then return the status

Write back to the SAME bundle path, changing ONLY:

- `body_markdown` — your final body with the cp-component blocks + `[[FIGURE]]`/`[[IMAGE]]`
  markers inserted (prose otherwise byte-for-byte unchanged — a prose editor reworks the
  flagged paragraphs in the next stage, not you);
- `figure_requests` — the drawn-figure contracts you emitted (`[]` if none);
- `image_requests` — the NB2 contracts you emitted (`[]` if none);
- `visual_rewrite_plan` — the paragraphs that need reworking (`[]` when the prose already
  seats every visual cleanly);
- `visuals_planned` — set to `true`;
- `generation_report.visual_count` + `generation_report.visual_types` — reflect what you placed.

Leave every other field untouched; `slug` stays verbatim. Then return ONLY a compact one-line
JSON status:

```json
{"slug": "...", "visuals_planned": true, "components": 0, "figures": 0, "images": 0, "rewrites_needed": 0, "flags": ["..."]}
```

`rewrites_needed` = the length of `visual_rewrite_plan` (the workflow runs the prose-rework
stage only when it is > 0). Do not paste the article body into your final message.
