"""Publish autopilot — promote the next ready draft to live if a quota slot is due.

Prints one JSON result so a scheduler (Celery beat, systemd timer, cron) can branch
on ``action``::

    manage.py publish_autopilot --dry-run
    {"action": "would_publish", "post": {"slug": "...", "cluster": "..."}, ...}

The decision + the publish are here; telling Google about the new URL (Indexing API)
is a host concern and lives in the host's own publish task — so a manual publish via
this command does NOT fire an indexing nudge. Day to day the host wires
``core.golive.run_tick`` into a task that both publishes and indexes; this command is
for inspection (``--dry-run``), an emergency out-of-cadence publish (``--force``), or
a host that prefers cron over Celery beat.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from keel_content.core import golive


class Command(BaseCommand):
    help = "Promote the next ready draft to live on the daily quota (prints JSON)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--quota", type=int, default=golive.DEFAULT_QUOTA,
            help=f"posts/day target (default {golive.DEFAULT_QUOTA}); interval is 24h/quota",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="report the post that would publish without changing anything",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="ignore the quota/interval gate (still publishes at most one)",
        )

    def handle(self, *args, **opts):
        result = golive.run_tick(
            quota=opts["quota"], dry_run=opts["dry_run"], force=opts["force"]
        )
        self.stdout.write(json.dumps(result, default=str))
