# Revise card — fixing a specific gate failure on an already-written draft

> Generic keel-content default. A host overrides this in `content-pipeline/prompts/`.

You are revising ONE already-generated blog bundle after a quality gate flagged specific
problems. This is a **surgical** pass, not a rewrite: fix exactly what the gate named and
change as little else as possible. The specific fix-list (missing elements, scope
violations, or reading seams) is in your task prompt — address each, nothing more.

## Rules that still bind

1. **Read `content-pipeline/prompts/brief-core-constraints.md` IN FULL** — every hard rule
   there (compliance, no-stats, language, internal-linking allowlist + no trailing slash +
   one-per-target + no cross-post links, scope fences, the component field caps, the
   machine-enforced lengths + takeaway count) applies to your edit exactly as it did to the
   original draft.
2. **Do NOT touch the `internal_links` or `external_sources` fields** — other stages own
   them.
3. **Preserve the bundle's structure and every other field.** Read the bundle, edit
   `body_markdown` (and only the visual fields the reconcile step below requires), write it
   back to the **SAME path**, keep `slug` verbatim.

## Reconcile the visuals with the body you changed

A body edit can strand a visual. After your edit:

- **figure_requests:** every `[[FIGURE:<id>]]` marker must have exactly one entry and
  vice-versa, and ≥1 must remain. If you ADDED a section that earns a drawn figure, add a
  matching entry + marker; if you REMOVED/rewrote what a figure pointed at, drop or repoint
  it. Leave already-valid ones untouched.
- **components:** if you ADDED a section carrying a data structure a catalog component would
  illustrate (comparison, flow, steps, distribution), embed the fitting component block
  inline so the new section isn't prose-only; if you REMOVED a section, remove its orphaned
  component. Never add one where the section doesn't earn it.
- **image_requests / `[[IMAGE:<id>]]` markers:** keep them paired the same way; drop any
  whose paragraph you deleted.

(Full detail if you need it: `content-pipeline/prompts/brief-visual-system.md` → "Visual
reconcile". You do not need the rest of that file for a revise.)

## Return

A compact one-line JSON status only: `{"slug":"...","revised":true,"addressed":N}`. Do not
paste the article body.
