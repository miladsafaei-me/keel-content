"""``./manage.py contentplan_ingest <worklist.json> --source-type <t>`` — load a
planning worklist into the ContentPlan roadmap.

The unifying step: every planning path's worklist — competitor top-pages
(``parse_top_pages.py``), keyword clustering (``parse_clusters.py``), or an ideation
JSON — is upserted into ``blog.ContentPlan`` keyed by slug via the shared
:func:`~keel_content.adapters.signalbots.upsert_content_plan_spec`. Facet NAMES
resolve to live DB rows; rows land in ``planned`` status (the queue head).

Upsert policy protects work: a slug already in production
(``generating`` / ``drafted`` / ``published``) is left untouched unless ``--replace``;
a ``planned`` / ``reconciled`` row is refreshed in place. Only ``blog`` / ``news``
content types are ingested — other types in a workbook (Product / Tool / Review /
Listing) are landing-pipeline work, not blog roadmap rows, and are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host
from keel_content.adapters import get_adapter

# Resolve the configured publisher adapter (default: the reference SignalBots adapter).
upsert_content_plan_spec = get_adapter().upsert_content_plan_spec

ContentPlan = host.content_plan_model()

_LOCKED = (
    ContentPlan.Status.GENERATING,
    ContentPlan.Status.DRAFTED,
    ContentPlan.Status.PUBLISHED,
)
_MARKS = {
    "created": "+ create",
    "updated": "* update",
    "locked": "= lock  ",
    "skipped": "- skip  ",
    "skipped-type": "- skip  ",
}


class Command(BaseCommand):
    help = "Ingest a planning worklist.json into the ContentPlan roadmap (upsert by slug)."

    def add_arguments(self, parser):
        parser.add_argument("worklist", help="A worklist .json (parse_top_pages / parse_clusters).")
        parser.add_argument(
            "--source-type",
            default=ContentPlan.Source.TOP_PAGES.value,
            choices=[c for c, _ in ContentPlan.Source.choices],
            help="Which planning path produced this worklist (default: top_pages).",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Overwrite even rows already in production (generating/drafted/published).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would happen, write nothing."
        )

    def handle(self, *args, **opts):
        wl_path = Path(opts["worklist"]).expanduser()
        if not wl_path.is_file():
            raise CommandError(f"worklist not found: {wl_path}")
        wl = json.loads(wl_path.read_text(encoding="utf-8"))
        contents = wl.get("contents", [])
        if not contents:
            raise CommandError(f"worklist {wl_path.name} has no contents")

        source_type = opts["source_type"]
        source_ref = (wl.get("source") or str(wl_path))[:500]
        replace = opts["replace"]
        tally: dict[str, int] = {}

        for spec in contents:
            if opts["dry_run"]:
                outcome = self._dry_outcome(spec, replace)
            else:
                _plan, outcome = upsert_content_plan_spec(
                    spec, source_type=source_type, source_ref=source_ref, replace=replace
                )
            tally[outcome] = tally.get(outcome, 0) + 1
            slug = (spec.get("slug") or "").strip() or "(no slug)"
            line = f"  {_MARKS.get(outcome, '? ' + outcome)} {slug}"
            if outcome in ("created", "updated"):
                self.stdout.write(self.style.SUCCESS(line))
            else:
                self.stdout.write(line)

        skipped = tally.get("skipped", 0) + tally.get("skipped-type", 0)
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"done: {tally.get('created', 0)} created, {tally.get('updated', 0)} updated, "
                f"{tally.get('locked', 0)} locked, {skipped} skipped (of {len(contents)})"
            )
        )

    def _dry_outcome(self, spec: dict, replace: bool) -> str:
        slug = (spec.get("slug") or "").strip()
        if not slug:
            return "skipped"
        target = (spec.get("content_type") or spec.get("target") or "blog").strip().lower()
        if target not in (ContentPlan.Target.BLOG.value, ContentPlan.Target.NEWS.value):
            return "skipped-type"
        plan = ContentPlan.objects.filter(slug=slug).only("status").first()
        if plan is None:
            return "created"
        if plan.status in _LOCKED and not replace:
            return "locked"
        return "updated"
