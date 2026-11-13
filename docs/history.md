# keel-content: extraction history

Moved verbatim out of `CLAUDE.md`. Migration narration from when the package was extracted from
SignalBots. Read only to understand why a host seam exists.

## Extraction notes (what was neutralized from SignalBots)

- `core/retrofit.py` + `core/glossary_backlog.py` no longer import `blog.models` at module
  scope - both route through `host.py`.
- `export_worklist._bridge_candidates` reads the host funnel map via `host.market_hubs()`
  instead of importing `blog.product_showcase._MARKET_HUBS`.
- The Twitter FKs (`content_plan`, `linked_post`) are swappable model references; migration
  history was reset to a single clean `0001_initial` (the SignalBots author-seed +
  hardcoded-watchlist seed migrations were dropped - a host seeds its own watchlist).
- Hero brand tokens (`core/hero/tokens.py`, `core/hero/chrome.py`) read from
  `KEEL_CONTENT["brand"]`; the SignalBots wordmark + logo polygons were removed.
- The management commands + Twitter package route all `blog`/`news`/`core` reaches through
  `host.py`; only the reference adapter keeps direct model imports.
