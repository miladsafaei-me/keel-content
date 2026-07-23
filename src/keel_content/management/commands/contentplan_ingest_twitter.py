"""``./manage.py contentplan_ingest_twitter`` — job 2 (idea sink): turn IDEA/BOTH
tweets into ``source_type=twitter`` ContentPlan rows.

The Twitter intake route into the roadmap (a sibling of ``contentplan_ingest``
and ``contentplan_ingest_youtube``). Each idea tweet is drafted into a user-need-
first article spec and upserted via the shared core; the row lands ``planned`` and
must pass the SAME reconcile / anti-cannibalization gate as every other route
before it can be generated. Run AFTER ``twitter_embed`` so homeless embed tweets
(rerouted to idea) are included.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from keel_content.twitter import ingest


class Command(BaseCommand):
    help = "Ingest IDEA/BOTH tweets as source_type=twitter ContentPlan rows."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=20)
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        stats = ingest.ingest_ideas(
            batch_size=opts["batch_size"], limit=opts["limit"], dry_run=opts["dry_run"]
        )
        self.stdout.write(self.style.SUCCESS(
            f"ingest: {stats['seen']} seen → created={stats['created']} "
            f"updated={stats['updated']} skipped={stats['skipped']}"
        ))
        if stats["created"] or stats["updated"]:
            self.stdout.write(
                "  rows are status=planned — they must pass the reconcile gate "
                "(cannibalization) before export_worklist will generate them."
            )
