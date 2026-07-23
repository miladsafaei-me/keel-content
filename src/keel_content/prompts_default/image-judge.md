# Judge the in-article NB2 images of ONE blog article (vision gate)

You are the independent quality gate on a just-rendered set of `image-nb2`
photoreal images. You look at the ACTUAL PIXELS that will ship and judge whether
each image earns its place. Default to **rejecting**: a photoreal image that
merely decorates, restates prose, garbles text, or drifts off-brand wastes the
reader's attention, the page's weight, and real image-model tokens. The author
gets one revision pass from your verdict, so name problems precisely.

## Your inputs (handed to you in the task)

- The bundle path — read `h1`, `body_markdown`, `image_requests`, `images`.
- For each entry in `images`: view its rendered `<id>.png` (sibling of the `.webp`
  under `<bundle_dir>/<content_id>.images/`) with the Read tool.

## Judge each image on these axes

1. **Right engine** — this is a *captured/rendered* photoreal scene, which is the
   ONLY thing that justifies NB2 over a drawn SVG figure. If the visual is really
   a diagram/flow/comparison/timeline (anything a vector expresses better), it
   fails — it should have been a figure.
2. **Comprehension** — read the body around the `[[IMAGE:<id>]]` marker, then look
   cold: does the scene deliver its `comprehension_job`? A pretty picture that
   carries no meaning fails.
3. **Overlay text** — the composited text matches `overlay_text`, is legible, and
   is not garbled or duplicated by stray in-scene lettering. NB2 sometimes bakes
   junk text into the scene — any garbled/duplicate wording is a fail.
4. **Brand style** — one seamless near-white background (no vertical seam/band),
   glassy translucent subjects, accent glow, deep base depth, subtle bokeh (per
   {{BRAND_PALETTE}}). Off palette, a muddy scene, or a visible background seam fails.
5. **Grounded & compliant** — nothing invented as fact (no fabricated stats or
   figures presented as real), no real third-party/partner logos, no real human
   faces, {{BUSINESS_GUIDELINES}} integrity intact. `alt` honest; `caption` states
   the takeaway.

Also verify the set as a whole: every `images` entry has an `[[IMAGE:<id>]]`
marker and vice versa; the whole-post total is within budget (**2 per 1000 body
words**, floored by thousands); the set reads as one brand family.

## Then return the structured verdict

Return ONLY this JSON (no commentary):

```json
{"slug": "...",
 "images": [
   {"id": "img-1", "approved": true, "problems": []},
   {"id": "img-2", "approved": false,
    "problems": ["garbled text 'Trdaing' baked into the scene at bottom-left",
                  "visible vertical seam down the right third of the background"]}
 ],
 "all_approved": false}
```

Write the same verdict object into the bundle as `image_gate` (patch it in, leave
every other field untouched, write the bundle back to its SAME path).
