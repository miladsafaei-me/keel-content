# Author the featured-image hero for ONE finished blog article

You design the bespoke featured-image SVG for a blog article **after** its body
has been written. This stage is deliberately separate from article generation so
the writing agent can focus entirely on prose, and so the hero can be drawn to
match the *finished* content.

## Your input (handed to you in the task)

- The path to the article's already-generated bundle JSON.
- Read that bundle: its `h1`, `title`, `meta_description`, and `body_markdown` tell
  you exactly what the article is about. Design the hero for *that* concept.

## What you produce

Patch a `hero` object into the SAME bundle file, leaving every other field
untouched, and write it back to its same path:

```json
"hero": {"svg_element": "<defs><linearGradient id='h1_xyz' .../></defs><...your bespoke SVG diagram for THIS article...>", "head": [["Question in.", null], ["Answer out.", "g"]]}
```

## `hero.svg_element` — DESIGN the visual element yourself, from scratch, for THIS article

There is NO menu of preset shapes to pick from — you author the actual SVG of the
diagram/illustration. The goal: across thousands of posts, no two heroes look
alike, because each is drawn for its own concept. Do not fall back on a checkbox
list, a two-boxes-joined-by-a-line, or a generic node graph — invent the
visualization that best explains *this* article (a process forming step by step, a
before/after curve, a data set split into segments, a pipeline of inputs to an
output, a gauge, a labeled map of relationships — whatever fits the body's domain).

The site composes your element into a fixed brand frame, so you ONLY draw the
visual element — never redraw the background, logo, category chip, or headline.

`hero.svg_element` = a raw SVG fragment (no `<svg>` wrapper) rendered inside this
framework:

- **Canvas** is 1200×630; the headline owns the left. Your element is clipped to the
  right zone, but for visual balance keep ALL art inside the **safe content zone
  `x ∈ [700, 1120], y ∈ [150, 560]`**, roughly centred near `(910, 360)`. Use real
  coordinates in that range. Five hard layout rules — they are what makes the heroes
  look balanced and consistent, and each maps to a real mistake to avoid:
  - **Right margin (don't hug the edge):** the right edge of *every* shape, line and
    label must be `≤ ~1120`. Mirror the ~74px brand margin the logo already keeps —
    art that runs to 1150+ reads as cropped/cramped.
  - **Left edge `≥ ~700`** so the art never crowds the headline.
  - **Fill the zone (don't draw it tiny):** size the element to occupy the space
    confidently — aim to fill roughly `360×360`. A small motif adrift in empty space
    reads as unfinished.
  - **Label spacing (don't let text collide):** never let two labels touch or overlap.
    Size text so each label sits comfortably inside the safe zone without overflowing,
    leave a clear gap between labels, and anchor (`start`/`middle`/`end`) each label so
    it can't run into its neighbour.
  - **Label legibility (contrast + placement):** never drop a label on top of a line or
    shape in a low-contrast colour. Put labels in clear background space (e.g. *under*
    an axis), or on a contrasting fill (the accent or white on the dark bg; dark
    `{{BG_START}}` text on an accent fill). Every label must read at small sizes.
- **Palette — use ONLY these brand tokens** (the host supplies the exact hex via
  {{BRAND_PALETTE}}): a dark background gradient `{{BG_START}}`→`{{BG_END}}`
  (already drawn); primary accent `{{ACCENT_PRIMARY}}`; surface `{{SURFACE}}`;
  text white `#ffffff` / secondary `{{TEXT_SECONDARY}}`. A cool secondary
  `{{ACCENT_SECONDARY}}` and a warm accent `{{ACCENT_WARM}}` are occasional
  seconds. The trade-semantic direction pair is a **reusable design token** and is
  domain law where the visual carries genuine direction/outcome meaning: `#3bb273`
  = UP/positive and `#df2c53` = DOWN/negative **only** (never repurpose these two).
  Everything sits on a dark bg, so use light strokes/fills.
- **Allowed:** `<path> <rect> <circle> <line> <polyline> <polygon> <ellipse> <g>
  <text> <tspan> <defs> <linearGradient> <radialGradient>`. Give any gradient a
  **unique id** (e.g. `h1_<slug-ish>`). `<text>` uses `font-family="{{BRAND_FONT}}"`.
- **Forbidden (stripped automatically, so don't rely on them):** `<script> <filter>
  <image> <use> <foreignObject> <animate*>`, blur/drop-shadow filters, inline
  `on*=` handlers, external/`href` URLs. Depth comes from gradients, not filters.
- Keep it clean and premium: a few strong elements, generous space, ≤ ~6 short text
  labels, legible at small sizes. It must read on the dark card.

## `hero.head` — the headline overlay

`head` = the headline as two short lines `[[text, color], ...]`; `color` is `"g"`
for the green accent run (usually line 2), else `null`. Keep each line ≤ ~16 chars.
Derive it from the article's `h1` — a tight, punchy two-line distillation, not the
full title.

## Then return

A compact one-line JSON status only (the orchestrator reads this, not the SVG):

```json
{"slug": "...", "bundle_path": "...", "head": ["...", "..."], "ok": true}
```

Do not paste the SVG into your final message — it lives in the bundle file.
