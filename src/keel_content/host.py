"""Host contract accessors — the one seam between keel-content and the host CMS.

keel-content is business-blind: its engine (``core/``) and management commands never
import the host project's Django models or render-layer modules directly. Every reach
into host data is routed through this module, which resolves host-provided models and
callables from the ``KEEL_CONTENT`` settings dict at call time.

Defaults target a conventional ``blog``-app host (SignalBots' current layout) so a host
that already looks like SignalBots needs no configuration; a keel-cms host overrides the
model paths to point at ``keel_cms.*``. Anything the host does not provide degrades to a
safe no-op (empty map, missing model raises only when actually used), never a hard import
error at module load — that is what keeps ``import keel_content`` model-free.

Configuration surface (all optional)::

    KEEL_CONTENT = {
        "content_plan_model": "blog.ContentPlan",     # swappable content queue model
        "cluster_job_model": "blog.KeywordClusterJob",  # swappable clustering queue model
        "post_model": "blog.Post",                    # swappable article model
        "tag_model": "blog.Tag",                      # swappable term/tag model
        "topic_cluster_model": "blog.TopicCluster",   # swappable cluster model
        "author_model": "blog.Author",                # swappable byline model
        "news_post_model": "news.NewsPost",           # swappable news article model
        "landing_model": "core.Landing",              # swappable landing-registry model
        "market_model": "blog.Market",                # swappable market model
        "refresh_rendered_hook": "blog.tasks.refresh_article_rendered",
        "prepare_storage_hook": "blog.markdown_convert.prepare_pipeline_content_for_storage",
        "markdown_html_hook": "blog.markdown_convert.markdown_to_blog_html",
        "featured_image_url_hook": "core.media_urls.featured_image_absolute_url",
        "glossary_category_order": "core.services.trading_glossary.CATEGORY_ORDER",
        "glossary_surface_labels": "core.services.trading_glossary.SURFACE_LABELS",
        "market_hubs_hook": "myapp.funnel.market_hubs",  # () -> {slug: [hub, ...]}
    }
"""

from __future__ import annotations

import os

from django.apps import apps as django_apps
from django.conf import settings
from django.utils.module_loading import import_string


def _cfg(key: str, default):
    return getattr(settings, "KEEL_CONTENT", {}).get(key, default)


def content_plan_model():
    return django_apps.get_model(_cfg("content_plan_model", "blog.ContentPlan"))


def cluster_job_model():
    """The keyword-clustering queue model, or ``None`` when the host has none.

    Unlike every other accessor here this one degrades to ``None`` instead of raising:
    the clustering queue is a newer capability than the rest of the pipeline, so a host
    pinned to an older CMS simply has no such model. Callers treat ``None`` as "this
    host does not run a clustering queue" and skip the stage rather than crashing the
    autopilot's decision pass, which must keep working for every other action.
    """
    label = _cfg("cluster_job_model", "blog.KeywordClusterJob")
    if not label:
        return None
    try:
        return django_apps.get_model(label)
    except (LookupError, ValueError):
        return None


def post_model():
    return django_apps.get_model(_cfg("post_model", "blog.Post"))


def tag_model():
    return django_apps.get_model(_cfg("tag_model", "blog.Tag"))


def topic_cluster_model():
    return django_apps.get_model(_cfg("topic_cluster_model", "blog.TopicCluster"))


def author_model():
    return django_apps.get_model(_cfg("author_model", "blog.Author"))


def news_post_model():
    return django_apps.get_model(_cfg("news_post_model", "news.NewsPost"))


def landing_model():
    return django_apps.get_model(_cfg("landing_model", "core.Landing"))


def market_model():
    return django_apps.get_model(_cfg("market_model", "blog.Market"))


def refresh_article_rendered(post) -> None:
    """Re-render a post's cached HTML after an out-of-band edit.

    Routed to the host's own re-render task; a host without one can point this at a
    no-op. Default targets ``blog.tasks.refresh_article_rendered``.
    """
    dotted = _cfg("refresh_rendered_hook", "blog.tasks.refresh_article_rendered")
    import_string(dotted)(post)


def prepare_pipeline_content_for_storage(markdown_source: str):
    """Canonicalize a post's Markdown body into the host's stored render form.

    Routed to the host's own storage-prep callable (the one ``publish_from_bundle``
    uses). Default targets ``blog.markdown_convert.prepare_pipeline_content_for_storage``.
    """
    dotted = _cfg(
        "prepare_storage_hook",
        "blog.markdown_convert.prepare_pipeline_content_for_storage",
    )
    return import_string(dotted)(markdown_source)


