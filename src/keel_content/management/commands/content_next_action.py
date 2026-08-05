"""Decide the ONE next pipeline action from durable state — the autonomous loop's brain.

An unattended driver has no memory: it may be a fresh process minutes after a
5-hour token window slammed shut mid-cluster. It cannot rely on a workflow cache
(``resumeFromRunId`` is same-session only), so every decision has to be derivable
from the database, which already holds the whole picture:

* ``ContentPlan.status`` — planned (needs dedup) / reconciled (queued) /
  generating (claimed) / drafted (done)
* ``ContentPlan.brief`` — empty means the cluster has not been briefed yet
* ``feasibility`` — ``human_only`` rows never enter the generation queue
* ``Post.images_ready`` — false means the post is still owed its visuals

This command collapses that into exactly one instruction and prints it as JSON, so
a shell driver can branch on ``action`` without parsing prose.

    manage.py content_next_action
    {"action": "generate", "cluster": "...", "rows": 11, "reason": "..."}

ONE CLUSTER AT A TIME, ARTICLES THEN IMAGES (Milad, 2026-08-05). The loop walks a
cycle: produce the highest-demand cluster's articles, wire its internal links,
draw ITS images, and only then start the next cluster. Before this, images were
fallback work that ran when the article queue emptied — so drafts piled up
without visuals for days, and a draft without visuals cannot be published. The
cycle keeps finished clusters actually finishable, at the cost of nothing: the
same work happens, in an order that produces publishable clusters instead of a
growing backlog of half-finished ones.

Actions, in priority order:

``recover``   a cluster is claimed (``generating``) but nothing is running — a
              previous run died. Import whatever finished, release the rest.
``reconcile`` rows sit in ``planned``: they have not cleared the intent-dedup gate,
              and every action below reads ``reconciled``, so they are invisible
              to the loop until this runs.
``relink``    a cluster finished producing; wire its links across the whole set.
``brief``     the cluster in flight has article rows with no brief.
``generate``  the cluster in flight is fully briefed and ready to produce.
``images``    a produced cluster still has posts without their visuals. Scoped to
              ONE cluster, and it outranks starting a new one.
``idle``      nothing to do.

Cluster ranking: the cluster already in flight (it has produced posts and still
holds producible article rows) always wins — a cluster split across two runs
degrades exactly the pillar/spoke linking the topic architecture depends on.
Among clusters that have not started, the highest whole-cluster demand wins.

GLOSSARY IS NOT IN THE CHAIN (Milad, 2026-08-05). Term authoring left the
autopilot and became a human-triggered pass (``author_glossary_terms
--from-backlog``). It is still counted and reported in the idle reason so the
backlog stays visible, but the loop never schedules it.

It is READ-ONLY. It claims nothing, changes nothing, and is safe to call on a
timer as often as you like.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from keel_content.core import visual_queue
from keel_content.host import content_plan_model, post_model


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
        Post = post_model()

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

        # 2. RECONCILE — `planned` rows have not passed the intent-dedup gate, and
        #    NOTHING downstream can see them: every later action here reads
        #    `reconciled`, so a planned row is invisible to the loop and waits
        #    forever. Before this action existed, ingesting a batch and expecting
        #    the autopilot to produce it silently did nothing at all — the queue
        #    reported idle with a hundred rows sitting in it.
        #
        #    It goes AHEAD of the production actions on purpose: reconciled rows are
        #    the input to briefing, generation and the demand ranking, so deduping
        #    first is what lets a fresh batch compete for the next cluster instead of
        #    joining a run already half-produced. It stays BEHIND `recover`, which
        #    releases a dead run's claims and must always come first.
        #
        #    Every pending target counts, not just articles: the registry keys terms
        #    too, and an unkeyed term row is exactly what a duplicate what-is blog
        #    collides with. If a pass moves nothing, this response repeats verbatim
        #    and the driver's no-progress guard stops the loop after three ticks —
        #    which is the correct outcome for a reconcile that cannot converge.
        pending = ContentPlan.objects.filter(status="planned").count()
        if pending:
            return self._emit(
                action="reconcile",
                cluster=None,
                rows=pending,
                reason=(
                    f"{pending} row(s) sit in `planned` and have not cleared the "
                    "intent-dedup gate; nothing downstream can see them until they "
                    "are reconciled"
                ),
            )

        # Walk the blog rows once: which clusters still hold producible article rows,
        # and which have already produced posts. Both questions drive every step below.
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
        #
        #    It stays AHEAD of the images pass: relinking rewrites bodies, and doing it
        #    after the images landed would edit prose around freshly placed figures.
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

        # 3/4/5. Candidate clusters for article work.
        #
        # A CLUSTER ONLY COUNTS IF IT HAS A RECONCILED *ARTICLE* ROW. The brief and
        # generate actions both work the blog worklist (`export_worklist --target
        # blog`), so a cluster whose only leftovers are glossary-term rows has
        # nothing either action can produce. Ranking such a cluster first used to
        # send the loop into a trap: it would emit `generate`, the session would
        # export zero specs, the queue would not move, and three of those in a row
        # stop the autopilot.
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

        queued_terms = ContentPlan.objects.filter(
            status="reconciled", target="glossary_term"
        ).count()
        candidates = {k: v for k, v in candidates.items() if v["articles"]}

        # DEMAND IS SUMMED OVER THE WHOLE CLUSTER, NOT OVER ITS LEFTOVERS. Scoring
        # only the reconciled rows meant a cluster's rank FELL as it was produced,
        # so the loop could walk away from a half-produced cluster. A whole-cluster
        # score is stable.
        if candidates:
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

        # 3. FINISH THE CLUSTER IN FLIGHT. A cluster that has already produced posts
        #    and still holds producible article rows was interrupted mid-way — by a
        #    closed token window, by a batch limit, by a dead run. It wins outright,
        #    ahead of its own images and ahead of any fresh cluster, because the
        #    overlap audit and the cluster-internal-link pass run over whatever one
        #    batch contained: splitting a cluster costs exactly the linking quality
        #    the topic architecture depends on.
        in_flight = {s: v for s, v in candidates.items() if produced.get(s)}
        if in_flight:
            slug, info = max(in_flight.items(), key=lambda kv: kv[1]["demand"])
            return self._article_action(slug, info, in_flight=True)

        # 4. IMAGES FOR A PRODUCED CLUSTER — ahead of starting a new one.
        #    This is the second half of the cycle. Every clustered post that is still
        #    owed visuals is grouped by cluster, and one cluster is handed over per
        #    run. Posts whose visuals could not be produced carry a block marker and
        #    are not counted here, so one undrawable post can never stall the cycle.
        pending = visual_queue.pending_posts(Post).only("id")
        pending_ids = set(pending.values_list("id", flat=True))
        if pending_ids:
            by_post = visual_queue.cluster_by_post_id(ContentPlan)
            per_cluster: dict[str, int] = {}
            orphans = 0
            for pid in pending_ids:
                slug = by_post.get(pid)
                if slug:
                    per_cluster[slug] = per_cluster.get(slug, 0) + 1
                else:
                    orphans += 1
            if per_cluster:
                # Rank the same way article work is ranked, so the cycle stays in one
                # order: the cluster that mattered most is also imaged first.
                totals: dict[str, int] = {}
                for row in (
                    ContentPlan.objects.filter(topic_cluster__slug__in=list(per_cluster))
                    .select_related("topic_cluster")
                    .only("keyword_volume", "competitor_traffic", "topic_cluster__slug")
                ):
                    slug = row.topic_cluster.slug
                    totals[slug] = totals.get(slug, 0) + (row.keyword_volume or 0) + (
                        row.competitor_traffic or 0
                    )
                slug = max(per_cluster, key=lambda s: (totals.get(s, 0), per_cluster[s]))
                return self._emit(
                    action="images",
                    cluster=slug,
                    rows=per_cluster[slug],
                    demand=totals.get(slug, 0),
                    reason=(
                        f"cluster '{slug}' has {per_cluster[slug]} produced draft(s) still "
                        "without their visuals; its images come before any new cluster is "
                        "started"
                    ),
                )

        # 5. START THE NEXT CLUSTER — nothing in flight, no cluster owed images.
        if candidates:
            slug, info = max(candidates.items(), key=lambda kv: kv[1]["demand"])
            return self._article_action(slug, info, in_flight=False)

        # 6. ORPHAN IMAGES — posts that belong to no cluster (hand-written, imported
        #    from YouTube, produced before the registry). They are real pending work
        #    but they can never gate a cluster cycle, so they are swept up only once
        #    the clustered queue is empty.
        if pending_ids:
            return self._emit(
                action="images",
                rows=len(pending_ids),
                reason=(
                    f"{len(pending_ids)} draft(s) outside any topic cluster are still "
                    "without their visuals, and no cluster work is left"
                ),
            )

        stuck = visual_queue.blocked_posts(Post).count()
        return self._emit(
            action="idle",
            reason=(
                "nothing left to produce: no article rows, no pending visuals"
                + (f"; {queued_terms} glossary term(s) queued for the manual pass" if queued_terms else "")
                + (f"; {stuck} post(s) blocked on visuals awaiting a human" if stuck else "")
            ),
        )

    def _article_action(self, slug: str, info: dict, *, in_flight: bool):
        where = "already in flight" if in_flight else f"next by cluster demand ({info['demand']})"
        if info["unbriefed"]:
            return self._emit(
                action="brief",
                cluster=slug,
                rows=info["unbriefed"],
                demand=info["demand"],
                reason=(
                    f"cluster '{slug}' is {where} and has "
                    f"{info['unbriefed']} article row(s) with no brief"
                ),
            )
        return self._emit(
            action="generate",
            cluster=slug,
            rows=info["articles"],
            demand=info["demand"],
            reason=(
                f"cluster '{slug}' is {where}, fully briefed, "
                f"{info['articles']} article row(s) ready"
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
