"""``./manage.py contentplan_ingest_intents --manifest <path>`` — write authored
intents back onto ContentPlan rows. Deterministic; never calls a model.

The write half of the pair opened by ``contentplan_export_intent_seeds``. An
authoring agent judges the seed batches and returns a manifest; this command
validates it and applies it. Keeping the write mechanical is the point — the
judgement is the only part that needs a model, and everything a model touches is
a file, never the database.

Manifest shape (a bare list, or ``{"intents": [...]}``)::

    [{"slug": "how-to-x", "intent": "…", "intent_frame": "how-to", "entity": "X"}]

Rules the command enforces rather than trusts:

* ``intent_frame`` must come from the controlled vocabulary; anything else is
  rejected for that row, because the frame is reconcile's HARD pre-filter — a
  typo silently partitions a page into a bucket of its own where it can never
  collide with anything, which looks exactly like "no cannibalization found".
* An unknown slug is reported and skipped, never created.
* ``--overwrite`` is required to touch a row that already has an intent, so a
  re-run cannot quietly rewrite human-authored values.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host

# Mirrors the archetypes agent-author-brief.md documents and the values the
# reference corpus actually uses.
VALID_FRAMES = {"what-is", "how-to", "guide", "best", "compare", "review", "cost", "list"}
_MAX_INTENT = 400


class Command(BaseCommand):
    help = "Apply an authored intent manifest onto ContentPlan rows (deterministic)."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, help="Path to the manifest JSON.")
        parser.add_argument(
            "--overwrite", action="store_true",
            help="Also update rows that already carry an intent.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")

    def handle(self, *args, **opts):
        path = Path(opts["manifest"]).expanduser()
        if not path.is_file():
            raise CommandError(f"no manifest at {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("intents") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            raise CommandError('manifest must be a list, or {"intents": [...]}')

        ContentPlan = host.content_plan_model()
        by_slug = {p.slug: p for p in ContentPlan.objects.all()}

        applied = skipped_existing = 0
        unknown: list[str] = []
        bad_frame: list[str] = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            slug = (e.get("slug") or "").strip()
            intent = (e.get("intent") or "").strip()
            frame = (e.get("intent_frame") or "").strip().lower()
            entity = (e.get("entity") or "").strip()
            if not slug or not intent:
                continue
            plan = by_slug.get(slug)
            if plan is None:
                unknown.append(slug)
                continue
            if frame and frame not in VALID_FRAMES:
                bad_frame.append(f"{slug}:{frame}")
                continue
            if (plan.intent or "").strip() and not opts["overwrite"]:
                skipped_existing += 1
                continue
            plan.intent = intent[:_MAX_INTENT]
            fields = ["intent"]
            if frame:
                plan.intent_frame = frame
                fields.append("intent_frame")
            if entity:
                plan.entity = entity[:160]
                fields.append("entity")
            if not opts["dry_run"]:
                plan.save(update_fields=fields)
            applied += 1

        for slug in unknown:
            self.stderr.write(self.style.WARNING(f"unknown slug, skipped: {slug}"))
        for item in bad_frame:
            self.stderr.write(self.style.ERROR(
                f"rejected — intent_frame not in {sorted(VALID_FRAMES)}: {item}"
            ))
        tail = " [dry-run]" if opts["dry_run"] else ""
        self.stderr.write(self.style.SUCCESS(
            f"applied {applied}, skipped {skipped_existing} with an existing intent, "
            f"{len(unknown)} unknown slug(s), {len(bad_frame)} bad frame(s){tail}"
        ))
