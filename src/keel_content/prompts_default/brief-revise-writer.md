# Brief-revise card — fixing an already-written production brief

> Generic keel-content default. A host overrides this in `content-pipeline/prompts/`.

You already wrote this article's production brief; an adversarial judge reviewed it and
flagged specific fixes. This is a **surgical** pass: edit the previous brief to fix exactly
what the judge named, and change nothing the judge did not flag. You do not need the full
brief-writer contract — you have a valid brief in front of you to edit. (Full contract if
an edge case truly needs it: `content-pipeline/prompts/brief-author.md`.)

## What you were given (in the task prompt)

- **The judge's required fixes** — address EVERY one.
- **YOUR PREVIOUS BRIEF** — the JSON object to revise. Keep its exact shape and every field
  the judge left alone; edit only what a fix requires.
- **The SPEC** and the **CLUSTER BRIEF** (binding) — for context and the scope fences.

## Rules that still bind

1. **Fix exactly the flagged issues, minimally.** Do not redesign passing parts of the
   brief, and do not add scope the judge did not ask for.
2. **Respect the scope fences** (`scope_includes` / `scope_excludes`) — never design content
   the reconcile step fenced OUT of this article, and never claim a sibling-owned element
   (link to it instead).
3. **Keep the output shape identical** to your previous brief (same fields, same JSON
   structure the contract specifies) — the result is schema-validated, so a malformed or
   renamed field is rejected. `slug` stays verbatim.
4. If a fix needs fresh evidence, WebFetch/WebSearch narrowly for that one gap — do not
   re-crawl the whole SERP.

## Return

Return exactly the JSON brief object (the same shape as your previous attempt, with the
fixes applied). Nothing else.
