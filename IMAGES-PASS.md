# The standalone images pass

**A post is not publishable until its images exist.** `Post.images_ready` is the
switch that says whether they do, and this document is how they get made.

## Why images left the generation run

The generation pipeline used to draw each article's bespoke featured hero and render
its in-article NB2 photoreal images as the last two stages of that article's chain.
Measured on an 11-article cluster:

| | agents | active time |
|---|---|---|
| Hero | 22 | 49 min |
| NB2 images (author + vision judge) | 40 | 74 min |

That is ~123 minutes of chain per cluster spent on output **nothing else in the run
consumes**. No gate reads the hero. No link pass reads an image. The article was
finished and correct before either stage started — they only delayed the moment it
could be imported and reviewed.

So they moved out. The generation run now ends at a gate-checked draft; the visuals
are produced afterwards, on their own schedule, at full concurrency.

## The three steps

```bash
# 1. Export a work order per post whose visuals do not exist yet
manage.py export_pending_visuals --out /tmp/visuals
#    -> /tmp/visuals/<slug>.bundle.json  +  /tmp/visuals/manifest.json

# 2. Produce them (multi-agent; hero + NB2 per post, all posts concurrent)
#    Workflow scriptPath = <keel_content>/tools/images.workflow.js
#    args {contents: manifest.contents, outDir: "/tmp/visuals", repoRoot: "<repo>"}

# 3. Apply them back and flip the flag
manage.py apply_post_images /tmp/visuals
```

Step 2 renders on the server through `render_on_server.sh`, exactly like the figure
and NB2 stages always did — the orchestrating machine needs only `ssh` + `scp`.

## How the handoff survives import

The author writes `[[IMAGE:<id>]]` markers into the body and a matching
`image_requests` entry for each. When the WebPs do not exist yet, `content_import`:

1. swaps each marker for an **invisible anchor**
   (`keel_content.core.pending_images.defer_images`) — invisible so a post published
   by accident shows a small gap, never a broken block or a raw `[[IMAGE:...]]` token;
2. writes the work order to `Post.pending_visuals`
   (`{image_requests, hero_needed, body_markdown}`);
3. sets `Post.images_ready = False`;
4. still attaches the deterministic fallback hero, so the draft is never image-less
   in listings.

`apply_post_images` then fills each anchor with the real `<figure>`, replaces the
fallback hero with the authored one, clears `pending_visuals`, and sets
`images_ready = True`. It is safe to re-run: an anchor is consumed when filled, and
an anchor whose image is still missing is **left in place** rather than stripped —
losing it would lose the author's chosen position for that visual.

Two import-side gates know about the deferred shape and do not fire on it:

* `image_violations` validates marker↔request pairing and the NB2 budget, then
  returns — the remaining checks are all about rendered files.
* The at-least-one-visual floor counts a *requested* NB2 image, because the visual
  is planned and positioned, just not drawn.

## The publish rule

**Do not publish a post while `images_ready` is False.** Its hero is the generic
fallback and any in-article image is still an empty anchor. Filter the drafts that
are waiting on `Post.objects.filter(images_ready=False)`.

Nothing in the pipeline publishes anything — publishing stays a human action — so
this is a review-time check, not an automated block. Treat it the same way as the
existing **Needs assets** flag: a draft carrying either flag is not ready to go live.

Existing posts are unaffected: the migration that adds the field backfills every
row that predates the split to `images_ready=True`, because the old inline pipeline
had already produced their visuals.
