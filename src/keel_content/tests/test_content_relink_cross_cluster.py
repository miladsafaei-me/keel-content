"""Tests for ``content_relink``'s ``--scope`` option (P1.2, cross-cluster linking).

DB-backed (``TestCase``, not ``SimpleTestCase``): ``content_relink`` reaches
``Post``/``ContentPlan``/``TopicCluster`` through ``keel_content.host``, so these
tests build real fixtures via the host accessors and drive the management command
through ``call_command`` exactly the way a caller would, the same posture
``anchor_registry_report`` would need if it had DB-backed tests.

Two concerns, one file:

1. **Regression guard** (``ContentRelinkScopeRegressionTests``): omitting ``--scope``
   must behave byte-identically to the pre-``--scope`` command — same export shape,
   same ``apply`` totals-dict keys, no registry scan, no ceiling.
2. **The new cross-cluster mode** (``CrossClusterExportTests`` /
   ``CrossClusterApplyTests``): export offers only pillars of OTHER active clusters,
   never a spoke and never the source's own cluster; apply enforces the 2-edge
   ceiling and consults the P1.1 anchor registry, rejecting (and reporting) a
   claimed-by-another-target anchor and a conflicted anchor.
"""

from __future__ import annotations

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from keel_content import host


class _RelinkTestBase(TestCase):
    """Shared fixture helpers — no assertions live here."""

    def _author(self, slug):
        Author = host.author_model()
        return Author.objects.create(name=f"Author {slug}", slug=slug)

    def _make_post(self, slug, title, body="", status="draft", author=None):
        Post = host.post_model()
        return Post.objects.create(
            title=title,
            slug=slug,
            author=author or self.author,
            status=status,
            content_markdown_source=body,
        )

    def _make_cluster(self, name, slug, status="active", pillar=None):
        TopicCluster = host.topic_cluster_model()
        return TopicCluster.objects.create(name=name, slug=slug, status=status, pillar=pillar)

    def _make_plan(self, slug, title, *, intent="", role="", topic_cluster=None,
                   produced_post=None, scope_includes=None, scope_excludes=None):
        ContentPlan = host.content_plan_model()
        return ContentPlan.objects.create(
            slug=slug,
            title=title,
            intent=intent,
            role=role,
            topic_cluster=topic_cluster,
            produced_post=produced_post,
            scope_includes=scope_includes or [],
            scope_excludes=scope_excludes or [],
            source_type="manual",
            target="blog",
        )

    def _write_plan(self, data: dict) -> str:
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, fh)
        fh.close()
        self.addCleanup(lambda: Path(fh.name).unlink(missing_ok=True))
        return fh.name

    def _apply(self, plan: dict, **opts) -> tuple[dict, str]:
        """Run ``apply`` in dry-run mode, return ``(totals_dict, stderr_text)``."""
        plan_path = self._write_plan(plan)
        out, err = StringIO(), StringIO()
        opts.setdefault("dry_run", True)
        call_command("content_relink", "apply", plan=plan_path, stdout=out, stderr=err, **opts)
        lines = out.getvalue().strip().splitlines()
        totals = json.loads(lines[-1])
        return totals, err.getvalue()


