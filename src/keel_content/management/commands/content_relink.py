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

``--scope`` (default ``cluster``) selects which round-trip runs:

- ``cluster`` (default, unchanged from before ``--scope`` existed): the within-cluster
  round-trip above — candidates are the source post's own cluster mates.
- ``cross-cluster`` (see ``prompts_default/cross-cluster-links.md``, the P1.2 pass):
  ``export`` offers, per source post, the PILLAR of every OTHER active
  ``TopicCluster`` as its only candidates — never a spoke, never the source's own
  cluster. ``apply`` enforces a hard ceiling of 2 accepted cross-cluster edges per
  source article, and consults the P1.1 site-wide anchor registry
  (``core/anchor_registry.py``) once per invocation — never per anchor, per that
  module's own documented reuse contract — rejecting (and reporting, never silently
  dropping) any edge whose anchor is already claimed by a different target or is
  itself conflicted across the corpus.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from keel_content import host
from keel_content.core.anchor_registry import AnchorRegistry, normalize_anchor, scan_anchor_registry
from keel_content.core.internal_links import (
    apply_internal_links,
    strip_internal_blog_links,
)

ContentPlan = host.content_plan_model()
Post = host.post_model()

# Mirrors internal_links._MAX_LINKS_PER_ARTICLE's role as a runaway guard, but this
# ceiling is specific to the cross-cluster pass and much tighter: pillar-to-pillar
# edges are the ones most likely to over-link a site (see cross-cluster-links.md), so
# they get their own hard cap that is enforced here, on top of (not instead of) the
# inserter's own 8-per-article ceiling downstream.
_MAX_CROSS_CLUSTER_EDGES_PER_ARTICLE = 2


def _produced_plans(cluster: str | None):
    """ContentPlan rows that produced a post which can reach the live site.

    A shelved row (``scope_relevance >= SCOPE_SHELF_FROM``) is never published — the
    publish autopilot excludes it by the same test — so a post produced before its row
    was shelved is a permanent draft. Wiring it into the link graph pointed live
    articles at a URL that 404s and always would, and spent edges from the plan's
    per-article ceiling on a dead target. ``human_only`` rows are excluded for the
    same reason the stamp below excludes them: the loop never produces them, so they
    are not part of the set the relink gate reasons about.

    Keeping this filter identical to ``_stamp``'s count is what lets the marker and
    the graph describe the same cluster; they drifted apart once already.
    """
    qs = (
        ContentPlan.objects.filter(produced_post_id__isnull=False)
        .exclude(feasibility="human_only")
        .exclude(scope_relevance__gte=ContentPlan.SCOPE_SHELF_FROM)
        .select_related("topic_cluster")
    )
    if cluster:
        qs = qs.filter(topic_cluster__name=cluster)
    return list(qs)


def _active_cluster_pillars() -> dict:
    """``{topic_cluster_id: candidate-pillar dict}`` for every active cluster with a pillar.

    Built once per export call and filtered per source post below rather than
    requeried per post — the candidate pool (every other active cluster's pillar) is
    the same set for every source article in the export, so there is exactly one
    query here, the same "scan once, reuse" posture ``anchor_registry.py`` documents
    for its own registry.
    """
    TopicCluster = host.topic_cluster_model()
    clusters = (
        TopicCluster.objects.filter(status="active", pillar__isnull=False)
        .select_related("pillar")
        .order_by("name")
    )
    out = {}
    for tc in clusters:
        pillar_post = tc.pillar
        plan = getattr(pillar_post, "content_plan", None)
        out[tc.id] = {
            "cluster": tc.name,
            "slug": pillar_post.slug,
            "title": pillar_post.title,
            "intent": (plan.intent if plan else "") or "",
            "scope_includes": list(plan.scope_includes or []) if plan else [],
            "scope_excludes": list(plan.scope_excludes or []) if plan else [],
        }
    return out


def _registry_verdict(registry: AnchorRegistry, anchor: str, target_url: str) -> str | None:
    """``None`` if ``anchor`` may be used for ``target_url``, else a rejection reason.

    Consults the already-built :class:`AnchorRegistry` passed in — this function never
    rescans the corpus itself, matching the reuse contract ``anchor_registry.py``
    documents (build once per pass, call ``.claimed_target``/inspect ``.counts`` many
    times). An anchor the registry has never seen is free to claim. An anchor already
    claimed by this SAME target is not a new claim and passes through. An anchor
    claimed by a DIFFERENT target, or one that is itself conflicted (mapped to more
    than one target already), is cannibalization at the internal-link layer and is
    rejected here rather than silently overwritten.
    """
    norm = normalize_anchor(anchor)
    targets = registry.counts.get(norm)
    if not targets:
        return None
    if len(targets) > 1:
        return "anchor is conflicted in the anchor registry"
    target_key = target_url.strip().rstrip("/").lower()
    (only_target,) = targets
    if only_target != target_key:
        return f"anchor already claimed by {only_target!r}"
    return None


