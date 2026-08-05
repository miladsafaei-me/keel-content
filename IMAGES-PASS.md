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
manage.py export_pending_visuals --out /tmp/visuals [--cluster <topic-cluster-slug>]
#    -> /tmp/visuals/<slug>.bundle.json  +  /tmp/visuals/manifest.json

# 2. Produce them (multi-agent; hero + NB2 per post, all posts concurrent)
#    Workflow scriptPath = <keel_content>/tools/images.workflow.js
#    args {contents: manifest.contents, outDir: "/tmp/visuals", repoRoot: "<repo>"}

# 3. Apply them back and flip the flag
manage.py apply_post_images /tmp/visuals
```

Step 2 renders on the server through `render_on_server.sh`, exactly like the figure
and NB2 stages always did — the orchestrating machine needs only `ssh` + `scp`.

`--cluster` exists because a consumer's loop may draw a cluster's visuals right
after producing it, so the cluster becomes publishable before the next one starts.
Without it the pass takes every pending post.

## Posts the machine cannot draw

A queue that must reach zero before other work resumes needs a way to stop waiting
on a post that will never finish — a body whose anchors lost their requests, a hero
the judge rejects every time, a bundle that will not render. `flag_stuck_visuals`
charges one attempt per post per finished run and, past the budget, writes a
`blocked` marker onto `pending_visuals`. Blocked posts are excluded from
`export_pending_visuals` (override with `--include-blocked`) and from any
pending count.

```bash
manage.py flag_stuck_visuals --cluster <slug> --max-attempts 2 --json   # after a run
manage.py flag_stuck_visuals --list                                     # what is stuck, and why
manage.py flag_stuck_visuals --unblock <slug>                           # requeue after a human fix
```

Charge attempts only after a run that genuinely attempted the scope. A run killed
by a closed token window attempted nothing.

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
fallback hero with the authored one, and sets `images_ready = True`. It is safe to
re-run: an anchor is consumed when filled, and an anchor whose image is still
missing is **left in place** rather than stripped — losing it would lose the
author's chosen position for that visual.

`pending_visuals` is cleared **only when the post actually finished**. It used to be
cleared unconditionally, which stranded any post that still held anchors: the
`image_requests` describing them were destroyed, so every later export produced a
bundle nothing could fill and the post stayed pending forever. Keeping the order on
an unfinished post is also what carries its attempt counter to the next run.

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
