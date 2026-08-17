"""Claim one keyword pool and write its keywords out for the clustering tools.

The autopilot's ``cluster`` action starts here. Claiming is atomic and bumps the
attempt counter in the same transaction, so a run that dies mid-pool can never be
retried forever: after ``CLUSTER_MAX_ATTEMPTS`` the pool stops being offered and the
loop moves on to content production instead of wedging behind it.

    manage.py clusterjob_claim --slug binary-options-signals --out /tmp/pool.csv

Writes a two-column ``keyword,volume`` CSV — the exact shape ``cluster_xlsx.py prep``
reads — and prints a JSON receipt describing what was claimed. Nothing here decides
anything about the keywords; the judgment happens in the clustering workflow the
driver runs next.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from keel_content.host import cluster_job_model
from keel_content.management.commands.content_next_action import CLUSTER_MAX_ATTEMPTS


class Command(BaseCommand):
    help = "Claim a keyword pool from the clustering queue and dump its keywords."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="", help="pool to claim (default: highest demand)")
        parser.add_argument("--out", required=True, help="path for the keyword CSV")
        parser.add_argument(
            "--prep-dir",
            default="",
            help="recorded on the job so a failed run leaves a readable trail",
        )

    def handle(self, *args, **opts):
        Job = cluster_job_model()
        if Job is None:
            raise CommandError("this host has no clustering queue model configured")

        with transaction.atomic():
            qs = Job.objects.select_for_update().filter(attempts__lt=CLUSTER_MAX_ATTEMPTS)
            if opts["slug"]:
                job = qs.filter(slug=opts["slug"]).first()
                if job is None:
                    raise CommandError(
                        f"no claimable pool '{opts['slug']}' "
                        f"(missing, or it has burned its {CLUSTER_MAX_ATTEMPTS} attempts)"
                    )
            else:
                # Same ordering the decision pass uses, so an unslugged claim picks the
                # pool the autopilot just named rather than a different one.
                job = (
                    qs.filter(status__in=("queued", "clustering"))
                    .order_by("-priority", "-created_at")
                    .first()
                )
                if job is None:
                    self.stdout.write(json.dumps({"claimed": None, "reason": "queue empty"}))
                    return

            rows = job.keyword_rows()
            if not rows:
                job.status = Job.Status.FAILED
                job.last_error = "pool holds no usable keywords"
                job.completed_at = timezone.now()
                job.save(update_fields=["status", "last_error", "completed_at", "updated_at"])
                raise CommandError(f"pool '{job.slug}' holds no usable keywords; marked failed")

            job.status = Job.Status.CLUSTERING
            job.attempts = (job.attempts or 0) + 1
            job.claimed_at = timezone.now()
            if opts["prep_dir"]:
                job.prep_dir = opts["prep_dir"][:500]
            job.save(
                update_fields=[
                    "status", "attempts", "claimed_at", "prep_dir", "updated_at",
                ]
            )

        out = Path(opts["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["keyword", "volume"])
            writer.writerows(rows)

        self.stdout.write(
            json.dumps({
                "claimed": job.slug,
                "label": job.label,
                "market": job.market,
                "keywords": len(rows),
                "attempt": job.attempts,
                "max_attempts": CLUSTER_MAX_ATTEMPTS,
                "csv": str(out),
            })
        )
