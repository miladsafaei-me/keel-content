"""``./manage.py contentplan_rejudge_scope --dump | --apply <grades.json>``

Re-grade a batch of ContentPlan rows on the 1-5 scope-relevance scale
(``ContentPlan.scope_relevance``). This is the data plumbing for a scope re-judge:
the LLM judgment itself runs OUTSIDE this command (an agent/workflow that reads the
dumped candidates + the consumer's scope doc and emits a grade per slug), matching
the house pattern where a JS workflow does the LLM work and a management command
persists it (cf. ``brief.workflow.js`` + ``contentplan_set_brief``).

Two mutually-exclusive modes:

- ``--dump`` — emit one JSON object per line (JSONL) of grading input for the
  selected rows: slug, title, intent, role, target, cluster, keyword evidence, the
  current grade, and a short body excerpt of the produced draft. Filter with
  ``--status`` (default ``drafted``) and ``--target`` (default ``blog``); write to
  ``--out FILE`` or stdout.
- ``--apply FILE`` — read grades (a JSON array OR JSONL of
  ``{"slug": ..., "scope_relevance": 1..5, "rationale": "..."}``), validate each
  level, and write ``scope_relevance`` onto the matching row. ``--dry-run`` prints
  the change set + the resulting distribution without saving. Idempotent; ``rationale``
  is echoed but not persisted (no column for it — the run's JSONL is the record).

The per-level meaning is defined in the consumer scope doc (SignalBots: BUSINESS.md
§2), never here — this command is business-blind.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host

ContentPlan = host.content_plan_model()

_VALID_LEVELS = {int(v) for v in ContentPlan.ScopeRelevance.values}
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _excerpt(post, limit: int = 600) -> str:
    """A short plain-text excerpt of the produced draft, for the grader to see what
    was actually written (markdown source preferred; HTML stripped as a fallback)."""
    if post is None:
        return ""
    raw = getattr(post, "content_markdown_source", "") or getattr(post, "content_raw", "") or ""
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", raw)).strip()
    return text[:limit]


class Command(BaseCommand):
    help = "Dump ContentPlan rows for scope re-judgment, or apply the resulting 1-5 grades."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dump", action="store_true", help="Emit grading candidates as JSONL.")
        mode.add_argument("--apply", metavar="FILE", help="Apply grades from a JSON/JSONL file.")
        parser.add_argument(
            "--status",
            default="drafted",
            help="Comma-separated ContentPlan statuses to dump (default: drafted).",
        )
        parser.add_argument(
            "--target",
            default="blog",
            help="ContentPlan target to dump (default: blog).",
        )
        parser.add_argument("--out", default="", help="--dump: write JSONL here instead of stdout.")
        parser.add_argument("--dry-run", action="store_true", help="--apply: report but do not save.")

    def handle(self, *args, **opts):
        if opts["dump"]:
            return self._dump(opts)
        return self._apply(opts)

    def _dump(self, opts) -> None:
        statuses = [s.strip() for s in (opts["status"] or "").split(",") if s.strip()]
        qs = (
            ContentPlan.objects.filter(target=opts["target"])
            .select_related("topic_cluster", "produced_post")
            .order_by("topic_cluster__slug", "slug")
        )
        if statuses:
            qs = qs.filter(status__in=statuses)

        lines = []
        for plan in qs:
            kws = [
                str(k.get("keyword", "")).strip()
                for k in (plan.keywords or [])
                if isinstance(k, dict) and str(k.get("keyword", "")).strip()
            ]
            lines.append(json.dumps({
                "slug": plan.slug,
                "title": plan.title,
                "h1": plan.h1,
                "intent": plan.intent,
                "intent_frame": plan.intent_frame,
                "entity": plan.entity,
                "role": plan.role,
                "target": plan.target,
                "status": plan.status,
                "cluster": plan.topic_cluster.name if plan.topic_cluster_id else "",
                "cluster_slug": plan.topic_cluster.slug if plan.topic_cluster_id else "",
                "keywords": kws[:10],
                "keyword_volume": plan.keyword_volume,
                "competitor_traffic": plan.competitor_traffic,
                "current_scope_relevance": plan.scope_relevance,
                "excerpt": _excerpt(plan.produced_post),
            }, ensure_ascii=False))

        payload = "\n".join(lines)
        if opts["out"]:
            Path(opts["out"]).expanduser().write_text(payload + "\n", encoding="utf-8")
            self.stderr.write(self.style.SUCCESS(f"dumped {len(lines)} candidate(s) -> {opts['out']}"))
        else:
            self.stdout.write(payload)

    def _apply(self, opts) -> None:
        path = Path(opts["apply"]).expanduser()
        if not path.is_file():
            raise CommandError(f"grades file not found: {path}")
        grades = self._read_grades(path)
        if not grades:
            raise CommandError("no grades parsed from file")

        dry = opts["dry_run"]
        updated = skipped_missing = skipped_same = invalid = 0
        dist: dict[int, int] = {}

        for entry in grades:
            slug = str(entry.get("slug", "")).strip()
            level = entry.get("scope_relevance")
            try:
                level = int(level)
            except (TypeError, ValueError):
                level = None
            if not slug or level not in _VALID_LEVELS:
                invalid += 1
                self.stderr.write(self.style.WARNING(f"  ! invalid entry: slug={slug!r} level={entry.get('scope_relevance')!r}"))
                continue
            plan = ContentPlan.objects.filter(slug=slug).first()
            if plan is None:
                skipped_missing += 1
                continue
            dist[level] = dist.get(level, 0) + 1
            if plan.scope_relevance == level:
                skipped_same += 1
                continue
            if dry:
                self.stdout.write(f"  ~ {slug}: {plan.scope_relevance} -> L{level}")
                updated += 1
                continue
            plan.scope_relevance = level
            plan.save(update_fields=["scope_relevance", "updated_at"])
            updated += 1

        shelved = sum(n for lvl, n in dist.items() if lvl >= ContentPlan.SCOPE_SHELF_FROM)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{'DRY-RUN — ' if dry else ''}applied {updated}, unchanged {skipped_same}, "
            f"missing {skipped_missing}, invalid {invalid}"
        ))
        dist_str = " ".join(f"L{lvl}={dist.get(lvl, 0)}" for lvl in sorted(_VALID_LEVELS))
        self.stdout.write(f"  distribution over graded set: {dist_str}  (shelved >=L{ContentPlan.SCOPE_SHELF_FROM}: {shelved})")

    @staticmethod
    def _read_grades(path: Path) -> list[dict]:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
        return out
