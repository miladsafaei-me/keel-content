"""``./manage.py contentplan_add_ideation <ideas.json>`` — add landing-support ideas
to the ContentPlan roadmap (path 3).

Path 3 fills the gap between our business needs and the competitor/keyword demand
data: blog content that strengthens an existing landing or cluster but that neither the
top-pages nor the keyword path surfaced. It has no workbook — the roadmap table IS its
home. Each idea is upserted as a ``source_type=ideation`` row in ``planned`` status,
keyed by slug, via the shared upsert core, so dedup + facet resolution behave exactly
like the other paths.

Input JSON = a list of idea objects (only ``title`` is required; ``slug`` defaults to a
slug of the title)::

  [{"title": "...", "intent": "...", "topic_cluster": "Cluster Name", "role": "spoke",
    "target": "blog", "categories": ["trading-signals"], "markets": ["forex"],
    "audience_roles": ["trader"], "audience_levels": ["beginner"],
    "glossary_terms": ["win-rate"]}]
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


class Command(BaseCommand):
    help = "Add landing-support ideation rows to the ContentPlan roadmap (path 3)."

    def add_arguments(self, parser):
        parser.add_argument("ideas", help="A JSON list of idea objects.")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Overwrite even rows already in production (generating/drafted/published).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["ideas"]).expanduser()
        if not path.is_file():
            raise CommandError(f"ideas file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):  # tolerate a {"ideas": [...]} / {"contents": [...]} wrapper
            data = data.get("ideas") or data.get("contents") or []
        if not isinstance(data, list) or not data:
            raise CommandError("ideas JSON must be a non-empty list of idea objects")

        source_ref = str(path)[:500]
        created = updated = skipped = locked = 0
        for idea in data:
            if not isinstance(idea, dict) or not (idea.get("title") or idea.get("slug")):
                skipped += 1
                continue
            if opts["dry_run"]:
                self.stdout.write(f"  ~ would add {idea.get('title') or idea.get('slug')}")
                created += 1
                continue
            plan, outcome = upsert_content_plan_spec(
                idea,
                source_type=ContentPlan.Source.IDEATION.value,
                source_ref=source_ref,
                replace=opts["replace"],
            )
            slug = plan.slug if plan else (idea.get("slug") or "?")
            if outcome == "created":
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + create {slug}"))
            elif outcome == "updated":
                updated += 1
                self.stdout.write(self.style.SUCCESS(f"  * update {slug}"))
            elif outcome == "locked":
                locked += 1
                self.stdout.write(f"  = lock   {slug} (in production; --replace to overwrite)")
            else:
                skipped += 1
                self.stdout.write(f"  - skip   {slug} ({outcome})")

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"done: {created} created, {updated} updated, {locked} locked, "
                f"{skipped} skipped (of {len(data)})"
            )
        )
