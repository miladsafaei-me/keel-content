"""Deposit a keyword pool into the clustering queue — the queue's only write path in.

Takes keyword-research output (whatever produced it: a Search Console export, a
Semrush workbook converted to JSON, a hand-written list) and parks it as one
``KeywordClusterJob`` for the autopilot to drain. It deliberately does NOT cluster
anything: that is a judgment pass, and this command is the dumb deposit step so the
material becomes durable the moment it exists instead of living in a file someone
has to remember.

    manage.py clusterjob_ingest pool.json --source-type search_console

The input is either a bare list of keywords or an object carrying one::

    {"label": "binary options signals", "market": "binary-options",
     "keywords": [{"keyword": "...", "volume": 120}, "bare string is fine too"]}

Re-ingesting the same slug MERGES keywords into the existing pool rather than
replacing it, so a second export of an overlapping query set grows the pool instead
of silently dropping either half. A pool already clustered is left alone unless
``--replace``, mirroring how ``contentplan_ingest`` protects produced rows.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from keel_content.host import cluster_job_model

# Terminal states: the pool was already turned into content plans, or a human ruled
# it out. Re-depositing over either would quietly re-do settled work.
_SETTLED = ("clustered", "skipped")


def _normalize(raw) -> list[dict]:
    """Accept bare strings or dicts; emit the stored ``{keyword, volume, ...}`` shape."""
    out, seen = [], set()
    for item in raw or []:
        if isinstance(item, str):
            item = {"keyword": item}
        if not isinstance(item, dict):
            continue
        term = str(item.get("keyword", "")).strip()
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())
        row = {"keyword": term}
        for key in ("volume", "impressions", "clicks", "position"):
            if item.get(key) is not None:
                row[key] = item[key]
        out.append(row)
    return out


def _demand(keywords: list[dict]) -> float:
    """Summed demand — real volume when we have it, impressions when GSC is all we get."""
    total = 0.0
    for kw in keywords:
        value = kw.get("volume")
        if value is None:
            value = kw.get("impressions", 0)
        try:
            total += float(value or 0)
        except (TypeError, ValueError):
            continue
    return total


def upsert_cluster_job(
    *,
    label: str,
    keywords,
    slug: str = "",
    market: str = "",
    source_type: str = "manual",
    source_ref: str = "",
    notes: str = "",
    replace: bool = False,
):
    """Upsert one keyword pool. Returns ``(job, outcome)``.

    Shared by this command and by any host-side caller that deposits a pool straight
    from a UI, so the merge/settle rules live in exactly one place.
    """
    Job = cluster_job_model()
    if Job is None:
        raise CommandError("this host has no clustering queue model configured")

    slug = (slug or slugify(label or "")).strip()[:255]
    if not slug:
        return None, "skipped"
    rows = _normalize(keywords)
    if not rows:
        return None, "skipped-empty"

    job = Job.objects.filter(slug=slug).first()
    if job and job.status in _SETTLED and not replace:
        return job, "settled"

    if job is None:
        job = Job(slug=slug, source_type=source_type, source_ref=source_ref)
        merged = rows
        outcome = "created"
    else:
        # Merge, keyed on the lowercased term: a re-export overlapping the last one
        # should grow the pool, and the incoming row wins on conflict because it
        # carries the fresher metrics.
        by_term = {r["keyword"].lower(): r for r in (job.keywords or []) if isinstance(r, dict)}
        by_term.update({r["keyword"].lower(): r for r in rows})
        merged = list(by_term.values())
        outcome = "updated"
        if replace:
            merged = rows
            job.status = Job.Status.QUEUED
            job.attempts = 0
            job.last_error = ""

    job.label = (label or job.label or slug)[:255]
    job.market = (market or job.market or "")[:64]
    job.keywords = merged
    job.priority = _demand(merged)
    if notes:
        job.notes = notes
    if source_ref:
        job.source_ref = source_ref[:500]
    job.save()
    return job, outcome


class Command(BaseCommand):
    help = "Deposit a keyword pool into the clustering queue."

    def add_arguments(self, parser):
        parser.add_argument("path", help="JSON file: a keyword list, or an object holding one")
        parser.add_argument("--slug", default="", help="pool slug (default: slugified label)")
        parser.add_argument("--label", default="", help="human name for the pool")
        parser.add_argument("--market", default="", help="scaffold market slug")
        parser.add_argument("--source-type", default="manual")
        parser.add_argument("--source-ref", default="")
        parser.add_argument("--notes", default="")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="overwrite an already-clustered pool and requeue it",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.exists():
            raise CommandError(f"no such file: {path}")
        try:
            doc = json.loads(path.read_text())
        except ValueError as exc:
            raise CommandError(f"{path} is not valid JSON: {exc}") from exc

        if isinstance(doc, list):
            doc = {"keywords": doc}
        if not isinstance(doc, dict):
            raise CommandError("expected a JSON list or object")

        label = opts["label"] or doc.get("label") or path.stem
        keywords = doc.get("keywords") or doc.get("queries") or []
        rows = _normalize(keywords)
        if not rows:
            raise CommandError("no usable keywords in the input")

        if opts["dry_run"]:
            self.stdout.write(
                json.dumps({
                    "dry_run": True,
                    "slug": opts["slug"] or slugify(label),
                    "label": label,
                    "keywords": len(rows),
                    "priority": _demand(rows),
                })
            )
            return

        job, outcome = upsert_cluster_job(
            label=label,
            keywords=keywords,
            slug=opts["slug"] or doc.get("slug", ""),
            market=opts["market"] or doc.get("market", ""),
            source_type=opts["source_type"],
            source_ref=opts["source_ref"] or str(path),
            notes=opts["notes"],
            replace=opts["replace"],
        )
        self.stdout.write(
            json.dumps({
                "outcome": outcome,
                "slug": getattr(job, "slug", None),
                "keywords": getattr(job, "keyword_count", 0),
                "status": getattr(job, "status", None),
            })
        )