class Command(BaseCommand):
    help = "Export/apply blog->blog internal-link plans for published pipeline posts."

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=["export", "apply"])
        parser.add_argument("--cluster", default=None, help="Limit export to one topic cluster name.")
        parser.add_argument("--plan", default=None, help="apply: path to the edge-plan JSON.")
        parser.add_argument("--backup", default=None, help="apply: path to write originals before mutating.")
        parser.add_argument("--dry-run", action="store_true", help="apply: report without writing.")
        parser.add_argument(
            "--scope",
            choices=["cluster", "cross-cluster"],
            default="cluster",
            help="'cluster' (default, unchanged): within-cluster round-trip against the "
            "source post's own cluster mates. 'cross-cluster': pillar-to-pillar edges "
            "against every OTHER active cluster's pillar, capped at 2 accepted edges "
            "per source article and checked against the site-wide anchor registry.",
        )

    def handle(self, *args, **opts):
        if opts["mode"] == "export":
            return self._export(opts["cluster"], opts["scope"])
        return self._apply(opts["plan"], opts["backup"], opts["dry_run"], opts["cluster"], opts["scope"])

    def _export(self, cluster: str | None, scope: str = "cluster"):
        if scope == "cross-cluster":
            return self._export_cross_cluster(cluster)
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

    def _export_cross_cluster(self, cluster: str | None):
        """Per source post, offer the pillar of every OTHER active cluster as candidates.

        Deliberately never the source's own cluster mates (that is the ``cluster``
        scope's job) and never a spoke of another cluster (``cross-cluster-links.md``'s
        hard "pillar-to-pillar only" rule) — a spoke is simply never in the candidate
        pool this builds. ``--cluster`` here still means "limit which SOURCE posts are
        exported", exactly as it does in the default scope; it does not limit the
        candidate pool, which is always every other active cluster's pillar.
        """
        plans = _produced_plans(cluster)
        posts = {p.id: p for p in Post.objects.filter(id__in=[pl.produced_post_id for pl in plans])}
        pillars = _active_cluster_pillars()

        out_posts = []
        for pl in plans:
            post = posts.get(pl.produced_post_id)
            if post is None:
                continue
            candidates = [
                entry for tc_id, entry in pillars.items() if tc_id != pl.topic_cluster_id
            ]
            out_posts.append(
                {
                    "slug": post.slug,
                    "title": post.title,
                    "intent": pl.intent or "",
                    "cluster": pl.topic_cluster.name if pl.topic_cluster_id else "(none)",
                    "body_markdown": strip_internal_blog_links(post.content_markdown_source or ""),
                    "candidate_pillars": candidates,
                }
            )
        self.stdout.write(json.dumps({"posts": out_posts}, ensure_ascii=False))

    def _stamp(self, cluster: str | None, dry_run: bool) -> None:
        """Record that this cluster has been relinked at its current article count.

        The autopilot needs a durable, self-limiting answer to "is this cluster
        already wired?" — otherwise a finished cluster would be re-planned on every
        tick forever. The marker lives in ``TopicCluster.brief`` (already a JSONField,
        so no migration) and stores the produced-article count it was computed at, so
        adding a later article to the cluster naturally re-arms it exactly once.

        The count MUST be taken over the same row set ``content_next_action``'s relink
        gate walks, because that gate is the marker's only reader and it compares the
        two numbers for equality. It skips rows that are ``human_only`` or shelved
        (``scope_relevance >= SCOPE_SHELF_FROM``); counting them here produced a marker
        the gate could never match, so a cluster holding even one shelved-but-produced
        row was rescheduled on every tick forever and re-running ``apply`` only rewrote
        the same unmatchable number.
        """
        if not cluster or dry_run:
            return
        TopicCluster = host.topic_cluster_model()
        tc = TopicCluster.objects.filter(slug=cluster).first() or TopicCluster.objects.filter(name=cluster).first()
        if tc is None:
            self.stderr.write(f"cluster {cluster!r} not found — marker not written")
            return
        rows = (
            ContentPlan.objects.filter(topic_cluster=tc, target="blog", produced_post__isnull=False)
            .exclude(feasibility="human_only")
            .exclude(scope_relevance__gte=ContentPlan.SCOPE_SHELF_FROM)
            .select_related("produced_post")
        )
        produced = rows.count()
        # The published count re-arms the pass ONCE MORE, when the cluster finishes
        # going live. Production runs weeks ahead of the publish quota, so the graph
        # written here necessarily links articles that are still drafts, and a draft
        # URL 404s: measured 2026-08-19, 38 such links sat in 26 live articles. Those
        # heal as the targets publish, but the anchor text was chosen against a set
        # that was only partly live, so one pass over the fully-live cluster is what
        # makes the graph describe what a reader can actually reach. It cannot loop:
        # the gate re-arms on a CHANGED count, and a fully-published cluster's count
        # stops moving.
        published = sum(
            1 for r in rows if r.produced_post and r.produced_post.status == "published"
        )
        brief = dict(tc.brief or {})
        brief["relinked"] = {"articles": produced, "published": published}
        tc.brief = brief
        tc.save(update_fields=["brief"])
        self.stdout.write(
            f"marked {tc.slug} relinked at {produced} article(s), {published} published"
        )

    def _apply(
        self,
        plan_path: str | None,
        backup_path: str | None,
        dry_run: bool,
        cluster: str | None = None,
        scope: str = "cluster",
    ):
        if not plan_path:
            raise CommandError("apply requires --plan PATH")
        if not dry_run and not backup_path:
            raise CommandError("apply requires --backup PATH (omit only with --dry-run)")
        with open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh) or {}
        edges_by_slug = plan.get("edges") or {}
        # Built ONCE for the whole apply run, never per anchor/per post — the exact
        # reuse contract anchor_registry.py documents for AnchorRegistry. Only needed
        # in cross-cluster scope; the default scope never touches the registry, which
        # is part of what keeps its behavior byte-identical to before --scope existed.
        registry = scan_anchor_registry() if scope == "cross-cluster" else None
        # OPTIONAL surgical rewrites. apply_internal_links can only link a phrase that
        # already exists in the prose — it matches the anchor verbatim and otherwise
        # reports "anchor not found". So a genuinely useful edge whose anchor has no
        # natural host used to be silently unlinkable. A rewrite is the smallest
        # possible fix: ONE sentence replaced by a version that carries the phrase.
        # Deliberately NOT a body rewrite — the rest of the article is untouched, the
        # match is exact, and anything that does not match exactly once is skipped and
        # reported rather than guessed at.
        rewrites_by_slug = plan.get("rewrites") or {}

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

        totals = {"posts": 0, "inserted": 0, "dropped_self": 0, "dropped_unknown": 0,
                  "skipped": 0, "rewrites": 0, "rewrites_skipped": 0}
        if scope == "cross-cluster":
            totals["dropped_ceiling"] = 0
            totals["dropped_registry"] = 0
        for slug, edges in edges_by_slug.items():
            post = posts.get(slug)
            if post is None:
                self.stderr.write(f"skip: no post for source slug {slug!r}")
                continue
            resolved = []
            cross_accepted = 0
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
                target_url = f"/blog/{target}"
                if scope == "cross-cluster":
                    if cross_accepted >= _MAX_CROSS_CLUSTER_EDGES_PER_ARTICLE:
                        totals["dropped_ceiling"] += 1
                        self.stderr.write(
                            f"  {slug}: edge {anchor!r} -> {target} rejected "
                            f"(cross-cluster ceiling of {_MAX_CROSS_CLUSTER_EDGES_PER_ARTICLE} reached)"
                        )
                        continue
                    verdict = _registry_verdict(registry, anchor, target_url)
                    if verdict:
                        totals["dropped_registry"] += 1
                        self.stderr.write(f"  {slug}: edge {anchor!r} -> {target} rejected ({verdict})")
                        continue
                    cross_accepted += 1
                resolved.append({"anchor": anchor, "target_url": target_url})

            clean = strip_internal_blog_links(post.content_markdown_source or "")
            for rw in rewrites_by_slug.get(slug) or []:
                find = (rw.get("find") or "").strip()
                repl = (rw.get("replace") or "").strip()
                if not find or not repl:
                    continue
                hits = clean.count(find)
                if hits != 1:
                    totals["rewrites_skipped"] += 1
                    self.stderr.write(
                        f"  rewrite skipped in {slug}: source sentence matched {hits} time(s), need exactly 1"
                    )
                    continue
                clean = clean.replace(find, repl, 1)
                totals["rewrites"] += 1
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
        # The "relinked at N articles" marker is a within-cluster autopilot concept
        # (content_next_action's relink gate reads it per cluster); the cross-cluster
        # pass has no equivalent per-cluster completion notion, so it never stamps.
        if scope == "cluster":
            self._stamp(cluster, dry_run)
