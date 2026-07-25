"""Unified production queue: glossary_term rows in ContentPlan, cluster-wide
claim/export across sources, terms-first ordering, aggregated-demand cluster
selection, DB-backed term queue + registry projection, and cluster-derived
categories at ingest."""

from __future__ import annotations

import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from keel_cms.models import Category, ContentPlan, Tag, TopicCluster
from keel_content.adapters.signalbots import upsert_content_plan_spec
from keel_content.core import glossary_backlog


def _plan(slug, cluster, **kw):
    defaults = dict(
        title=slug.replace("-", " ").title(),
        target=ContentPlan.Target.BLOG,
        source_type=ContentPlan.Source.TOP_PAGES,
        status=ContentPlan.Status.RECONCILED,
        topic_cluster=cluster,
    )
    defaults.update(kw)
    return ContentPlan.objects.create(slug=slug, **defaults)


class GlossaryBacklogDbTests(TestCase):
    def test_upsert_creates_reconciled_term_row_with_affinity(self):
        cluster = TopicCluster.objects.create(name="Test Copy Basics", slug="test-copy-basics")
        plan, outcome = glossary_backlog.upsert(
            "Test Regime Zeta",
            reason="Core framing for strategy fit.",
            sources=[{"content_id": "batch-1", "keyword": "3 articles"}],
            cluster_slug="test-copy-basics",
        )
        self.assertEqual(outcome, "created")
        self.assertEqual(plan.target, ContentPlan.Target.GLOSSARY_TERM)
        self.assertEqual(plan.status, ContentPlan.Status.RECONCILED)
        self.assertEqual(plan.slug, "term-test-regime-zeta")
        self.assertEqual(plan.canonical_key, "what-is-test-regime-zeta")
        self.assertEqual(plan.topic_cluster_id, cluster.pk)
        self.assertEqual(plan.brief["sources"][0]["content_id"], "batch-1")

    def test_upsert_skips_live_terms_and_merges_queued_sources(self):
        Tag.objects.create(name="Test Slippage Zeta", slug="test-slippage-zeta", is_term=True)
        _p, outcome = glossary_backlog.upsert("Test Slippage Zeta")
        self.assertEqual(outcome, "skipped-live")

        glossary_backlog.upsert("Test Reversion Zeta", sources=[{"content_id": "a"}])
        plan, outcome = glossary_backlog.upsert("Test Reversion Zeta", sources=[{"content_id": "b"}])
        self.assertEqual(outcome, "updated")
        ids = [s["content_id"] for s in plan.brief["sources"]]
        self.assertEqual(ids, ["a", "b"])
        self.assertEqual(
            ContentPlan.objects.filter(target=ContentPlan.Target.GLOSSARY_TERM).count(), 1
        )

    def test_remove_marks_drafted_and_backfill_links_tag(self):
        glossary_backlog.upsert("Test Flow Zeta")
        self.assertTrue(glossary_backlog.remove("Test Flow Zeta"))
        plan = ContentPlan.objects.get(slug="term-test-flow-zeta")
        self.assertEqual(plan.status, ContentPlan.Status.DRAFTED)
        self.assertIsNone(plan.produced_term)
        self.assertEqual(glossary_backlog.pending(), [])

        tag = Tag.objects.create(name="Test Flow Zeta", slug="test-flow-zeta", is_term=True)
        call_command("contentplan_backfill", stdout=StringIO())
        plan.refresh_from_db()
        self.assertEqual(plan.produced_term_id, tag.pk)

    def test_authored_term_row_is_never_requeued(self):
        glossary_backlog.upsert("Test Block Zeta")
        glossary_backlog.remove("Test Block Zeta")
        _plan_row, outcome = glossary_backlog.upsert("Test Block Zeta")
        self.assertEqual(outcome, "skipped-live")
        self.assertEqual(
            ContentPlan.objects.get(slug="term-test-block-zeta").status,
            ContentPlan.Status.DRAFTED,
        )


