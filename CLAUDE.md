# keel-content — package guide

Part of the **Keel** platform (see keel-kit `PLATFORM.md`). This is a Bucket-2 reusable
Django app: the business-blind content-generation pipeline. English only; no banner
comments; block-form multi-line comments only; CSS variables only in any styling.

## Task tracking

Remaining and follow-up work for this project is tracked in [TODO.md](TODO.md), not in chat memory. Every pending task — priority, prerequisites/dependencies, enough context to resume cold — goes there before starting new work; remove a task from TODO.md the moment it's done.

## Boundaries — what is here vs what stays in the host

- **Here (generic engine):** `core/` (Anthropic client, gates, figure/hero/link passes,
  glossary-gap), `heroart/` (the subject-driven card/hero renderer + its layout audit —
  Django-free, see [HEROART.md](HEROART.md)), the five intake routes, `crawlmap/` (the crawl-map route's structure
  recovery, classification and atlas builders), the Twitter funnel models, the generator +
  parsers under `tools/`, the glossary-term authoring commands, and a default prompt set.
- **Consumed from a sibling package:** the in-body visual catalog + renderer come from
  **keel-ui** (`from keel_ui import render, ...`). keel-content never vendors components.
- **Stays in the host (Bucket-0):** the `ContentPublisher` adapter implementation (the
  package ships `adapters/signalbots.py` only as a reference), the CMS models it writes,
  the monetization render layer (auto-linker, product showcase, asides — the pipeline is
  business-blind by design), the project `content-pipeline/` dir (prompts, config,
  external-domains list), and the brand identity (wordmark, logo mark, palette).

## The crawl-map route — the one route that designs structure, not articles

The other four intake routes all answer the same question in different ways: *which
article should we write next*. Their output is a worklist of blog/news rows, and
`contentplan_ingest` deliberately drops every other content type in a workbook.

The crawl-map route answers a different question: **what page types should this site
have at all, and how should they relate**. It reads a competitor crawl and reports the
full published surface — broker/product directories, head-to-head comparisons,
calculators and tools, glossaries, country and regulation pages, landings, hub pages —
because a site's architecture is decided by that whole surface, not by its blog. A
route that only ever proposed articles would silently reproduce a blog-shaped site.

Consequences that must not be "simplified" away later:

- Its output is a **page-type map plus a cluster graph**, not a ContentPlan worklist.
  Article rows are one *derived* slice of it; the landing/tool/directory rows are
  first-class output that flows to the host's landing pipeline, not to the blog queue.
- It is **deterministic** — structure recovery, classification and atlas assembly all
  run without a model call, so mapping a competitor costs no tokens.
- It is **tiered on purpose.** A competitor corpus is far too large to read; the atlas
  exists so a planning stage loads a small overview plus the single cluster it is
  working on. Anything that makes a stage read raw crawl pages defeats the route.
- The only business-aware input is a **host-supplied vocabulary** (what a "broker" or a
  "strategy" is for this project). It arrives through config, exactly like every other
  host reach — never hardcoded here.

Two traps this route already hit, both of which fail *silently* — the run reports
success and the corpus looks populated, so only a structure count reveals them:

- **An id/class chrome hint must never remove the dominant text block.** Themes name
  the wrapper that holds the article after the layout it participates in; a container
  classed `site with-custom-sidebar` matches a "sidebar" hint while carrying the whole
  page body. Dropping it turned 1,299-word pages into 70-word stubs. `_is_chrome_block`
  therefore keeps any block above `_CHROME_MAX_SHARE` of the page's text whatever its
  class says.
- **A poorer extraction must never overwrite a richer one.** A blocked or challenged
  refetch still returns HTML — just an empty shell — and a naive write lets that shell
  replace the good copy recovered from cache. Rank by (headings, words) and keep the
  best. Related: present a desktop browser identity when re-fetching, or these sites
  serve the shell in the first place.

## The one seam — the publisher protocol

`core/publisher.py` defines `ContentPublisher`. A host writes exactly one adapter
implementing it; that adapter is the *only* code allowed to import the host's CMS models.
Everything else in the engine reaches host data through `keel_content.host`.

## Override hooks (config-contract)

| Hook | Where | Default | Host provides |
|---|---|---|---|
| `KEEL_CONTENT["*_model"]` | `host.py` model accessors | `blog.*` / `core.Landing` / `news.NewsPost` | model label |
| `KEEL_CONTENT["refresh_rendered_hook"]` etc. | `host.py` callable accessors | `blog.markdown_convert.*` / `blog.tasks.*` / `core.media_urls.*` | dotted path |
| `KEEL_CONTENT["market_hubs_hook"]` | `host.market_hubs` | none → `{}` → `business_bridge: none` | `() -> {slug: [hub]}` |
| `KEEL_CONTENT["brand"]` | `config.brand` | neutral (no wordmark/mark) | colors + wordmark + logo mark |
| `KEEL_CONTENT["external_domains"]` | `config.external_domains` | `[]` (ships a finance default set) | extra fast-lane hosts |
| `KEEL_CONTENT_CONTENT_PLAN_MODEL` / `_POST_MODEL` | `models.py` swappable FKs | `blog.ContentPlan` / `blog.Post` | swappable target |
| `ContentPublisher` adapter | `core/publisher.py` | reference: `adapters/signalbots.py` | own implementation |
| prompt set | `content-pipeline/prompts/` (via `CONTENT_PIPELINE_ROOT`) | `prompts_default/` | project prompts |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | `core/claude_client.py`, `host.py` | env | key (or host `AiSetting` row) |

## Editing rule (drift prevention)

When a consuming project has this installed, its copy of these files is **not** editable
in that project — change them **here**, bump the version, and let the project pull the
new version. Project-specific behavior belongs in `KEEL_CONTENT` config, the publisher
adapter, or the project `content-pipeline/` dir — never in a fork of this code.

## Extraction notes (what was neutralized from SignalBots)

- `core/retrofit.py` + `core/glossary_backlog.py` no longer import `blog.models` at module
  scope — both route through `host.py`.
- `export_worklist._bridge_candidates` reads the host funnel map via `host.market_hubs()`
  instead of importing `blog.product_showcase._MARKET_HUBS`.
- The Twitter FKs (`content_plan`, `linked_post`) are swappable model references; migration
  history was reset to a single clean `0001_initial` (the SignalBots author-seed +
  hardcoded-watchlist seed migrations were dropped — a host seeds its own watchlist).
- Hero brand tokens (`core/hero/tokens.py`, `core/hero/chrome.py`) read from
  `KEEL_CONTENT["brand"]`; the SignalBots wordmark + logo polygons were removed.
- The management commands + Twitter package route all `blog`/`news`/`core` reaches through
  `host.py`; only the reference adapter keeps direct model imports.
