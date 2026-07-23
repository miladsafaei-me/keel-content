# Overlap audit — Layer 4 (cannibalization catch)

Run an overlap audit across a just-generated batch of blog bundles, to catch intent
cannibalization / near-duplication BEFORE these articles publish. This is the Layer-4
safety net from the cannibalization-prevention plan ({{CANNIBALIZATION_PLAN}}) §3:
because Layer 1 auto-decides with no human gate, this stage reads every finished
bundle and scores every pair. The audit itself does not modify bundles, but its
output now has teeth at import: a pair scoring **>=75 hard-blocks BOTH its articles**
at `content_import` (a human must merge/differentiate, then re-import); pairs scoring
60–74 are flagged for review but still import. The run still returns either way.

## Your input (handed to you in the task)

- The bundles directory (`outDir`) and the list of slugs to compare.
- Read each bundle's `body_markdown` + `h1` + `meta_description`. Use Bash +
  python/jq to pull fields so you don't overflow context.

## What to do

For EACH unordered pair of articles, score overlap on four signals:

- shared H2 headings (same / near-same section topics),
- duplicated widgets/calculators (same concept re-implemented, e.g. two calculators
  for the same computation),
- repeated key stats/claims stated as if each is original,
- intro/thesis similarity (the same cold-open formula or thesis sentence).

Give each pair an overlap score 0–100 and a one-line reason.

## Output

Write `<outDir>/overlap-audit.json`:

```json
{"pairs":[{"a":"<slug>","b":"<slug>","score":N,"block":false,"signals":["shared_h2","duplicate_widget"],"reason":"..."}],"flagged":[<pairs with score >= 60>]}
```

Set `block: true` on every pair scoring **>= 75** (`content_import` reads this — and
the raw score — to hard-block both articles in such a pair). Sort `pairs` by score
descending. Do NOT modify any bundle.

Then return ONLY a compact one-line JSON status: `{"pairs":P,"flagged":F,"top_score":S}`.