class IngestTermsCommandTests(TestCase):
    def test_ingests_backlog_shaped_file_with_cluster_fallback(self):
        TopicCluster.objects.create(name="Test Risk Basics", slug="test-risk-basics")
        payload = {"pending": [
            {"term": "Test Drawdown Zeta", "reason": "r1"},
            {"term": "", "reason": "unusable"},
        ]}
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "suggestions.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            out = StringIO()
            call_command("contentplan_ingest_terms", str(p), "--cluster", "test-risk-basics", stdout=out)
        plan = ContentPlan.objects.get(slug="term-test-drawdown-zeta")
        self.assertEqual(plan.topic_cluster.slug, "test-risk-basics")
        self.assertIn("1 queued", out.getvalue())


class UnifiedWorklistTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cluster = TopicCluster.objects.create(name="Test Copy Cluster", slug="test-copy-cluster")
        cls.other = TopicCluster.objects.create(name="Test Grid Cluster", slug="test-grid-cluster")
        # Mixed-source cluster: top-pages pillar + briefed keyword spoke + term.
        # The brief gate is source-agnostic, so the top-pages pillar is briefed too.
        _plan(
            "copy-trading-guide", cls.cluster,
            role=ContentPlan.Role.PILLAR, competitor_traffic=500,
            brief={"intent_statement": "x"},
        )
        _plan(
            "copy-trading-fees", cls.cluster,
            source_type=ContentPlan.Source.KEYWORD_CLUSTERING,
            keyword_volume=900, brief={"intent_statement": "x"},
        )
        _plan(
            "copy-trading-unbriefed", cls.cluster,
            source_type=ContentPlan.Source.KEYWORD_CLUSTERING, keyword_volume=100,
        )
        glossary_backlog.upsert("Test Ratio Zeta", cluster_slug="test-copy-cluster")
        # Lower aggregated demand in the other cluster.
        _plan("grid-bot-guide", cls.other, role=ContentPlan.Role.PILLAR, competitor_traffic=200)

    def _worklist(self, *args):
        out, err = StringIO(), StringIO()
        call_command("export_worklist", *args, stdout=out, stderr=err)
        return json.loads(out.getvalue()), err.getvalue()

    def test_next_cluster_claims_whole_cluster_across_sources_terms_first(self):
        wl, err = self._worklist("--next-cluster", "--claim")
        self.assertIn("test-copy-cluster", err)
        slugs = [c["slug"] for c in wl["contents"]]
        # Aggregated demand: 500 + 900 + 100 = 1500 beats 200 — copy-trading wins.
        # Unbriefed keyword row held back; term first, then pillar, then spoke.
        self.assertEqual(slugs, ["term-test-ratio-zeta", "copy-trading-guide", "copy-trading-fees"])
        self.assertEqual(wl["contents"][0]["content_type"], "glossary_term")
        statuses = set(
            ContentPlan.objects.filter(slug__in=slugs).values_list("status", flat=True)
        )
        self.assertEqual(statuses, {ContentPlan.Status.GENERATING})
        held = ContentPlan.objects.get(slug="copy-trading-unbriefed")
        self.assertEqual(held.status, ContentPlan.Status.RECONCILED)

    def test_source_filter_still_narrows(self):
        wl, _err = self._worklist("--source", "top_pages")
        slugs = {c["slug"] for c in wl["contents"]}
        self.assertEqual(slugs, {"copy-trading-guide", "grid-bot-guide"})

    def test_article_specs_carry_lead_visual_terms_do_not(self):
        wl, _err = self._worklist("--next-cluster", "--claim")
        by_slug = {c["slug"]: c for c in wl["contents"]}
        self.assertNotIn("lead_visual_archetype", by_slug["term-test-ratio-zeta"])
        self.assertIn("lead_visual_archetype", by_slug["copy-trading-guide"])


class RegistryProjectionTests(TestCase):
    def test_queued_term_projects_as_planned_owner_not_plan_entry(self):
        glossary_backlog.upsert("Test Regime Zeta")
        out = StringIO()
        call_command("contentplan_export_registry", stdout=out, stderr=StringIO())
        registry = json.loads(out.getvalue())
        entries = {e["canonical_key"]: e for e in registry["entries"]}
        entry = entries["what-is-test-regime-zeta"]
        self.assertEqual(entry["owner_kind"], "glossary_term")
        self.assertEqual(entry["owner_status"], "planned")
        # The term row must not ALSO appear as an owner_kind=plan entry.
        plan_kinds = [
            e for e in registry["entries"]
            if e["owner_content_id"] == "term-test-regime-zeta"
        ]
        self.assertEqual(plan_kinds, [])