class ContentRelinkScopeRegressionTests(_RelinkTestBase):
    """Test 1 — omitting --scope must be byte-identical to --scope cluster (default)."""

    def setUp(self):
        self.author = self._author("regress-author")
        self.cluster = self._make_cluster("Regression Cluster", "regression-cluster")
        self.pillar_post = self._make_post(
            "regression-pillar", "Regression Pillar", status="published",
            body="This is the pillar. See spoke content for details.",
        )
        self.spoke_post = self._make_post(
            "regression-spoke", "Regression Spoke", status="published",
            body="This spoke covers pillar content deeply.",
        )
        self.cluster.pillar = self.pillar_post
        self.cluster.save(update_fields=["pillar"])
        self._make_plan(
            "regression-pillar-plan", "Regression Pillar", intent="pillar intent",
            role="pillar", topic_cluster=self.cluster, produced_post=self.pillar_post,
        )
        self._make_plan(
            "regression-spoke-plan", "Regression Spoke", intent="spoke intent",
            role="spoke", topic_cluster=self.cluster, produced_post=self.spoke_post,
        )

    def _export(self, **kwargs):
        out = StringIO()
        call_command("content_relink", "export", cluster="Regression Cluster", stdout=out, **kwargs)
        return json.loads(out.getvalue())

    def test_omitted_scope_export_matches_explicit_cluster_scope(self):
        default_result = self._export()
        explicit_result = self._export(scope="cluster")
        self.assertEqual(default_result, explicit_result)

        # And the shape itself is exactly the pre-existing one: grouped by "clusters",
        # each post carrying the original field set, nothing added or removed.
        self.assertEqual(list(default_result.keys()), ["clusters"])
        cluster_entry = default_result["clusters"][0]
        self.assertEqual(cluster_entry["name"], "Regression Cluster")
        slugs = {p["slug"] for p in cluster_entry["posts"]}
        self.assertEqual(slugs, {"regression-pillar", "regression-spoke"})
        for post_entry in cluster_entry["posts"]:
            self.assertEqual(
                set(post_entry.keys()),
                {"slug", "role", "title", "intent", "observed_intent",
                 "scope_includes", "scope_excludes", "body_markdown"},
            )

    def test_omitted_scope_apply_totals_shape_and_behavior_unchanged(self):
        plan = {
            "edges": {
                "regression-spoke": [
                    {"anchor": "pillar content", "target_slug": "regression-pillar"},
                ],
            }
        }
        totals_default, _ = self._apply(plan)
        totals_explicit, _ = self._apply(plan, scope="cluster")
        self.assertEqual(totals_default, totals_explicit)

        # Exactly the original totals keys — no dropped_ceiling/dropped_registry, which
        # only exist in cross-cluster scope. This is the regression guard itself.
        self.assertEqual(
            set(totals_default.keys()),
            {"posts", "inserted", "dropped_self", "dropped_unknown",
             "skipped", "rewrites", "rewrites_skipped"},
        )
        self.assertEqual(totals_default["inserted"], 1)
        self.assertEqual(totals_default["dropped_self"], 0)
        self.assertEqual(totals_default["dropped_unknown"], 0)

    def test_default_scope_never_touches_anchor_registry_even_when_claimed_elsewhere(self):
        # A different post claims the same anchor for a different target. In the
        # default (within-cluster) scope this must have NO effect at all — the
        # registry is a cross-cluster-scope-only concern.
        Post = host.post_model()
        Post.objects.create(
            title="Claimer", slug="regression-claimer", author=self.author, status="published",
            content_markdown_source="[pillar content](/blog/somewhere-else)",
        )
        plan = {
            "edges": {
                "regression-spoke": [
                    {"anchor": "pillar content", "target_slug": "regression-pillar"},
                ],
            }
        }
        totals, _ = self._apply(plan)
        self.assertEqual(totals["inserted"], 1)
        self.assertNotIn("dropped_registry", totals)


