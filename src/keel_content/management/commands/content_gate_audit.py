"""``./manage.py content_gate_audit`` — is the intent registry still describing the
corpus, or has the corpus outgrown it?

The intent gate only works while every published article has a ``ContentPlan`` row
carrying a declared intent and a cluster. Nothing keeps that true on its own: posts
arrive from imports, migrations and hand-editing, and each one that lands without a
plan row is invisible to reconcile (it can never be found cannibalizing anything),
invisible to the linking pass (it is neither a source nor a candidate), and invisible
to the reading path. The failure is silent by construction — every command still
reports success, over a smaller corpus than the operator thinks.

So this is the standing check, read-only and advisory, meant for the weekly Keel-drift
routine. It prints one FLAG line per gap that is over threshold and exits 0 either
way; the human decides what to do. ``--json`` emits the same numbers as a single
object for a routine that wants to parse rather than grep.

The four gaps it measures, and what each one silently breaks:

* **Unkeyed posts** — published, but no plan row. Outside the gate entirely.
  ``contentplan_backfill`` is the fix.
* **No intent** — keyed, but ``intent`` is empty. Reconcile's comparison is between
  declared intents, so an empty one collides with nothing and the page reads as
  unique no matter how many duplicates it has. ``contentplan_export_intent_seeds``
  + ``contentplan_ingest_intents``.
* **No cluster** — keyed, but no ``TopicCluster``. The linking pass draws candidates
  from cluster mates, so an unclustered post can neither give nor receive an internal
  link. ``contentplan_ingest_clusters``.
* **No Markdown body** — published with an empty ``content_markdown_source``. Every
  Markdown-based pass in this package is a silent no-op on it.
  ``backfill_markdown_source``.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from keel_content import host

# A corpus is never perfectly keyed the day after a publish batch, so a small gap is
# normal operations, not drift. Ten percent is the line the rollout standard drew.
_FLAG_RATIO = 0.10


class Command(BaseCommand):
    help = "Report how much of the published corpus the intent registry still covers."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit one JSON object.")
        parser.add_argument(
            "--threshold", type=float, default=_FLAG_RATIO,
            help=f"Flag a gap above this share of published posts (default {_FLAG_RATIO}).",
        )

    def handle(self, *args, **opts):
        Post = host.post_model()
        ContentPlan = host.content_plan_model()

        published = Post.objects.filter(status="published")
        total = published.count()
        keyed_ids = set(
            ContentPlan.objects.filter(produced_post_id__isnull=False)
            .values_list("produced_post_id", flat=True)
        )
        published_ids = set(published.values_list("id", flat=True))
        keyed_published = published_ids & keyed_ids

        plans = ContentPlan.objects.filter(produced_post_id__in=keyed_published)
        gaps = {
            "unkeyed": len(published_ids - keyed_ids),
            "no_intent": plans.filter(intent="").count(),
            "no_cluster": plans.filter(topic_cluster__isnull=True).count(),
            "no_markdown_body": published.filter(content_markdown_source="").count(),
        }
        fixes = {
            "unkeyed": "contentplan_backfill",
            "no_intent": "contentplan_export_intent_seeds + contentplan_ingest_intents",
            "no_cluster": "contentplan_ingest_clusters",
            "no_markdown_body": "backfill_markdown_source",
        }

        threshold = opts["threshold"]
        flagged = {k: v for k, v in gaps.items() if total and v / total > threshold}
        if opts["json"]:
            self.stdout.write(json.dumps(
                {"published": total, "keyed": len(keyed_published), "gaps": gaps,
                 "flagged": sorted(flagged), "threshold": threshold},
                ensure_ascii=False,
            ))
            return

        self.stdout.write(f"published posts: {total}  keyed by a ContentPlan: {len(keyed_published)}")
        for name, count in gaps.items():
            share = (100 * count / total) if total else 0
            mark = "FLAG" if name in flagged else "ok  "
            self.stdout.write(f"  {mark} {name:<18} {count:>5} ({share:.1f}%)  fix: {fixes[name]}")
        if flagged:
            self.stdout.write(self.style.WARNING(
                f"{len(flagged)} gap(s) above {threshold:.0%} of the published corpus. "
                "Advisory only — nothing was changed."
            ))
