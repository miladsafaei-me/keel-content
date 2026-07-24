"""Adapter resolution — the host's ``ContentPublisher`` + its companion functions.

The engine and management commands never import a concrete adapter module by name; they
resolve the configured one through ``get_adapter()``. keel-content ships **no** concrete
adapter — a concrete adapter imports the host's CMS models (``Post``/``NewsPost``/…) and
therefore belongs in the host project, not in this business-blind package. A host points
``KEEL_CONTENT["adapter"]`` at its own module, which must expose the companion callables
the commands use: ``publish_from_bundle``, ``upsert_content_plan_spec``,
``existing_glossary_terms``, ``internal_link_violations``, ``resolve_facet_rows``, …

SignalBots' adapter (the reference implementation) lives in its repo at
``content_pipeline/keel_adapter.py``; copy it as the starting point for a new host.
"""

from __future__ import annotations

import importlib


def get_adapter():
    """Import and return the host-configured adapter module.

    Raises ``ImproperlyConfigured`` when ``KEEL_CONTENT["adapter"]`` is unset — there is
    no default, because a default would hard-couple this neutral package to one host's
    CMS models.
    """
    from django.core.exceptions import ImproperlyConfigured

    try:
        from django.conf import settings

        dotted = getattr(settings, "KEEL_CONTENT", {}).get("adapter")
    except Exception:
        dotted = None

    if not dotted:
        raise ImproperlyConfigured(
            "keel-content needs a host adapter: set KEEL_CONTENT['adapter'] to a dotted "
            "path (e.g. 'content_pipeline.keel_adapter'). See keel_content.adapters."
        )
    return importlib.import_module(dotted)
