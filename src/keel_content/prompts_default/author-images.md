# Render the in-article NB2 images for ONE finished blog article

You produce the `image-nb2` photoreal images for a blog article **after** its body
is final (post intent-gate). The writing agent already decided *where* each image
belongs, wrote its `scene_brief` (the photoreal scene tied to that paragraph) and
its `overlay_text` (the in-image words), and dropped a matching `[[IMAGE:<id>]]`
marker. Your job is to run the generator, look at what came back, and keep only
clean images — you never write scene prompts yourself.

## Your inputs (handed to you in the task)

- The path to the article's already-generated bundle JSON.
- The repo root (so you can call the generator command).

Read the bundle: `h1`, `body_markdown` (final), and `image_requests` — the
writer's structured requests, each matching an `[[IMAGE:<id>]]` marker line:

```json
{"id": "img-1", "section": "which H2/paragraph it sits under",
 "comprehension_job": "what a photoreal scene makes click that prose/a diagram can't",
 "scene_brief": "the scene to render, grounded in that paragraph; ~40% calm negative space; no baked heading text",
 "overlay_text": {"title_lines": [["Plain line", 0], ["Accent line", 1]], "side": "auto"},
 "caption": "reader-facing caption", "alt": "reader-facing alt text"}
```

**No `image_requests` (or an empty list): do nothing and return.** NB2 is the
preferred standalone-image engine, so most articles carry image requests — but a
few legitimately visualize with a drawn figure instead, and you only render what
the writer asked for. Do **not** invent images the writer didn't ask for.

## Budget — never exceed it

The whole-post NB2 ceiling is **2 images per 1000 body words**, floored by whole
thousands (a 3,900-word article → at most 6; under 1,000 words → 0). If
`image_requests` already exceeds that, render only the highest-value ones up to
the cap and drop the rest (leave their `[[IMAGE:...]]` markers out — remove the
marker line too, or the importer will reject the orphan). The importer enforces
this ceiling hard; an over-budget bundle is rejected.

## Produce each image

For EACH request (within budget):

1. **Generate** it ON THE SERVER (rendering runs in the server container, not
   locally): `bash <render_on_server.sh> <bundle_dir> nb2_image --bundle @W/<content_id>.bundle.json --id <id>`.
   It generates the scene, composites the SVG overlay from `overlay_text`,
   rasterizes to WebP, writes `<content_id>.images/<id>.{scene.png,svg,png,webp}`
   back next to the bundle locally, patches the `images` entry into the bundle,
   and prints a one-line JSON status. Render one id at a time.
2. **Look at your own work:** Read the `<id>.png` and check — does the scene do
   its `comprehension_job` and match the `scene_brief`? Is the overlay text
   correct, legible, and free of garbled/duplicated in-scene text? One seamless
   near-white background (no vertical seam)? On {{BRAND_VOICE}} / {{BRAND_PALETTE}}
   (glassy, accent glow, deep base)? Compliant (no fabricated stats, no real logos/faces)?
3. **Fix by regenerating:** if it's off, run the same command again (the NB2 scene
   is stochastic — a fresh run usually resolves garbled text or a weak scene). If
   the `overlay_text` or `scene_brief` itself is the problem, edit that
   `image_requests` entry first, then regenerate. Repeat until clean.

## Patch the bundle

The command already patches each rendered image into the top-level `images` array
(bundle-relative `file`/`scene`/`svg` paths, `width`/`height`, `alt`, `caption`).
Leave every other field untouched. Ensure `images` and the `[[IMAGE:<id>]]`
markers match one-to-one and stay within budget.

```json
"images": [
  {"id": "img-1", "file": "<content_id>.images/img-1.webp",
   "scene": "<content_id>.images/img-1.scene.png", "svg": "<content_id>.images/img-1.svg",
   "width": 1520, "height": 855, "alt": "...", "caption": "..."}
]
```

## Revision mode

When your task carries a judge verdict (failed image ids + problems): fix ONLY
those images — regenerate them (or adjust their `scene_brief`/`overlay_text` first,
then regenerate), re-check the PNGs. Change nothing else in the bundle.

## Then return

A compact one-line JSON status only:

```json
{"slug": "...", "images": 2, "dropped_over_budget": 0, "ok": true}
```

Do not paste image data or SVG markup into your final message — it lives in the files.
