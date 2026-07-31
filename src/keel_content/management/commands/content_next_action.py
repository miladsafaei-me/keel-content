"""Decide the ONE next pipeline action from durable state — the autonomous loop's brain.

An unattended driver has no memory: it may be a fresh process minutes after a
5-hour token window slammed shut mid-cluster. It cannot rely on a workflow cache
(``resumeFromRunId`` is same-session only), so every decision has to be derivable
from the database, which already holds the whole picture:

* ``ContentPlan.status`` — reconciled (queued) / generating (claimed) / drafted (done)
* ``ContentPlan.brief`` — empty means the cluster has not been briefed yet
* ``feasibility`` — ``human_only`` rows never enter the generation queue

This command collapses that into exactly one instruction and prints it as JSON, so
a shell driver can branch on ``action`` without parsing prose.

    manage.py content_next_action
    {"action": "generate", "cluster": "...", "rows": 11, "reason": "..."}

Actions, in priority order:

``recover``   a cluster is claimed (``generating``) but nothing is running — a
              previous run died. Import whatever finished, release the rest.
``relink``    a cluster finished producing; wire its links across the whole set.
``brief``     the next cluster has article rows with no brief.
``generate``  the next cluster is fully briefed and ready to produce.
``glossary``  no article rows left, but glossary-term rows are queued.
``images``    no article or term rows left, but posts still need their visuals.
``idle``      nothing to do.

Cluster ranking: whole-cluster demand (every row, any status), among clusters that
still hold a reconciled ARTICLE row. Scoring only the leftovers made a cluster's
rank fall as it was produced, so a half-finished cluster lost its turn to a fresh
one; and a cluster whose only leftovers are glossary-term rows has nothing the blog
worklist can produce, so letting it rank first stalled the loop.

It is READ-ONLY. It claims nothing, changes nothing, and is safe to call on a
timer as often as you like. The IMAGES pass is deliberately absent — visuals are
triggered by a human, never by the loop.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from keel_content.host import content_plan_model, post_model, topic_cluster_model


class Command(BaseCommand):
    help = "Print the single next pipeline action as JSON (read-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--assume-idle-claim",
            action="store_true",
            help="treat a claimed cluster as a dead run needing recovery. The driver "
                 "passes this only when it holds the run lock, i.e. it has already "
                 "proven no generation is in flight.",
        )

    def handle(self, *args, **opts):
        ContentPlan = content_plan_model()

        # 1. RECOVER — rows stuck in `generating`. Only the driver can tell a dead run
        #    from a live one (it holds the lock), so this needs the explicit flag;
        #    without it a claimed cluster just means "busy, come back later".
        claimed = (
            ContentPlan.objects.filter(status="generating")
            .select_related("topic_cluster")
            .order_by("topic_cluster__slug")
        )
        if claimed.exists():
            slug = next(
                (r.topic_cluster.slug for r in claimed if r.topic_cluster_id), None
            )
            unproduced = claimed.filter(produced_post__isnull=True).count()
            if opts["assume_idle_claim"]:
                return self._emit(
                    action="recover",
                    cluster=slug,
                    rows=unproduced,
                    reason=(
                        f"cluster '{slug}' holds {claimed.count()} claimed row(s), "
                        f"{unproduced} without a produced post, and no run is live — "
                        "a previous run died mid-cluster"
                    ),
                )
            return self._emit(
                action="busy",
                cluster=slug,
                rows=claimed.count(),
                reason=f"cluster '{slug}' is claimed; a run may be in flight",
            )

        # 2. RELINK — a cluster that has just finished producing its articles.
        #    A cluster is only really finished when its blog->blog links are wired, and
        #    that pass runs over whatever a single generation batch contained. Since
        #    runs are now sized to the token window, a cluster is produced across
        #    several batches, so the in-batch pass can only ever link forward: articles
        #    written later see their already-produced siblings (spec.cluster_siblings),
        #    but the earlier ones were finalized and never link back. For a pillar
        #    produced first — the usual case — that is the wrong direction to lose.
        #    One whole-cluster pass afterwards repairs it, and this action schedules it.
        #
        #    Self-limiting by design: the marker in TopicCluster.brief records the
        #    article count it was computed at, so a finished cluster is scheduled once,
        #    and adding a later article to that cluster re-arms it exactly once more.
        TopicCluster = topic_cluster_model()
        blocked, produced, clusters = set(), {}, {}
        for row in (
            ContentPlan.objects.filter(target="blog")
            .exclude(feasibility="human_only")
            .select_related("topic_cluster")
        ):
            if not row.topic_cluster_id:
                continue
            slug = row.topic_cluster.slug
            clusters[slug] = row.topic_cluster
            if row.status in ("reconciled", "generating"):
                blocked.add(slug)
            if row.produced_post_id:
                produced[slug] = produced.get(slug, 0) + 1
        for slug, n in sorted(produced.items(), key=lambda kv: -kv[1]):
            if slug in blocked or n < 2:
                continue
            marker = (clusters[slug].brief or {}).get("relinked") or {}
            if marker.get("articles") == n:
                continue
            return self._emit(
                action="relink",
                cluster=slug,
                rows=n,
                reason=(
                    f"cluster '{slug}' has finished producing ({n} article(s), none left "
                    "in the queue) and its internal links have not been wired across the "
                    "whole cluster yet"
                ),
            )

        # 3/4. Pick the next cluster. Two rules, both learned the hard way.
        #
        # A CLUSTER ONLY COUNTS IF IT HAS A RECONCILED *ARTICLE* ROW. The brief and
        # generate actions both work the blog worklist (`export_worklist --target
        # blog`), so a cluster whose only leftovers are glossary-term rows has
        # nothing either action can produce. Ranking such a cluster first used to
        # send the loop into a trap: it would emit `generate`, the session would
        # export zero specs, the queue would not move, and three of those in a row
        # stop the autopilot. Term rows are still counted and reported, they just
        # cannot make a cluster "next" on their own.
        #
        # DEMAND IS SUMMED OVER THE WHOLE CLUSTER, NOT OVER ITS LEFTOVERS. Scoring
        # only the reconciled rows meant a cluster's rank FELL as it was produced:
        # `algorithmic-automated-trading-fundamentals` ranked first at 4054, then a
        # token block killed the run after 3 of 9 articles, and the remaining 6 --
        # already briefed -- scored 1056, below a fresh cluster at 2857. The loop
        # walked away from a half-produced cluster, which is the one thing it must
        # not do: the batch's overlap audit and cluster-internal-link pass run over
        # whatever the batch contained, so splitting a cluster across two runs
        # degrades exactly the pillar/spoke linking the topic architecture depends
        # on. A whole-cluster score is stable, so a started cluster stays on top
        # until it has no producible article rows left.
        candidates: dict[str, dict] = {}
        rows = (
            ContentPlan.objects.filter(status="reconciled")
            .exclude(feasibility="human_only")
            .select_related("topic_cluster")
        )
        for row in rows:
            if not row.topic_cluster_id:
                continue
            slug = row.topic_cluster.slug
            entry = candidates.setdefault(
                slug, {"demand": 0, "rows": 0, "unbriefed": 0, "terms": 0, "articles": 0}
            )
            entry["rows"] += 1
            if row.target == "glossary_term":
                entry["terms"] += 1
            else:
                entry["articles"] += 1
                if not row.brief:
                    # Term rows are exempt from the brief gate; article rows are not.
                    entry["unbriefed"] += 1

        stranded_terms = sum(
            e["terms"] for e in candidates.values() if not e["articles"]
        )
        candidates = {k: v for k, v in candidates.items() if v["articles"]}

        if not candidates:
            # 4/5. THE FALLBACK CHAIN (Milad, 2026-07-31). An open token window with an
            #      empty article queue used to mean `idle` — the window simply expired
            #      unused. Two real backlogs exist that no article action touches, so
            #      they absorb that capacity in his stated order: glossary terms first,
            #      then images. Both stay noindex-by-default, so this widens what the
            #      loop PRODUCES, never what it publishes.
            Post = post_model()
            terms = ContentPlan.objects.filter(
                status="reconciled", target="glossary_term"
            ).count()
            if terms:
                return self._emit(
                    action="glossary",
                    rows=terms,
                    reason=(
                        f"no article rows left to produce; {terms} glossary-term row(s) "
                        "are queued, and the term pass is the next-best use of an open "
                        "window"
                    ),
                )
            pending_visuals = Post.objects.filter(images_ready=False).count()
            if pending_visuals:
                return self._emit(
                    action="images",
                    rows=pending_visuals,
                    reason=(
                        f"no article or glossary rows left to produce; {pending_visuals} "
                        "post(s) still carry images_ready=False"
                    ),
                )
            return self._emit(
                action="idle",
                reason="nothing left to produce: no article rows, no glossary terms, no pending visuals",
            )

        # Whole-cluster demand: every row of the cluster in any status, so producing
        # part of it cannot change where it ranks.
        totals: dict[str, int] = {}
        for row in (
            ContentPlan.objects.filter(topic_cluster__slug__in=list(candidates))
            .select_related("topic_cluster")
            .only("keyword_volume", "competitor_traffic", "topic_cluster__slug")
        ):
            slug = row.topic_cluster.slug
            totals[slug] = totals.get(slug, 0) + (row.keyword_volume or 0) + (
                row.competitor_traffic or 0
            )
        for slug, entry in candidates.items():
            entry["demand"] = totals.get(slug, 0)

        slug, info = max(candidates.items(), key=lambda kv: kv[1]["demand"])

        if info["unbriefed"]:
            return self._emit(
                action="brief",
                cluster=slug,
                rows=info["unbriefed"],
                demand=info["demand"],
                reason=(
                    f"cluster '{slug}' is next by demand ({info['demand']}) and has "
                    f"{info['unbriefed']} article row(s) with no brief"
                ),
            )

        return self._emit(
            action="generate",
            cluster=slug,
            rows=info["articles"],
            demand=info["demand"],
            reason=(
                f"cluster '{slug}' is next by cluster demand ({info['demand']}), fully "
                f"briefed, {info['articles']} article row(s) ready"
                + (
                    f" ({info['terms']} glossary-term row(s) also pending, not produced "
                    "by this action)"
                    if info["terms"]
                    else ""
                )
            ),
        )

    def _emit(self, **payload):
        self.stdout.write(json.dumps({k: v for k, v in payload.items() if v is not None}))
