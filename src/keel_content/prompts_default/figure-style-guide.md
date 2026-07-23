# In-article figure style guide — the shared visual framework

Every in-article figure across every {{PROJECT_NAME}} blog post is drawn inside ONE
shared visual framework so the figures read as siblings — but this framework is
**deliberately NOT the site's design system**. Figures are editorial diagrams:
light, white-background, flat, calm. They ship as standalone WebP images (drawn
as SVG, rasterized), so nothing here inherits page CSS — every color and size is
written into the SVG itself.

A figure exists to do ONE comprehension job the surrounding prose cannot do as
well: show a structure, a flow, a spatial relationship, a contrast, a sequence.
If a figure only restates a sentence or decorates a section, it is wrong.

## Canvas

- Root: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 H">` —
  **viewBox only, never `width`/`height` attributes** (the rasterizer sizes it).
- Height `H`: pick what the content needs, between **600 and 1200**. Common
  choices: 675 (16:9 flows), 800 (3:2 layered diagrams), 900 (4:3 stacks).
- First element, always: `<rect x="0" y="0" width="1200" height="H" fill="#FFFFFF"/>`.
- Safe padding: keep ALL art and text inside a **64-unit margin** on every side.

## Typography

- Every `<text>` carries `font-family="Liberation Sans, Arial, sans-serif"`.
- Sizes (design units; the figure displays at ~760px, so 22 units ≈ 13px):
  primary labels **28–30**, secondary labels **24–26**, small annotations
  **never below 22**. Optional in-figure kicker/title: 34–38, bold — use only
  when the figure needs a framing line the caption can't carry.
- Weights: `400` and `700` only. Horizontal text only — never rotate labels.
- Anchor (`start`/`middle`/`end`) every label deliberately so neighbours can
  never collide; minimum 24 units of clear space between separate labels.
- Total text budget: aim ≤ ~40 words per figure. One idea per figure.

## Color — ONE fixed editorial identity (never varies)

Figures across ALL articles and ALL posts share ONE palette in which every hue
plays a FIXED role — that constancy is what makes the figures read as one
family, recognizably ours. Never swap hues per figure or per article; variety
comes from layout and content, never from re-coloring. (Deliberately not the
site's brand colors — never reuse the site brand accent/base tokens
`{{ACCENT_PRIMARY}}` / `{{BG_START}}` here; the editorial-figure palette below is
its own reusable design-token set, separate from the brand.)

- Ink: text `#111827`, secondary text `#4B5563`.
- Neutrals: hairlines/grid `#D1D5DB`, panel fills `#F8FAFC` or `#F3F4F6`,
  neutral borders `#94A3B8`. Neutrals carry the canvas (~60% of it).
- **PRIMARY — violet, the protagonist.** Stroke/solid `#7C3AED`, tint fill
  `#F5F3FF`, deep text-on-tint `#5B21B6`. The main concept, the emphasized
  path, the thing the figure is about — the dominant chromatic element of
  EVERY figure (~25–30%).
- **SECONDARY — sky, the supporting cast.** Stroke + colored text `#0369A1`,
  tint fill `#E0F2FE`, bright fill `#0EA5E9` (fills only, never thin
  strokes/text). The counterpart or context: the second option in a contrast,
  the alternate branch, background structure (~10%).
- **ACCENT — amber, one small pop.** Fill `#F59E0B` (put ink or white text ON
  it), tint `#FEF3C7`, text `#B45309`. At most ONE small amber moment per
  figure — the pivotal detail or caution. Never large areas (≤5%).
- Direction/outcome semantics are a **reusable design token** and outrank
  everything: green `#16A34A` (tint `#DCFCE7`) = positive/up/allowed, red
  `#DC2626` (tint `#FEE2E2`) = negative/down/blocked — **only** for genuine
  direction/outcome meaning, never decoration. When they appear they own the
  emphasis; don't compete with an amber pop next to them.
- No other hues, ever: no rose/pink, no teal, no extra blues. A warm
  non-semantic highlight is amber; a cool one is sky.
- Contrast rule: colored TEXT only in the deep variants (`#5B21B6`,
  `#0369A1`, `#B45309`); `#0EA5E9` and `#F59E0B` are fill-only.

## Shapes & composition

- Flat design: **no gradients, no shadows, no filters, no 3D, no clipart, no
  emoji, no mascots.** Depth comes from tint fills + strokes.
- Boxes: `rx="12"`; primary strokes `stroke-width="2.5"`, hairlines `1.5`.
- Arrows: straight or elbow lines with a small solid triangle head; dashed
  strokes (`stroke-dasharray="8 6"`) mean hypothetical/blocked paths.
- Step badges: filled circles (r≈20–24) with white bold numbers.
- Density caps: ≤ ~9 labeled elements. If the concept needs more, split it
  into two figures or simplify — never shrink text to fit more in.
- Fill the canvas confidently; a small motif adrift in white space reads as
  unfinished. Balance around the center; respect the 64-unit margin.

## Allowed SVG (self-contained, presentation attributes only)

`<path> <rect> <circle> <ellipse> <line> <polyline> <polygon> <g> <text>
<tspan> <defs> <marker> <clipPath>`. Style everything with presentation
attributes (`fill=`, `stroke=`, `font-size=`, …).

**Forbidden:** `<script> <style> <filter> <image> <use> <foreignObject>
<animate*>`, external `href`s, base64 payloads, CSS classes, and `width`/
`height` attributes on the root.

## Truthfulness (hard gate)

- Every label, number, and relationship must come from the article body or the
  figure request — **never invent data, stats, or examples** the article
  doesn't state. No third-party statistics (see {{COMPLIANCE_GUIDELINES}}).
- No prohibited outcome-guarantee wording (see {{COMPLIANCE_GUIDELINES}}).
- English only.

## Words around the figure

- `alt`: one sentence describing what the image shows, written for someone who
  cannot see it (also what Google Images indexes). Not a keyword string.
- `caption`: the takeaway in plain words — what the reader should conclude,
  not a description of the drawing.

## Delivery contract

- Source: `<content_id>.figures/<figure_id>.svg` next to the bundle.
- Rasterized with the pipeline's figure rasterizer → sibling
  `.png` (judge preview) + `.webp` (ships; 1520px wide = 2× the 760px reading
  column). Keep the WebP ≤ 150 KB — flat design lands well under that.
