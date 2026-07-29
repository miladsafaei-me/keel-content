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
``brief``     the next cluster by demand has article rows with no brief.
``generate``  the next cluster is fully briefed and ready to produce.
``idle``      nothing to do.

It is READ-ONLY. It claims nothing, changes nothing, and is safe to call on a
timer as often as you like. The IMAGES pass is deliberately absent — visuals are
triggered by a human, never by the loop.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from keel_content.host import content_plan_model


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

        # 2/3. The next cluster by aggregate demand, among rows that could actually
        #      produce: reconciled, not human-only. Mirrors export_worklist's ordering
        #      so the loop and a hand-run command never disagree about what is next.
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
                slug, {"demand": 0, "rows": 0, "unbriefed": 0, "terms": 0}
            )
            entry["demand"] += (row.keyword_volume or 0) + (row.competitor_traffic or 0)
            entry["rows"] += 1
            if row.target == "glossary_term":
                entry["terms"] += 1
            elif not row.brief:
                # Term rows are exempt from the brief gate; article rows are not.
                entry["unbriefed"] += 1

        if not candidates:
            return self._emit(
                action="idle", reason="no reconciled, machine-producible rows in the queue"
            )

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
            rows=info["rows"],
            demand=info["demand"],
            reason=(
                f"cluster '{slug}' is next by demand ({info['demand']}), fully briefed, "
                f"{info['rows']} row(s) ready ({info['terms']} glossary term(s))"
            ),
        )

    def _emit(self, **payload):
        self.stdout.write(json.dumps({k: v for k, v in payload.items() if v is not None}))