class ClusterDerivedCategoriesTests(TestCase):
    def test_ingest_derives_categories_and_bootstraps_primary(self):
        bots = Category.objects.create(name="Test Macro Alpha", slug="test-macro-alpha")
        signals = Category.objects.create(name="Test Macro Beta", slug="test-macro-beta")
        spec1 = {
            "slug": "bot-guide",
            "title": "Bot Guide",
            "topic_cluster": "Test Automation Basics",
            "categories": ["Test Macro Alpha"],
        }
        upsert_content_plan_spec(spec1, source_type=ContentPlan.Source.TOP_PAGES)
        cluster = TopicCluster.objects.get(slug="test-automation-basics")
        self.assertEqual(cluster.primary_category_id, bots.pk)

        # A sibling bringing another category grows the cluster set, and every
        # member row carries the cluster's (union) category set.
        spec2 = {
            "slug": "bot-signals",
            "title": "Bot Signals",
            "topic_cluster": "Test Automation Basics",
            "categories": ["Test Macro Beta"],
        }
        plan2, _ = upsert_content_plan_spec(spec2, source_type=ContentPlan.Source.TOP_PAGES)
        cluster.refresh_from_db()
        self.assertEqual(cluster.primary_category_id, bots.pk)
        self.assertEqual(
            set(cluster.categories.values_list("pk", flat=True)), {bots.pk, signals.pk}
        )
        self.assertEqual(
            set(plan2.categories.values_list("pk", flat=True)), {bots.pk, signals.pk}
        )


class MapTermsCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.copy = TopicCluster.objects.create(name="Test Copyx Cluster", slug="test-copyx-cluster")
        cls.grid = TopicCluster.objects.create(name="Test Gridx Cluster", slug="test-gridx-cluster")
        # Populated clusters only participate — give each one article row.
        _plan("copyx-followers-guide", cls.copy, title="Copyx Followers Sizing Handbook")
        _plan("gridx-spacing-guide", cls.grid, title="Gridx Spacing Levels Handbook")
        # An EMPTY near-duplicate cluster must never attract terms.
        TopicCluster.objects.create(name="Test Copyx Empty", slug="test-copyx-empty")

    def _run(self, *args):
        out = StringIO()
        call_command("contentplan_map_terms", *args, stdout=out)
        return out.getvalue()

    def test_strong_unique_match_auto_attaches(self):
        glossary_backlog.upsert("Copyx Ratio Zeta", reason="How a copyx follower scales sizing.")
        out = self._run()
        plan = ContentPlan.objects.get(slug="term-copyx-ratio-zeta")
        self.assertEqual(plan.topic_cluster_id, self.copy.pk)
        self.assertIn("1 attached", out)

    def test_no_match_stays_unmapped_and_feeds_theme_report(self):
        for n in ("Extensionx Alpha Permission", "Extensionx Beta Manifest", "Extensionx Gamma Overlay"):
            glossary_backlog.upsert(n)
        out = self._run()
        self.assertEqual(
            ContentPlan.objects.filter(
                target=ContentPlan.Target.GLOSSARY_TERM, topic_cluster__isnull=True
            ).count(),
            3,
        )
        self.assertIn("missing-cluster report", out)
        self.assertIn("extensionx", out)

    def test_dry_run_writes_nothing(self):
        glossary_backlog.upsert("Gridx Level Zeta", reason="Spacing of gridx levels.")
        out = self._run("--dry-run")
        self.assertIn("1 attached", out)
        self.assertIsNone(
            ContentPlan.objects.get(slug="term-gridx-level-zeta").topic_cluster
        )


class SourceAgnosticBriefTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cluster = TopicCluster.objects.create(name="Test Briefx Cluster", slug="test-briefx-cluster")
        _plan(
            "briefx-pillar", cls.cluster,
            role=ContentPlan.Role.PILLAR, competitor_traffic=300,
            brief={"intent_statement": "x"},
        )
        # Unbriefed TOP-PAGES spoke: held back by the (now source-agnostic) gate.
        _plan("briefx-toppages-spoke", cls.cluster, competitor_traffic=100)

    def test_unbriefed_top_pages_row_is_held_back(self):
        out, err = StringIO(), StringIO()
        call_command("export_worklist", "--next-cluster", "--claim", stdout=out, stderr=err)
        wl = json.loads(out.getvalue())
        slugs = [c["slug"] for c in wl["contents"]]
        self.assertEqual(slugs, ["briefx-pillar"])
        self.assertIn("held back", err.getvalue())
        held = ContentPlan.objects.get(slug="briefx-toppages-spoke")
        self.assertEqual(held.status, ContentPlan.Status.RECONCILED)

    def test_specs_carry_cluster_brief(self):
        self.cluster.brief = {"shared_context": "spine", "element_ownership": []}
        self.cluster.save(update_fields=["brief"])
        out = StringIO()
        call_command("export_worklist", "--cluster", "test-briefx-cluster", stdout=out, stderr=StringIO())
        wl = json.loads(out.getvalue())
        pillar = next(c for c in wl["contents"] if c["slug"] == "briefx-pillar")
        self.assertEqual(pillar["cluster_brief"]["shared_context"], "spine")


class SetBriefClusterTests(TestCase):
    def test_cluster_brief_persists_and_scope_excludes_union(self):
        cluster = TopicCluster.objects.create(name="Test Setbx Cluster", slug="test-setbx-cluster")
        plan = _plan(
            "setbx-spoke", cluster,
            status=ContentPlan.Status.RECONCILED,
            scope_excludes=["from-reconcile"],
        )
        payload = {
            "cluster_briefs": [{
                "cluster_slug": "test-setbx-cluster",
                "cluster_brief": {"shared_context": "s", "element_ownership": [],
                                  "scope_fences": [], "link_terms": [], "notes": ""},
            }],
            "briefs": [{
                "slug": "setbx-spoke",
                "feasibility": "llm_full",
                "brief": {"intent_statement": "i", "scope_excludes": ["from-cluster-pass", "from-reconcile"]},
            }],
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "briefs.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            call_command("contentplan_set_brief", str(p), stdout=StringIO(), stderr=StringIO())
        cluster.refresh_from_db()
        plan.refresh_from_db()
        self.assertEqual(cluster.brief["shared_context"], "s")
        self.assertEqual(plan.brief["intent_statement"], "i")
        self.assertEqual(plan.scope_excludes, ["from-reconcile", "from-cluster-pass"])


class AdminBriefPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model

        cls.admin = get_user_model().objects.create_superuser(
            username="brief-admin", email="brief-admin@test.local", password="x-test-pass-1"
        )
        cluster = TopicCluster.objects.create(name="Test Admbx Cluster", slug="test-admbx-cluster")
        cls.plan = _plan(
            "admbx-spoke", cluster,
            brief={"intent_statement": "seen-in-page", "_judge": {"verdict": "pass"}},
        )

    def test_get_renders_and_post_saves_json(self):
        self.client.force_login(self.admin)
        url = f"/admin-os/content-plan/{self.plan.pk}/brief/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "seen-in-page")
        resp = self.client.post(url, {
            "brief_json": json.dumps({"intent_statement": "edited"}),
            "cluster_brief_json": json.dumps({"shared_context": "cb"}),
            "feasibility": "human_only",
        })
        self.assertEqual(resp.status_code, 302)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.brief["intent_statement"], "edited")
        self.assertEqual(self.plan.feasibility, "human_only")
        self.assertEqual(self.plan.topic_cluster.brief["shared_context"], "cb")

    def test_invalid_json_saves_nothing(self):
        self.client.force_login(self.admin)
        url = f"/admin-os/content-plan/{self.plan.pk}/brief/"
        resp = self.client.post(url, {"brief_json": "{not json", "cluster_brief_json": ""})
        self.assertEqual(resp.status_code, 200)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.brief["intent_statement"], "seen-in-page")
