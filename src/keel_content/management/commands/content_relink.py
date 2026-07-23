"""Recompute blog->blog internal links for ALREADY-PUBLISHED pipeline posts.

The cluster-linking pass (``prompts/cluster-internal-links.md``) normally runs once,
at generation time, over a cluster's bundles. Published posts have no bundles, so this
command provides the equivalent round-trip for correcting live posts:

    manage.py content_relink export [--cluster NAME]      # DB -> JSON on stdout
    <an LLM linking pass writes the edge plan JSON>
    manage.py content_relink apply --plan PLAN.json --backup BACKUP.json [--dry-run]

``export`` emits, per topic cluster, each post's ``slug``/``role``/``title``/declared
``intent`` (+ scope fences) and a ``body_markdown`` with existing blog->blog links
stripped back to plain text — the exact shape the linking pass reads. ``apply`` takes
the pass's ``{"edges": {slug: [{anchor, target_slug}]}}`` plan, resets each post's body
to its clean state, inserts the new edges via the same deterministic ``apply_internal_links``
inserter used at publish, then rebuilds ``content_raw`` + ``content_rendered`` exactly as
``publish_from_bundle`` does. Self-links and edges to unknown slugs are dropped as a
deterministic backstop. Originals are written to ``--backup`` before any DB write.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from keel_content import host
from keel_content.core.internal_links import (
    apply_internal_links,
    strip_internal_blog_links,
)

ContentPlan = host.content_plan_model()
Post = host.post_model()


def _produced_plans(cluster: str | None):
    """ContentPlan rows that produced a live post, optionally filtered to one cluster."""
    qs = ContentPlan.objects.filter(produced_post_id__isnull=False).select_related(
        "topic_cluster"
    )
    if cluster:
        qs = qs.filter(topic_cluster__name=cluster)
    return list(qs)


class Command(BaseCommand):
    help = "Export/apply blog->blog internal-link plans for published pipeline posts."

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=["export", "apply"])
        parser.add_argument("--cluster", default=None, help="Limit export to one topic cluster name.")
        parser.add_argument("--plan", default=None, help="apply: path to the edge-plan JSON.")
        parser.add_argument("--backup", default=None, help="apply: path to write originals before mutating.")
        parser.add_argument("--dry-run", action="store_true", help="apply: report without writing.")

    def handle(self, *args, **opts):
        if opts["mode"] == "export":
            return self._export(opts["cluster"])
        return self._apply(opts["plan"], opts["backup"], opts["dry_run"])

    def _export(self, cluster: str | None):
        plans = _produced_plans(cluster)
        posts = {p.id: p for p in Post.objects.filter(id__in=[pl.produced_post_id for pl in plans])}
        clusters: dict[str, dict] = {}
        for pl in plans:
            post = posts.get(pl.produced_post_id)
            if post is None:
                continue
            name = pl.topic_cluster.name if pl.topic_cluster_id else "(none)"
            bucket = clusters.setdefault(name, {"name": name, "posts": []})
            bucket["posts"].append(
                {
                    "slug": post.slug,
                    "role": pl.role or "spoke",
                    "title": post.title,
                    "intent": pl.intent or "",
                    "observed_intent": pl.observed_intent or "",
                    "scope_includes": list(pl.scope_includes or []),
                    "scope_excludes": list(pl.scope_excludes or []),
                    "body_markdown": strip_internal_blog_links(post.content_markdown_source or ""),
                }
            )
        self.stdout.write(json.dumps({"clusters": list(clusters.values())}, ensure_ascii=False))

    def _apply(self, plan_path: str | None, backup_path: str | None, dry_run: bool):
        if not plan_path:
            raise CommandError("apply requires --plan PATH")
        if not dry_run and not backup_path:
            raise CommandError("apply requires --backup PATH (omit only with --dry-run)")
        with open(plan_path, encoding="utf-8") as fh:
            edges_by_slug = (json.load(fh) or {}).get("edges") or {}

        valid_slugs = set(Post.objects.values_list("slug", flat=True))
        posts = {p.slug: p for p in Post.objects.filter(slug__in=list(edges_by_slug))}

        if not dry_run:
            backup = {
                slug: (posts[slug].content_markdown_source or "")
                for slug in edges_by_slug
                if slug in posts
            }
            with open(backup_path, "w", encoding="utf-8") as fh:
                json.dump(backup, fh, ensure_ascii=False, indent=2)

        totals = {"posts": 0, "inserted": 0, "dropped_self": 0, "dropped_unknown": 0, "skipped": 0}
        for slug, edges in edges_by_slug.items():
            post = posts.get(slug)
            if post is None:
                self.stderr.write(f"skip: no post for source slug {slug!r}")
                continue
            resolved = []
            for e in edges or []:
                target = (e.get("target_slug") or "").strip()
                anchor = (e.get("anchor") or "").strip()
                if not anchor or not target:
                    continue
                if target == slug:
                    totals["dropped_self"] += 1
                    continue
                if target not in valid_slugs:
                    totals["dropped_unknown"] += 1
                    continue
                resolved.append({"anchor": anchor, "target_url": f"/blog/{target}"})

            clean = strip_internal_blog_links(post.content_markdown_source or "")
            new_md, report = apply_internal_links(clean, resolved)
            totals["posts"] += 1
            totals["inserted"] += len(report.applied)
            totals["skipped"] += len(report.skipped)

            self.stdout.write(
                f"{slug}: {len(report.applied)} inserted, {len(report.skipped)} skipped"
                + (" [dry-run]" if dry_run else "")
            )
            if dry_run:
                continue
            post.content_markdown_source = new_md
            post.content_raw = host.prepare_pipeline_content_for_storage(new_md)
            post.save(update_fields=["content_markdown_source", "content_raw"])
            host.refresh_article_rendered(post)

        self.stdout.write(self.style.SUCCESS(json.dumps(totals)))
