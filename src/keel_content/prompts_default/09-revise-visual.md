# Step 09 — Revise a rejected glossary visual

The vision judge rejected the current visual for this term. Re-author the data
`spec` to land the term's aha and clear the judge's specific misses. Output only
the JSON spec.

## The term

- **Term:** {{term}}
- **What it is:** {{what_is}}
- **Why it matters:** {{why_it_matters}}
- **Formula:** {{formula}}
- **Real-world example:** {{real_world_example}}

## The rejected attempt

- **Component:** {{rejected_component_id}}
- **Spec:** {{rejected_spec}}

## The judge verdict (clear THESE)

- **Misses:** {{misses}}
- **Suggested fix:** {{suggested_fix}}

## How to revise

- If the suggested fix is a data/spec tweak the current component can satisfy,
  apply it on the same component.
- **Switch component when the archetype structurally can't teach the idea** —
  this is the most common real fix. Example swaps that have worked before:
  `before_after` → `comparison_table` (when green/red colours or duplicate
  captions fight a non-directional contrast); a calculator → `formula_block`
  (when the point is the relationship, not a number); a dense domain-specific
  chart → `chart_bar`/`mermaid_flowchart`; a phase `timeline` → `how_it_works_steps`
  (when the point is discrete actions, not phases). Use them as inspiration, but
  pick the fix THIS term's specific failure calls for, not a reflexive table lookup.
- **Direction/outcome colours are a reusable design token and are domain law** —
  reserve green/red strictly for genuine positive/negative or up/down direction.
  For non-directional contrasts use a neutral component + amber `warning` tone.
  (Misusing the direction colours is a common rejection reason.)
- Keep a single `caption`; never duplicate it inside `spec`.

## Component catalog (id · when to pick)

{{catalog_block}}

## Output — write ONLY this JSON (no code fence, no commentary)

```json
{
  "component_id": "<id — may differ from the rejected one>",
  "spec": { "...": "data matching that component's schema" },
  "caption": "One figure caption stating the aha.",
  "eyebrow": "Short kicker"
}
```
