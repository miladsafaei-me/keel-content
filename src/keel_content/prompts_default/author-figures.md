# Author the in-article figures for ONE finished blog article

You draw the standalone explanatory images for a blog article **after** its body
is final (post intent-gate). The writing agent already decided *where* figures
belong and *what job* each does — you design and produce the actual images, so
the writer never spends context on SVG geometry.

## Your inputs (handed to you in the task)

- The path to the article's already-generated bundle JSON.
- The path to the figure style guide (`figure-style-guide.md`) — **read it in
  full first; it is the binding visual framework.**
- The path to the server-render wrapper (`render_on_server.sh`) — rasterization
  runs on the server, not locally (see "Produce each figure").

Read the bundle: `h1`, `body_markdown` (the final article), and
`figure_requests` — the writer's structured requests, each matching a
`[[FIGURE:<id>]]` marker line in the body:

```json
{"id": "fig-1", "section": "which H2 it sits in",
 "comprehension_job": "what the reader must grasp that prose alone can't deliver",
 "content_notes": "the labels/steps/relationships to show — all grounded in the body",
 "takeaway": "the one-line conclusion the figure proves",
 "caption": "reader-facing caption", "alt": "reader-facing alt text"}
```

**No `figure_requests` in the bundle (or an empty list):** NB2 photoreal images
are now the preferred standalone-image engine, so an article legitimately has
zero figures when its imagery is carried by NB2 images (an `images` array or
`[[IMAGE:...]]` markers). **If the bundle already has NB2 imagery, do nothing and
return** — figures are not required on top. Only when the article has *neither*
figures nor NB2 images should you derive figures yourself: find the concepts
where a *drawn* figure does a comprehension job prose and cp-components cannot (a
structure, flow, contrast, sequence, spatial relationship), insert a
`[[FIGURE:fig-N]]` marker at each exact spot, write the matching `figure_requests`
entries, then continue — at least one, so every article ships one standalone
image.

## Produce each figure

For EACH request:

1. **Design the SVG** per the style guide: 1200-wide viewBox, white background,
   the ONE fixed identity palette with its fixed roles (violet protagonist,
   sky support, ≤1 amber pop — never re-colored per figure), flat,
   one idea, every label grounded in the article. The figure must *do* its
   `comprehension_job` — a reader who just read that section should get the
   `takeaway` from the image in under ten seconds.
2. **Write it** to `<bundle_dir>/<content_id>.figures/<id>.svg` (create the dir).
3. **Rasterize ON THE SERVER:** run
   `bash <render_on_server.sh> <bundle_dir> figure_raster --svg @W/<content_id>.figures/<id>.svg`.
   The wrapper renders inside the server container and writes `<id>.png` +
   `<id>.webp` back next to the SVG locally, printing `{"width": W, "height": H, ...}`.
4. **Look at your own work:** Read the `<id>.png` and self-check — labels
   legible and non-colliding? margins respected? palette/framework right?
   nothing invented? Fix the SVG and re-rasterize until it is clean.

## Patch the bundle

Add/replace a top-level `figures` array (leave `figure_requests` and every
other field untouched unless you ran the fallback above), then write the bundle
back to its SAME path:

```json
"figures": [
  {"id": "fig-1", "file": "<content_id>.figures/fig-1.webp",
   "svg": "<content_id>.figures/fig-1.svg", "width": 1520, "height": 855,
   "alt": "...", "caption": "...",
   "comprehension_job": "...", "section": "..."}
]
```

`file`/`svg` are RELATIVE to the bundle's directory — the importer copies the
WebP into media storage and replaces each `[[FIGURE:<id>]]` marker with the
final `<figure>` markup. `width`/`height` come from the rasterizer output.

## Revision mode

When your task carries a judge verdict (failed figure ids + problems): fix ONLY
those figures — edit their SVGs, re-rasterize, re-check the PNGs, update their
`figures` entries. Change nothing else in the bundle.

## Then return

A compact one-line JSON status only (the orchestrator reads this, not the SVG):

```json
{"slug": "...", "figures": 2, "derived_requests": false, "ok": true}
```

Do not paste SVG markup into your final message — it lives in the files.
