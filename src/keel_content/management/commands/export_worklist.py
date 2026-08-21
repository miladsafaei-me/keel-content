"""``./manage.py export_worklist`` — project ContentPlan rows into a worklist.json.

This makes the ``blog.ContentPlan`` table — not a scattered workbook — the source the
generation Workflow reads. The emitted JSON has the exact shape
``tools/content_pipeline/parse_top_pages.py`` produces, so the pipeline (and
``content_status``) consume table-sourced and workbook-sourced worklists identically.

Default selection is ``reconciled`` rows only — the cannibalization gate is ON, so a
row must pass reconciliation (intent dedup + scope fences) before it can be generated.
Pass ``--status planned,reconciled`` to bypass the gate (rare). Filter by market /
cluster / target / source and cap with ``--limit``; rows come out highest-priority first.

The queue is UNIFIED across planning paths and content kinds (2026-07-16): a
cluster's blog/news rows from every source PLUS its queued glossary terms
(``target=glossary_term``) claim and export together — ``--next-cluster``/``--claim``
operate on the whole cluster, so one cluster never generates in two waves from two
"queues". ``--source`` is an optional filter (rarely needed — e.g. re-running one
path's stragglers), no longer required. Cluster order = aggregated demand: each
row's monthly-demand estimate is its keyword volume (keyword route) or competitor
traffic (top-pages route) — different estimators of the same quantity, summed per
cluster; ``--cluster <slug>`` remains the operator's manual override. Within a
cluster the export order is glossary terms -> pillar -> spokes (terms first, so
resolve-only blog tags and term links find their targets at import time).

Two generation gates apply on those commands: ``feasibility=human_only`` rows never
export (their brief is a human-writer handoff, not pipeline work), and
keyword-clustering article rows without a written ``brief`` are held back until the
brief stage has run (``--allow-unbriefed`` overrides; term rows need no brief).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import (
    Avg,
    Case,
    Count,
    F,
    FloatField,
    IntegerField,
    Q,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from keel_content.core.scope import PRIORITY_BUCKET
from keel_content import host
from keel_content.host import content_plan_model, market_hubs

# Command modules import only when a command runs (apps already populated), so
# resolving the swappable content-queue model at module load is safe here.
ContentPlan = content_plan_model()

# Cluster-level visual-variety nudge (computed BEFORE fan-out, where we can see the
# whole cluster — the blind per-article author cannot). Each row gets a LEAD visual
# archetype it must honor as its most-prominent visual, deriving the rest from intent;
# rotating the lead across a cluster's rows stops every article collapsing to the same
# visual rhythm (the "vibe template" Google reads as low-effort). Frame-aware so a
# comparison article never leads with a process flow; rotation within the frame's pool
# keeps siblings distinct. The author brief (§2.4) reads ``lead_visual_archetype``.
_FRAME_LEAD_POOLS = {
    "compare": ["comparison-table", "scenario-table", "decision-checklist", "annotated-chart"],
    "vs": ["comparison-table", "scenario-table", "decision-checklist", "annotated-chart"],
    "best": ["comparison-table", "decision-checklist", "annotated-chart", "scenario-table"],
    "review": ["annotated-chart", "comparison-table", "decision-checklist", "scenario-table"],
    "how-to": ["process-flow", "interactive-calculator", "checklist", "concept-diagram"],
    "guide": ["concept-diagram", "process-flow", "interactive-calculator", "scenario-table"],
    "what-is": ["concept-diagram", "annotated-chart", "interactive-simulator", "process-flow"],
}
_DEFAULT_LEAD_POOL = [
    "concept-diagram", "process-flow", "comparison-table",
    "annotated-chart", "interactive-calculator", "scenario-table",
]


def _lead_visual_archetype(intent_frame: str, position_in_cluster: int) -> str:
    pool = _FRAME_LEAD_POOLS.get((intent_frame or "").strip().lower(), _DEFAULT_LEAD_POOL)
    return pool[position_in_cluster % len(pool)]


def _bridge_candidates(plan) -> list[dict]:
    """Deterministic same-market surfaces the brief's ``business_bridge`` may
    pick from (BLOG.md "Business bridge"). The brief stage chooses among these
    — or declares ``none`` — and never invents a surface; keeping the
    monetization *decision* out of the model's free-generation space is what
    stops the author drifting into promotion. Market integrity is structural:
    only the row's own markets contribute surfaces.

    The surfaces come entirely from the host's funnel-topology map
    (``KEEL_CONTENT["market_hubs_hook"]`` → ``{market_slug: [hub, ...]}`` where each
    hub is ``{"surface": "/url", "label": "...", "kind": "..."}``). keel-content holds
    no opinion about which surfaces exist; a content-only host returns an empty map and
    every ``business_bridge`` degrades to ``none``.
    """
    hubs_map = market_hubs()

    out: list[dict] = []
    seen: set[str] = set()

    def add(surface, label, kind):
        if surface and surface not in seen:
            seen.add(surface)
            out.append({"surface": surface, "label": label, "kind": kind})

    cluster = plan.topic_cluster if plan.topic_cluster_id else None
    landing = getattr(cluster, "conversion_landing", None) if cluster else None
    if landing is not None:
        add(landing.url, landing.title, "conversion_landing")
    for m in plan.markets.all():
        for hub in hubs_map.get(m.slug, []):
            add(hub.get("surface"), hub.get("label"), hub.get("kind", "hub"))
    return out


class Command(BaseCommand):
    help = "Export ContentPlan rows as a pipeline worklist.json (table -> worklist)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--status",
            default="reconciled",
            help="Comma list of statuses to include (default: reconciled — the "
            "cannibalization gate; pass 'planned,reconciled' to bypass it).",
        )
        parser.add_argument(
            "--market", default="", help="Only rows tagged this market (name or slug)."
        )
        parser.add_argument(
            "--source",
            default="",
            choices=["", *(c for c, _ in ContentPlan.Source.choices)],
            help="Optional filter: only rows from this planning path. The queue is "
            "unified — cluster selection/claiming spans ALL sources by default.",
        )
        parser.add_argument(
            "--allow-unbriefed",
            action="store_true",
            help="Export keyword-clustering rows even when their brief is empty "
            "(default: held back until the brief stage has run).",
        )
        parser.add_argument(
            "--unkeyed",
            action="store_true",
            help="Only rows whose canonical_key is still empty. Reconcile-seed flow: "
            "export unkeyed PRODUCED rows (--status drafted,published --unkeyed) and "
            "merge them into the reconcile worklist so the normalizer keys them and "
            "the registry sees ALL produced content, not just pipeline-planned rows.",
        )
        parser.add_argument(
            "--cluster", default="", help="Only rows in this topic-cluster slug."
        )
        parser.add_argument(
            "--next-cluster",
            action="store_true",
            help="Auto-select the highest-priority cluster that still has unproduced "
            "rows (the next cluster to generate). Overrides --cluster / --market.",
        )
        parser.add_argument(
            "--claim",
            action="store_true",
            help="Atomically flip the selected cluster's queue rows (those matching "
            "--status, default 'reconciled') to 'generating' before emitting, so "
            "parallel sessions never pick the same cluster. Pass --status "
            "planned,reconciled to also claim planned rows. Requires --next-cluster "
            "or --cluster; incompatible with --limit.",
        )
        parser.add_argument(
            "--unclaim",
            action="store_true",
            help="Recovery: release a cluster claimed by a failed/abandoned generation "
            "run — flips its 'generating' rows (those without a produced post) back "
            "to 'reconciled' and exits without exporting. Requires --cluster.",
        )
        parser.add_argument(
            "--target",
            default="blog,glossary_term",
            help="Comma list of content targets: blog|news|glossary_term "
            "(default 'blog,glossary_term' — the unified editorial queue; ask for "
            "news explicitly).",
        )
        parser.add_argument(
            "--limit", type=int, default=0, help="Keep the N highest-priority rows."
        )
        parser.add_argument(
            "--out", default="", help="Write the worklist JSON here (default: stdout)."
        )

    def handle(self, *args, **opts):
        statuses = [s.strip() for s in opts["status"].split(",") if s.strip()]
        targets = [t.strip() for t in opts["target"].split(",") if t.strip()]
        valid_targets = {c for c, _ in ContentPlan.Target.choices}
        unknown = [t for t in targets if t not in valid_targets]
        if unknown:
            raise CommandError(f"unknown --target value(s): {', '.join(unknown)}")
        source = (opts["source"] or "").strip()
        if opts["unclaim"]:
            if not opts["cluster"]:
                raise CommandError("--unclaim requires --cluster <slug>.")
            released = ContentPlan.objects.filter(
                topic_cluster__slug=opts["cluster"].strip(),
                target__in=targets,
                status=ContentPlan.Status.GENERATING,
                produced_post__isnull=True,
                produced_term__isnull=True,
            ).update(status=ContentPlan.Status.RECONCILED)
            self.stderr.write(
                self.style.SUCCESS(
                    f"Released {released} row(s) of cluster {opts['cluster']!r} "
                    "back to 'reconciled'."
                )
            )
            return
        if opts["claim"]:
            if not (opts["next_cluster"] or opts["cluster"]):
                raise CommandError("--claim requires --next-cluster or --cluster.")
            # --limit with --claim is how a token-bounded batch works: claim exactly
            # the rows this run will produce. Without it the claim spans the whole
            # cluster, the run dies when the 5-hour window closes, and every leftover
            # row sits in `generating` until a recover tick releases it — measured
            # overnight as 26 of 149 agents killed mid-article, their tokens spent and
            # their output lost. Claiming the batch instead lets the window close
            # BETWEEN articles.
            slug, claimed_pks = self._select_and_claim(statuses, targets, opts)
            if slug is None:
                self.stderr.write(self.style.WARNING("Queue is empty — no cluster left to generate."))
                return
            self.stderr.write(
                self.style.SUCCESS(
                    f"Claimed cluster: {slug}  ({len(claimed_pks)} row(s) -> generating)"
                )
            )
            # Claimed rows are now 'generating', so re-select them by pk rather than status.
            qs = ContentPlan.objects.filter(pk__in=claimed_pks)
        else:
            qs = ContentPlan.objects.filter(status__in=statuses, target__in=targets).exclude(
                scope_relevance__gte=ContentPlan.SCOPE_SHELF_FROM
            )
            if source:
                qs = qs.filter(source_type=source)
            if opts["unkeyed"]:
                qs = qs.filter(canonical_key="")
            if opts["next_cluster"]:
                qs = self._generation_gates(qs, opts["allow_unbriefed"])
                nxt = self._next_cluster(qs)
                if not nxt:
                    self.stderr.write(
                        self.style.WARNING("Queue is empty — no cluster left to generate.")
                    )
                    return
                self.stderr.write(
                    self.style.SUCCESS(
                        f"Next cluster: {nxt['topic_cluster__name']}  ({nxt['topic_cluster__slug']})"
                    )
                )
                qs = qs.filter(topic_cluster__slug=nxt["topic_cluster__slug"])
            else:
                if opts["market"]:
                    m = opts["market"].strip()
                    qs = qs.filter(Q(markets__name__iexact=m) | Q(markets__slug=m)).distinct()
                if opts["cluster"]:
                    qs = qs.filter(topic_cluster__slug=opts["cluster"].strip())
        # Production order = terms -> hub -> spokes: a cluster's queued glossary
        # terms build first (so the articles' resolve-only tags + term links find
        # live targets at import), then the pillar before its spokes (so a spoke can
        # link to an existing pillar), then by priority desc. Run per cluster
        # (--cluster <slug>) for a single cluster's exact generation order; see
        # content-pipeline/CONTENT-PLAN.md.
        qs = (
            qs.select_related("topic_cluster", "topic_cluster__conversion_landing", "produced_post")
            .prefetch_related(
                "categories", "markets", "audience_roles", "audience_levels", "glossary_terms"
            )
            .annotate(
                _role_rank=Case(
                    When(target=ContentPlan.Target.GLOSSARY_TERM, then=0),
                    When(role=ContentPlan.Role.PILLAR, then=1),
                    default=2,
                    output_field=IntegerField(),
                )
            )
            .order_by("_role_rank", F("priority").desc(nulls_last=True), "-created_at")
        )
        rows = list(qs)
        if opts["limit"]:
            rows = rows[: opts["limit"]]

        # Existing produced content per cluster — route-independent: a keyword-route
        # spoke joining a cluster that top-pages (or any other path) already built
        # must inline-link to that cluster's live pillar/spokes, not only to its own
        # batch. Attached as spec["cluster_siblings"]; the generation workflow's
        # cluster-links phase treats them as valid link TARGETS.
        batch_slugs = {p.slug for p in rows}
        cluster_ids = {p.topic_cluster_id for p in rows if p.topic_cluster_id}
        siblings_by_cluster: dict[int, list[dict]] = {}
        if cluster_ids:
            sib_qs = (
                ContentPlan.objects.filter(
                    topic_cluster_id__in=cluster_ids,
                    produced_post__isnull=False,
                    target=ContentPlan.Target.BLOG,
                )
                .exclude(slug__in=batch_slugs)
                # Never link TO a shelved (>= SCOPE_SHELF_FROM) draft: it may be
                # unpublished/deleted, so it is not a valid internal-link target.
                .exclude(scope_relevance__gte=ContentPlan.SCOPE_SHELF_FROM)
                .order_by(F("priority").desc(nulls_last=True))
            )
            for sib in sib_qs:
                siblings_by_cluster.setdefault(sib.topic_cluster_id, []).append({
                    "slug": sib.slug,
                    "title": sib.title,
                    "role": sib.role or "spoke",
                    "intent": sib.intent,
                })
            for cid, sibs in siblings_by_cluster.items():
                sibs.sort(key=lambda s: 0 if s["role"] == "pillar" else 1)
                siblings_by_cluster[cid] = sibs[:20]

        contents = []
        cluster_pos: dict[str, int] = {}
        for p in rows:
            spec = p.to_worklist_spec()
            # The reconcile engine (tools/intent_registry.py) is stdlib-only and
            # cannot reverse a route, so the host's real article URL has to travel
            # with the spec. Without it the engine emits no target_url rather than
            # the fabricated /blog/<slug> it used to guess.
            if p.produced_post_id:
                spec["url"] = host.post_url(p.produced_post)
            if p.target == ContentPlan.Target.GLOSSARY_TERM:
                # Term rows go to the glossary authoring engine, not the article
                # workflow — no visual-lead rotation, no sibling link plan.
                contents.append(spec)
                continue
            ckey = spec.get("topic_cluster") or ""
            idx = cluster_pos.get(ckey, 0)
            cluster_pos[ckey] = idx + 1
            spec["lead_visual_archetype"] = _lead_visual_archetype(
                spec.get("intent_frame", ""), idx
            )
            spec["cluster_siblings"] = siblings_by_cluster.get(p.topic_cluster_id, [])
            # The cluster-level brief (element ownership, scope fences, link-terms)
            # rides every article spec: the brief stage skips its cluster pass when
            # one already exists (late additions brief in constrained mode), and the
            # author treats its ownership map as binding.
            spec["cluster_brief"] = (
                p.topic_cluster.brief if p.topic_cluster_id else {}
            ) or {}
            # Same-market bridge surfaces for the brief stage's business_bridge
            # decision (deterministic candidates — the model picks, never invents).
            spec["bridge_candidates"] = _bridge_candidates(p)
            contents.append(spec)
        # YouTube-transcript rows carry a large ``source_transcript``. When writing to
        # a file, spill each transcript to a sidecar (``<slug>.transcript.txt`` next to
        # the worklist) and pass a ``source_transcript_path`` instead of inlining it —
        # so the worklist JSON (and the generator's args) stay small. The generator
        # reads the file itself (buildPrompt honors source_transcript_path). Stdout
        # export keeps the transcript inline (it is for inspection, not a real run).
        if opts["out"]:
            out_dir = Path(opts["out"]).expanduser().resolve().parent
            for spec in contents:
                transcript = spec.get("source_transcript") or ""
                if transcript:
                    side = out_dir / f"{spec['slug']}.transcript.txt"
                    side.write_text(transcript, encoding="utf-8")
                    spec["source_transcript"] = ""
                    spec["source_transcript_path"] = str(side)
        worklist = {
            "source": "blog.ContentPlan",
            "generated_date": datetime.date.today().isoformat(),
            "count": len(contents),
            "contents": contents,
        }
        text = json.dumps(worklist, indent=2, ensure_ascii=False)
        if opts["out"]:
            Path(opts["out"]).expanduser().write_text(text + "\n", encoding="utf-8")
            self.stderr.write(
                self.style.SUCCESS(f"Wrote {len(contents)} content spec(s) -> {opts['out']}")
            )
        else:
            self.stdout.write(text)

    def _generation_gates(self, qs, allow_unbriefed):
        """Hold back rows that must not reach the generation engine.

        Two gates: ``feasibility=human_only`` rows are a human-writer handoff (their
        brief IS the deliverable), and EVERY article row whose ``brief`` is still
        empty waits for the brief stage — source-agnostic since 2026-07-16 (the
        top-pages route is briefed too; its evidence is the same ``competitor_urls``
        field). Term rows are exempt (their suggestion payload rides ``brief``, no
        article brief needed). Briefing is LAZY — per cluster, when its production
        turn comes (see CONTENT-PLAN.md). Both exclusions are surfaced so held-back
        work stays visible.
        """
        human_only = qs.filter(feasibility=ContentPlan.Feasibility.HUMAN_ONLY).count()
        if human_only:
            qs = qs.exclude(feasibility=ContentPlan.Feasibility.HUMAN_ONLY)
            self.stderr.write(
                self.style.WARNING(
                    f"  ({human_only} human-only row(s) held back — their brief is the "
                    "handoff to a human writer; see /admin-os/content-plan/)"
                )
            )
        if not allow_unbriefed:
            unbriefed_q = Q(brief={}) & ~Q(target=ContentPlan.Target.GLOSSARY_TERM)
            unbriefed = qs.filter(unbriefed_q).count()
            if unbriefed:
                qs = qs.exclude(unbriefed_q)
                self.stderr.write(
                    self.style.WARNING(
                        f"  ({unbriefed} article row(s) held back — no brief written yet; "
                        "run the brief stage (brief.workflow.js + contentplan_set_brief) "
                        "or pass --allow-unbriefed)"
                    )
                )
        return qs

    @staticmethod
    def _next_cluster(qs):
        """The most ON-SCOPE cluster still holding queue rows.

        Production priority is scope-relevance ONLY (Milad, 2026-08-09) — keyword
        volume and competitor traffic play NO part. Each cluster is ranked by the
        mean scope-relevance level of its producible rows (the 3-question model,
        BUSINESS.md §2; an ungraded NULL row counts as 3); the lowest mean — the most
        L1/L2 content — wins. Shelf rows are already excluded from ``qs`` upstream.

        The mean is compared in HALF-LEVEL BUCKETS, exactly as
        ``scope.cluster_priority`` does it, because shelving lifts a cluster's raw
        mean: a 3-row remnant of an otherwise shelved cluster scores 1.00 and jumps
        ahead of a whole 13-row cluster at 1.05. Inside a bucket the larger cluster
        wins, so equally on-scope work is built most-complete-first. This screen and
        that in-loop scorer MUST agree — they are the claim path and the read path of
        one decision, and a cluster the brain picks but the claimer skips exports an
        empty worklist, which the driver scores as no progress.

        Ties break toward the larger cluster, then name, for determinism.
        ``--cluster <slug>`` is the operator's manual override.
        """
        mean_scope = Avg(Coalesce("scope_relevance", Value(3)), output_field=FloatField())
        rows = (
            qs.exclude(topic_cluster__isnull=True)
            .values("topic_cluster__slug", "topic_cluster__name")
            .annotate(mean_scope=mean_scope, n_rows=Count("pk"))
        )
        # Bucketed in Python, not SQL: this list is one entry per CLUSTER, so
        # materializing it is cheap, and the arithmetic stays byte-identical to the
        # shared policy instead of being re-expressed as a database rounding
        # expression that could quietly drift from it.
        ranked = sorted(
            rows,
            key=lambda r: (
                round(r["mean_scope"] / PRIORITY_BUCKET) * PRIORITY_BUCKET,
                -r["n_rows"],
                r["topic_cluster__name"] or "",
            ),
        )
        return ranked[0] if ranked else None

    @transaction.atomic
    def _select_and_claim(self, statuses, targets, opts):
        """Atomically pick the next cluster and flip its queue rows to 'generating'.

        Row-level locks (``select_for_update``) serialize concurrent claimers: if a
        sibling session claims the picked cluster first, this transaction sees its
        rows leave the queue and re-picks the next cluster. Returns
        ``(slug, [claimed_pk, ...])`` or ``(None, [])`` when the queue is empty.
        The claim spans the whole cluster across sources and targets (articles +
        queued glossary terms) — never per-source — UNLESS ``--limit`` bounds it to
        one batch, which is how a run sized to the token window claims only what it
        will finish. Only rows that pass the
        generation gates are claimed — a held-back row (human-only, or unbriefed
        keyword row) stays in its queue status.
        """
        source = (opts["source"] or "").strip()
        explicit = bool(opts["cluster"]) and not opts["next_cluster"]
        while True:
            base = ContentPlan.objects.filter(status__in=statuses, target__in=targets).exclude(
                scope_relevance__gte=ContentPlan.SCOPE_SHELF_FROM
            )
            if source:
                base = base.filter(source_type=source)
            base = self._generation_gates(base, opts["allow_unbriefed"])
            if explicit:
                slug = opts["cluster"].strip()
                if not base.filter(topic_cluster__slug=slug).exists():
                    return None, []
            else:
                nxt = self._next_cluster(base)
                if not nxt:
                    return None, []
                slug = nxt["topic_cluster__slug"]
            picked = base.select_for_update().filter(topic_cluster__slug=slug)
            if opts["limit"]:
                # When a batch is smaller than the cluster, claim its most on-scope
                # rows first — scope-relevance only, no volume/traffic (Milad,
                # 2026-08-09). Articles before glossary terms: a term row is not
                # producible by the generation workflow, so letting one occupy a batch
                # slot would silently shrink the batch. pk breaks ties deterministically.
                picked = picked.order_by(
                    "target", F("scope_relevance").asc(nulls_last=True), "pk"
                )[: opts["limit"]]
            claimed = list(picked.values_list("pk", flat=True))
            if not claimed:
                # A concurrent session claimed this cluster between pick and lock.
                if explicit:
                    return None, []
                continue
            ContentPlan.objects.filter(pk__in=claimed).update(
                status=ContentPlan.Status.GENERATING
            )
            return slug, claimed
