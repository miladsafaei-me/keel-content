"""``./manage.py contentplan_ingest_clusters --manifest <path>`` — retro-cluster an
already-published corpus from an authored assignment manifest. Deterministic.

A corpus migrated from another CMS arrives with no ``TopicCluster`` membership at
all, and nothing downstream works without it: the reconcile engine compares within
a cluster, the linking pass draws its candidates from cluster mates, and the
reading-path widget has no path to render. ``contentplan_backfill`` reconstructs a
plan row per post but cannot invent the topical structure — that is a judgement.

So the judgement is made outside (read the titles, propose a taxonomy, assign each
post) and lands here as a manifest. This command only applies it, and validates
rather than trusts: an unknown cluster slug is rejected, an unknown post slug is
reported and skipped, and a cluster is created only when ``--create-clusters`` says
so, so a typo in the manifest cannot quietly spawn a junk cluster.

Manifest shape (a bare list, or ``{"assignments": [...]}``)::

    [{"slug": "post-slug", "cluster": "cluster-slug", "role": "spoke"}]

Optional ``--taxonomy`` supplies display names and is the ONLY source of valid
cluster slugs when creating: ``{"clusters": [{"slug": ..., "name_fa": ...}]}``.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host

VALID_ROLES = {"pillar", "spoke"}


class Command(BaseCommand):
    help = "Apply an authored cluster-assignment manifest onto ContentPlan + Post rows."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument(
            "--taxonomy", default="",
            help="Taxonomy JSON supplying cluster display names; also the allow-list "
                 "of cluster slugs when --create-clusters is used.",
        )
        parser.add_argument(
            "--create-clusters", action="store_true",
            help="Create missing TopicCluster rows named in the taxonomy. Without "
                 "this, a manifest naming an absent cluster is an error, not a create.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["manifest"]).expanduser()
        if not path.is_file():
            raise CommandError(f"no manifest at {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("assignments") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise CommandError('manifest must be a list, or {"assignments": [...]}')

        names: dict[str, str] = {}
        allowed: set[str] | None = None
        if opts["taxonomy"]:
            tax = json.loads(Path(opts["taxonomy"]).expanduser().read_text(encoding="utf-8"))
            clusters = tax.get("clusters") or []
            names = {c["slug"]: (c.get("name_fa") or c.get("name") or c["slug"]) for c in clusters}
            allowed = set(names)

        ContentPlan = host.content_plan_model()
        TopicCluster = host.topic_cluster_model()
        Post = host.post_model()

        wanted = {(r.get("cluster") or "").strip() for r in rows if isinstance(r, dict)}
        wanted.discard("")
        if allowed is not None:
            stray = wanted - allowed
            if stray:
                raise CommandError(
                    f"manifest names {len(stray)} cluster(s) absent from the taxonomy: "
                    f"{sorted(stray)[:5]}. Refusing — a typo must not create a cluster."
                )

        existing = {c.slug: c for c in TopicCluster.objects.filter(slug__in=wanted)}
        missing = sorted(wanted - set(existing))
        if missing and not opts["create_clusters"]:
            raise CommandError(
                f"{len(missing)} cluster(s) do not exist: {missing[:5]}. Re-run with "
                "--create-clusters to create them from the taxonomy."
            )
        created_clusters = 0
        for slug in missing:
            if not opts["dry_run"]:
                existing[slug] = TopicCluster.objects.create(
                    slug=slug, name=names.get(slug, slug)
                )
            created_clusters += 1

        plans = {p.slug: p for p in ContentPlan.objects.select_related("produced_post")}
        assigned = skipped = 0
        unknown_posts: list[str] = []
        bad_role: list[str] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            slug = (r.get("slug") or "").strip()
            cslug = (r.get("cluster") or "").strip()
            role = (r.get("role") or "spoke").strip().lower()
            if not slug or not cslug:
                continue
            if role not in VALID_ROLES:
                bad_role.append(f"{slug}:{role}")
                continue
            plan = plans.get(slug)
            if plan is None:
                unknown_posts.append(slug)
                continue
            cluster = existing.get(cslug)
            if cluster is None and opts["dry_run"]:
                assigned += 1
                continue
            if plan.topic_cluster_id == getattr(cluster, "id", None) and plan.role == role:
                skipped += 1
                continue
            if not opts["dry_run"]:
                plan.topic_cluster = cluster
                plan.role = role
                plan.save(update_fields=["topic_cluster", "role"])
                # The Post carries the membership the public reading-path widget
                # reads; the plan row alone would leave the site unchanged.
                post = plan.produced_post
                if post is not None and hasattr(post, "topic_cluster_id"):
                    post.topic_cluster = cluster
                    post.save(update_fields=["topic_cluster"])
            assigned += 1

        for s in unknown_posts:
            self.stderr.write(self.style.WARNING(f"unknown post slug, skipped: {s}"))
        for b in bad_role:
            self.stderr.write(self.style.ERROR(f"rejected — role not in {sorted(VALID_ROLES)}: {b}"))
        tail = " [dry-run]" if opts["dry_run"] else ""
        self.stderr.write(self.style.SUCCESS(
            f"assigned {assigned}, unchanged {skipped}, clusters created "
            f"{created_clusters}, {len(unknown_posts)} unknown post(s), "
            f"{len(bad_role)} bad role(s){tail}"
        ))