class CrossClusterExportTests(_RelinkTestBase):
    """Test 2 — cross-cluster export offers only OTHER active clusters' pillars."""

    def setUp(self):
        self.author = self._author("xc-export-author")

        self.cluster_a = self._make_cluster("XC Forex Basics", "xc-forex-basics")
        self.pillar_a = self._make_post(
            "xc-forex-pillar", "XC Forex Pillar", status="published", body="Forex pillar body.",
        )
        self.spoke_a = self._make_post(
            "xc-forex-spoke", "XC Forex Spoke", status="published", body="Forex spoke body.",
        )
        self.cluster_a.pillar = self.pillar_a
        self.cluster_a.save(update_fields=["pillar"])
        self._make_plan(
            "xc-forex-pillar-plan", "XC Forex Pillar", intent="forex basics intent",
            role="pillar", topic_cluster=self.cluster_a, produced_post=self.pillar_a,
        )
        self._make_plan(
            "xc-forex-spoke-plan", "XC Forex Spoke", intent="forex spoke intent",
            role="spoke", topic_cluster=self.cluster_a, produced_post=self.spoke_a,
        )

        self.cluster_b = self._make_cluster("XC Copy Trading", "xc-copy-trading")
        self.pillar_b = self._make_post(
            "xc-copytrading-pillar", "XC Copy Trading Pillar", status="published",
            body="Copy trading pillar body.",
        )
        self.spoke_b = self._make_post(
            "xc-copytrading-spoke", "XC Copy Trading Spoke", status="published",
            body="Copy trading spoke body.",
        )
        self.cluster_b.pillar = self.pillar_b
        self.cluster_b.save(update_fields=["pillar"])
        self._make_plan(
            "xc-copytrading-pillar-plan", "XC Copy Trading Pillar", intent="copy trading intent",
            role="pillar", topic_cluster=self.cluster_b, produced_post=self.pillar_b,
        )
        self._make_plan(
            "xc-copytrading-spoke-plan", "XC Copy Trading Spoke", intent="copy trading spoke intent",
            role="spoke", topic_cluster=self.cluster_b, produced_post=self.spoke_b,
        )

        # A third cluster that is NOT active — its pillar must never be a candidate.
        self.cluster_c = self._make_cluster("XC Prop Firms", "xc-prop-firms", status="proposed")
        self.pillar_c = self._make_post(
            "xc-propfirm-pillar", "XC Prop Firm Pillar", status="published", body="Prop firm pillar body.",
        )
        self.cluster_c.pillar = self.pillar_c
        self.cluster_c.save(update_fields=["pillar"])
        self._make_plan(
            "xc-propfirm-pillar-plan", "XC Prop Firm Pillar", intent="prop firm intent",
            role="pillar", topic_cluster=self.cluster_c, produced_post=self.pillar_c,
        )

    def _export(self):
        out = StringIO()
        call_command("content_relink", "export", scope="cross-cluster", stdout=out)
        return json.loads(out.getvalue())

    def test_candidates_are_only_other_active_pillars(self):
        data = self._export()
        posts_by_slug = {p["slug"]: p for p in data["posts"]}

        # Cluster A's spoke: only cluster B's pillar qualifies (never A's own pillar,
        # never a spoke anywhere, never the inactive cluster C's pillar).
        spoke_candidates = posts_by_slug["xc-forex-spoke"]["candidate_pillars"]
        self.assertEqual({c["slug"] for c in spoke_candidates}, {"xc-copytrading-pillar"})

        # Cluster A's own pillar: same rule applies to it too — it never sees itself.
        pillar_candidates = posts_by_slug["xc-forex-pillar"]["candidate_pillars"]
        self.assertEqual({c["slug"] for c in pillar_candidates}, {"xc-copytrading-pillar"})

        # Cluster B's members see only cluster A's pillar, symmetrically.
        b_spoke_candidates = posts_by_slug["xc-copytrading-spoke"]["candidate_pillars"]
        self.assertEqual({c["slug"] for c in b_spoke_candidates}, {"xc-forex-pillar"})

        # Never a spoke slug, never the inactive cluster's pillar, anywhere in the export.
        forbidden = {"xc-forex-spoke", "xc-copytrading-spoke", "xc-propfirm-pillar"}
        for post_entry in data["posts"]:
            candidate_slugs = {c["slug"] for c in post_entry["candidate_pillars"]}
            self.assertEqual(candidate_slugs & forbidden, set())

        # Candidate entries carry declared intent, ready for the anchor-intent rule.
        candidate = spoke_candidates[0]
        self.assertEqual(candidate["intent"], "copy trading intent")
        self.assertEqual(candidate["cluster"], "XC Copy Trading")


