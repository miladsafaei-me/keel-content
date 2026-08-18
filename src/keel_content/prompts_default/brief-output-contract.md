# Output contract — the bundle JSON and the return status

> Generic keel-content default. A host overrides this in `content-pipeline/prompts/`.

Write a single JSON file to `<outDir>/<content_id>.bundle.json` (path given in your task).
It MUST match this shape (the publisher reads it via `content_import`):

```json
{
  "content_id": "<spec.content_id>",
  "slug": "<spec.slug — verbatim>",
  "target": "blog",
  "title": "<SEO title tag / breadcrumb label — <=65 chars>",
  "h1": "<on-page visible H1 — from spec.h1, reader-facing; distinct from title; <=65 chars>",
  "meta_title": "<=65 chars",
  "meta_description": "<=160 chars; complements the title, carries the primary keyword naturally>",
  "excerpt": "<=200 chars; the card/summary line>",
  "key_takeaways_markdown": "- 2-4 bullet takeaways in Markdown",
  "body_markdown": "the FULL article body in Markdown: first H2 onward, PURE PROSE with no visuals of any kind (no cp-component blocks, no [[FIGURE]]/[[IMAGE]] markers — a separate downstream visual-plan stage reads this finished body and adds every in-body visual afterward), every heading carrying {#section-id}, FAQ at the bottom",
  "featured_image_url": "",
  "external_sources": [
    {"url": "https://en.wikipedia.org/wiki/...", "anchor": "Source name — what it covers", "role": "further_reading"}
  ],
  "video_embeds": [
    {"id": "vid-1", "url": "https://www.youtube.com/watch?v=...",
     "title": "what the video shows", "channel": "the channel name",
     "placement": "which section it belongs in"}
  ],
  "asset_requests": [
    {"id": "ar-1", "type": "video|screenshot|photo|data|chart",
     "description": "what the human must supply (specific enough to produce from)",
     "placement": "which section it belongs in"}
  ],
  "author_slug": null,
  "reviewer_slug": null,
  "initial_status": "draft",
  "facets": {
    "topic_cluster": "<spec.topic_cluster>",
    "categories": ["<spec.categories...>"],
    "markets": ["<spec.markets...>"],
    "audience_roles": ["<spec.audience_roles...>"],
    "audience_levels": ["<spec.audience_levels...>"],
    "glossary_terms": ["<spec.glossary_terms UNION every glossary term you linked in the body>"],
    "role": "<spec.role>"
  },
  "generation_report": {
    "word_count": 0,
    "visual_count": 0,
    "visual_types": ["chartjs", "mermaid", "..."],
    "competitor_urls_used": ["..."],
    "competitor_urls_discarded": [{"url": "...", "reason": "off-intent: ..."}],
    "risk_warning_linked": true,
    "self_flags": ["anything a human reviewer should double-check"]
  }
}
```

- Carry the `facets` NAMES straight from the spec (the publisher resolves them to DB rows);
  extend only `glossary_terms` with the terms you actually linked.
- `video_embeds` / `asset_requests` stay `[]` when you produced everything yourself. Every
  entry needs a matching `[[VIDEO:<id>]]` / `[[ASSET:<id>]]` marker line (and vice versa); an
  unverifiable video auto-downgrades to an asset request.
- Leave `author_slug` and `reviewer_slug` **null** — the publisher assigns byline + reviewer
  from the host's editorial model (it keys off `facets.markets`). Just get `facets` right.
- `featured_image_url` stays `""` for code-in-page articles (the site supplies a default
  social card). Set it only for a real, available hero image.
- **Do NOT author `hero`, `figures`, `figure_requests`, `image_requests`, or any `cp-component`
  block** — `body_markdown` is pure prose here, with no visuals of any kind. A separate
  downstream visual-plan stage reads your FINISHED body afterward and decides, places, and
  seats every in-body visual (components, drawn figures, NB2 images) and the hero against it —
  deliberately decoupled so your writing is never bent to fit whatever happens to be in the
  component catalog. Omit these fields entirely; the visual-plan stage patches them into the
  SAME bundle file later. The one-standalone-image floor is that same downstream stage's
  responsibility, not yours.

**Then return — as your final message (the orchestrator reads this, not the article) — a
compact one-line JSON status only:**

```json
{"slug": "...", "bundle_path": "...", "word_count": 0, "visual_count": 0, "visual_types": ["..."], "discarded_urls": 0, "flags": ["..."]}
```

Do not paste the article body into your final message — it lives in the bundle file.
