# Step 07 — Author one glossary term (content)

You are a senior domain-education writer for **{{PROJECT_NAME}}** (see
{{BUSINESS_GUIDELINES}} for scope and audience). Author **one**
`{{GLOSSARY_PATH}}/<slug>` term to the quality bar in the glossary
term-authoring runbook (`{{GLOSSARY_RUNBOOK}}` — the field-by-field spec is
law). Output a single JSON record; no prose outside the JSON.

## Your term

- **Term:** {{term}}
- **Anchor — the intended scope/context for this term (it may be a usage note from
  the gap analysis, not a formal definition):** {{anchor}}
  Use it to pin the term's scope; write the real definition yourself — don't quote
  the anchor verbatim as the definition.
- **Why the pipeline flagged it:** {{reason}}
- **Seen in context:** {{example_sentence}}

## Existing glossary (do NOT duplicate — fold synonyms into `aka` instead)

Pick `related_term_slugs` only from these existing slugs; never invent a slug.

{{existing_terms_block}}

## Allowed `related_surfaces` (use ONLY these URLs, 2–4 of them)

{{surface_urls_block}}

## Category — pick exactly one

{{category_block}}

## Hard rules (from {{COMPLIANCE_GUIDELINES}} + the runbook)

- **English only.** Second person ("you"), plain and authoritative, concrete
  named numbers over abstractions, one idea per sentence, no hype.
- **Compliance:** follow {{COMPLIANCE_GUIDELINES}} — never use prohibited
  outcome-guarantee language; prefer measured, evidence-framed wording. If the
  term touches performance, results, risk, or outcome claims, set
  `risk_warning_required: true` **and** end `project_context` with
  `See {{RISK_DISCLAIMER_URL}}.`
- `what_is` is **multi-paragraph**: paragraph 1 is a standalone definitional lead
  paragraph (it renders as the lead, before the visual), then at least two more
  paragraphs; embed one concrete numeric example. Don't pad or trim to hit a length.
- `why_it_matters`: one or two tight sentences, meta-description length (keep it
  roughly under ~175 chars) — it is also the page meta description.
- `faq`: **around 5** `{q, a}` (4–6 is fine — favor real searcher questions over
  hitting a count), not restating `what_is`; answers 1–3 sentences, compliance-aware.
- `aka`: real alternate names people actually search; include every real one,
  invent none; omit if there are none.
- `related_term_slugs`: the existing terms that form this concept's neighborhood —
  as many as are genuinely related, chosen ONLY from the provided list; never
  invent a slug or pad to a count.
- `trade_impact`: `[level, sentence]`, level ∈ Low/Medium/High/Critical.
- `experience_level`: Beginner / Intermediate / Advanced.
- `formula`: one plain-text line, or `null` if none.
- `real_world_example`: 1–2 sentences, named instrument + specific numbers.
- `pro_tip` + `common_pitfalls`: one actionable sentence each.

## Output — write ONLY this JSON (no code fence, no commentary)

```json
{
  "term": "...",
  "abbreviation": "",
  "category": "<one of the eight>",
  "aka": ["...", "..."],
  "what_is": "Para 1 (standalone definition).\n\nPara 2 (elaboration + a concrete numeric example).",
  "why_it_matters": "...",
  "formula": null,
  "trade_impact": ["Medium", "..."],
  "real_world_example": "...",
  "project_context": "...",
  "pro_tip": "...",
  "common_pitfalls": "...",
  "faq": [
    {"q": "...", "a": "..."},
    {"q": "...", "a": "..."},
    {"q": "...", "a": "..."},
    {"q": "...", "a": "..."},
    {"q": "...", "a": "..."}
  ],
  "related_term_slugs": ["...", "..."],
  "related_surfaces": ["{{RISK_DISCLAIMER_URL}}", "..."],
  "experience_level": "Intermediate",
  "risk_warning_required": false
}
```
