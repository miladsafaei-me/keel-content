"""The images queue: who is still waiting for visuals, and who has stopped waiting.

The images pass is a loop, not a one-shot. A post lands from generation with
``images_ready=False`` and its work order on ``pending_visuals``; the pass draws
the hero and the in-article images and flips the flag. Everything that reads or
writes that queue goes through here, so "still pending" means exactly one thing
in every command.

WHY A BLOCK MARKER EXISTS. Some posts cannot be finished by the machine, and the
queue had no way to say so. A body whose anchors lost their ``image_requests``,
a hero the vision judge rejects every time, a bundle that fails to render — each
one keeps answering "pending" forever, and an unattended loop that must clear the
queue before it starts the next cluster would sit on it until a human noticed. So
a post that has been attempted and did not finish carries a counter, and once it
has burned its attempts it is marked blocked and leaves the queue. Blocked is not
"broken": it is "a human decides what happens next", the same footing as
``needs_human_assets``. Both markers live on ``pending_visuals`` so no migration
is needed and the work order stays with them.

    {"image_requests": [...], "hero_needed": true,
     "visual_attempts": 2,
     "blocked": {"reason": "...", "attempts": 2, "at": "2026-08-05T09:00:00Z"}}
"""
from __future__ import annotations

from datetime import timezone as _timezone

from django.utils import timezone

BLOCKED_KEY = "blocked"
ATTEMPTS_KEY = "visual_attempts"

# How many times the pass may attempt one post before it leaves the queue. Two,
# because the first failure is very often a closed token window or a rejected
# render that the next run fixes, and the second is evidence of something the
# machine cannot draw.
DEFAULT_MAX_ATTEMPTS = 2


def pending_posts(Post, *, include_published: bool = False, include_blocked: bool = False):
    """Posts whose machine visuals are still owed.

    Mirrors ``export_pending_visuals``' own filters, so the count the driver acts
    on can never disagree with the set the exporter would actually write.
    """
    qs = Post.objects.filter(images_ready=False)
    if not include_published:
        qs = qs.exclude(status="published")
    if not include_blocked:
        qs = qs.exclude(pending_visuals__has_key=BLOCKED_KEY)
    return qs


def blocked_posts(Post):
    return Post.objects.filter(images_ready=False, pending_visuals__has_key=BLOCKED_KEY)


def cluster_by_post_id(ContentPlan) -> dict[int, str]:
    """post id -> topic-cluster slug, for the rows that produced a post."""
    return {
        row.produced_post_id: row.topic_cluster.slug
        for row in (
            ContentPlan.objects.filter(produced_post__isnull=False)
            .select_related("topic_cluster")
            .only("produced_post_id", "topic_cluster__slug")
        )
        if row.topic_cluster_id
    }


def post_ids_for_cluster(ContentPlan, slug: str) -> list[int]:
    return list(
        ContentPlan.objects.filter(
            topic_cluster__slug=slug, produced_post__isnull=False
        ).values_list("produced_post_id", flat=True)
    )


def _work_order(post) -> dict:
    order = post.pending_visuals
    return dict(order) if isinstance(order, dict) else {}


def attempts(post) -> int:
    try:
        return int(_work_order(post).get(ATTEMPTS_KEY) or 0)
    except (TypeError, ValueError):
        return 0


def record_attempt(post, *, save: bool = True) -> int:
    """Count one finished attempt against this post. Returns the new total."""
    order = _work_order(post)
    total = attempts(post) + 1
    order[ATTEMPTS_KEY] = total
    post.pending_visuals = order
    if save:
        post.save(update_fields=["pending_visuals"])
    return total


def block(post, *, reason: str, attempts_used: int | None = None, save: bool = True) -> None:
    order = _work_order(post)
    order[BLOCKED_KEY] = {
        "reason": reason,
        "attempts": attempts_used if attempts_used is not None else attempts(post),
        "at": timezone.now().astimezone(_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    post.pending_visuals = order
    if save:
        post.save(update_fields=["pending_visuals"])


def unblock(post, *, save: bool = True) -> bool:
    """Put a blocked post back in the queue with a fresh attempt budget."""
    order = _work_order(post)
    if BLOCKED_KEY not in order and ATTEMPTS_KEY not in order:
        return False
    order.pop(BLOCKED_KEY, None)
    order.pop(ATTEMPTS_KEY, None)
    post.pending_visuals = order
    if save:
        post.save(update_fields=["pending_visuals"])
    return True


def block_note(post) -> dict:
    note = _work_order(post).get(BLOCKED_KEY)
    return note if isinstance(note, dict) else {}
