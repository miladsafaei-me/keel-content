"""Crawl-map intake route: turn a competitor crawl into a site-architecture map.

The other intake routes answer *"which articles should we write"*. This one answers
*"what page types should this site have, and how should they be organised"* — so it
maps every page a competitor publishes (directories, comparisons, tools, glossaries,
country pages, landings), not only their blog.

The route runs in three deterministic stages, none of which calls a model:

1. **structure** (:mod:`keel_content.crawlmap.structure`) — recover Markdown with real
   headings, tables and lists from stored HTML, plus a compact per-page signal record.
2. **classify** — group pages into page types and clusters using a host-supplied
   vocabulary (the only business-aware input to the route).
3. **atlas** — emit the tiered map the planning stages read: a small always-loaded
   overview, per-cluster indexes, and per-page skeletons.

Stage 1 ships here; the remaining stages are additive and land behind the same package.
"""
from keel_content.crawlmap.structure import PageSignals, extract, parse_html

__all__ = ["PageSignals", "extract", "parse_html"]
