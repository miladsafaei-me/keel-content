"""Regression coverage for the `bucket` collision-detection hole (cannibalization
gate): a residual spec (canonical_key: null at bucket time) that the LLM Normalize
stage later assigns to an EXISTING registry key must still be detectable as a
collision. Python's job is only to hand the reconcile workflow (JS, untested here)
everything it needs to detect that case itself — `registry_owners`. These tests pin
that contract plus the two paths that already worked, so neither regresses.

Pure stdlib — ``cmd_bucket`` touches only JSON in/out, hence ``SimpleTestCase``.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from keel_content.tools import intent_registry as ir


def _registry(entries, families=None):
    return {"entity_families": families or [], "entries": entries}


def _owner_entry(**over):
    base = {
        "canonical_key": "what-is-demo-account",
        "canonical_intent": "explain what a demo account is",
        "need_signature": "cross-market | glossary | demo account",
        "market": "cross-market",
        "cross_market": True,
        "intent_frame": "glossary",
        "entity": "demo account",
        "entity_family": None,
        "owner": "What Is a Demo Account?",
        "owner_content_id": "what-is-demo-account",
        "owner_kind": "glossary_term",
        "owner_status": "published",
        "owner_url": "/glossary/demo-account/",
        "evidence": [],
        "scope_includes": [],
        "scope_excludes": [],
    }
    base.update(over)
    return base


def _spec(**over):
    base = {
        "content_id": "how-to-open-a-binary-options-demo-account",
        "slug": "how-to-open-a-binary-options-demo-account",
        "title": "How to Open a Binary Options Demo Account",
        "topic_cluster": "getting-started",
        "intent_frame": "glossary",
        "markets": [],
        "entity": "demo account",
        "competitor_urls": [],
        "keywords": [],
        "produced": False,
    }
    base.update(over)
    return base


def _run_bucket(registry, specs):
    with tempfile.TemporaryDirectory() as tmp:
        reg_path = Path(tmp) / "registry.json"
        wl_path = Path(tmp) / "worklist.json"
        reg_path.write_text(json.dumps(registry), encoding="utf-8")
        wl_path.write_text(json.dumps({"contents": specs}), encoding="utf-8")
        args = argparse.Namespace(registry=str(reg_path), worklist=str(wl_path), out="")
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ir.cmd_bucket(args)
        assert rc == 0
        return json.loads(buf.getvalue())


class RegistryOwnersEmittedTests(SimpleTestCase):
    """(1) `bucket` emits `registry_owners`, keyed by canonical_key, with the owner
    fields present — this is the new field that closes the detection hole."""

    def test_registry_owners_present_and_keyed_by_canonical_key(self):
        entry = _owner_entry()
        out = _run_bucket(_registry([entry]), [_spec()])
        self.assertIn("registry_owners", out)
        self.assertIn("what-is-demo-account", out["registry_owners"])
        owner = out["registry_owners"]["what-is-demo-account"]
        self.assertEqual(owner["canonical_key"], "what-is-demo-account")
        self.assertEqual(owner["owner_content_id"], "what-is-demo-account")
        self.assertEqual(owner["owner_kind"], "glossary_term")
        self.assertEqual(owner["owner_status"], "published")
        self.assertEqual(owner["owner_url"], "/glossary/demo-account/")
        self.assertEqual(owner["market"], "cross-market")
        self.assertIs(owner["cross_market"], True)

    def test_registry_owners_covers_every_keyed_entry(self):
        entries = [
            _owner_entry(canonical_key="what-is-demo-account", owner_content_id="what-is-demo-account"),
            _owner_entry(canonical_key="what-is-payout-percentage", owner_content_id="what-is-payout-percentage",
                        entity="payout percentage"),
        ]
        out = _run_bucket(_registry(entries), [_spec()])
        self.assertEqual(set(out["registry_owners"]), {"what-is-demo-account", "what-is-payout-percentage"})

    def test_registry_owners_excludes_null_key_entries(self):
        # A registry entry with no canonical_key (shouldn't happen, but guard the
        # dict-key contract) must never surface as a "null" owner key.
        entries = [_owner_entry(canonical_key=None)]
        out = _run_bucket(_registry(entries), [_spec()])
        self.assertNotIn(None, out["registry_owners"])
        self.assertNotIn("null", out["registry_owners"])


class RegistryKeysUnchangedTests(SimpleTestCase):
    """(2) `registry_keys` is unchanged in shape and content — Normalize's
    vocabulary must not regress when `registry_owners` is added alongside it."""

    def test_registry_keys_is_sorted_list_of_key_strings(self):
        entries = [
            _owner_entry(canonical_key="what-is-payout-percentage", owner_content_id="b"),
            _owner_entry(canonical_key="what-is-demo-account", owner_content_id="a"),
        ]
        out = _run_bucket(_registry(entries), [_spec()])
        self.assertEqual(out["registry_keys"], ["what-is-demo-account", "what-is-payout-percentage"])
        self.assertTrue(all(isinstance(k, str) for k in out["registry_keys"]))

    def test_registry_keys_drops_falsy_keys_same_as_before(self):
        entries = [_owner_entry(canonical_key=None), _owner_entry(canonical_key="what-is-demo-account")]
        out = _run_bucket(_registry(entries), [_spec()])
        self.assertEqual(out["registry_keys"], ["what-is-demo-account"])


class RegistryMatchesPreExistingPathTests(SimpleTestCase):
    """(3) A spec with a deterministic key that matches an owner still gets its
    `registry_matches` populated exactly as before (no regression on the path that
    already worked, e.g. an entity_family hit)."""

    def test_deterministic_key_spec_gets_registry_match(self):
        families = [{"canonical_key_hint": "what-is-demo-account", "members": ["demo account"]}]
        entries = [_owner_entry()]
        spec = _spec(entity="demo account")
        out = _run_bucket(_registry(entries, families), [spec])
        specs_out = out["buckets"][0]["specs"]
        self.assertEqual(len(specs_out), 1)
        self.assertEqual(specs_out[0]["canonical_key"], "what-is-demo-account")
        matches = specs_out[0]["registry_matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["canonical_key"], "what-is-demo-account")
        self.assertEqual(matches[0]["owner_content_id"], "what-is-demo-account")
        self.assertEqual(matches[0]["owner_kind"], "glossary_term")

    def test_market_incompatible_deterministic_match_stays_empty(self):
        families = [{"canonical_key_hint": "what-is-demo-account", "members": ["demo account"]}]
        entries = [_owner_entry(market="us", cross_market=False)]
        spec = _spec(entity="demo account", markets=["eu"])
        out = _run_bucket(_registry(entries, families), [spec])
        specs_out = out["buckets"][0]["specs"]
        self.assertEqual(specs_out[0]["registry_matches"], [])

    def test_residual_spec_without_family_gets_empty_registry_matches(self):
        # The bug's exact precondition: no deterministic family resolves this spec's
        # key, so registry_matches stays empty even though an owner of the SAME key
        # the LLM will later assign already exists. registry_owners (tested above)
        # is what lets the JS side catch this instead.
        entries = [_owner_entry()]
        spec = _spec(entity="totally unrelated wording")
        out = _run_bucket(_registry(entries), [spec])
        specs_out = out["buckets"][0]["specs"]
        self.assertIsNone(specs_out[0]["canonical_key"])
        self.assertEqual(specs_out[0]["registry_matches"], [])
        self.assertIn(spec["content_id"], out["buckets"][0]["needs_normalization"])
        # ...but the owner is still reachable via registry_owners under the key the
        # LLM would reuse from the vocabulary.
        self.assertIn("what-is-demo-account", out["registry_owners"])
