"""``./manage.py twitter_triage`` — job 1 (quality gate): score, classify, and
route every FETCHED tweet.

Deterministic pre-filter drops obvious noise (self-promo, below the view floor);
the survivors are LLM-classified into markets / evergreen / quality / route
(embed | idea | both | discard). Needs the Anthropic API key (AiSetting or
ANTHROPIC_API_KEY).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from keel_content.twitter import triage


class Command(BaseCommand):
    help = "Score + classify + route fetched tweets (the quality gate)."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=40)
        parser.add_argument("--limit", type=int, default=None, help="Cap tweets triaged this run.")

    def handle(self, *args, **opts):
        stats = triage.triage_pending(batch_size=opts["batch_size"], limit=opts["limit"])
        self.stdout.write(self.style.SUCCESS(
            f"triage: {stats['seen']} seen → embed={stats['embed']} idea={stats['idea']} "
            f"both={stats['both']} discarded={stats['discarded']}"
        ))
        if stats["embed"] or stats["both"]:
            self.stdout.write("  next: ./manage.py twitter_embed")
        if stats["idea"] or stats["both"]:
            self.stdout.write("  then: ./manage.py contentplan_ingest_twitter")
