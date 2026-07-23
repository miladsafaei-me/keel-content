"""``./manage.py contentplan_apply_reconcile <worklist.reconciled.json> [--report report.json]``

Write the reconcile engine's outcomes back into the ContentPlan roadmap — the binding
step that makes the table reflect the cannibalization-dedup decision.

- Survivors (rows present in the reconciled worklist) get their ``canonical_key`` /
  scopes / observed intent and move to ``reconciled`` (ready to generate).
- Merged-away losers (named in the reconciliation report's ``merge`` decisions and
  dropped from the reconciled worklist in auto mode) move to ``merged`` with
  ``merged_into`` pointing at the survivor row, so their need stays accounted for and is
  never re-planned. A loser's keyword evidence is unioned into the surviving row so the
  eventual article still sees all measured demand.
- Enrichment opportunities (collisions with an ALREADY-EXISTING page — a produced post
  or a glossary term) are echoed from the report: the row leaves the queue (``merged``)
  and the printed ledger tells the content team which live page to optimize with which
  keywords. A glossary-term survivor has no plan row, so ``merged_into`` stays empty —
  the report is the record.

Run after ``intent_registry.py apply ... --mode auto``. Read-only against the engine's
files; idempotent.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host

ContentPlan = host.content_plan_model()

_QUEUE_OPEN = (ContentPlan.Status.PLANNED, ContentPlan.Status.RECONCILED)


class Command(BaseCommand):
    help = "Apply reconcile-engine outcomes to ContentPlan (canonical_key, scopes, merges)."

    def add_arguments(self, parser):
        parser.add_argument("reconciled", help="worklist.reconciled.json from intent_registry.py apply.")
        parser.add_argument(
            "--report", default="", help="reconciliation-report.json (drives merge -> merged_into)."
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        rec_path = Path(opts["reconciled"]).expanduser()
        if not rec_path.is_file():
            raise CommandError(f"reconciled worklist not found: {rec_path}")
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        contents = rec.get("contents", [])
        dry = opts["dry_run"]
        survived = merged = missing = conflicts = 0
        survivor_by_slug: dict[str, ContentPlan] = {}

        for spec in contents:
            slug = (spec.get("slug") or "").strip()
            if not slug:
                continue
            plan = ContentPlan.objects.filter(slug=slug).first()
            if plan is None:
                missing += 1
                continue
            if dry:
                self.stdout.write(f"  ~ would reconcile {slug}")
                survived += 1
                continue
            plan.canonical_key = (spec.get("canonical_key") or plan.canonical_key or "").strip()
            if spec.get("observed_intent"):
                plan.observed_intent = spec["observed_intent"]
            plan.scope_includes = list(spec.get("scope_includes") or plan.scope_includes or [])
            plan.scope_excludes = list(spec.get("scope_excludes") or plan.scope_excludes or [])
            owner = spec.get("canonical_owner")
            if isinstance(owner, dict) and owner:
                plan.canonical_owner = owner
            if plan.status in _QUEUE_OPEN:
                plan.status = ContentPlan.Status.RECONCILED
            plan.save(update_fields=[
                "canonical_key", "observed_intent", "scope_includes",
                "scope_excludes", "canonical_owner", "status", "updated_at",
            ])
            survivor_by_slug[slug] = plan
            survived += 1

        if opts["report"]:
            rep_path = Path(opts["report"]).expanduser()
            if not rep_path.is_file():
                raise CommandError(f"report not found: {rep_path}")
            report = json.loads(rep_path.read_text(encoding="utf-8"))
            for decision in report.get("decisions", []):
                if decision.get("effective_action") != "merge":
                    continue
                survivor_slug = decision.get("survivor")
                survivor = survivor_by_slug.get(survivor_slug) or ContentPlan.objects.filter(
                    slug=survivor_slug
                ).first()
                for loser_slug in decision.get("dropped", []):
                    loser = ContentPlan.objects.filter(slug=loser_slug).first()
                    if loser is None:
                        continue
                    # Orphaned-draft guard: a loser that already produced a Post must
                    # NOT be silently merged away — that draft and the survivor would
                    # cannibalize each other if both reach publish. Flag for a human to
                    # resolve (unpublish/delete the draft, or keep it as the survivor)
                    # instead of dropping the row out of the queue.
                    if loser.is_produced:
                        self.stderr.write(self.style.WARNING(
                            f"  ! CONFLICT: {loser_slug} already has a draft/post but the "
                            f"reconcile wants it merged into {survivor_slug}; left as-is for "
                            "human review (resolve the duplicate draft manually)."
                        ))
                        conflicts += 1
                        continue
                    if dry:
                        self.stdout.write(f"  ~ would merge {loser_slug} -> {survivor_slug}")
                        merged += 1
                        continue
                    loser.status = ContentPlan.Status.MERGED
                    loser.merged_into = survivor
                    if survivor and not loser.canonical_key:
                        loser.canonical_key = survivor.canonical_key
                    loser.save(update_fields=["status", "merged_into", "canonical_key", "updated_at"])
                    merged += 1
                    # Keyword demand must survive the merge: union the loser's keyword
                    # evidence into the surviving row so the eventual article (or a
                    # regenerated brief) sees everything that was measured.
                    if survivor and loser.keywords:
                        seen = {
                            str(k.get("keyword", "")).strip().lower()
                            for k in (survivor.keywords or []) if isinstance(k, dict)
                        }
                        extra = [
                            k for k in loser.keywords
                            if isinstance(k, dict)
                            and str(k.get("keyword", "")).strip()
                            and str(k.get("keyword", "")).strip().lower() not in seen
                        ]
                        if extra:
                            survivor.keywords = list(survivor.keywords or []) + extra
                            survivor.save(update_fields=["keywords", "updated_at"])

        enriched = 0
        if opts["report"]:
            enriched = self._print_enrichment(report)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"done: {survived} reconciled, {merged} merged "
                f"({enriched} enrich-existing), {missing} missing-from-DB"
            )
        )
        if conflicts:
            self.stdout.write(self.style.WARNING(
                f"  ({conflicts} merge(s) skipped — loser already has a draft; resolve manually)"
            ))

    def _print_enrichment(self, report: dict) -> int:
        """Echo the report's enrichment ledger — which live page to optimize with
        which keyword demand. The row already left the queue (merged); this printed
        ledger + the report file are the content team's to-do list."""
        opportunities = report.get("enrichment_opportunities") or []
        if not opportunities:
            return 0
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"enrichment opportunities ({len(opportunities)}) — optimize these existing pages:"
        ))
        for opp in opportunities:
            kind = opp.get("target_kind", "plan")
            url = opp.get("target_url") or opp.get("target", "")
            title = opp.get("target_title", "")
            kws = opp.get("keywords") or []
            kw_preview = ", ".join(k.get("keyword", "") for k in kws[:5])
            more = f" (+{len(kws) - 5} more)" if len(kws) > 5 else ""
            self.stdout.write(
                f"  -> [{kind}] {url or title}: absorbed {len(opp.get('absorbed') or [])} "
                f"cluster(s), volume {opp.get('keyword_volume') or 0}"
            )
            if kw_preview:
                self.stdout.write(f"       keywords: {kw_preview}{more}")
        return len(opportunities)
