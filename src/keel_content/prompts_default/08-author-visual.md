# Step 08 — Author one comprehension-gated visual (data spec only)

You pick ONE component from the typed catalog and author **only its data
`spec`** — the server renders the component template, so you never write HTML,
CSS, or JS. The visual must make **this term's learner question** click; it is
held to a vision-judge comprehension gate, so intent-match matters more than
decoration.

## The term you are visualizing

- **Term:** {{term}}
- **What it is:** {{what_is}}
- **Why it matters:** {{why_it_matters}}
- **Formula:** {{formula}}
- **Real-world example:** {{real_world_example}}

## Hard rules

- **Intent-match:** the visual must teach *this* term, not a related one. Choose
  the component whose archetype most directly answers the learner's question.
- **Author for the judge rubric.** Your visual is vision-judged on four axes —
  author for all four: comprehension (does it make THIS term click?), legibility
  (readable at a glance in BOTH light and dark), mental_model (builds the right
  mental model, not a tangent), on_brand (clean, premium, uses brand tokens).
- **Direction/outcome colours are a reusable design token and are domain law:**
  green `#3bb273` = positive/up, red `#df2c53` = negative/down. Reserve green/red
  strictly for genuine positive/negative or up/down direction. For non-directional
  contrasts use neutral or amber tones (e.g. `comparison_table` default variant,
  amber `warning` tone). (Misusing the direction colours is a common rejection reason.)
- Author data only — no inline styles/JS, no hardcoded hex/px in your spec
  beyond what the schema explicitly asks for.
- Your `spec` MUST validate against the chosen component's JSON Schema
  (`additionalProperties: false` — include only schema-defined keys).
- Optionally add a top-level `caption` (≤ ~200 chars, the single figure caption)
  and `eyebrow` (a short kicker). Do **not** also put a `caption` inside `spec`
  unless the schema requires it — a duplicate caption fails the gate.

## Component catalog (id · when to pick)

{{catalog_block}}

## Author your spec to the chosen component's schema

Every component's full JSON Schema and a worked example are already listed in the
catalog above (one block per component). Once you pick, author your `spec` to THAT
component's schema exactly.

## Output — write ONLY this JSON (no code fence, no commentary)

```json
{
  "component_id": "<one id from the catalog>",
  "spec": { "...": "data matching that component's schema" },
  "caption": "One figure caption that states the aha in plain words.",
  "eyebrow": "Short kicker"
}
```
