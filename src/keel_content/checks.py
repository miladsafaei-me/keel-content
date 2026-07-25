"""System checks that fail loud when the host's CMS model wiring is broken.

keel-content resolves every host CMS model from the ``KEEL_CONTENT`` settings dict at
*runtime* (see ``keel_content.host``), defaulting each to the pre-Keel ``blog.*`` /
``news.*`` layout. If a host moves those models to another app (e.g. keel-cms) without
repointing the matching dict key, resolution silently falls back to a model that no
longer exists, and the pipeline crashes with ``LookupError`` only when a command is
actually run. That failure is invisible to ``makemigrations`` / ``migrate`` / the test
suite (none of which exercise the runtime resolution path), so it reaches production.

This check turns that latent runtime crash into a ``manage.py check`` failure — which
CI runs on every build — so a half-finished model move is caught before merge instead
of in a broken pipeline run.
"""
from __future__ import annotations

from django.core.checks import Error, register

# The host-model accessors keel-content depends on, each paired with the KEEL_CONTENT
# dict key a host overrides to repoint it. Kept in lock-step with keel_content.host.
_MODEL_KEYS = (
    "content_plan_model",
    "post_model",
    "tag_model",
    "topic_cluster_model",
    "author_model",
    "news_post_model",
    "landing_model",
    "market_model",
)


@register()
def check_host_models_resolve(app_configs, **kwargs):
    """Error if any host CMS model keel-content needs fails to resolve."""
    from django.conf import settings

    from . import host

    cfg = getattr(settings, "KEEL_CONTENT", {}) or {}
    errors = []
    for key in _MODEL_KEYS:
        try:
            getattr(host, key)()
        except Exception as exc:
            configured = cfg.get(key)
            source = (
                f'KEEL_CONTENT["{key}"] = {configured!r}'
                if configured is not None
                else f'the built-in default (no KEEL_CONTENT["{key}"] override)'
            )
            errors.append(
                Error(
                    f"keel-content cannot resolve its {key}: {source} did not "
                    f"resolve ({exc}).",
                    hint=(
                        f'Set KEEL_CONTENT["{key}"] in the host settings to the '
                        "app-qualified model backing the pipeline (e.g. "
                        "'keel_cms.<Model>' after a keel-cms model move)."
                    ),
                    id="keel_content.E001",
                )
            )
    return errors