class CrossClusterApplyTests(_RelinkTestBase):
    """Tests 3-5 — the ceiling and the anchor-registry checks in --scope cross-cluster apply."""

    def setUp(self):
        self.author = self._author("xc-apply-author")

    def test_third_proposed_edge_rejected_by_the_ceiling(self):
        self._make_post(
            "xc-source-ceiling", "Source Ceiling",
            body=(
                "Intro line.\n\n"
                "Learn about alpha topic here.\n\n"
                "Learn about beta topic here.\n\n"
                "Learn about gamma topic here.\n"
            ),
        )
        self._make_post("xc-target-alpha", "Alpha Target")
        self._make_post("xc-target-beta", "Beta Target")
        self._make_post("xc-target-gamma", "Gamma Target")

        plan = {
            "edges": {
                "xc-source-ceiling": [
                    {"anchor": "alpha topic", "target_slug": "xc-target-alpha"},
                    {"anchor": "beta topic", "target_slug": "xc-target-beta"},
                    {"anchor": "gamma topic", "target_slug": "xc-target-gamma"},
                ],
            }
        }
        totals, err = self._apply(plan, scope="cross-cluster")
        self.assertEqual(totals["dropped_ceiling"], 1)
        self.assertEqual(totals["inserted"], 2)
        self.assertIn("gamma topic", err)
        self.assertIn("ceiling", err)

    def test_anchor_claimed_by_a_different_target_is_rejected_and_reported(self):
        # A different, already-published post claims "delta topic" for a DIFFERENT
        # target than the one this plan proposes.
        self._make_post(
            "xc-claimer", "Claimer Post", status="published",
            body="[delta topic](/blog/xc-target-other)",
        )
        self._make_post("xc-source-claimed", "Source Claimed", body="Learn about delta topic today.\n")
        self._make_post("xc-target-delta", "Delta Target")

        plan = {
            "edges": {
                "xc-source-claimed": [
                    {"anchor": "delta topic", "target_slug": "xc-target-delta"},
                ],
            }
        }
        totals, err = self._apply(plan, scope="cross-cluster")
        self.assertEqual(totals["dropped_registry"], 1)
        self.assertEqual(totals["inserted"], 0)
        self.assertIn("delta topic", err)
        self.assertIn("already claimed", err)

    def test_conflicted_anchor_is_rejected_and_reported(self):
        # Two different published posts claim the SAME anchor for two DIFFERENT
        # targets — the anchor is conflicted before this plan even proposes anything.
        self._make_post(
            "xc-claimer-1", "Claimer One", status="published",
            body="[epsilon topic](/blog/xc-target-eps-a)",
        )
        self._make_post(
            "xc-claimer-2", "Claimer Two", status="published",
            body="[epsilon topic](/blog/xc-target-eps-b)",
        )
        self._make_post("xc-source-conflict", "Source Conflict", body="Learn about epsilon topic soon.\n")
        self._make_post("xc-target-eps-c", "Epsilon Target C")

        plan = {
            "edges": {
                "xc-source-conflict": [
                    {"anchor": "epsilon topic", "target_slug": "xc-target-eps-c"},
                ],
            }
        }
        totals, err = self._apply(plan, scope="cross-cluster")
        self.assertEqual(totals["dropped_registry"], 1)
        self.assertEqual(totals["inserted"], 0)
        self.assertIn("epsilon topic", err)
        self.assertIn("conflicted", err)

    def test_unclaimed_anchor_and_same_target_reclaim_both_pass(self):
        # Sanity check alongside 3-5: an anchor nobody has claimed yet is free, and an
        # anchor already claimed by the SAME target is not a new claim — neither is a
        # registry rejection. Guards against the verdict function being overzealous.
        self._make_post(
            "xc-same-target-claimer", "Same Target Claimer", status="published",
            body="[zeta topic](/blog/xc-target-zeta)",
        )
        self._make_post(
            "xc-source-clean", "Source Clean",
            body="Learn about zeta topic and also eta topic here.\n",
        )
        self._make_post("xc-target-zeta", "Zeta Target")
        self._make_post("xc-target-eta", "Eta Target")

        plan = {
            "edges": {
                "xc-source-clean": [
                    {"anchor": "zeta topic", "target_slug": "xc-target-zeta"},  # same target as claim
                    {"anchor": "eta topic", "target_slug": "xc-target-eta"},  # never claimed
                ],
            }
        }
        totals, _ = self._apply(plan, scope="cross-cluster")
        self.assertEqual(totals.get("dropped_registry", 0), 0)
        self.assertEqual(totals.get("dropped_ceiling", 0), 0)
        self.assertEqual(totals["inserted"], 2)
