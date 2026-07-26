# Visual system — selecting and emitting article visuals

> Generic keel-content default. A host overrides this in `content-pipeline/prompts/`.

How to choose and emit every visual: catalog `cp-component` blocks (the default), drawn
`figure_requests` (fallback), and NB2 photoreal `image_requests` (preferred standalone
image). You never write HTML/CSS/JS — visuals are data specs the server renders.

## Deriving the set (no quota)

- **Derive from THIS article's intent, never a fixed count or one-of-each.** List the
  concepts a reader grasps better *shown* than *told*; give each the ONE format that
  explains it best. The count falls out of that (a focused how-to may need 2, a data-dense
  comparison 5; most land around 3–5 — an observation, not a target). Before finalizing each
  visual ask: "does the concept demand this format, or am I filling a slot?" — cut every
  slot-filler. "One table + one flowchart + one chart + one calculator" on every article is
  the templated sameness search engines read as low-effort.
- **`lead_visual_archetype` hint:** honor it as your LEAD / most-prominent visual, then
  derive the rest from intent (it is a cluster-level variety nudge). If it can't serve this
  article, pick the closest fitting lead and note why in `generation_report.self_flags`.
  Absent → derive the whole set from intent.
- **Match vocabulary to the archetype** (`intent_frame`): a comparison → comparison tables +
  a decision aid; a step-by-step how-to → a process diagram + an inline calculator; a
  forecast → annotated charts + a scenario table; a concept explainer → one strong diagram
  or an interactive simulator.

## Catalog components (`cp-component`) — the default in-body visual

- **Pick from the typed catalog; emit DATA, never HTML.** The full catalog (each
  component's `when_to_pick`, JSON schema, worked example) is
  `content-pipeline/components/CATALOG.md`; components live at
  `content-pipeline/components/<category>/<id>/`. **Open CATALOG.md and the shortlisted
  component's `manifest.json` before authoring.** Author **only its data `spec`** — valid
  against its JSON Schema, schema-defined keys only.
- **Match the reader's need to `when_to_pick`, not a similar-sounding id.** A near-name is a
  trap — confirm fit by `when_to_pick`, not by a label that sounds close.
- **Selection workflow (concept-first):** (1) per section, name the concept better shown
  than told + the reader's JOB; (2) narrow to a family via the map below; (3) open CATALOG.md,
  read candidates' `when_to_pick` + `schema`, confirm fit in the chosen `manifest.json`. If no
  component genuinely fits, **skip the visual rather than hand-roll HTML** — note the gap in
  `self_flags`.
  - process / sequence → flow / how-it-works-steps
  - comparing options → comparison-table
  - distribution / outcome spread → a chart, or a simulator
  - reader computes their own numbers → calculator
  - confirming understanding → quiz / checklist / faq
- **Embed each as a fenced block at the exact point it belongs:**
  ```cp-component
  {"component_id": "calculator", "spec": { … schema-valid … }, "caption": "the one-line aha", "eyebrow": "Try the numbers"}
  ```
  `caption` (≤ ~200 chars) and `eyebrow` are optional. A block whose spec fails validation is
  **dropped** — get the schema exactly right.
- **Put at least one INTERACTIVE visual in a long article** (a reader-manipulated component —
  a calculator, simulator, checklist, or quiz). Everything else is static.
- **Prose-bearing `structure` blocks** carry the article's own prose and frame a *key
  moment* (schema-validated): an opening answer hero, a beat section, an element card, a
  closing loop. Use sparingly, only when a moment deserves a designed frame.

## Drawn figures (`figure_requests`) — the FALLBACK diagram; you do NOT draw it

A flat, white-background editorial diagram produced as a WebP by a separate stage.
**Default standalone imagery to an NB2 image (below); use a figure ONLY when the concept is
inherently *drawn* and a photoreal scene genuinely can't express it** — a structure, a
spatial contrast, a branching flow, a timeline, a labeled map of relationships. If a catalog
component can express it, the component wins.

- **Need-driven, no min/max/quota.** Every article ships **at least one standalone
  explanatory image** — met in most articles by an NB2 image; use a figure for the floor only
  when the topic is genuinely diagram-only. `spec.brief.figure_opportunities` (if present) are
  hints — honor the good ones, drop what the text doesn't support.
- **Non-decorative bar:** each `comprehension_job` names what the reader grasps that prose
  can't deliver as well. "Breaks up the text" is not a job.
- **Emit the contract:** a `[[FIGURE:fig-N]]` marker on its own line at the exact spot, and a
  matching entry (markers ↔ entries one-to-one):
  ```json
  {"id": "fig-1", "section": "which H2 it sits in",
   "comprehension_job": "what must click that prose can't do as well",
   "content_notes": "the exact labels/steps/relationships — ONLY facts stated in your body",
   "takeaway": "the one-line conclusion the image proves",
   "caption": "reader-facing caption (states the takeaway, not the drawing)",
   "alt": "one honest sentence describing the image for someone who can't see it"}
  ```
  `content_notes` may contain ONLY facts your body states — the figure stage draws exactly
  what you specify and never invents data.

## NB2 photoreal images (`image_requests`) — the PREFERRED standalone image; budgeted

The default engine for standalone imagery: a premium photoreal scene with a crisp SVG text
overlay composited on top, delivered as WebP — a conceptual metaphor or an evocative section
opener. Reach for it first.

- **Hard budget (whole post):** at most **2 NB2 images per 1000 body words**, with a floor so
  even a sub-1,000-word post may carry up to **2**. A global ceiling on the total, not a
  density rule. Overflow is a hard import error.
- **Non-decorative bar:** `comprehension_job` names what a photoreal scene makes click that
  prose/a diagram can't. Compliance binds: no fabricated stats in a scene, no real
  brand/regulator logos, no real faces.
- **Emit the contract:** an `[[IMAGE:img-N]]` marker on its own line, and a matching entry.
  YOU write the `scene_brief` (scene tied to THIS paragraph; the scene carries NO baked
  heading text) and the exact `overlay_text`:
  ```json
  {"id": "img-1", "section": "which H2/paragraph it sits under",
   "comprehension_job": "what a photoreal scene makes click that prose/a diagram can't",
   "scene_brief": "the scene grounded in THIS paragraph: the metaphor, the objects, subject on ONE side and ~40% calm negative space reserved on the OPPOSITE side for the text; no baked heading text",
   "overlay_text": {"title_lines": [["Plain line", 0], ["Accent line", 1]], "side": "left"},
   "caption": "reader-facing caption (states the takeaway, not the drawing)",
   "alt": "one honest sentence describing the image for someone who can't see it"}
  ```
  `title_lines` = `[text, is_accent]` pairs (2–4 short lines). **`side` MUST be the empty
  side** (`left`/`right`, matching where `scene_brief` reserves the space) — **never `auto`**.
  Markers ↔ entries one-to-one.

## Visual reconcile (after ANY body edit — used by the revise stages)

A body edit can strand a visual. After changing the body, reconcile:
- **figure_requests:** every `[[FIGURE:<id>]]` marker has exactly one entry and vice-versa,
  and ≥1 remains. Added a section that earns a drawn figure → add entry + marker; removed/
  rewrote what a figure pointed at → drop or repoint it. Leave already-valid ones untouched.
- **cp-components:** added a section carrying a data structure a component would illustrate
  (comparison, flow, steps, distribution) → embed the fitting component inline; removed a
  section → remove its orphaned component. Never add one where the section doesn't earn it.
- **image_requests / `[[IMAGE:<id>]]`:** keep them paired the same way; drop any whose
  paragraph you deleted.
