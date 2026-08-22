# keel-content

The reusable, **business-blind** content-generation pipeline for Keel projects —
extracted from SignalBots and neutralized so every project-specific piece is a config
hook, not hardcoded. It takes topics in through five intake routes, generates
pipeline-quality articles (with in-body visuals, a bespoke hero image, and a verified
"Sources & Further Reading" list), and hands the host CMS a **draft**. It does not
publish, index, or monetize — those are the host's concern.

Read [`PLATFORM.md`](https://github.com/miladsafaei-me/keel-kit) (in keel-kit) for the
platform model, and this repo's [`CLAUDE.md`](CLAUDE.md) for the contract.

## What it provides

- **The engine** (`keel_content.core`): the Anthropic client + cost accounting, the
  bundle lint / quality rubric gates, the `[[FIGURE]]`/`[[IMAGE]]` marker passes, the
  `cp-component` embed pass (rendered via **keel-ui**), the internal/external link
  passes, the bespoke hero-SVG builder, and the glossary-gap analysis.
- **Five intake routes** → one unified queue: top-pages, keyword-clustering, ideation,
  YouTube-transcript, and crawl-map, plus a Twitter/X funnel (`TwitterSource` +
  `TweetCandidate`, the only models this package owns) and a glossary-term queue.
  Four of the five propose *articles*; **crawl-map** (`keel_content.crawlmap`) is the
  one that proposes a *site architecture* — see below.
- **The crawl-map route** (`keel_content.crawlmap`): reads a competitor crawl and
  derives the page types a site should have — directories, comparisons, calculators,
  glossaries, country/regulation pages, landings — not only its blog. It is fully
  deterministic (no model calls) and emits a tiered map so planning stages read a small
  overview plus the one cluster they need, instead of the whole corpus.
- **The boilerplate detector** (`keel_content.core.boilerplate`): finds the components a
  page corpus publishes more than once — a paragraph, a section heading or a rendered
  figure that is byte-identical across N pages. Repeated *structure* (anchors, column
  headers, block types) is the contract that makes a section comparable and is never
  reported; repeated *substance* is what makes a section read as generated, and is.
  Business-blind, Django-free and stdlib-only: the caller extracts the text and hands
  it a fingerprint per figure, and owns the thresholds, because "too many" is an
  editorial judgement that differs per section.
- **The generator + parsers** (`keel_content.tools`): the JS generation/brief/reconcile
  workflows and the worklist parsers.
- **Subject-driven card and hero art** (`keel_content.heroart`): a second, newer image
  engine that builds a listing cover and an article hero from *what the article
  compares* — the column of its own comparison table that carries names. Deterministic,
  balanced across the whole corpus including the order the feed paginates in, and gated
  by a layout audit that reads the SVG it produced rather than the code that produced
  it. Django-free. See [`HEROART.md`](HEROART.md). It does not replace
  `core.hero` (five brand styles over six abstract motifs, chosen from a topic, which is
  what SignalBots ships) — pick one per project rather than mixing them.
- **The standalone images pass** (`images.workflow.js` + `export_pending_visuals` /
  `apply_post_images`): the bespoke hero and the in-article NB2 photoreal images are
  produced AFTER `content_import`, not inside the generation run — they cost ~123
  minutes of per-article chain for output no other stage consumes. A freshly imported
  post lands `images_ready=False` and is **not publishable** until the pass flips it.
  See [`IMAGES-PASS.md`](IMAGES-PASS.md).
- **The glossary-term authoring pipeline** (author → validate → screenshot → vision-judge
  → persist), gated on a recorded pass verdict.
- **A default prompt set** (`keel_content/prompts_default/`) a host overrides per project.

## Consume it (host wiring)

1. `pip install keel-content` (or a git/editable install during development). It depends
   on `keel-ui` for the in-body component catalog.
2. Add `keel_content` to `INSTALLED_APPS`.
3. Provide a **publisher adapter** implementing `keel_content.core.publisher.ContentPublisher`
   (the only sanctioned seam that touches your CMS models) and point
   `KEEL_CONTENT["adapter"]` at it — the package ships no default adapter.
4. Provide your own `content-pipeline/` directory (copy `content-pipeline-template/` and
   fill it): `config.json`, your `prompts/` overrides, and your `EXTERNAL-DOMAINS` list.
   Point `CONTENT_PIPELINE_ROOT` at it (or place it next to `backend/`).
5. Configure via `KEEL_CONTENT` (all optional — see `keel_content/host.py` +
   `keel_content/config.py`).

## Config-contract / override seams (the rawification points)

Two settings surfaces, both optional; defaults target a conventional `blog`/`core`/`news`
host (SignalBots' current layout) so an existing host adopts with little config:

- **`keel_content.host`** — resolves the host's Django models and render callables from
  `KEEL_CONTENT` (e.g. `content_plan_model`, `post_model`, `tag_model`,
  `refresh_rendered_hook`, `prepare_storage_hook`, `market_hubs_hook`). A content-only
  host that provides no `market_hubs_hook` gets empty `bridge_candidates` and every
  brief's `business_bridge` degrades to `none`.
- **`keel_content.config`** — value-level config: `brand` tokens the hero/OG builders
  paint with (defaults are neutral — no wordmark, no logo mark, so the package carries no
  host identity) and `external_domains` (extra fast-lane hosts for the further-reading
  gate).
- **Swappable model targets** — `KEEL_CONTENT_CONTENT_PLAN_MODEL` /
  `KEEL_CONTENT_POST_MODEL` (default `blog.ContentPlan` / `blog.Post`) let a keel-cms host
  point the Twitter FKs at `keel_cms.*`.
- **The `ContentPublisher` adapter** — the one place your CMS models are touched. The
  package ships **no** concrete adapter (that would couple it to one host's models):
  set `KEEL_CONTENT["adapter"]` to your module. SignalBots' adapter, at
  `content_pipeline/keel_adapter.py` in its repo, is the reference implementation to copy.
- **The prompt set** — `prompts_default/` is a generic starting point; a host ships its
  own voice/rules in `content-pipeline/prompts/`.
- **AiSetting-shaped config** — the Anthropic + Gemini keys resolve from the host's
  `AiSetting` admin row when present, else from `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`
  env vars.

## Runtime requirements

- `yt-dlp` on `PATH` (the YouTube-transcript route shells out to it; no API key).
- `playwright` (optional extra `keel-content[raster]`) for HTML→PNG raster passes.
- `django-unfold` (optional extra `keel-content[admin]`) for the themed admin; the admin
  degrades to Django's stock admin without it.

## Status

v0.1.5 — extracted, neutralized, and consumed by SignalBots (its first host) through
its `content_pipeline.keel_adapter` host adapter: the intake routes, the generator, the
figures/hero/external-links stages, and glossary authoring are all in use. The package
ships no concrete adapter of its own — a host provides one and points
`KEEL_CONTENT["adapter"]` at it.

The generation workflow (`tools/*.workflow.js`) is the canonical orchestration; hosts
consume it from the package rather than forking it locally. As of v0.1.4 it carries:
an **editorial-quality gate** (an independent reader that judges prose flow/cohesion/
voice/seams after the intent gate and rewrites once on fail), the **intent gate ordered
before the relevance gate** (so links + visuals are judged against the final body), a
brief-stage **glossary_targets** selection and directed **link_plan** (designed internal
links), a **brief overlap precheck**, and a **shared visual-reconciliation** contract on
every body-revising stage. **v0.1.5** adds **per-stage model tiering** (every `agent()`
sets `model:` explicitly — Opus for substance authoring + the prose-quality editorial
gate, Sonnet for all judgement/verification/spec-driven visual stages, Haiku for the
script-runner) plus **deterministic overlap scoring** (`tools/overlap_score.py` computes
the Layer-4 pairwise audit with zero LLM tokens; only gray-band pairs get a Sonnet
confirm pass; the brief overlap precheck is likewise plain-JS with Sonnet only on the
gray band). `overlap_score.py` is invoked from the host repoRoot like `render_on_server.sh`
(a host copies it from the package template into its `tools/`). The default
`agent-author-brief.md` and `cluster-internal-links.md` prompts were re-verified against
this flow on 2026-08-18 (`intent-gate-rollout.md` P1.3): both now describe the brief-stage
`glossary_targets`/`link_plan` contract and the directed `anchor_concept` hand-off
accurately, so a host using the defaults gets the fully-designed glossary/link behavior,
not just a working pipeline.
