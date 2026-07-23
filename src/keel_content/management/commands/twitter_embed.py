"""``./manage.py twitter_embed`` — job 3 (embed sink): attach EMBED/BOTH tweets to
a genuinely related published post.

Existing content is the anchor: a tweet embeds only when it complements a post's
declared intent + brief (intent gate), and each post holds at most
``TWEETS_PER_POST_CAP`` tweets (a rolling window, enforced in code). A homeless
EMBED tweet is rerouted to the idea sink as a content-gap signal — so run this
BEFORE ``contentplan_ingest_twitter`` so those reroutes get picked up.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from keel_content.twitter import embed


class Command(BaseCommand):
    help = "Match embed-worthy tweets to related posts (intent-gated, capped)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true", help="Report matches, write nothing.")

    def handle(self, *args, **opts):
        stats = embed.embed_pending(limit=opts["limit"], dry_run=opts["dry_run"])
        self.stdout.write(self.style.SUCCESS(
            f"embed: {stats['seen']} seen → embedded={stats['embedded']} "
            f"(evicted={stats['evicted']}, surplus={stats['surplus']}), "
            f"rerouted-to-idea={stats['rerouted']}, no-embed={stats['nomatch']}"
        ))
