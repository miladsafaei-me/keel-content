"""Adapter resolution — the host's ``ContentPublisher`` + its companion functions.

The engine and management commands never import a concrete adapter module by name; they
resolve the configured one through ``get_adapter()``. The default is the bundled
SignalBots reference adapter (``keel_content.adapters.signalbots``) — a working example a
host copies. A host points ``KEEL_CONTENT["adapter"]`` at its own module (which must
expose the same companion callables the commands use: ``publish_from_bundle``,
``upsert_content_plan_spec``, ``existing_glossary_terms``, ``internal_link_violations``,
``resolve_facet_rows``, ...).
"""

from __future__ import annotations

import importlib


def get_adapter():
    """Import and return the configured adapter module (default: the reference adapter)."""
    try:
        from django.conf import settings

        dotted = getattr(settings, "KEEL_CONTENT", {}).get("adapter", "keel_content.adapters.signalbots")
    except Exception:
        dotted = "keel_content.adapters.signalbots"
    return importlib.import_module(dotted)
