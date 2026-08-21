"""``./manage.py contentplan_map_terms`` — late-binding pass that attaches
unmapped queued glossary terms to the clusters that exist NOW.

Term-to-cluster mapping is not a one-time event: a term suggested today may
belong to a cluster that only gets planned next month. This command re-scans
every PENDING term row (``target=glossary_term``) with no ``topic_cluster`` and
scores it against every cluster that holds at least one article row. Scoring is
deterministic (token overlap — no LLM): a strong, unambiguous winner is attached
automatically; ambiguous candidates are reported for a human/session verdict;
no-match terms stay unmapped (a healthy state — they still produce via the
standalone glossary batch).

Run it as a standard step after every ``contentplan_ingest`` of a clustering run
(new clusters appeared) and after ``contentplan_ingest_terms`` (new terms
appeared — most arrive pre-mapped via ``--cluster``, so this catches the rest).

The run ends with the MISSING-CLUSTER report (the layer after the glossary-gap
suggestions): unmapped terms — queued, plus live terms central to no cluster
with ``--include-live`` — grouped by shared salient token. Three or more terms
sharing a theme signal a need-space we have not planned a cluster for yet; the
report is advisory input to the next planning round.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand

from keel_content import host
from keel_content.core.term_match import tokens

ContentPlan = host.content_plan_model()
Tag = host.tag_model()
TopicCluster = host.topic_cluster_model()

# Tokens carrying no discriminating power between OUR clusters: generic English
# plus domain words present in almost every cluster/title.
_STOPWORDS = frozenset(
    """a an and are as at be best by can do does for from how in into is it its
    of on or that the this to top vs what when which why with you your guide
    guides review reviews strategy strategies signal signals trading trade
    trader traders market markets bot bots automated automation platform
    platforms 2025 2026""".split()
)

_PENDING = ("planned", "reconciled", "generating")


def _salient(text: str) -> frozenset[str]:
    return frozenset(t for t in tokens(text) if t not in _STOPWORDS and len(t) > 2)


class Command(BaseCommand):
    help = "Attach unmapped queued glossary terms to existing clusters (deterministic)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-score",
            type=int,
            default=3,
            help="Minimum winning score to auto-attach (default 3 = at least one "
            "term-name token hit).",
        )
        parser.add_argument(
            "--include-live",
            action="store_true",
            help="Missing-cluster report also considers live terms that are "
            "central to no cluster (empty key_in_clusters).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would happen, write nothing."
        )

    def handle(self, *args, **opts):
        bags = self._cluster_bags()
        if not bags:
            self.stdout.write(self.style.WARNING("no populated clusters to map against."))
            return

        pending = list(
            ContentPlan.objects.filter(
                target=ContentPlan.Target.GLOSSARY_TERM,
                produced_term__isnull=True,
                status__in=_PENDING,
                topic_cluster__isnull=True,
            )
        )
        attached, ambiguous, unmatched = 0, [], []
        for plan in pending:
            name_toks = _salient(plan.title)
            reason = (plan.brief or {}).get("reason", "") or plan.observed_intent
            reason_toks = _salient(reason)
            scores = sorted(
                (
                    (3 * len(name_toks & bag) + len(reason_toks & bag), slug)
                    for slug, (bag, _tc) in bags.items()
                ),
                reverse=True,
            )
            best, best_slug = scores[0]
            second = scores[1][0] if len(scores) > 1 else 0
            if best >= opts["min_score"] and best >= 2 * second:
                if not opts["dry_run"]:
                    plan.topic_cluster = bags[best_slug][1]
                    plan.save(update_fields=["topic_cluster", "updated_at"])
                attached += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  + map   {plan.title!r} -> {best_slug} (score {best})"
                ))
            elif best > 0:
                top3 = ", ".join(f"{s}:{sc}" for sc, s in scores[:3] if sc > 0)
                ambiguous.append(plan)
                self.stdout.write(f"  ? amb   {plan.title!r} — candidates: {top3}")
            else:
                unmatched.append(plan)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"done: {attached} attached, {len(ambiguous)} ambiguous (decide in "
            f"/admin-os/content-plan/ or re-run after new clusters), "
            f"{len(unmatched)} unmatched (of {len(pending)})"
        ))
        self._missing_cluster_report(unmatched + ambiguous, opts["include_live"])

    def _cluster_bags(self):
        """{slug: (salient token bag from name + member article titles, cluster)}.

        Only clusters holding at least one article row participate — an empty
        cluster is not a real need-space yet (and stale empty near-duplicates
        must never attract terms).
        """
        bags: dict[str, tuple[set, TopicCluster]] = {}
        member_titles = defaultdict(list)
        rows = (
            ContentPlan.objects.exclude(target=ContentPlan.Target.GLOSSARY_TERM)
            .exclude(status__in=(ContentPlan.Status.MERGED, ContentPlan.Status.REJECTED))
            .exclude(topic_cluster__isnull=True)
            .values_list("topic_cluster__slug", "title")
        )
        for slug, title in rows:
            member_titles[slug].append(title)
        for tc in TopicCluster.objects.exclude(status=TopicCluster.Status.ARCHIVED):
            titles = member_titles.get(tc.slug)
            if not titles:
                continue
            bag = set(_salient(tc.name))
            for title in titles:
                bag |= _salient(title)
            bags[tc.slug] = (bag, tc)
        return bags

    def _missing_cluster_report(self, unmapped_plans, include_live: bool):
        """Group cluster-less terms by shared salient token — 3+ sharing a theme
        signal a need-space with no planned cluster (advisory, feeds planning)."""
        names = [p.title for p in unmapped_plans]
        if include_live:
            names += list(
                host.glossary_term_queryset().filter(key_in_clusters__isnull=True)
                .values_list("name", flat=True)
            )
        themes: dict[str, list[str]] = defaultdict(list)
        for name in names:
            for tok in _salient(name):
                themes[tok].append(name)
        candidates = {t: ns for t, ns in themes.items() if len(ns) >= 3}
        self.stdout.write("")
        if not candidates:
            self.stdout.write("missing-cluster report: no shared theme among unmapped terms.")
            return
        self.stdout.write(self.style.MIGRATE_HEADING(
            "missing-cluster report — unplanned need-spaces suggested by unmapped terms:"
        ))
        for tok, ns in sorted(candidates.items(), key=lambda kv: -len(kv[1])):
            self.stdout.write(f"  • theme {tok!r} ({len(ns)} terms): {', '.join(sorted(set(ns))[:8])}")
        self.stdout.write(
            "  (advisory — a recurring theme here is input for the next planning "
            "round: it may deserve its own topic cluster + pillar.)"
        )
