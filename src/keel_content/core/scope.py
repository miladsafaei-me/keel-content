"""Scope-relevance ranking policy for the content queue.

WHAT A COMPLETE CLUSTER IS (Milad, 2026-08-19). A topic cluster is complete when its
**L1-L3 rows** are produced, linked and published. L4/L5 rows are not late members of
the cluster and not debt — they are OUTSIDE it. They stay in the database, undeleted,
purely so a human can revisit the judgement in some later month or year; until then
every part of the pipeline ignores them completely.

The operative consequence is a hard rule: **nothing may block on, wait for, or be
counted from a shelved row.** Not cluster ranking, not the brief or generate gate,
not the relink marker, not the visuals queue, not the publish gate. A cluster whose
L1-L3 rows are done IS done, however many shelved rows sit beside it. Each of these
gates learned that separately and at least one of them cost real downtime, so a new
query over ContentPlan or Post is wrong by default until it excludes the shelf.


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


# Mean levels are compared in half-level buckets, not as raw floats. See
# ``cluster_priority`` — this is the width of "the same scope tier".
PRIORITY_BUCKET = 0.5


def cluster_priority(rows) -> tuple[float, int]:
    """Production-priority sort key for one cluster — SCOPE-RELEVANCE ONLY.

    Keyword volume and competitor traffic play NO part in what the content autopilot
    builds first (Milad, 2026-08-09): the only criterion is the cluster's scope
    relevance (the 3-question model, BUSINESS.md §2). ``rows`` is the cluster's
    producible ContentPlan rows; the returned key is ordered so **smaller is higher
    priority** — ``(mean scope level bucketed to PRIORITY_BUCKET, -row count)``. The
    mean counts a shelved row (scope_weight 0) not at all and an ungraded (NULL) row
    as 3. Pick the next cluster with ``min(..., key=)``.

    THE MEAN IS BUCKETED BECAUSE A RAW MEAN REWARDS FRAGMENTS (Milad, 2026-08-19).
    Shelved rows are dropped before the mean is taken, so shelving IMPROVES a
    cluster's rank: a cluster of 3 L1 rows and 40 shelved ones scores a perfect 1.00
    and outranked a 13-row cluster at 1.05, while delivering three articles. That is
    backwards for both halves of the pipeline — a topic cluster earns its internal
    links by being a complete hub-and-spoke set, and three articles do not make one.
    Comparing half-level buckets keeps scope strictly first (an L1 tier always beats
    an L2 tier) while letting the row count decide inside a tier, so the larger, more
    complete cluster is built and published first among equally on-scope work.
    """
    levels = [
        3 if r.scope_relevance is None else int(r.scope_relevance)
        for r in rows
        if scope_weight(r.scope_relevance) > 0
    ]
    if not levels:
        return (99.0, 0)
    mean = sum(levels) / len(levels)
    bucket = round(mean / PRIORITY_BUCKET) * PRIORITY_BUCKET
    return (bucket, -len(levels))
