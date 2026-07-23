"""``./manage.py contentplan_set_brief <briefs.json>`` — persist brief-stage output.

The brief stage (``tools/content_pipeline/brief.workflow.js``) crawls each
reconciled article row's stored evidence URLs (``competitor_urls`` — SERP-verify
samples on the keyword route, competitor pages on the top-pages route) and returns
one structured brief per slug, plus one CLUSTER brief per newly-passed cluster;
the session writes them to a JSON file and this command binds them to the roadmap:

    {"cluster_briefs": [{"cluster_slug": "...", "cluster_brief": {...}}, ...],
     "briefs": [{"slug": "...",
                 "feasibility": "llm_full|llm_with_assets|human_only",
                 "brief": {user_problem, intent_statement, answer_strategy,
                           essential_elements, complementary_elements,
                           keyword_usage, headings_outline, title, h1, evidence,
                           scope_excludes, asset_predictions, rationale,
                           _judge}}, ...]}

(A bare list of brief entries is still accepted.)

- ``brief`` lands in ``ContentPlan.brief`` (export_worklist projects it into the
  generation spec; the author treats it as the article's structural contract).
- ``cluster_brief`` lands in ``TopicCluster.brief`` (element ownership across
  siblings + scope fences + link-terms; export attaches it to every article spec,
  and the brief stage skips its cluster pass when one already exists).
- A brief's ``scope_excludes`` unions into the row's ``scope_excludes`` (the
  cluster pass fences siblings against each other; reconcile's fences stay).
- ``feasibility`` gates the queue: ``human_only`` rows never export for generation —
  their brief IS the deliverable, handed to a human writer via /admin-os/content-plan/.
- A brief may refine ``title`` / ``h1`` (pre-generation only — rows already in
  production are never touched).

Idempotent: re-running overwrites the brief with the newer one.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host

ContentPlan = host.content_plan_model()
TopicCluster = host.topic_cluster_model()

_LOCKED = (
    ContentPlan.Status.GENERATING,
    ContentPlan.Status.DRAFTED,
    ContentPlan.Status.PUBLISHED,
)


class Command(BaseCommand):
    help = "Persist brief-stage briefs + feasibility verdicts onto ContentPlan rows."

    def add_arguments(self, parser):
        parser.add_argument("briefs", help="A briefs .json (list of {slug, brief, feasibility}).")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["briefs"]).expanduser()
        if not path.is_file():
            raise CommandError(f"briefs file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("briefs") if isinstance(data, dict) else data
        cluster_entries = data.get("cluster_briefs", []) if isinstance(data, dict) else []
        if not isinstance(entries, list) or not entries:
            raise CommandError(f"{path.name} carries no briefs (expected a list or {{'briefs': [...]}})")

        for centry in cluster_entries:
            if not isinstance(centry, dict):
                continue
            cslug = (centry.get("cluster_slug") or "").strip()
            cbrief = centry.get("cluster_brief")
            if not cslug or not isinstance(cbrief, dict) or not cbrief:
                self.stderr.write(self.style.WARNING(f"  - skip cluster brief {cslug or '(no slug)'}"))
                continue
            tc = TopicCluster.objects.filter(slug=cslug).first()
            if tc is None:
                self.stderr.write(self.style.WARNING(f"  ? missing cluster {cslug}"))
                continue
            if opts["dry_run"]:
                self.stdout.write(f"  ~ would set cluster brief {cslug}")
                continue
            tc.brief = cbrief
            tc.save(update_fields=["brief", "updated_at"])
            self.stdout.write(self.style.SUCCESS(f"  * cluster brief {cslug}"))

        valid_feasibility = dict(ContentPlan.Feasibility.choices)
        updated = missing = locked = invalid = 0
        for entry in entries:
            if not isinstance(entry, dict):
                invalid += 1
                continue
            slug = (entry.get("slug") or "").strip()
            brief = entry.get("brief")
            if not slug or not isinstance(brief, dict) or not brief:
                self.stderr.write(self.style.WARNING(f"  - skip   {slug or '(no slug)'}: no brief object"))
                invalid += 1
                continue
            plan = ContentPlan.objects.filter(slug=slug).first()
            if plan is None:
                self.stderr.write(self.style.WARNING(f"  ? missing {slug} (not in ContentPlan)"))
                missing += 1
                continue
            if plan.status in _LOCKED:
                self.stdout.write(f"  = lock   {slug} (already {plan.status}; brief not applied)")
                locked += 1
                continue
            if opts["dry_run"]:
                self.stdout.write(f"  ~ would brief {slug}")
                updated += 1
                continue
            plan.brief = brief
            feasibility = (entry.get("feasibility") or "").strip()
            update_fields = ["brief", "updated_at"]
            # The cluster pass fences siblings against each other — union its
            # per-content excludes into the row (reconcile's fences are kept).
            fences = [
                f for f in (brief.get("scope_excludes") or [])
                if isinstance(f, str) and f.strip()
            ]
            if fences:
                merged = list(plan.scope_excludes or [])
                merged += [f for f in fences if f not in merged]
                plan.scope_excludes = merged
                update_fields.append("scope_excludes")
            if feasibility in valid_feasibility:
                plan.feasibility = feasibility
                update_fields.append("feasibility")
            # A brief may sharpen the crafted title/h1 before generation.
            if (t := (brief.get("title") or "").strip()):
                plan.title = t[:255]
                update_fields.append("title")
            if (h := (brief.get("h1") or "").strip()):
                plan.h1 = h[:255]
                update_fields.append("h1")
            plan.save(update_fields=update_fields)
            marker = {"human_only": " [human-only]", "llm_with_assets": " [needs-assets]"}.get(feasibility, "")
            self.stdout.write(self.style.SUCCESS(f"  * brief  {slug}{marker}"))
            updated += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"done: {updated} briefed, {locked} locked, {missing} missing, "
                f"{invalid} invalid (of {len(entries)})"
            )
        )
