# The republish route

A fourth intake route beside the keyword, Twitter and YouTube ones: take pages
that already rank, and produce **our** content from them.

It differs from the others in one way that shapes everything: **the number of
outputs is independent of the number of inputs.** Two thin sources often deserve
one article. One broad source can owe several. And the smallest useful output is
not an article at all — it is a single visual dropped into a post published
months ago, which creates no URL and needs no rewrite.

## Who does what

| | Where | Why there |
|---|---|---|
| Fetch, extract, image triage, chart recovery, figure drawing, format policy | **`page-extract`** (standalone, no Django, no keel) | None of it knows about a content model, and it is useful outside this pipeline |
| Plan contract, bundle assembly, component catalog, grafting | **here** | All of it knows about *our* content model |
| Classifying the visuals; writing the prose | **a model** | The only two parts that need judgment |

Everything outside that middle column is deterministic and costs no tokens.

## The plan

One `plan.json`, validated by `keel_content.republish.validate_plan`. Its
`outputs` array carries two kinds:

```jsonc
{
  "notes": "Why these sources were merged / split this way.",
  "outputs": [
    { "kind": "post", "slug": "...", "from": ["s1", "s2"],
      "bundle": { /* title, meta, body_markdown, facets, ... */ },
      "figures": [ { "id": "fig-1", "builder": "hub_spokes",
                     "params": { }, "alt": "...", "caption": "..." } ] },

    { "kind": "graft", "graft_id": "call-put-split",
      "target_slug": "an-article-we-published-in-may",
      "anchor": { "mode": "after_heading", "text": "What a traditional option is" },
      "visual": { "component_id": "comparison_table", "spec": { } } }
  ]
}
```

A `graft` carries **either** a `visual` (a live component) **or** a `figure` (a
drawn WebP) — never both. Which one is a real decision; see below.

## Not everything should become HTML

`page_extract.policy.decide()` answers this, and says why.

**Live markup** wins when the reader operates the visual — sorts, hovers,
expands it — or when it must reflow onto a phone. Text stays selectable,
translatable, themeable and machine-readable.

**A drawn figure** wins when the layout *is* the information: a hub with its
parts around it, a process whose arrows cross, a 2x2 read by quadrant. Stacking
those into markup deletes the relationship the visual existed to show. Figures
also survive in RSS, email and OG cards, where components do not.

When both would work, prefer markup.

## Using it during briefing, without being led by the source

This is the part with a trap in it, and the trap is subtle: look at what a
competitor drew, and write your brief around it, and you have produced a
reproduction of their outline with better styling. It reads as thorough
research. It is the opposite.

So the order is fixed, and `keel_content.republish.brief` enforces it:

1. **The brief writes its own visual needs first**, from its own outline, before
   any harvested visual is looked at. A `Need` says what the reader should
   understand — never what a picture should contain.
2. `visual_opportunities(needs, gallery)` then reports, **per need**, whether
   anything harvested happens to answer it. It iterates over needs, never over
   the gallery, so a source visual matching nothing is never surfaced and
   therefore cannot suggest itself.
3. What matched gets reproduced as our component or our drawn figure. Nothing of
   the source's layout, palette or watermark ships.

```python
from keel_content.republish.brief import Need, visual_opportunities, report

needs = [Need("v1", "Show that a binary option settles all-or-nothing", shape="contrast_table")]
print(report(visual_opportunities(needs, harvest["gallery"])))
```

`needs_fingerprint(needs)` hashes the needs as written. Store it with the brief:
if the needs are later edited to match what a competitor happened to have, the
fingerprint disagrees and the ordering rule has visibly been broken.

Two guards keep matches honest. A need's declared `shape` must be compatible
with the source image's `kind`, so a flat infographic never answers a need for a
price chart. And a match needs at least two meaningful words in common — one is
a coincidence. A missed match costs a figure drawn from scratch, which is
cheap; a false match costs a visual that answers the wrong question.

## Shipping

```bash
manage.py content_import <workspace>/out/<slug>.bundle.json   # post outputs
manage.py republish_graft <workspace>/out/graft-<id>.json     # graft outputs
```

`content_import` runs its usual gates on top of the plan's own validation.

`republish_graft` writes the block into **both** `content_rendered` and
`content_markdown_source`, so the rendered page and the editor never disagree,
and stamps a `data-graft-id`. Re-running the same payload replaces its own block
rather than stacking a second copy — change the id and you get a second block.

## Traps

- **The host's body sanitizer may strip custom classes.** Hand-written component
  HTML in a body does not survive. Visuals go through `cp-component` fences or
  figures, always.
- **`content_markdown_source` holds post-expansion markdown**, with components
  already rendered — not the authored bundle. That is why grafting writes
  rendered HTML instead of re-running the bundle pipeline.
- **Never read numbers off a chart with a model.** `page-extract chart` recovers
  the series from pixels; a model asked to read a chart invents plausible values
  and you cannot tell which.
