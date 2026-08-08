"""Promote gate-checked, image-complete drafts to live — the publish autopilot.

The generation loop (``content_next_action``) deliberately stops at a noindex,
gate-checked draft; promoting a draft to PUBLISHED was left to a human. This module
is the other half a host can opt into: a scheduler that promotes ready drafts to
live on a daily quota, draining ONE cluster at a time by demand so the site fills
in coherent topic clusters instead of scattered posts.

Like the rest of ``core/`` it is business-blind: it resolves the host's Post /
ContentPlan / TopicCluster models through :mod:`keel_content.host` and ranks with
the shared :mod:`keel_content.core.scope` policy, so publish order follows the SAME
``demand x scope_relevance`` formula the generation loop builds by.

Readiness — a draft is publishable when it is::

    status == draft, not soft-deleted, images_ready, not needs_human_assets,
    pipeline-generated, no "blocked" visual marker, and its ContentPlan is not
    shelved (scope_relevance < ContentPlan.SCOPE_SHELF_FROM).

``images_ready`` is the hard gate: a False there means the hero is a generic
fallback and any in-article image is still a placeholder block, so the post is not
publishable no matter what else is true.

Order — the highest-demand cluster that still holds ready drafts wins (the same
``sum(keyword_volume + competitor_traffic) x scope_weight`` per cluster used by the
generation brain), and within it the highest ``ContentPlan.priority``. Draining the
top cluster fully before moving on is what makes "a day's posts come from one
cluster, spilling into the next only when the cluster runs short" fall out for free.

Cadence — a daily quota ``Q`` spread across 24h: publish one when fewer than ``Q``
have gone out today AND at least ``24h / Q`` has passed since the last publish. The
count caps the day; the interval spaces the publishes. Both are derived from durable
state (``Post.published_at``), so an unattended timer can call :func:`run_tick` as
often as it likes and still land ~``Q`` evenly-spaced posts a day.

Publishing is nothing but ``status -> published`` + stamping ``published_at``; the
host's own ``post_save`` sync advances the linked ContentPlan, the (dynamic) sitemap
picks the post up on its next fetch, and — because a blog post's indexability is
derived from ``status`` — the page flips from noindex to indexable at the same time.
Telling Google about the new URL (Indexing API) is a host concern and lives in the
host's publish task, not here (core/ never imports the SEO client).
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from keel_content.core.scope import scope_weight
from keel_content.core.visual_queue import BLOCKED_KEY
from keel_content.host import content_plan_model, post_model

# Posts/day target when the host does not override it. The interval between
# publishes is 24h / quota (6 -> every 4h).
DEFAULT_QUOTA = 6

# A tick that runs slightly before an interval boundary should still fire, so the
# cadence does not drift later by one beat period every slot.
DEFAULT_GRACE_MINUTES = 10


def _shelf_from() -> int:
    """Lowest shelved scope-relevance level (rows >= this never publish)."""
    return int(getattr(content_plan_model(), "SCOPE_SHELF_FROM", 4))


def ready_posts_qs(Post=None):
    """Drafts that are fully machine-finished and eligible to go live."""
    Post = Post or post_model()
    return (
        Post.objects.filter(
            status=Post.Status.DRAFT,
            is_deleted=False,
            images_ready=True,
            needs_human_assets=False,
            is_pipeline_generated=True,
        )
        .exclude(pending_visuals__has_key=BLOCKED_KEY)
        .exclude(content_plan__scope_relevance__gte=_shelf_from())
    )


def _cluster_demand(cluster_slugs) -> dict:
    """``sum((keyword_volume + competitor_traffic) x scope_weight)`` per cluster.

    Mirrors ``content_next_action``'s in-loop scorer exactly (both demand signals
    summed, scope-weighted), so publish order matches production order.
    """
    ContentPlan = content_plan_model()
    totals: dict[str, float] = {}
    rows = (
        ContentPlan.objects.filter(topic_cluster__slug__in=list(cluster_slugs))
        .select_related("topic_cluster")
        .only("keyword_volume", "competitor_traffic", "scope_relevance", "topic_cluster__slug")
    )
    for row in rows:
        slug = row.topic_cluster.slug
        raw = (row.keyword_volume or 0) + (row.competitor_traffic or 0)
        totals[slug] = totals.get(slug, 0.0) + raw * scope_weight(row.scope_relevance)
    return totals


def _by_priority(qs):
    """Highest ContentPlan.priority first, newest as the tiebreak."""
    return qs.order_by(F("content_plan__priority").desc(nulls_last=True), "-created_at")


def select_next_post():
    """The single highest-priority ready draft to publish next.

    Returns ``(post, cluster_slug, cluster_demand)`` or ``(None, None, 0.0)`` when
    nothing is ready. Picks the top-demand cluster that still has a ready draft,
    then that cluster's top-priority draft; clusterless drafts fall to the end.
    """
    Post = post_model()
    ready = ready_posts_qs(Post).select_related("content_plan", "topic_cluster")

    cluster_slugs = set(
        ready.exclude(topic_cluster__isnull=True).values_list("topic_cluster__slug", flat=True)
    )
    if cluster_slugs:
        demand = _cluster_demand(cluster_slugs)
        for slug in sorted(cluster_slugs, key=lambda s: demand.get(s, 0.0), reverse=True):
            post = _by_priority(ready.filter(topic_cluster__slug=slug)).first()
            if post is not None:
                return post, slug, demand.get(slug, 0.0)

    orphan = _by_priority(ready.filter(topic_cluster__isnull=True)).first()
    if orphan is not None:
        return orphan, None, 0.0
    return None, None, 0.0


def published_today_count(Post, now) -> int:
    """Posts that went live today (local calendar day) — counts manual publishes too."""
    local_today = timezone.localtime(now).date()
    return Post.objects.filter(
        status=Post.Status.PUBLISHED, published_at__date=local_today
    ).count()


def last_published_at(Post):
    """The most recent ``published_at`` across all live posts (spacing anchor)."""
    return (
        Post.objects.filter(status=Post.Status.PUBLISHED, published_at__isnull=False)
        .order_by("-published_at")
        .values_list("published_at", flat=True)
        .first()
    )


def slot_due(Post, quota, now, grace_minutes=DEFAULT_GRACE_MINUTES):
    """Is a publish slot due right now? Returns ``(bool, reason)``."""
    if quota <= 0:
        return False, "quota is 0"
    today = published_today_count(Post, now)
    if today >= quota:
        return False, f"daily quota met ({today}/{quota})"
    interval = timedelta(hours=24.0 / quota)
    last = last_published_at(Post)
    if last is not None:
        elapsed = now - last
        if elapsed < interval - timedelta(minutes=grace_minutes):
            mins = int(elapsed.total_seconds() // 60)
            return False, f"too soon ({mins}m since last publish, interval {interval})"
    return True, f"slot due ({today}/{quota} today)"


def publish_post(post, now=None):
    """Promote one draft to live and stamp ``published_at`` if unset."""
    now = now or timezone.now()
    Post = type(post)
    post.status = Post.Status.PUBLISHED
    fields = ["status"]
    if not post.published_at:
        post.published_at = now
        fields.append("published_at")
    # updated_at is auto_now; include it so the sitemap lastmod moves.
    fields.append("updated_at")
    post.save(update_fields=fields)
    return post


def run_tick(quota=DEFAULT_QUOTA, now=None, dry_run=False, force=False, grace_minutes=DEFAULT_GRACE_MINUTES):
    """Publish at most one ready draft if a quota slot is due. Returns a result dict.

    ``force`` ignores the quota/interval gate (still publishes at most one).
    ``dry_run`` reports the post it would publish without changing anything.
    """
    now = now or timezone.now()
    Post = post_model()
    result = {
        "action": "skipped",
        "quota": quota,
        "published_today": published_today_count(Post, now),
    }

    if not force:
        due, reason = slot_due(Post, quota, now, grace_minutes=grace_minutes)
        if not due:
            result["reason"] = reason
            return result

    post, cluster_slug, demand = select_next_post()
    if post is None:
        result["reason"] = "no ready-to-publish drafts"
        result["ready_total"] = ready_posts_qs(Post).count()
        return result

    info = {
        "id": post.pk,
        "slug": post.slug,
        "title": post.title,
        "cluster": cluster_slug,
        "cluster_demand": round(demand),
    }
    if dry_run:
        result["action"] = "would_publish"
        result["post"] = info
        result["reason"] = "dry-run"
        return result

    publish_post(post, now)
    result["action"] = "published"
    result["post"] = info
    result["published_today"] = published_today_count(Post, now)
    result["reason"] = f"published from cluster {cluster_slug!r}"
    return result