def markdown_to_blog_html(markdown_source: str):
    """Render a post's Markdown body to the host's blog HTML.

    Default targets ``blog.markdown_convert.markdown_to_blog_html``.
    """
    dotted = _cfg("markdown_html_hook", "blog.markdown_convert.markdown_to_blog_html")
    return import_string(dotted)(markdown_source)


def featured_image_absolute_url(*args, **kwargs):
    """Resolve a post's featured image to an absolute URL via the host's helper.

    Default targets ``core.media_urls.featured_image_absolute_url``.
    """
    dotted = _cfg("featured_image_url_hook", "core.media_urls.featured_image_absolute_url")
    return import_string(dotted)(*args, **kwargs)


def glossary_category_order():
    """The host's ordered glossary-category list (drives the term-authoring picker).

    Default imports ``core.services.trading_glossary.CATEGORY_ORDER``; a host without
    a glossary taxonomy degrades to an empty list (the authoring prompt just gets no
    category menu).
    """
    dotted = _cfg("glossary_category_order", "core.services.trading_glossary.CATEGORY_ORDER")
    try:
        return import_string(dotted) or []
    except Exception:
        return []


def glossary_surface_labels():
    """The host's ``{surface_url: label}`` map of glossary-linkable surfaces.

    Default imports ``core.services.trading_glossary.SURFACE_LABELS``; a host without
    a glossary surface map degrades to an empty dict.
    """
    dotted = _cfg("glossary_surface_labels", "core.services.trading_glossary.SURFACE_LABELS")
    try:
        return import_string(dotted) or {}
    except Exception:
        return {}


def resolved_image_ai_api_key() -> str:
    """The host's inline-image (Gemini) API key.

    DB value (the host's ``AiSetting`` admin form) wins over the env var, mirroring
    ``core/claude_client.py``'s resolution; a host without ``core.services.ai_settings``
    degrades to ``GEMINI_API_KEY`` from the environment. Resolved lazily so importing
    keel-content never touches the host's settings model.
    """
    try:
        from core.services.ai_settings import get_resolved_image_ai_api_key
        return get_resolved_image_ai_api_key() or ""
    except Exception:
        return os.environ.get("GEMINI_API_KEY", "").strip()


def gemini_image_generate_content_url_for_inline() -> str:
    """The host-resolved Gemini generateContent URL for inline image generation.

    Routed to ``core.services.ai_settings.resolve_gemini_image_generate_content_url_for_inline``;
    a host without it raises only when actually called (there is no safe generic
    default for the endpoint URL).
    """
    from core.services.ai_settings import resolve_gemini_image_generate_content_url_for_inline
    return resolve_gemini_image_generate_content_url_for_inline()


def gemini_image_request(*args, **kwargs):
    """Perform an inline Gemini image-generation HTTP request via the host's core.

    The Gemini image-gen HTTP core lives in the host (keel-web ships it); keel-content
    only orchestrates the NB2 raster around it. Routed via
    ``KEEL_CONTENT["gemini_image_request_hook"]`` (default
    ``admin_os.gemini_featured_image._gemini_image_request``). Raises only when called
    if the host provides no such core.
    """
    dotted = _cfg("gemini_image_request_hook", "admin_os.gemini_featured_image._gemini_image_request")
    return import_string(dotted)(*args, **kwargs)


def extract_first_image_bytes(*args, **kwargs):
    """Pull the first image payload out of a Gemini response, via the host's helper.

    Routed via ``KEEL_CONTENT["gemini_extract_bytes_hook"]`` (default
    ``admin_os.gemini_featured_image._extract_first_image_bytes``).
    """
    dotted = _cfg("gemini_extract_bytes_hook", "admin_os.gemini_featured_image._extract_first_image_bytes")
    return import_string(dotted)(*args, **kwargs)


def market_hubs() -> dict:
    """Return the host funnel-topology map used to compute a brief's bridge surfaces.

    Shape: ``{market_slug: [{"surface": "/url", "label": "...", "kind": "..."}, ...]}``.
    The engine only reads this map — it holds no opinion about which surfaces exist;
    a monetizing host supplies them, a content-only host returns ``{}`` and every
    brief's ``business_bridge`` degrades to ``none``. Configured via
    ``KEEL_CONTENT["market_hubs_hook"]`` (a dotted path to ``() -> dict``).
    """
    dotted = _cfg("market_hubs_hook", None)
    if not dotted:
        return {}
    try:
        return import_string(dotted)() or {}
    except Exception:
        return {}
