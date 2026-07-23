"""DB-backed queue of glossary terms the pipeline has suggested but not authored yet.

Since the unified-production-queue change (2026-07-16) the queue of record is
``blog.ContentPlan`` — each pending suggestion is a row with
``target=glossary_term``, living in the SAME clustered pool as the blog/news
roadmap, so ``export_worklist --next-cluster`` emits a cluster's queued terms
together with its articles (terms first, so resolve-only blog tags find them).
The git-tracked ``glossary-backlog.json`` file this module used to wrap is
retired; ``contentplan_ingest_terms`` ingests suggestion JSONs into the table.

Row mapping: ``slug=term-<slug>``, ``canonical_key=what-is-<slug>`` (the same key
the intent registry uses for glossary owners, so reconcile collisions keep
working), ``status=reconciled`` on create (a definitional need is pre-reconciled —
it IS a registry owner), and the suggestion payload (reason / example_sentence /
sources) rides the row's ``brief`` JSON. The row's ``topic_cluster`` is a
SCHEDULING AFFINITY — produce the term alongside the cluster that first demanded
it — never ontological membership: a live term serves every cluster through the
cross-cutting tag/link mesh.

Kept API-compatible with the file era: ``pending()`` / ``add()`` / ``remove()``
(+ ``clear()``), so the term-authoring commands keep working unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from django.utils.text import slugify

from . import term_match
from .types import ContentInput

logger = logging.getLogger(__name__)

_PENDING_STATUSES = ("planned", "reconciled", "generating")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _models():
    # Resolved through the host contract so importing this module never races
    # Django app loading and never hard-couples to a specific app label.
    from keel_content import host

    return host.content_plan_model(), host.tag_model(), host.topic_cluster_model()


def _pending_qs():
    ContentPlan, _Tag, _TC = _models()
    return (
        ContentPlan.objects.filter(
            target=ContentPlan.Target.GLOSSARY_TERM,
            produced_term__isnull=True,
            status__in=_PENDING_STATUSES,
        )
        .select_related("topic_cluster")
        .order_by("created_at")
    )


def _entry(plan) -> dict[str, Any]:
    payload = plan.brief if isinstance(plan.brief, dict) else {}
    return {
        "term": plan.title,
        "reason": payload.get("reason", "") or plan.observed_intent or "",
        "example_sentence": payload.get("example_sentence", ""),
        "sources": list(payload.get("sources", []) or []),
        "cluster": plan.topic_cluster.slug if plan.topic_cluster_id else "",
    }


def pending() -> list[dict[str, Any]]:
    """The queued (not yet authored) term suggestions, oldest first."""
    return [_entry(p) for p in _pending_qs()]


def _live_term_for(term: str):
    """The live Tag(is_term=True) matching ``term`` (slug or normalized tokens)."""
    _CP, Tag, _TC = _models()
    slug = slugify(term)
    hit = Tag.objects.filter(is_term=True, slug=slug).first()
    if hit is not None:
        return hit
    toks = term_match.tokens(term)
    if not toks:
        return None
    for tag in Tag.objects.filter(is_term=True).only("name", "slug"):
        if term_match.tokens(tag.name) == toks:
            return tag
    return None


def _pending_row_for(term: str):
    toks = term_match.tokens(term)
    if not toks:
        return None
    for plan in _pending_qs():
        if term_match.tokens(plan.title) == toks:
            return plan
    return None


def upsert(
    term: str,
    *,
    reason: str = "",
    example_sentence: str = "",
    sources: list[dict[str, Any]] | None = None,
    cluster_slug: str = "",
    source_type: str = "",
) -> tuple[Any, str]:
    """Upsert one term suggestion as a ContentPlan glossary_term row.

    Returns ``(plan_or_None, outcome)`` — outcome is ``created`` /
    ``updated`` (already queued: sources merged, cluster affinity filled) /
    ``skipped-live`` (the glossary already covers it) / ``skipped`` (unusable).
    """
    ContentPlan, _Tag, TopicCluster = _models()
    name = (term or "").strip()
    if not name or not term_match.tokens(name):
        return None, "skipped"
    if _live_term_for(name) is not None:
        return None, "skipped-live"

    cluster = None
    if cluster_slug:
        cluster = TopicCluster.objects.filter(slug=cluster_slug.strip().lower()).first()
        if cluster is None:
            logger.warning(
                "glossary_backlog: cluster slug %r not found; term %r queued without "
                "a scheduling affinity", cluster_slug, name,
            )

    existing = _pending_row_for(name)
    if existing is not None:
        payload = existing.brief if isinstance(existing.brief, dict) else {}
        merged = list(payload.get("sources", []) or [])
        seen_ids = {s.get("content_id") for s in merged if isinstance(s, dict)}
        for src in sources or []:
            if isinstance(src, dict) and src.get("content_id") not in seen_ids:
                merged.append(src)
                seen_ids.add(src.get("content_id"))
        payload["sources"] = merged
        payload.setdefault("reason", (reason or "").strip())
        payload.setdefault("example_sentence", (example_sentence or "").strip())
        existing.brief = payload
        if cluster is not None and existing.topic_cluster_id is None:
            existing.topic_cluster = cluster
        existing.save()
        return existing, "updated"

    slug = f"term-{slugify(name)}"[:255]
    plan = ContentPlan.objects.filter(slug=slug).first()
    if plan is not None and plan.target != ContentPlan.Target.GLOSSARY_TERM:
        logger.warning("glossary_backlog: slug %r already used by a %s row; skipped",
                       slug, plan.target)
        return None, "skipped"
    if plan is not None and plan.status not in _PENDING_STATUSES:
        # Already authored (drafted/published) or explicitly rejected by a human —
        # a fresh suggestion never silently re-queues it.
        return plan, "skipped-live"
    if plan is None:
        plan = ContentPlan(slug=slug)
    plan.target = ContentPlan.Target.GLOSSARY_TERM
    plan.title = name
    plan.h1 = name
    plan.intent = f"Understand what {name} means in trading"
    plan.intent_frame = "what-is"
    plan.entity = name[:160]
    plan.canonical_key = f"what-is-{slugify(name)}"[:255]
    plan.observed_intent = (reason or "").strip()
    plan.brief = {
        "reason": (reason or "").strip(),
        "example_sentence": (example_sentence or "").strip(),
        "sources": [s for s in (sources or []) if isinstance(s, dict)],
    }
    plan.status = ContentPlan.Status.RECONCILED
    plan.source_type = source_type or ContentPlan.Source.IDEATION
    if cluster is not None:
        plan.topic_cluster = cluster
    plan.save()
    return plan, "created"


def add(
    content_id: str, ci: ContentInput | None, suggestions: list[dict[str, Any]]
) -> tuple[int, int]:
    """Queue new suggestions (kept API-compatible with the file-backed era).

    Dedupes by normalized term against the live glossary AND the queued rows —
    an already-queued term only gains a new ``sources`` entry. Returns
    ``(newly_added, total_pending)``.
    """
    keyword = getattr(ci, "keyword", "") if ci else ""
    source = {"content_id": content_id, "keyword": keyword, "added_at": _today()}
    added = 0
    for s in suggestions or []:
        _plan, outcome = upsert(
            (s or {}).get("term", ""),
            reason=(s or {}).get("reason", ""),
            example_sentence=(s or {}).get("example_sentence", ""),
            sources=[source],
            cluster_slug=(s or {}).get("topic_cluster_slug", ""),
        )
        if outcome == "created":
            added += 1
    return added, _pending_qs().count()


def remove(term: str) -> bool:
    """Mark the queued row for ``term`` authored — it leaves the pending queue.

    Called by ``persist_glossary_terms`` right after it stages a term. The live
    ``Tag`` may not exist yet (the persist step ships a data migration), so the
    row flips to ``drafted`` now and ``contentplan_backfill`` links
    ``produced_term`` once the migration has run. Returns True when a queued row
    matched.
    """
    ContentPlan, _Tag, _TC = _models()
    plan = _pending_row_for(term)
    if plan is None:
        return False
    plan.produced_term = _live_term_for(term)
    plan.status = ContentPlan.Status.DRAFTED
    plan.save()
    return True


def clear() -> int:
    """Reject every pending suggestion (audit-trail stays). Returns the count."""
    ContentPlan, _Tag, _TC = _models()
    return ContentPlan.objects.filter(
        target=ContentPlan.Target.GLOSSARY_TERM,
        produced_term__isnull=True,
        status__in=_PENDING_STATUSES,
    ).update(status=ContentPlan.Status.REJECTED)
