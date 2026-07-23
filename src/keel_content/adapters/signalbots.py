"""Signalbots-specific publisher adapter.

This is the only place in content_pipeline that imports Django models. The core/
package stays project-agnostic; swapping this file for another adapter (e.g.
``adapters/revenika.py``) is what lets the pipeline target a different host.

Reads ``meta.json`` + ``final.md`` from the article directory and creates a
``blog.Post`` or ``news.NewsPost`` in DRAFT status with ``is_pipeline_generated=True``,
so the render task skips the nh3 sanitize pass and AI-emitted visual blocks
(Mermaid, Chart.js, custom HTML) are preserved.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils.text import slugify

from blog.markdown_convert import prepare_pipeline_content_for_storage
from blog.models import (
    AudienceLevel,
    AudienceRole,
    Author,
    Category,
    ContentPlan,
    Market,
    Post,
    Tag,
    TopicCluster,
)
from blog.tasks import refresh_article_rendered
from news.models import NewsPost

from blog.editorial_desks import BOARD, desk_slug_for_market

from ..core import paths
from ..core.asset_requests import apply_asset_requests
from ..core.components_embed import apply_components
from ..core.external_links import apply_external_sources
from ..core.figures import apply_figures
from ..core.images import apply_images
from ..core.internal_links import apply_internal_links
from ..core.types import PublishPayload
from ..core.video_embeds import apply_video_embeds

logger = logging.getLogger(__name__)

# Max glossary terms surfaced as a generated post's tag chips (see _apply_facets).
_PIPELINE_TAG_LIMIT = 6


def _resolve_author(slug: str | None, *, role: str = "author") -> Author | None:
    if not slug:
        return None
    try:
        return Author.objects.get(slug=slug)
    except Author.DoesNotExist:
        raise RuntimeError(
            f"{role.capitalize()} with slug={slug!r} not found. "
            "Create it in /admin-os/cms/ or fix the slug in backend/blog/editorial_desks.py."
        )


def _key_takeaways_html(markdown_src: str) -> str:
    """The Post model stores key takeaways as sanitized HTML (display-side).

    For consistency with admin-edited posts we **do** sanitize this small block —
    it never contains visual widgets, just bullet text.
    """
    if not markdown_src.strip():
        return ""
    from blog.markdown_convert import markdown_to_blog_html
    return markdown_to_blog_html(markdown_src)


def _read_meta_and_body(content_id: str) -> tuple[dict[str, Any], str]:
    art = paths.article_dir(content_id)
    meta = json.loads((art / "meta.json").read_text(encoding="utf-8"))
    final_md = (art / "final.md").read_text(encoding="utf-8")
    if not final_md.strip():
        raise RuntimeError(f"final.md is empty for {content_id}; run the pipeline first.")
    return meta, final_md


def _admin_url_for_post(instance: Post | NewsPost) -> str:
    app_label = instance._meta.app_label
    model_name = instance._meta.model_name
    try:
        path = reverse(f"admin:{app_label}_{model_name}_change", args=[instance.pk])
    except Exception:
        return ""
    base = getattr(settings, "ADMIN_PUBLIC_URL", "") or ""
    return f"{base.rstrip('/')}{path}" if base else path


def _persist(payload: PublishPayload) -> tuple[Post | NewsPost, bool]:
    author = _resolve_author(payload.author_slug, role="author")
    reviewer = _resolve_author(payload.reviewer_slug, role="reviewer")
    if author is None:
        raise RuntimeError(
            "No author resolved. The byline is the post's primary-market Editorial "
            "Desk — check facets.markets and backend/blog/editorial_desks.py."
        )
    content_raw = prepare_pipeline_content_for_storage(payload.final_markdown)
    if payload.target == "news":
        return _upsert_news(payload, content_raw, author, reviewer)
    return _upsert_post(payload, content_raw, author, reviewer)


def _render_and_url(instance: Post | NewsPost, created: bool, target: str) -> str:
    refresh_article_rendered(instance)
    logger.info(
        "keel_content.publish target=%s slug=%s status=%s created=%s",
        target, instance.slug, instance.status, created,
    )
    return _admin_url_for_post(instance)


@transaction.atomic
def publish(payload: PublishPayload) -> str:
    """Persist the post from a direct ``payload``; return the admin change URL.

    This path does NOT set facets — see :func:`publish_from_bundle` for the
    facet-aware path used by ``content_import``.
    """
    instance, created = _persist(payload)
    return _render_and_url(instance, created, payload.target)


def _common_fields(payload: PublishPayload, content_raw: str, author: Author, reviewer: Author | None) -> dict[str, Any]:
    return {
        "title": payload.title,
        "h1": payload.h1,
        "excerpt": payload.excerpt,
        "key_takeaways_markdown_source": payload.key_takeaways_markdown,
        "key_takeaways": _key_takeaways_html(payload.key_takeaways_markdown),
        "content_markdown_source": payload.final_markdown,
        "content_raw": content_raw,
        "featured_image_url": payload.featured_image_url or "",  # og:image source; blank = template default.
        "status": payload.initial_status,
        "is_pipeline_generated": True,
        "author": author,
        "reviewer": reviewer,
        "meta_title": (payload.meta_title or "")[:65],
        "meta_description": (payload.meta_description or "")[:160],
    }


def _upsert_post(payload: PublishPayload, content_raw: str, author: Author, reviewer: Author | None) -> tuple[Post, bool]:
    fields = _common_fields(payload, content_raw, author, reviewer)
    obj = Post.all_objects.filter(slug=payload.slug).first()
    if obj is None:
        obj = Post(slug=payload.slug, **fields)
        obj.save()
        return obj, True
    for k, v in fields.items():
        setattr(obj, k, v)
    obj.save()
    return obj, False


def _upsert_news(payload: PublishPayload, content_raw: str, author: Author, reviewer: Author | None) -> tuple[NewsPost, bool]:
    fields = _common_fields(payload, content_raw, author, reviewer)
    # NewsPost has neither a reviewer nor an h1 field; drop them and use the model's manager.
    fields.pop("reviewer", None)
    fields.pop("h1", None)
    obj = NewsPost._default_manager.filter(slug=payload.slug).first()
    if obj is None:
        obj = NewsPost(slug=payload.slug, **fields)
        obj.save()
        return obj, True
    for k, v in fields.items():
        setattr(obj, k, v)
    obj.save()
    return obj, False


def _resolve_one(model, value: str | None, *, label: str):
    """Resolve an existing facet row by name (case-insensitive) or slug; warn + skip if absent."""
    value = (value or "").strip()
    if not value:
        return None
    obj = (
        model.objects.filter(name__iexact=value).first()
        or model.objects.filter(slug=slugify(value)).first()
    )
    if obj is None:
        logger.warning("keel_content.facets: %s %r not found; skipped", label, value)
    return obj


def _resolve_many(model, values, *, label: str) -> list:
    return [o for o in (_resolve_one(model, v, label=label) for v in (values or [])) if o is not None]


# Scaffold/worklist market names that don't match a canonical blog.Market row 1:1.
# Maps the stale/variant name → the canonical Market name to resolve against.
_MARKET_SYNONYMS = {
    "stocks & indices": "Stocks",
    "stocks and indices": "Stocks",
    "equities": "Stocks",
    # Pre-rename / variant names → the aligned canonical Market names (migration 0048).
    "gold & metals": "Gold & Silver",
    "gold and metals": "Gold & Silver",
    "metals": "Gold & Silver",
    "gold": "Gold & Silver",
    "futures & commodities": "Futures",
    "futures and commodities": "Futures",
    "commodities": "Futures",
    "crude oil": "WTI Brent",
    "crude": "WTI Brent",
    "oil": "WTI Brent",
    "wti": "WTI Brent",
    "brent": "WTI Brent",
}
# General fallback market when a post resolves to NO market (never leave a post
# market-less — see content_pipeline market handling). "Cross-market" is the
# canonical general bucket.
_FALLBACK_MARKET_NAME = "Cross-market"


def _resolve_markets(values) -> list:
    """Resolve market facet names with synonym mapping + a general fallback.

    A name that doesn't match a Market row is retried through ``_MARKET_SYNONYMS``;
    if the whole list still resolves to nothing, the post is assigned the general
    ``Cross-market`` bucket so it is never left without a market facet.
    """
    out = _resolve_many(Market, values, label="market")
    if out:
        return out
    mapped = [_MARKET_SYNONYMS.get((v or "").strip().lower()) for v in (values or [])]
    out = _resolve_many(Market, [m for m in mapped if m], label="market")
    if out:
        return out
    fallback = Market.objects.filter(name__iexact=_FALLBACK_MARKET_NAME).first()
    if fallback:
        logger.warning(
            "keel_content.facets: markets %r resolved to none; falling back to %r",
            values, _FALLBACK_MARKET_NAME,
        )
        return [fallback]
    return []


def _resolve_glossary_terms(values) -> list[Tag]:
    """Resolve facet term names to existing glossary terms (never creates) — see Tag.resolve_existing_terms."""
    return Tag.resolve_existing_terms(values)


def existing_glossary_terms() -> list[dict[str, Any]]:
    """Return every existing trading-glossary term as a plain dict.

    Project-specific DB read consumed by ``core.glossary_gap`` so the gap analysis
    never suggests a term the glossary already defines. Each row carries its
    canonical ``name`` plus the ``abbreviation`` and ``aka`` aliases the analyzer
    should also treat as "already covered". Returns ``[]`` if the table can't be read.
    """
    out: list[dict[str, Any]] = []
    for row in Tag.objects.filter(is_term=True).values("name", "abbreviation", "aka"):
        aka = row.get("aka") or []
        out.append({
            "name": row["name"],
            "abbreviation": (row.get("abbreviation") or "").strip(),
            "aka": [a for a in aka if isinstance(a, str)] if isinstance(aka, list) else [],
        })
    return out


def resolve_facet_rows(facets: dict[str, Any]) -> dict[str, Any]:
    """Resolve scaffold facet NAMES to live DB rows — the shared resolver.

    Used by the bundle publisher (:func:`_apply_facets`) and the ``ContentPlan``
    ingest command so a worklist's facet names map to the same rows whichever path
    consumes them. ``categories`` / ``markets`` / ``audience_*`` / glossary terms
    resolve to EXISTING rows (an unresolved name is logged + skipped, never fatal);
    ``topic_cluster`` is get-or-created — it carries no public URL, so minting one is
    SEO-safe. Performs no writes other than that get-or-create.
    """
    facets = facets or {}
    cluster = None
    # Slug-first: a spec that names an EXISTING TopicCluster by slug always joins
    # that cluster — the content spine is route-independent, so a keyword-route
    # spoke lands in the same cluster a top-pages run built (never a near-duplicate
    # minted from a slightly different name). Name get-or-create is the fallback.
    cluster_slug = (facets.get("topic_cluster_slug") or "").strip().lower()
    if cluster_slug:
        cluster = TopicCluster.objects.filter(slug=cluster_slug).first()
        if cluster is None:
            logger.warning(
                "keel_content.facets: topic_cluster_slug %r not found; falling "
                "back to name resolution", cluster_slug,
            )
    cluster_name = (facets.get("topic_cluster") or "").strip()
    if cluster is None and cluster_name:
        cluster, _created = TopicCluster.objects.get_or_create(
            slug=slugify(cluster_name)[:200], defaults={"name": cluster_name}
        )
    return {
        "categories": _resolve_many(Category, facets.get("categories"), label="category"),
        "markets": _resolve_markets(facets.get("markets")),
        "audience_roles": _resolve_many(AudienceRole, facets.get("audience_roles"), label="audience_role"),
        "audience_levels": _resolve_many(AudienceLevel, facets.get("audience_levels"), label="audience_level"),
        "glossary_terms": _resolve_glossary_terms(facets.get("glossary_terms")),
        "topic_cluster": cluster,
    }


def unresolved_required_facets(facets: dict | None) -> list[str]:
    """Strict pre-import check: errors for facet NAMES that fail to resolve to a
    controlled-vocabulary DB row.

    ``content_import`` HARD-blocks a bundle that returns any error here, instead of
    letting ``_apply_facets`` silently drop the typo'd name — a draft missing its
    category / market / audience facet is unsearchable on that facet and gets the
    wrong byline (see the cluster-quality backlog). Categories + audience levels/roles
    are a fixed seeded vocabulary, so a miss is always a bug. Markets are checked
    per supplied name (a name resolving to neither a row nor a synonym is a typo); an
    EMPTY markets list is fine — the publisher falls back to the general bucket.
    ``topic_cluster`` (get-or-created) and glossary terms (resolve-only by design)
    are intentionally NOT hard-checked here.
    """
    facets = facets or {}
    errors: list[str] = []

    def _exists(model, value: str) -> bool:
        return bool(
            model.objects.filter(name__iexact=value).first()
            or model.objects.filter(slug=slugify(value)).first()
        )

    for label, model, key in (
        ("category", Category, "categories"),
        ("audience_role", AudienceRole, "audience_roles"),
        ("audience_level", AudienceLevel, "audience_levels"),
    ):
        for v in facets.get(key) or []:
            v0 = (v or "").strip()
            if v0 and not _exists(model, v0):
                errors.append(f"{label} {v0!r} not found in the controlled vocabulary")

    for v in facets.get("markets") or []:
        v0 = (v or "").strip()
        if not v0:
            continue
        syn = _MARKET_SYNONYMS.get(v0.lower())
        if not _exists(Market, v0) and not (syn and _exists(Market, syn)):
            errors.append(f"market {v0!r} not found (no row and no synonym match)")

    return errors


# Author-written internal links (markdown, not image syntax). Image embeds and
# /media//static asset paths are exempt — the allowlist governs page links only.
_INTERNAL_MD_LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\((/[^)\s]+)\)")
_SKIP_LINK_PREFIXES = ("/media/", "/static/")
# Compliance-mandated target: always linkable even if its Landing row ever flips,
# so the risk-warning rule can never dead-lock an import.
_ALWAYS_ALLOWED_PATHS = {"/risk-warning"}


def internal_link_violations(bundle: dict | None) -> list[str]:
    """Strict pre-import check on the author-written internal links in the body.

    Enforces the author brief's linking contract at the one place that has the live
    registry: body links may target ONLY indexable pages (``core.Landing`` rows with
    ``is_indexable=True`` — the same set handed to agents as ``INDEXABLE_URLS``),
    never another blog post (blog→blog edges arrive via the cluster-linking pass in
    ``internal_links``, not the body), with no trailing slash and at most one link
    per distinct target. ``content_import`` HARD-blocks a bundle that returns any
    error here — linking indexable content to a noindex page wastes crawl/link
    equity, and a guessed ``/blog/`` slug is broken by construction.
    """
    body = (bundle or {}).get("body_markdown") or ""
    if not body:
        return []
    hits = _INTERNAL_MD_LINK_RE.findall(body)
    if not hits:
        return []
    from core.models import Landing  # local: keep the blog-focused import block clean

    allowed = {
        (u or "").split("#")[0].split("?")[0].rstrip("/") or "/"
        for u in Landing.objects.filter(is_indexable=True).values_list("url", flat=True)
    }
    allowed |= {p.rstrip("/") for p in _ALWAYS_ALLOWED_PATHS}

    errors: list[str] = []
    seen: dict[str, int] = {}
    for raw in hits:
        path = raw.split("#")[0].split("?")[0]
        if not path or path.startswith(_SKIP_LINK_PREFIXES):
            continue
        if path == "/blog" or path.startswith("/blog/"):
            errors.append(
                f"author-written blog link {raw!r} — blog→blog links are wired by the "
                "cluster-linking pass, never hand-written in the body"
            )
            continue
        if len(path) > 1 and path.endswith("/"):
            errors.append(
                f"internal link {raw!r} has a trailing slash (canonical routes are slash-less)"
            )
        norm = path.rstrip("/") or "/"
        seen[norm] = seen.get(norm, 0) + 1
        if norm not in allowed:
            errors.append(
                f"internal link {raw!r} is not in the live indexable allowlist "
                "(Landing.is_indexable=True) — link an allowlisted page or drop the link"
            )
    for norm, n in sorted(seen.items()):
        if n > 1:
            errors.append(
                f"internal target {norm!r} linked {n} times (one link per distinct target)"
            )
    return errors


def _apply_facets(post: Post, facets: dict[str, Any]) -> None:
    """Resolve top-pages facet NAMES to DB rows and wire them onto the post.

    Non-fatal: an unresolved facet name is logged and skipped (a typo never blocks
    a draft). ``categories`` / ``markets`` / ``audience_*`` / glossary ``related_terms``
    link to existing rows; ``topic_cluster`` is get-or-created (it carries no public
    URL, so creating one is SEO-safe).
    """
    if not facets:
        return
    rows = resolve_facet_rows(facets)
    categories = rows["categories"]
    markets = rows["markets"]
    roles = rows["audience_roles"]
    levels = rows["audience_levels"]
    terms = rows["glossary_terms"]

    if categories:
        post.categories.set(categories)
        post.category = categories[0]  # primary topic FK = first ticked
    if markets:
        post.markets.set(markets)
    if roles:
        post.audience_roles.set(roles)
    if levels:
        post.audience_levels.set(levels)
    if terms:
        post.related_terms.set(terms)
        # Blog tags are drawn from the glossary vocabulary: tag the post with the first
        # few glossary terms it links to. Resolve-only (terms already exist) — generation
        # never mints a new Tag row.
        post.tags.set(terms[:_PIPELINE_TAG_LIMIT])

    cluster = rows["topic_cluster"]
    if cluster:
        # classify the cluster itself with the same facets (add, never clobber)
        cluster.categories.add(*categories)
        cluster.markets.add(*markets)
        cluster.audience_roles.add(*roles)
        cluster.audience_levels.add(*levels)
        post.topic_cluster = cluster
        if (facets.get("role") or "").lower() == "pillar" and cluster.pillar_id is None:
            cluster.pillar = post
            cluster.save(update_fields=["pillar"])

    post.save(update_fields=["category", "topic_cluster"])


def _sync_content_plan(post: Post) -> None:
    """Link the produced Post back to its ContentPlan row and advance the queue.

    Closes the production loop: the plan row whose slug matches the post points at
    the Post and moves to ``published`` (if the post is live) or ``drafted``. The
    roadmap therefore always reflects what has been produced. Best-effort — a post
    that was never planned (e.g. a hand-run bundle) simply has no row, which is fine
    and never fails the import.
    """
    from blog.models import ContentPlan

    try:
        plan = ContentPlan.objects.filter(slug=post.slug).first()
        if plan is None:
            return
        plan.produced_post = post
        plan.status = (
            ContentPlan.Status.PUBLISHED
            if post.status == Post.Status.PUBLISHED
            else ContentPlan.Status.DRAFTED
        )
        plan.save(update_fields=["produced_post", "status", "updated_at"])
        # YouTube-transcript route: mirror the source video onto the produced Post
        # so the blog can link to / embed the original (the transcript stays on the
        # plan row only). Never clobber a URL a human already set on the post.
        if plan.youtube_url and not post.youtube_url:
            post.youtube_url = plan.youtube_url
            post.save(update_fields=["youtube_url", "updated_at"])
    except Exception:  # noqa: BLE001 -- plan sync is best-effort, never blocks ingest
        logger.exception("content_pipeline: ContentPlan sync failed for slug=%s", post.slug)


def _pos_int_or_none(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _pos_float_or_none(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


# Plan statuses that are already in production — never silently reset by a re-ingest.
_PLAN_PRODUCTION_LOCKED = (
    ContentPlan.Status.GENERATING,
    ContentPlan.Status.DRAFTED,
    ContentPlan.Status.PUBLISHED,
)


def upsert_content_plan_spec(
    spec: dict[str, Any], *, source_type: str, source_ref: str = "", replace: bool = False
) -> tuple[ContentPlan | None, str]:
    """Upsert one worklist spec into a ContentPlan row — the shared ingest core.

    Used by every path that deposits into the roadmap (``contentplan_ingest`` for
    top-pages/keyword worklists, ``contentplan_add_ideation`` for landing-support
    ideas) so the spec -> row mapping lives in exactly one place. Facet NAMES/slugs
    resolve via :func:`resolve_facet_rows`. Returns ``(plan, outcome)`` where outcome
    is ``created`` / ``updated`` / ``locked`` / ``skipped`` / ``skipped-type``. A row
    already in production is left untouched unless ``replace``; only ``blog`` / ``news``
    targets are accepted (other content types are landing work, not blog roadmap rows).
    """
    slug = (spec.get("slug") or slugify(spec.get("title") or "")).strip()
    if not slug:
        return None, "skipped"
    target = (spec.get("content_type") or spec.get("target") or "blog").strip().lower()
    if target not in (ContentPlan.Target.BLOG.value, ContentPlan.Target.NEWS.value):
        return None, "skipped-type"

    plan = ContentPlan.objects.filter(slug=slug).first()
    if plan and plan.status in _PLAN_PRODUCTION_LOCKED and not replace:
        return plan, "locked"

    is_new = plan is None
    if is_new:
        plan = ContentPlan(slug=slug, source_type=source_type)

    owner = spec.get("canonical_owner")
    plan.title = (spec.get("title") or "").strip() or slug
    plan.h1 = spec.get("h1") or ""
    plan.intent = spec.get("intent") or ""
    plan.role = (spec.get("role") or "").strip().lower()
    plan.target = target
    plan.intent_frame = spec.get("intent_frame") or ""
    plan.entity = (spec.get("entity") or "")[:160]
    plan.observed_intent = spec.get("observed_intent") or ""
    plan.scope_includes = list(spec.get("scope_includes") or [])
    plan.scope_excludes = list(spec.get("scope_excludes") or [])
    plan.canonical_owner = owner if isinstance(owner, dict) else {}
    # Only overwrite when the incoming spec actually carries a key. Table-sourced
    # worklists (top-pages, clustering) always ship an empty ``canonical_key``, so an
    # unconditional assignment would wipe a reconcile decision on re-ingest of an
    # already-reconciled row and silently reopen the cannibalization gate.
    incoming_key = (spec.get("canonical_key") or "").strip()
    if incoming_key:
        plan.canonical_key = incoming_key
    plan.competitor_traffic = _pos_int_or_none(spec.get("traffic"))
    plan.competitor_urls = list(spec.get("competitor_urls") or [])
    plan.keyword_volume = _pos_int_or_none(spec.get("keyword_volume"))
    # Keyword evidence is ingest-owned; ``brief`` / ``feasibility`` are NOT touched
    # here — the brief stage (contentplan_set_brief) owns them, and a re-ingest must
    # never wipe a written brief.
    incoming_keywords = spec.get("keywords")
    if incoming_keywords:
        plan.keywords = [
            kw for kw in incoming_keywords
            if isinstance(kw, dict) and str(kw.get("keyword", "")).strip()
        ]
    plan.priority = _pos_float_or_none(spec.get("priority"))
    plan.clarity = _pos_int_or_none(spec.get("clarity"))
    plan.source_type = source_type
    if source_ref:
        plan.source_ref = source_ref[:500]
    # YouTube-transcript route: only overwrite when the incoming spec carries them,
    # so re-ingesting the same row from another path never wipes the source video
    # or its transcript (mirrors the canonical_key / keywords guard above).
    incoming_youtube_url = (spec.get("youtube_url") or "").strip()
    if incoming_youtube_url:
        plan.youtube_url = incoming_youtube_url[:500]
    incoming_transcript = spec.get("source_transcript")
    if incoming_transcript:
        plan.source_transcript = incoming_transcript
    if is_new:
        plan.status = ContentPlan.Status.PLANNED

    rows = resolve_facet_rows(spec)
    plan.topic_cluster = rows["topic_cluster"]
    # One pillar per cluster, across ALL planning routes: if this spec claims the
    # pillar role but the cluster already has one (an earlier route built it), the
    # newcomer is a spoke of the existing hub — clusters strengthen over time, they
    # don't grow second heads.
    if plan.role == ContentPlan.Role.PILLAR and plan.topic_cluster is not None:
        existing_pillar = (
            ContentPlan.objects.filter(
                topic_cluster=plan.topic_cluster, role=ContentPlan.Role.PILLAR
            )
            .exclude(slug=plan.slug)
            .exclude(status__in=(ContentPlan.Status.MERGED, ContentPlan.Status.REJECTED))
            .first()
        )
        if existing_pillar is not None:
            logger.info(
                "keel_content.ingest: %s demoted to spoke — cluster %r already "
                "has pillar %s", plan.slug, plan.topic_cluster.name, existing_pillar.slug,
            )
            plan.role = ContentPlan.Role.SPOKE
    plan.save()
    # Categories are CLUSTER-DERIVED (the two-level tree: Category -> TopicCluster
    # -> content). The cluster's category set grows as the union of its members'
    # planned categories (first category bootstraps primary_category, the cluster's
    # home in the tree), and every member row then carries the cluster's set — so
    # a post can never claim a category its cluster doesn't have, and drift between
    # siblings is structurally impossible. Cluster-less rows keep their own.
    categories = rows["categories"]
    cluster = plan.topic_cluster
    if cluster is not None:
        if categories:
            cluster.categories.add(*categories)
            if cluster.primary_category_id is None:
                cluster.primary_category = categories[0]
                cluster.save(update_fields=["primary_category"])
        cluster_categories = list(cluster.categories.all())
        if cluster_categories:
            categories = cluster_categories
    plan.categories.set(categories)
    plan.markets.set(rows["markets"])
    plan.audience_roles.set(rows["audience_roles"])
    plan.audience_levels.set(rows["audience_levels"])
    plan.glossary_terms.set(rows["glossary_terms"])
    return plan, ("created" if is_new else "updated")


def _resolve_internal_links(raw_links) -> list[dict[str, str]]:
    """Map a bundle's ``internal_links`` plan to ``[{"anchor", "target_url"}]``.

    The cluster-linking pass writes edges as ``{"anchor", "target_slug"}`` (a slug of
    a sibling blog post in the same cluster). Each ``target_slug`` resolves to the
    canonical slash-less ``/blog/<slug>`` route via :func:`~django.urls.reverse`, so
    the inserted link is always canonical even if the target post is not published
    yet (the URL is built from the slug, not the row). A blank/unresolvable slug is
    dropped. A pre-resolved ``target_url`` is honored as-is.
    """
    out: list[dict[str, str]] = []
    for raw in raw_links or []:
        if not isinstance(raw, dict):
            continue
        anchor = (raw.get("anchor") or "").strip()
        url = (raw.get("target_url") or "").strip()
        slug = (raw.get("target_slug") or "").strip()
        if not url and slug:
            try:
                url = reverse("blog:post_detail", kwargs={"slug": slug})
            except Exception:
                logger.warning("keel_content.internal_links: unroutable slug %r; skipped", slug)
                continue
        if anchor and url:
            out.append({"anchor": anchor, "target_url": url})
    return out


def publish_from_bundle(
    bundle: dict[str, Any],
    report_sink: dict[str, Any] | None = None,
    *,
    verify_external: bool = True,
    bundle_dir: Any = None,
) -> str:
    """Publish one self-contained generation bundle (body + meta + facets) as a draft.

    The bundle is the portable unit emitted by the generation Workflow; this is the
    facet-aware entry point (unlike :func:`publish`). Idempotent by slug via upsert.

    Three deterministic body passes run here, *outside* the DB transaction (so neither
    network latency nor text rewriting holds a transaction open):

    1. ``external_sources`` are verified (authoritative-domain allowlist + live HTTP
       200) and rendered as an appended "Sources & Further Reading" list.
    2. ``internal_links`` — the within-cluster blog->blog edges chosen by the
       cluster-linking pass — are inserted inline as canonical ``/blog/<slug>``
       links (idempotent; never touches the AI-emitted visual/HTML blocks).
    3. ``cp-component`` placeholders — the in-body visuals the author emitted as
       data (component_id + spec) — are validated and rendered to HTML via the
       typed component library (``apply_components``), so every visual's markup
       comes from the single shared catalog, not hand-written per article.
    """
    body = bundle.get("body_markdown") or bundle.get("final_markdown") or ""
    if not body.strip():
        raise RuntimeError(f"bundle {bundle.get('slug')!r} has empty body_markdown")
    body, ext_report = apply_external_sources(
        body, bundle.get("external_sources"), verify=verify_external
    )
    body, int_report = apply_internal_links(body, _resolve_internal_links(bundle.get("internal_links")))
    body, comp_report = apply_components(body)
    # Figures pass: copy each drawn WebP into media and swap its [[FIGURE:<id>]]
    # marker for the final <figure> markup. Integrity is pre-checked at import
    # (figure_violations); this pass is defensive about anything that slipped by.
    body, fig_report = apply_figures(
        body, bundle.get("figures"), bundle_dir=bundle_dir, slug=bundle["slug"]
    )
    # Images pass: same shape as figures but for the ``image-nb2`` engine — copy each
    # photoreal WebP into media and swap its [[IMAGE:<id>]] marker. Integrity + the
    # NB2 word-budget are pre-checked at import (image_violations); defensive here.
    body, image_report = apply_images(
        body, bundle.get("images"), bundle_dir=bundle_dir, slug=bundle["slug"]
    )
    # Video pass runs BEFORE the asset pass: a video that fails oEmbed verification
    # is downgraded to an [[ASSET:...]] marker + synthetic request, which the asset
    # pass then renders as a placeholder (and the post gets flagged).
    body, video_fallbacks, video_report = apply_video_embeds(
        body, bundle.get("video_embeds"), verify=verify_external
    )
    body, asset_requests, asset_report = apply_asset_requests(
        body, list(bundle.get("asset_requests") or []) + video_fallbacks
    )
    if report_sink is not None:
        # Surface what each deterministic pass silently dropped (sources / links /
        # components) so content_import can report it — not just bury it in logs.
        report_sink["external"] = ext_report
        report_sink["internal"] = int_report
        report_sink["components"] = comp_report
        report_sink["figures"] = fig_report
        report_sink["images"] = image_report
        report_sink["video_embeds"] = video_report
        report_sink["asset_requests"] = asset_report
    return _persist_bundle(bundle, body, asset_requests=asset_requests)


@transaction.atomic
def _persist_bundle(
    bundle: dict[str, Any], body: str, asset_requests: list[dict[str, str]] | None = None
) -> str:
    """DB-write half of :func:`publish_from_bundle` (kept atomic, no network I/O)."""
    facets = bundle.get("facets") or {}
    # Byline: the post is authored by its primary-market Editorial Desk and
    # reviewed by the single Editorial Board. A bundle may override the desk
    # explicitly; the reviewer is always the Board.
    author_slug = bundle.get("author_slug") or desk_slug_for_market(facets.get("markets"))
    reviewer_slug = bundle.get("reviewer_slug") or BOARD["slug"]
    payload = PublishPayload(
        slug=bundle["slug"],
        title=bundle["title"],
        h1=bundle.get("h1", "") or "",
        meta_title=(bundle.get("meta_title") or bundle["title"]),
        meta_description=bundle.get("meta_description", "") or "",
        excerpt=bundle.get("excerpt", "") or "",
        key_takeaways_markdown=bundle.get("key_takeaways_markdown", "") or "",
        final_markdown=body,
        target=bundle.get("target", "blog"),
        author_slug=author_slug,
        reviewer_slug=reviewer_slug,
        initial_status=bundle.get("initial_status", "draft"),
        featured_image_url=bundle.get("featured_image_url", "") or "",
    )
    instance, created = _persist(payload)
    if payload.target != "news" and isinstance(instance, Post):
        # Human-asset flag: mirror the bundle's asset requests onto the Post so the
        # content team can filter for drafts awaiting a video/screenshot/data element.
        # NewsPost has no such fields — a news bundle carrying asset_requests is
        # logged and its markers were still replaced with visible placeholders.
        requests = asset_requests or []
        instance.asset_requests = requests
        instance.needs_human_assets = bool(requests)
        instance.save(update_fields=["asset_requests", "needs_human_assets"])
        _apply_facets(instance, facets)
        _sync_content_plan(instance)
    elif asset_requests:
        logger.warning(
            "content_pipeline: news bundle %s carries %d asset request(s) — "
            "NewsPost has no needs_human_assets flag; review the draft manually.",
            bundle.get("slug"), len(asset_requests),
        )
    return _render_and_url(instance, created, payload.target)
