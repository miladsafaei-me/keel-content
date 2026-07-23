# Glossary-gap analysis — batch (across a generated cluster)

Run a GLOSSARY-GAP analysis across a just-generated batch of blog bundles. Goal:
find important domain terms the articles rely on that are MISSING from the existing
glossary, so an editor can author dedicated `{{GLOSSARY_PATH}}` pages. This
is the batch/workflow path; the single-article API path uses
[`06-glossary-gap.md`](06-glossary-gap.md). **Advisory only — never blocks anything.**

## Your input (handed to you in the task)

- The bundles directory (`outDir`) and the list of slugs.
- The EXISTING glossary terms (the live `Tag.is_term=True` names) — do NOT suggest
  these or trivial plural / hyphen / abbreviation variants.
- The path of the suggestions JSON to write (next to the bundles).

## What to do

1. Read each bundle's `body_markdown` (use Bash + python/jq to pull the field so you
   don't overflow context).
2. Surface only genuinely glossary-worthy, on-topic terms used across MULTIPLE
   articles with real definitional weight (a reader would search "what is …?" for
   them). A term qualifies only if it is a domain concept in {{DOMAIN}}, literally
   appears in the bodies, is central enough that not knowing it blocks comprehension,
   and is not already covered. Exclude brand / partner / product names, generic
   English words, and bare identifiers/codes. Be conservative; dedupe.
3. Write your suggestions to the given path (pretty JSON, 2-space indent) with shape
   `{"pending": [...]}` — each term as
   `{"term","reason","example_sentence":"","sources":[{"content_id":"<batch>","keyword":"<N articles>","added_at":"<date>"}]}`.
   This file is NOT the queue itself — the operator ingests it into the DB roadmap
   with `manage.py contentplan_ingest_terms <file> --cluster <batch cluster>` (the
   command dedupes against the live glossary and the queued rows), so just write the
   file; do not edit anything git-tracked.

## Output

Return ONLY a compact one-line JSON status: `{"suggested":N,"path":"<file>"}`.
