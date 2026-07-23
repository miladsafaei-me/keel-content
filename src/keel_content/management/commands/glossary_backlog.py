"""``./manage.py glossary_backlog`` — review and manage the queue of glossary
terms the content pipeline has suggested but that are not authored yet.

The queue lives in ``blog.ContentPlan`` (``target=glossary_term`` rows — the same
clustered production pool as the blog roadmap), so run this against the
environment that holds the roadmap (prod, for the real queue). No arguments lists
the pending terms. ``--remove "Term"`` drops one (call this after you author it in
the glossary). ``--clear`` rejects the whole queue.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from keel_content.core import glossary_backlog


class Command(BaseCommand):
    help = "List or prune the pipeline's pending glossary-term suggestions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--remove", metavar="TERM", default=None,
            help="Remove the queued term that matches TERM (use after authoring it).",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="Reject every pending term in the queue.",
        )

    def handle(self, *args, **opts):
        if opts.get("clear"):
            count = glossary_backlog.clear()
            self.stdout.write(self.style.SUCCESS(f"cleared {count} pending term(s)."))
            return

        term = opts.get("remove")
        if term:
            if glossary_backlog.remove(term):
                self.stdout.write(self.style.SUCCESS(f"removed {term!r} from the queue."))
            else:
                self.stdout.write(self.style.WARNING(f"no queued term matched {term!r}."))
            return

        items = glossary_backlog.pending()
        if not items:
            self.stdout.write("glossary term queue is empty.")
            self.stdout.write("(queue: ContentPlan rows with target=glossary_term)")
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"glossary term queue — {len(items)} pending:"))
        for e in items:
            term = e.get("term", "")
            reason = e.get("reason", "")
            cluster = e.get("cluster", "")
            sources = e.get("sources", []) or []
            src_label = ", ".join(s.get("keyword") or s.get("content_id", "") for s in sources)
            self.stdout.write(f"\n  • {term}")
            if reason:
                self.stdout.write(f"      why: {reason}")
            if cluster:
                self.stdout.write(f"      produce with cluster: {cluster}")
            if src_label:
                self.stdout.write(f"      from: {src_label}")
        self.stdout.write(
            "\nAfter authoring a term in the glossary, drop it with:\n"
            "  ./manage.py glossary_backlog --remove \"Term name\""
        )
