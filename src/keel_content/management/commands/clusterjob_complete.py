"""Close out a claimed keyword pool — the last step of the autopilot's ``cluster`` action.

Marks the pool clustered (or failed, or released back to the queue) and records what
it produced. This exists as its own command rather than being folded into
``contentplan_ingest`` on purpose: ingest is shared by five intake routes and must
not learn about a queue only one of them has.

    manage.py clusterjob_complete --slug binary-options-signals --produced 14 \
        --spec docs/seo/clusters/binary-options.spec.json
    manage.py clusterjob_complete --slug binary-options-signals --fail "SERP verify never finished"
    manage.py clusterjob_complete --slug binary-options-signals --release

``--release`` puts the pool back to ``queued`` WITHOUT clearing the attempt counter,
so a run that gives up honestly still counts against the retry cap. Only an operator
re-queueing deliberately (``--reset-attempts``) clears it.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from keel_content.host import cluster_job_model


class Command(BaseCommand):
    help = "Mark a claimed keyword pool clustered, failed, or released."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True)
        parser.add_argument("--produced", type=int, default=0, help="ContentPlan rows created")
        parser.add_argument("--spec", default="", help="path of the resolved cluster spec")
        parser.add_argument("--fail", default="", help="mark failed with this reason")
        parser.add_argument(
            "--release",
            action="store_true",
            help="return the pool to the queue without consuming it",
        )
        parser.add_argument(
            "--reset-attempts",
            action="store_true",
            help="clear the retry counter (operator action, not for the driver)",
        )
        parser.add_argument(
            "--skip",
            action="store_true",
            help="retire the pool without clustering it",
        )

    def handle(self, *args, **opts):
        Job = cluster_job_model()
        if Job is None:
            raise CommandError("this host has no clustering queue model configured")
        job = Job.objects.filter(slug=opts["slug"]).first()
        if job is None:
            raise CommandError(f"no pool '{opts['slug']}'")

        if opts["skip"]:
            job.status = Job.Status.SKIPPED
            job.completed_at = timezone.now()
        elif opts["fail"]:
            job.status = Job.Status.FAILED
            job.last_error = opts["fail"][:2000]
            job.completed_at = timezone.now()
        elif opts["release"]:
            job.status = Job.Status.QUEUED
            job.claimed_at = None
            # A released pool is waiting again, not broken. Leaving the previous run's
            # error on it would show a queued row flagged as failing, which reads as a
            # problem needing attention when the truth is "nobody has retried it yet".
            job.last_error = ""
        else:
            # A pool that clustered into nothing is not a success: it means the
            # analysis ran and found no producible content, which a human needs to
            # see rather than have it silently disappear from the queue as "done".
            if opts["produced"] <= 0:
                job.status = Job.Status.FAILED
                job.last_error = "clustering produced no content-plan rows"
            else:
                job.status = Job.Status.CLUSTERED
                job.last_error = ""
            job.produced_plan_count = max(0, opts["produced"])
            job.completed_at = timezone.now()

        if opts["reset_attempts"]:
            job.attempts = 0
        if opts["spec"]:
            job.spec_path = opts["spec"][:500]
        job.save()

        self.stdout.write(
            json.dumps({
                "slug": job.slug,
                "status": job.status,
                "produced": job.produced_plan_count,
                "attempts": job.attempts,
                "error": job.last_error or None,
            })
        )
