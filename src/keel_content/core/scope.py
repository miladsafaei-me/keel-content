"""Scope-relevance ranking policy for the content queue.

A row's demand contribution to its cluster is weighted by how tightly it sits in the
consumer's niche (``ContentPlan.scope_relevance``, 1..5). A whole cluster of L1 rows
therefore outranks an L3 cluster at equal raw demand — so the autopilot builds the
most on-scope clusters first. Shelved levels (>= ``ContentPlan.SCOPE_SHELF_FROM``)
weigh 0 (and are excluded from the queue upstream anyway); ungraded rows (NULL) are
mildly discounted so a known-core cluster beats an unknown one at equal demand.

Both the autopilot brain (``content_next_action``) and the claim/export path
(``export_worklist``) import this single policy, so screen and claim never diverge.
"""

from __future__ import annotations

from django.db.models import Case, FloatField, Value, When

# level -> demand weight. Keep >= SCOPE_SHELF_FROM at 0.0.
SCOPE_WEIGHTS = {1: 1.0, 2: 0.7, 3: 0.45, 4: 0.0, 5: 0.0}
UNGRADED_WEIGHT = 0.6


def scope_weight(level) -> float:
    """Demand weight for a scope-relevance level (Python side, for in-loop scoring)."""
    if level is None:
        return UNGRADED_WEIGHT
    try:
        return SCOPE_WEIGHTS.get(int(level), UNGRADED_WEIGHT)
    except (TypeError, ValueError):
        return UNGRADED_WEIGHT


def scope_weight_case(field: str = "scope_relevance") -> Case:
    """The same policy as a Case expression, for ORM aggregate weighting."""
    whens = [When(**{field: lvl}, then=Value(w)) for lvl, w in SCOPE_WEIGHTS.items()]
    return Case(*whens, default=Value(UNGRADED_WEIGHT), output_field=FloatField())


def cluster_priority(rows) -> tuple[float, int]:
    """Production-priority sort key for one cluster — SCOPE-RELEVANCE ONLY.

    Keyword volume and competitor traffic play NO part in what the content autopilot
    builds first (Milad, 2026-08-09): the only criterion is the cluster's scope
    relevance (the 3-question model, BUSINESS.md §2). ``rows`` is the cluster's
    producible ContentPlan rows; the returned key is ordered so **smaller is higher
    priority** — ``(mean scope level, -row count)``. The mean level counts a shelved
    row (scope_weight 0) not at all and an ungraded (NULL) row as 3; the larger
    on-scope cluster wins an exact tie. Pick the next cluster with ``min(..., key=)``.
    """
    levels = [
        3 if r.scope_relevance is None else int(r.scope_relevance)
        for r in rows
        if scope_weight(r.scope_relevance) > 0
    ]
    mean = (sum(levels) / len(levels)) if levels else 99.0
    return (mean, -len(levels))
