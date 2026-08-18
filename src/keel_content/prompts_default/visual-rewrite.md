# Visual-rewrite card — rework the prose around freshly placed visuals

> Generic keel-content default. A host overrides this in `content-pipeline/prompts/`. It
> composes with `brief-core-constraints.md` — a host that overrides one should keep the set
> consistent.

A visual-plan stage added this article's visuals to finished prose and flagged the paragraphs
that now read wrong beside them — a lead-in that gestures at nothing, prose that restates what
the visual already shows, a transition that skips the visual. Your job is to make each flagged
paragraph seat its visual cleanly, so the article reads as ONE piece: a reader who skips the
visual still follows, and a reader who studies it is never told the same thing twice.

This is a **surgical** pass. Fix exactly the paragraphs in `visual_rewrite_plan`, nothing else.

## Read first

`content-pipeline/prompts/brief-core-constraints.md` IN FULL — every hard rule (compliance,
no-stats, correct language, internal-link allowlist + no trailing slash + one-per-target,
market/scope integrity, domain-semantic colours, the machine-enforced lengths + 2–4 takeaways)
binds your edit exactly as it did the original draft.

## What to do

1. Read the bundle. `body_markdown` is the article with visuals in place; `visual_rewrite_plan`
   is your fix-list — each entry names an `anchor`, its `visual_id`, the `problem`, and the
   `rewrite_goal`.
2. For each entry, rework **only that paragraph** (and, if strictly needed, its immediate
   transition) so the prose sets the visual up and pays it off — introduce what it shows, then
   carry the reader forward with the takeaway, without duplicating the visual's content in
   sentences. Match the article's existing voice and rhythm exactly; add no new sections, no
   new claims, no new stats.
3. **Do NOT** move, add, drop, or re-spec any visual — the plan owns the visual set. **Do NOT**
   touch `internal_links`, `external_sources`, `figure_requests`, `image_requests`, or the
   cp-component blocks themselves. Change as little prose as the goal requires.

## Output

Write the bundle back to the SAME path with the reworked `body_markdown`; set
`visual_rewrite_plan` to `[]` (consumed). Leave every other field untouched; `slug` verbatim.
Return ONLY a compact one-line JSON status: `{"slug":"...","reworked":N}`. Do not paste the
article body.
