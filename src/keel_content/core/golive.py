"""Promote gate-checked, image-complete drafts to live — the publish autopilot.

The generation loop (``content_next_action``) deliberately stops at a noindex,
gate-checked draft; promoting a draft to PUBLISHED was left to a human. This module
is the other half a host can opt into: a scheduler that promotes ready drafts to
live on a daily quota, draining ONE cluster at a time so the site fills in coherent
topic clusters instead of scattered posts.

Like the rest of ``core/`` it is business-blind: it resolves the host's Post /
ContentPlan / TopicCluster models through :mod:`keel_content.host` and ranks with
the shared :mod:`keel_content.core.scope` policy, so publish order follows the SAME
rule the generation loop builds by — ``scope.cluster_priority``, scope relevance
and nothing else.

Readiness — a draft is publishable when it is::

    status == draft, not soft-deleted, images_ready, not needs_human_assets,
    pipeline-generated, no "blocked" visual marker, and its ContentPlan is not
    shelved (scope_relevance < ContentPlan.SCOPE_SHELF_FROM).

``images_ready`` is the hard gate: a False there means the hero is a generic
fallback and any in-article image is still a placeholder block, so the post is not
publishable no matter what else is true.

Order — the most ON-SCOPE cluster that still holds ready drafts wins, ranked by
``scope.cluster_priority`` (mean scope-relevance level, larger cluster breaking an
exact tie), and within it the highest ``ContentPlan.priority``. Draining the top
cluster fully before moving on is what makes "a day's posts come from one cluster,
spilling into the next only when the cluster runs short" fall out for free.

KEYWORD VOLUME AND COMPETITOR TRAFFIC PLAY NO PART (Milad, 2026-08-09, extended to
publishing 2026-08-14). Ranking here used to be
``sum(keyword_volume + competitor_traffic) x scope_weight`` and claimed in its own
docstring to mirror the generation brain — but the brain dropped both demand signals
on 2026-08-09 and this half was never changed, so for five days the two ends of the
pipeline built and published in genuinely different orders. Volume dominated the
product, so a high-volume L2 cluster outranked an L1 one and the most on-scope work
was produced first and published last. One rule, imported from one module, is the
only thing that keeps them from drifting again.

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

from keel_content.core.scope import cluster_priority
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


def _cluster_ranks(cluster_slugs) -> dict:
    """``scope.cluster_priority`` per cluster — SMALLER IS HIGHER PRIORITY.

    The identical call the generation brain makes, over the identical row set: the
    WHOLE cluster, not just the rows still to be published, so a cluster's rank does
    not drift as it drains. Shelved rows weigh nothing and ungraded rows count as
    L3, exactly as they do in production.
    """
    ContentPlan = content_plan_model()
    rows_by_cluster: dict[str, list] = {s: [] for s in cluster_slugs}
    rows = (
        ContentPlan.objects.filter(topic_cluster__slug__in=list(cluster_slugs))
        .select_related("topic_cluster")
        .only("scope_relevance", "topic_cluster__slug")
    )
    for row in rows:
        rows_by_cluster.setdefault(row.topic_cluster.slug, []).append(row)
    return {s: cluster_priority(rows_by_cluster.get(s, [])) for s in cluster_slugs}


def _by_priority(qs):
    """Highest ContentPlan.priority first, newest as the tiebreak."""
    return qs.order_by(F("content_plan__priority").desc(nulls_last=True), "-created_at")


def select_next_post():
    """The single highest-priority ready draft to publish next.

    Returns ``(post, cluster_slug, mean_scope_level)`` or ``(None, None, None)``
    when nothing is ready. Picks the most on-scope cluster that still has a ready
    draft, then that cluster's top-priority draft; clusterless drafts fall to the
    end, since a post with no cluster has no scope rank to compare.
    """
    Post = post_model()
    ready = ready_posts_qs(Post).select_related("content_plan", "topic_cluster")

    cluster_slugs = set(
        ready.exclude(topic_cluster__isnull=True).values_list("topic_cluster__slug", flat=True)
    )
    if cluster_slugs:
        ranks = _cluster_ranks(cluster_slugs)
        # min-first: cluster_priority returns (mean level, -row count) and smaller
        # means more on-scope. The slug is the last tiebreak so the order is total
        # and two ticks never disagree about what comes next.
        for slug in sorted(cluster_slugs, key=lambda s: (ranks[s], s)):
            post = _by_priority(ready.filter(topic_cluster__slug=slug)).first()
            if post is not None:
                return post, slug, round(ranks[slug][0], 2)

    orphan = _by_priority(ready.filter(topic_cluster__isnull=True)).first()
    if orphan is not None:
        return orphan, None, None
    return None, None, None


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
    """Promote one draft to live and stamp ``published_at`` if unset.

    On first publish, ``updated_at`` must land EXACTLY on ``published_at`` — the host
    shows ``updated_at`` as "Last Updated" and both dates go into the page's schema, so
    a go-live should not read as an edit that happened a moment later. ``save()``'s
    ``auto_now`` handling calls its own fresh ``timezone.now()`` regardless of what is
    assigned to the field, so it cannot be trusted to match ``published_at`` to the
    microsecond; force it back afterward with a plain ``update()`` (no signals, no
    second ``pre_save`` pass) rather than a second ``save()``.
    """
    now = now or timezone.now()
    Post = type(post)
    post.status = Post.Status.PUBLISHED
    fields = ["status"]
    first_publish = not post.published_at
    if first_publish:
        post.published_at = now
        fields.append("published_at")
    # updated_at is auto_now; include it so the sitemap lastmod moves.
    fields.append("updated_at")
    post.save(update_fields=fields)
    if first_publish:
        Post.objects.filter(pk=post.pk).update(updated_at=post.published_at)
        post.updated_at = post.published_at
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

    post, cluster_slug, mean_level = select_next_post()
    if post is None:
        result["reason"] = "no ready-to-publish drafts"
        result["ready_total"] = ready_posts_qs(Post).count()
        return result

    info = {
        "id": post.pk,
        "slug": post.slug,
        "title": post.title,
        "cluster": cluster_slug,
        "cluster_scope_level": mean_level,
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
