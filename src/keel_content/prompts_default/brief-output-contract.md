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
  "body_markdown": "the FULL article body in Markdown: first H2 onward, each in-body visual as a fenced cp-component data block at its anchor, every heading carrying {#section-id}, FAQ at the bottom",
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
  "figure_requests": [
    {"id": "fig-1", "section": "...", "comprehension_job": "...",
     "content_notes": "...", "takeaway": "...", "caption": "...", "alt": "..."}
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
- **Do NOT author the `hero` field** — a separate stage designs the featured-image SVG after
  your draft exists (`author-hero.md`). Omit `hero` entirely.
- **Do NOT author the `figures` field** — you emit only `figure_requests` + their markers; a
  separate stage draws, rasterizes, and judge-gates them. **At least one `figure_requests`
  entry is required** — a bundle with none is import-blocked.

**Then return — as your final message (the orchestrator reads this, not the article) — a
compact one-line JSON status only:**

```json
{"slug": "...", "bundle_path": "...", "word_count": 0, "visual_count": 0, "visual_types": ["..."], "discarded_urls": 0, "flags": ["..."]}
```

Do not paste the article body into your final message — it lives in the bundle file.
