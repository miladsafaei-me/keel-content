"""``./manage.py content_status [worklist.json]`` — the production-queue ledger.

With NO argument it reports the ``blog.ContentPlan`` roadmap queue itself: a count by
status and the next planned rows to generate. The DB is the single source of truth, so
this is the canonical queue view ("where do I resume?").

With a worklist (from ``parse_top_pages.py`` / ``export_worklist``) it joins each spec
to the blog ``Post`` table by slug and prints a done/pending report — the resume answer
for a specific worklist/market.

Read-only. ``--pending`` prints just the bare pending slugs, one per line (pipe-able).
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from keel_content import host

ContentPlan = host.content_plan_model()
Post = host.post_model()

_MARKS = {
    "published": "[published]",
    "draft": "[draft]    ",
    "archived": "[archived] ",
}

_QUEUE_PENDING = (ContentPlan.Status.PLANNED, ContentPlan.Status.RECONCILED)


class Command(BaseCommand):
    help = "Report the ContentPlan queue, or diff a worklist against produced posts."

    def add_arguments(self, parser):
        parser.add_argument(
            "worklist",
            nargs="?",
            default="",
            help="Optional worklist .json. Omit to report the ContentPlan queue.",
        )
        parser.add_argument(
            "--pending",
            action="store_true",
            help="Print only the bare pending slugs, one per line.",
        )

    def handle(self, *args, **opts):
        if opts["worklist"]:
            self._worklist_report(opts)
        else:
            self._queue_report(opts)

    def _queue_report(self, opts) -> None:
        counts: dict[str, int] = {}
        for status in ContentPlan.objects.values_list("status", flat=True):
            counts[status] = counts.get(status, 0) + 1

        pending_qs = ContentPlan.objects.filter(status__in=_QUEUE_PENDING).order_by(
            F("priority").desc(nulls_last=True), "-created_at"
        )
        if opts["pending"]:
            for slug in pending_qs.values_list("slug", flat=True):
                self.stdout.write(slug)
            return

        total = sum(counts.values())
        if total == 0:
            self.stdout.write(
                "ContentPlan queue is empty. Ingest a plan (contentplan_ingest) or "
                "back-fill from posts (contentplan_backfill)."
            )
            return
        self.stdout.write(f"ContentPlan queue: {total} row(s)")
        for code, label in ContentPlan.Status.choices:
            self.stdout.write(f"  {counts.get(code, 0):>4}  {code:<11} {label}")
        npending = sum(counts.get(s, 0) for s in _QUEUE_PENDING)
        if npending:
            self.stdout.write(
                f"\nnext to generate: {npending} (use --pending for the bare list, "
                f"export_worklist to build a worklist)"
            )

    def _worklist_report(self, opts) -> None:
        wl_path = Path(opts["worklist"]).expanduser()
        if not wl_path.is_file():
            raise CommandError(f"worklist not found: {wl_path}")
        wl = json.loads(wl_path.read_text(encoding="utf-8"))
        contents = wl.get("contents", [])
        if not contents:
            raise CommandError(f"worklist {wl_path.name} has no contents")

        slugs = [c["slug"] for c in contents]
        status_by_slug = dict(Post.all_objects.filter(slug__in=slugs).values_list("slug", "status"))
        pending = [c for c in contents if c["slug"] not in status_by_slug]

        if opts["pending"]:
            for c in pending:
                self.stdout.write(c["slug"])
            return

        done = len(contents) - len(pending)
        self.stdout.write(
            f"worklist: {wl_path.name}  "
            f"({len(contents)} planned, {done} exist, {len(pending)} pending)\n"
        )
        for c in contents:
            mark = _MARKS.get(status_by_slug.get(c["slug"]), "[pending]  ")
            self.stdout.write(f"  {mark} {c['slug']}")
        if pending:
            self.stdout.write(f"\nnext to generate: {len(pending)} (use --pending for the bare list)")
