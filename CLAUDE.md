# keel-content — package guide

Part of the **Keel** platform (see keel-kit `PLATFORM.md`). This is a Bucket-2 reusable
Django app: the business-blind content-generation pipeline. English only; no banner
comments; block-form multi-line comments only; CSS variables only in any styling.

## Task tracking

Remaining and follow-up work for this project is tracked in [TODO.md](TODO.md), not in chat memory. Every pending task — priority, prerequisites/dependencies, enough context to resume cold — goes there before starting new work; remove a task from TODO.md the moment it's done.

## Boundaries — what is here vs what stays in the host

- **Here (generic engine):** `core/` (Anthropic client, gates, figure/hero/link passes,
  glossary-gap), the four intake routes, the Twitter funnel models, the generator +
  parsers under `tools/`, the glossary-term authoring commands, and a default prompt set.
- **Consumed from a sibling package:** the in-body visual catalog + renderer come from
  **keel-ui** (`from keel_ui import render, ...`). keel-content never vendors components.
- **Stays in the host (Bucket-0):** the `ContentPublisher` adapter implementation (the
  package ships `adapters/signalbots.py` only as a reference), the CMS models it writes,
  the monetization render layer (auto-linker, product showcase, asides — the pipeline is
  business-blind by design), the project `content-pipeline/` dir (prompts, config,
  external-domains list), and the brand identity (wordmark, logo mark, palette).

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
