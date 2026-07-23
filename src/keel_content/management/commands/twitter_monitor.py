"""``./manage.py twitter_monitor`` — job 1 (fetch): pull the active watchlist's
recent tweets into the ``TweetCandidate`` staging table.

Run manually (there is deliberately NO scheduled/automatic monitoring). Fetches
the last ``--hours`` hours (default 24) for every active ``TwitterSource`` and
upserts new tweets (dedup on tweet id). Triage/embed/ingest are separate stages.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from keel_content.twitter import monitor


class Command(BaseCommand):
    help = "Fetch recent tweets for the active Twitter watchlist into staging."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24, help="Look-back window (default 24).")
        parser.add_argument(
            "--accounts",
            help="Comma-separated usernames to fetch instead of the full active watchlist.",
        )

    def handle(self, *args, **opts):
        usernames = None
        if opts.get("accounts"):
            usernames = [a.strip() for a in opts["accounts"].split(",") if a.strip()]
        stats = monitor.fetch_and_store(hours=opts["hours"], usernames=usernames)
        self.stdout.write(self.style.SUCCESS(
            f"monitor: {stats['sources']} source(s), {stats['fetched']} fetched, "
            f"{stats['new']} new, {stats['skipped']} already staged"
        ))
        if stats["new"]:
            self.stdout.write("  next: ./manage.py twitter_triage")
