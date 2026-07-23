"""``./manage.py contentplan_ingest_terms <suggestions.json>`` — queue glossary-term
suggestions as ContentPlan rows (the unified production queue).

Accepts either the legacy backlog shape (``{"pending": [...]}``) or a generation
run's ``glossary-suggestions.json`` (``{"pending": [...]}`` written next to the
bundles). Each item is ``{"term", "reason", "example_sentence", "sources",
"topic_cluster_slug"}`` — only ``term`` is required. Items already covered by a
live glossary term (or already queued) are deduped; an already-queued term only
gains the new source + a cluster affinity if it had none.

``--cluster <slug>`` sets the scheduling affinity for items that don't carry their
own ``topic_cluster_slug`` — the batch's cluster, so ``export_worklist
--next-cluster`` emits the term together with the articles that need it.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host
from keel_content.core import glossary_backlog

ContentPlan = host.content_plan_model()

_MARKS = {
    "created": "+ queue ",
    "updated": "* merge ",
    "skipped-live": "- live  ",
    "skipped": "- skip  ",
}


class Command(BaseCommand):
    help = "Queue glossary-term suggestions as ContentPlan glossary_term rows."

    def add_arguments(self, parser):
        parser.add_argument("suggestions", help="A suggestions .json ({'pending': [...]}).")
        parser.add_argument(
            "--cluster",
            default="",
            help="TopicCluster slug used as the scheduling affinity for items "
            "without their own topic_cluster_slug.",
        )
        parser.add_argument(
            "--source-type",
            default=ContentPlan.Source.IDEATION.value,
            choices=[c for c, _ in ContentPlan.Source.choices],
            help="Which planning path surfaced these terms (default: ideation).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would happen, write nothing."
        )

    def handle(self, *args, **opts):
        path = Path(opts["suggestions"]).expanduser()
        if not path.is_file():
            raise CommandError(f"suggestions file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CommandError(f"unreadable suggestions JSON: {exc}") from exc
        items = data.get("pending") if isinstance(data, dict) else data
        if not isinstance(items, list) or not items:
            raise CommandError(f"{path.name} has no pending suggestions")

        tally: dict[str, int] = {}
        for item in items:
            item = item if isinstance(item, dict) else {}
            term = (item.get("term") or "").strip()
            cluster_slug = (item.get("topic_cluster_slug") or opts["cluster"] or "").strip()
            if opts["dry_run"]:
                outcome = "created" if term else "skipped"
            else:
                _plan, outcome = glossary_backlog.upsert(
                    term,
                    reason=item.get("reason", ""),
                    example_sentence=item.get("example_sentence", ""),
                    sources=list(item.get("sources") or []),
                    cluster_slug=cluster_slug,
                    source_type=opts["source_type"],
                )
            tally[outcome] = tally.get(outcome, 0) + 1
            line = f"  {_MARKS.get(outcome, '? ' + outcome)} {term or '(no term)'}"
            if outcome in ("created", "updated"):
                self.stdout.write(self.style.SUCCESS(line))
            else:
                self.stdout.write(line)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"done: {tally.get('created', 0)} queued, {tally.get('updated', 0)} merged, "
                f"{tally.get('skipped-live', 0)} already covered, "
                f"{tally.get('skipped', 0)} skipped (of {len(items)})"
            )
        )
