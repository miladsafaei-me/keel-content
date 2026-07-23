#!/usr/bin/env python3
"""Global intent registry — the deterministic engine behind cannibalization
prevention (content-pipeline/CANNIBALIZATION-PREVENTION-PLAN.md §2 + Layer 1).

This is the "no-AI" half of the fix: everything reproducible lives here. The LLM
half (canonical-key normalization + deep adjudication of the real competitor
pages) runs in tools/content_pipeline/reconcile.workflow.js and hands its verdicts
back to `apply`. There are NO embeddings and NO external API anywhere — semantic
matching is canonical-key normalization (a controlled vocabulary), and the free
first net is a hand-curated synonym family.

Three subcommands:

  bucket  <worklist.json>
      Load the persistent registry, enrich every spec (market / cross-market flag /
      entity_family / a pre-assigned canonical_key when the family resolves it for
      free), partition specs by the hard intent_frame pre-filter, and emit the
      workload the reconcile workflow fans out over (which specs still need an LLM
      canonical_key, and which existing keys to reuse). Pure stdlib, no tokens.

  apply   <worklist.json> <adjudications.json>
      Take the workflow's verdicts (merge / re-scope / keep + confidence + observed
      intent + scopes), apply the SAFE-BY-DEFAULT policy (merge only on high
      confidence, otherwise downgrade to re-scope — never silently over-merge),
      update the persistent registry, and write worklist.reconciled.json +
      reconciliation-report.json. `--mode suggest` (the calibration default) makes
      this NON-binding: it writes the report + an annotated (non-destructive)
      reconciled worklist and a .suggested registry sidecar, but does NOT drop any
      spec and does NOT mutate the real persistent registry.

  selftest [--golden PATH]
      Run the golden-set regression test (§2.6): the deterministic invariants (the
      frame pre-filter separates cross-frame pairs; the entity_family net groups the
      synonym pairs and never groups the distinct ones) always run; the canonical_key
      invariants run against the golden fixture's captured_keys when present.

Usage:
  intent_registry.py bucket  WORKLIST [--registry PATH] [--out PATH]
  intent_registry.py apply   WORKLIST ADJUDICATIONS [--registry PATH]
                             [--mode suggest|auto] [--out-dir DIR]
  intent_registry.py selftest [--golden PATH] [--registry PATH]
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPO_ROOT / "content-pipeline" / "intent-registry.json"
DEFAULT_GOLDEN = REPO_ROOT / "content-pipeline" / "intent-registry.golden.json"

CROSS_MARKET = "cross-market"


# ── shared helpers ─────────────────────────────────────────────────────────

def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _dump_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _today():
    return datetime.date.today().isoformat()


def _norm(text):
    """Lower-case + collapse whitespace."""
    return " ".join(str(text or "").lower().split())


def _tokens(text):
    """Whole alphanumeric tokens of a string (hyphen splits into parts too)."""
    return set(re.findall(r"[a-z0-9]+", _norm(text)))


def _frame(spec):
    """The hard pre-filter axis. Prefer the explicit intent_frame; never guess
    beyond what the spec declares (a wrong frame would wrongly compare pages)."""
    return _norm(spec.get("intent_frame") or "") or "unknown"


def _markets(spec):
    """(is_cross_market, primary_specific_market). A spec with no specific market,
    or one tagged cross-market, is a wildcard that overlaps every market in its
    frame (§2.6); a single specific market only compares to its own or a wildcard."""
    raw = [_norm(m) for m in (spec.get("markets") or []) if _norm(m)]
    specifics = [m for m in raw if "cross" not in m]
    is_cross = (not specifics) or any("cross" in m for m in raw)
    primary = specifics[0] if specifics else CROSS_MARKET
    return is_cross, primary


def market_compatible(a_cross, a_market, b_cross, b_market):
    """Two specs in the same frame may be compared iff one is a cross-market
    wildcard or they share the same specific market."""
    if a_cross or b_cross:
        return True
    return a_market == b_market


# ── entity_family resolution (the free deterministic net) ────────────────────

def _family_match(entity_text, family):
    """A family matches a spec's entity when any of its members appears as a whole
    token (single-word members) or as a bounded phrase (multi-word members)."""
    toks = _tokens(entity_text)
    norm_entity = " " + _norm(entity_text) + " "
    for member in family.get("members", []):
        m = _norm(member)
        if " " in m or "-" in m.replace(" ", ""):
            # multi-word / hyphenated phrase: bounded substring match
            if (" " + m + " ") in norm_entity or m in _norm(entity_text):
                # require the phrase to appear, bounded by non-alnum on both sides
                if re.search(r"(?<![a-z0-9])" + re.escape(m) + r"(?![a-z0-9])", _norm(entity_text)):
                    return True
        else:
            if m in toks:
                return True
    return False


def resolve_entity_family(entity_text, families):
    """Return the canonical_key_hint of the first family whose synonym net matches,
    else None. Ordering is the curated order in the registry file."""
    for fam in families:
        if _family_match(entity_text, fam):
            return fam.get("canonical_key_hint")
    return None


# ── bucket ──────────────────────────────────────────────────────────────────

def _spec_ref(spec, families):
    is_cross, primary = _markets(spec)
    entity = spec.get("entity") or ""
    family = resolve_entity_family(entity, families)
    return {
        "content_id": spec.get("content_id") or spec.get("slug") or "",
        "slug": spec.get("slug") or "",
        "title": spec.get("title") or spec.get("h1") or "",
        "topic_cluster": spec.get("topic_cluster") or "",
        "intent_frame": _frame(spec),
        "market": primary,
        "cross_market": is_cross,
        "entity": entity,
        "entity_family": family,
        # A family resolves the canonical_key for free; residual specs get null and
        # are sent to the LLM normalizer. Same family -> same key -> guaranteed to be
        # examined together.
        "canonical_key": family,
        "competitor_urls": list(spec.get("competitor_urls") or []),
        # Keyword-route evidence: the cluster's top keyword strings. The normalizer /
        # adjudicator read these the way they read competitor_urls on the top-pages
        # path (a spec with no competitor pages is judged from its live SERP instead).
        "keywords": [
            k.get("keyword") for k in (spec.get("keywords") or [])[:10]
            if isinstance(k, dict) and k.get("keyword")
        ],
        # Registry seed: this spec's Post already exists. It can absorb new demand
        # (survivor of a merge -> enrichment) but is never re-generated.
        "produced": bool(spec.get("produced")),
    }


def cmd_bucket(args):
    registry = _load_json(args.registry)
    families = registry.get("entity_families", [])
    entries = registry.get("entries", [])
    worklist = _load_json(args.worklist)
    specs = worklist.get("contents") or []

    refs = [_spec_ref(s, families) for s in specs]

    # Existing registry keys, grouped by frame, so the normalizer reuses a live key
    # rather than minting a near-duplicate (cross-run stability, §2.2).
    keys_by_frame = {}
    owners_by_key = {}
    for e in entries:
        fr = _norm(e.get("intent_frame") or "")
        keys_by_frame.setdefault(fr, set()).add(e.get("canonical_key"))
        owners_by_key.setdefault(e.get("canonical_key"), e)

    buckets = {}
    for r in refs:
        buckets.setdefault(r["intent_frame"], []).append(r)

    out_buckets = []
    for frame, members in sorted(buckets.items()):
        # cross-run prior matches: a batch spec whose resolved family-key already
        # owns a registry entry in this frame is a candidate against that owner.
        for r in members:
            r["registry_matches"] = []
            if r["canonical_key"] and r["canonical_key"] in owners_by_key:
                owner = owners_by_key[r["canonical_key"]]
                if market_compatible(r["cross_market"], r["market"],
                                     bool(owner.get("cross_market")), _norm(owner.get("market") or CROSS_MARKET)):
                    r["registry_matches"].append({
                        "canonical_key": owner.get("canonical_key"),
                        "owner": owner.get("owner"),
                        "owner_content_id": owner.get("owner_content_id"),
                        "owner_kind": owner.get("owner_kind", "plan"),
                        "owner_status": owner.get("owner_status", ""),
                        "owner_url": owner.get("owner_url", ""),
                        "market": owner.get("market"),
                    })
        # within-batch deterministic groups: specs sharing a non-null family key,
        # respecting market-compatibility.
        det_groups = _deterministic_groups(members)
        needs_norm = [r["content_id"] for r in members if not r["canonical_key"]]
        out_buckets.append({
            "intent_frame": frame,
            "existing_keys": sorted(k for k in keys_by_frame.get(frame, set()) if k),
            "specs": members,
            "deterministic_groups": det_groups,
            "needs_normalization": needs_norm,
        })

    out = {
        "version": 1,
        "worklist": str(args.worklist),
        "registry": str(args.registry),
        "registry_keys": sorted(k for k in owners_by_key if k),
        "buckets": out_buckets,
    }
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.out:
        _dump_json(args.out, out)
        print(f"bucket: {len(refs)} spec(s) across {len(out_buckets)} frame(s) -> {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def _deterministic_groups(members):
    """Cluster same-frame members that share a non-null canonical_key (an
    entity_family hit) and are market-compatible. Returns lists of content_ids
    (length >= 2). Simple union over key + market-compat."""
    by_key = {}
    for r in members:
        if r["canonical_key"]:
            by_key.setdefault(r["canonical_key"], []).append(r)
    groups = []
    for key, rs in by_key.items():
        # split a key group into market-compatible clusters
        clusters = []
        for r in rs:
            placed = False
            for cl in clusters:
                if any(market_compatible(r["cross_market"], r["market"],
                                         o["cross_market"], o["market"]) for o in cl):
                    cl.append(r)
                    placed = True
                    break
            if not placed:
                clusters.append([r])
        for cl in clusters:
            if len(cl) >= 2:
                groups.append({"canonical_key": key,
                               "members": [r["content_id"] for r in cl]})
    return groups


# ── apply ─────────────────────────────────────────────────────────────────

def cmd_apply(args):
    registry = _load_json(args.registry)
    worklist = _load_json(args.worklist)
    adj = _load_json(args.adjudications)
    specs = {s.get("content_id") or s.get("slug"): s for s in (worklist.get("contents") or [])}
    families = registry.get("entity_families", [])

    normalizations = adj.get("normalizations") or {}
    adjudications = adj.get("adjudications") or []
    mode = args.mode

    report = {"updated_at": _today(), "mode": mode,
              "counts": {"merged": 0, "rescoped": 0, "kept": 0, "enriched": 0},
              "decisions": [],
              # Same-intent collisions with an ALREADY-EXISTING page (produced post or
              # glossary term): the new demand leaves the queue, and this ledger tells
              # the content team which live page to optimize with which keywords.
              "enrichment_opportunities": []}
    dropped = set()           # content_ids merged away (auto mode only)
    annotations = {}          # content_id -> {observed_intent, scope_includes, scope_excludes, _reconcile}
    new_entries = []          # registry upserts

    for a in adjudications:
        members = [m for m in (a.get("members") or []) if m in specs]
        if not members:
            continue
        action = a.get("action", "keep")
        conf = a.get("confidence", "low")
        prior = a.get("prior_owner") or {}
        raw_survivor = a.get("survivor")
        # An EXTERNAL survivor is a prior-run registry owner (cross-cluster / cross-run
        # collision, decisions #3/#4): the batch spec(s) are absorbed by a page that
        # already exists, so ALL members drop. A survivor naming a batch member is the
        # ordinary within-batch case.
        external = bool(raw_survivor) and raw_survivor not in members and (
            bool(prior) or raw_survivor == (prior.get("owner_content_id") if prior else None))
        survivor = raw_survivor if raw_survivor in members else (
            raw_survivor if external else members[0])
        observed = a.get("observed_intent") or {}
        scopes = a.get("scopes") or {}
        rationale = a.get("rationale", "")
        ckey = a.get("canonical_key") or (normalizations.get(survivor) if survivor in members else "") \
            or prior.get("canonical_key") or ""

        # SAFE-BY-DEFAULT policy (decision #1): merge only on high confidence; any
        # uncertainty downgrades to re-scope (keep both, fence them). Never a silent
        # over-merge.
        effective = action
        downgraded = False
        if action == "merge" and conf != "high":
            effective = "rescope"
            downgraded = True

        decision = {
            "canonical_key": ckey,
            "intent_frame": a.get("intent_frame", ""),
            "members": members,
            "requested_action": action,
            "effective_action": effective,
            "confidence": conf,
            "survivor": survivor,
            "downgraded_from_merge": downgraded,
            "rationale": rationale,
        }

        if effective == "merge":
            losers = list(members) if external else [m for m in members if m != survivor]
            decision["dropped"] = losers
            decision["survivor_external"] = external
            report["counts"]["merged"] += 1
            if mode == "auto":
                dropped.update(losers)
            # union the absorbed specs' evidence into the survivor's registry entry
            evidence = []
            for m in members:
                evidence += list(specs[m].get("competitor_urls") or [])
            if external:
                # absorbed by a pre-existing page; refresh that entry's evidence only.
                new_entries.append({
                    "canonical_key": ckey,
                    "canonical_intent": prior.get("canonical_intent", ""),
                    "need_signature": prior.get("need_signature", ""),
                    "market": prior.get("market") or _markets(specs[members[0]])[1],
                    "cross_market": bool(prior.get("cross_market")),
                    "intent_frame": prior.get("intent_frame", a.get("intent_frame", "")),
                    "entity": prior.get("entity", ""),
                    "entity_family": prior.get("entity_family"),
                    "owner": prior.get("owner", ""),
                    "owner_content_id": survivor,
                    "owner_kind": prior.get("owner_kind", "plan"),
                    "owner_status": prior.get("owner_status", ""),
                    "owner_url": prior.get("owner_url", ""),
                    "evidence": sorted(set(evidence)),
                    "scope_includes": [], "scope_excludes": [],
                })
                # Enrichment ledger: the need already has a live owner, so instead of
                # a new page the team optimizes the existing one with this demand.
                kw_union, kw_volume = {}, 0
                for m in members:
                    for k in specs[m].get("keywords") or []:
                        if isinstance(k, dict) and k.get("keyword"):
                            kw = str(k["keyword"]).strip()
                            vol = k.get("volume") or 0
                            kw_union[kw] = max(kw_union.get(kw, 0), int(vol) if str(vol).isdigit() or isinstance(vol, int) else 0)
                    kw_volume += int(specs[m].get("keyword_volume") or 0)
                enrichment = {
                    "canonical_key": ckey,
                    "target": survivor,
                    "target_kind": prior.get("owner_kind", "plan"),
                    "target_status": prior.get("owner_status", ""),
                    "target_url": prior.get("owner_url", ""),
                    "target_title": prior.get("owner", ""),
                    "absorbed": losers,
                    "keywords": [
                        {"keyword": kw, "volume": vol}
                        for kw, vol in sorted(kw_union.items(), key=lambda x: -x[1])
                    ],
                    "keyword_volume": kw_volume,
                    "rationale": rationale,
                }
                decision["enrichment"] = enrichment
                report["enrichment_opportunities"].append(enrichment)
                report["counts"]["enriched"] += 1
            else:
                new_entries.append(_entry_for(specs[survivor], ckey, families,
                                               evidence=sorted(set(evidence)),
                                               scope_includes=[], scope_excludes=[]))
                annotations[survivor] = {"observed_intent": observed.get(survivor, ""),
                                         "canonical_key": ckey,
                                         "_reconcile": {"action": "merge", "absorbed": losers,
                                                        "confidence": conf}}
                # A within-batch merge into a PRODUCED spec (a registry seed — its
                # Post already exists) is also an enrichment: the absorbed demand
                # belongs to that live page, not to a new one.
                if specs[survivor].get("produced"):
                    kw_union, kw_volume = {}, 0
                    for m in losers:
                        for k in specs[m].get("keywords") or []:
                            if isinstance(k, dict) and k.get("keyword"):
                                kw = str(k["keyword"]).strip()
                                vol = k.get("volume") or 0
                                kw_union[kw] = max(kw_union.get(kw, 0), int(vol) if isinstance(vol, int) or str(vol).isdigit() else 0)
                        kw_volume += int(specs[m].get("keyword_volume") or 0)
                    enrichment = {
                        "canonical_key": ckey,
                        "target": survivor,
                        "target_kind": "post",
                        "target_status": "produced",
                        "target_url": f"/blog/{specs[survivor].get('slug') or survivor}",
                        "target_title": specs[survivor].get("title", ""),
                        "absorbed": losers,
                        "keywords": [
                            {"keyword": kw, "volume": vol}
                            for kw, vol in sorted(kw_union.items(), key=lambda x: -x[1])
                        ],
                        "keyword_volume": kw_volume,
                        "rationale": rationale,
                    }
                    decision["enrichment"] = enrichment
                    report["enrichment_opportunities"].append(enrichment)
                    report["counts"]["enriched"] += 1
            # Annotate the absorbed losers so suggest-mode output is honest (in auto
            # mode they are dropped from the reconciled worklist, so this is moot there).
            for m in losers:
                annotations[m] = {"observed_intent": observed.get(m, ""),
                                  "canonical_key": ckey,
                                  "_reconcile": {"action": "merge-absorbed",
                                                 "into": survivor, "confidence": conf}}
        elif effective == "rescope":
            report["counts"]["rescoped"] += 1
            for m in members:
                sc = scopes.get(m) or {}
                inc = sc.get("includes") or ([observed[m]] if observed.get(m) else [])
                exc = sc.get("excludes") or []
                annotations[m] = {"observed_intent": observed.get(m, ""),
                                  "canonical_key": ckey,
                                  "scope_includes": inc,
                                  "scope_excludes": exc,
                                  "_reconcile": {"action": "rescope", "confidence": conf,
                                                 "downgraded_from_merge": downgraded}}
                new_entries.append(_entry_for(specs[m], ckey, families,
                                              evidence=sorted(set(specs[m].get("competitor_urls") or [])),
                                              scope_includes=inc, scope_excludes=exc))
        else:  # keep
            report["counts"]["kept"] += 1
            for m in members:
                annotations.setdefault(m, {})
                annotations[m].update({"observed_intent": observed.get(m, ""),
                                       "canonical_key": ckey or normalizations.get(m, ""),
                                       "_reconcile": {"action": "keep", "confidence": conf}})
                new_entries.append(_entry_for(specs[m], ckey or normalizations.get(m, ""), families,
                                              evidence=sorted(set(specs[m].get("competitor_urls") or [])),
                                              scope_includes=[], scope_excludes=[]))

        report["decisions"].append(decision)

    # Specs never touched by an adjudication are singletons — register them so the
    # next run dedups against them, and carry their normalized key through.
    for cid, spec in specs.items():
        if cid in annotations or cid in dropped:
            continue
        ckey = normalizations.get(cid) or resolve_entity_family(spec.get("entity") or "", families) or ""
        annotations[cid] = {"canonical_key": ckey, "observed_intent": "",
                            "_reconcile": {"action": "singleton"}}
        if ckey:
            new_entries.append(_entry_for(spec, ckey, families,
                                          evidence=sorted(set(spec.get("competitor_urls") or [])),
                                          scope_includes=[], scope_excludes=[]))

    # Build the reconciled worklist.
    reconciled_contents = []
    for cid, spec in specs.items():
        if cid in dropped:
            continue
        out_spec = dict(spec)
        ann = annotations.get(cid, {})
        if ann.get("observed_intent"):
            out_spec["observed_intent"] = ann["observed_intent"]
        if ann.get("canonical_key"):
            out_spec["canonical_key"] = ann["canonical_key"]
        out_spec["scope_includes"] = ann.get("scope_includes", spec.get("scope_includes", []))
        out_spec["scope_excludes"] = ann.get("scope_excludes", spec.get("scope_excludes", []))
        out_spec.setdefault("canonical_owner", spec.get("canonical_owner") or {})
        out_spec["_reconcile"] = ann.get("_reconcile", {"action": "singleton"})
        reconciled_contents.append(out_spec)

    reconciled = dict(worklist)
    reconciled["contents"] = reconciled_contents
    reconciled["count"] = len(reconciled_contents)
    reconciled["reconciled_mode"] = mode

    out_dir = Path(args.out_dir) if args.out_dir else Path(args.worklist).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    _dump_json(out_dir / "worklist.reconciled.json", reconciled)
    _dump_json(out_dir / "reconciliation-report.json", report)

    # Registry persistence: binding only in auto mode; suggest writes a sidecar.
    updated = _upsert_entries(registry, new_entries)
    if mode == "auto":
        _dump_json(args.registry, updated)
    else:
        sidecar = Path(args.registry).with_suffix(".suggested.json")
        _dump_json(sidecar, updated)

    c = report["counts"]
    print(f"apply [{mode}]: merged={c['merged']} (enrich-existing={c['enriched']}) "
          f"rescoped={c['rescoped']} kept={c['kept']} "
          f"-> {out_dir}/worklist.reconciled.json (+ reconciliation-report.json)", file=sys.stderr)
    if mode == "suggest":
        print(f"apply [suggest]: NON-binding — no specs dropped, registry untouched "
              f"(suggested registry written to {Path(args.registry).with_suffix('.suggested.json')})", file=sys.stderr)
    return 0


def _entry_for(spec, canonical_key, families, evidence, scope_includes, scope_excludes):
    is_cross, primary = _markets(spec)
    entity = spec.get("entity") or ""
    return {
        "canonical_key": canonical_key,
        "canonical_intent": spec.get("observed_intent") or spec.get("intent") or "",
        "need_signature": f"{primary} | {_frame(spec)} | {entity}",
        "market": primary,
        "cross_market": is_cross,
        "intent_frame": _frame(spec),
        "entity": entity,
        "entity_family": resolve_entity_family(entity, families),
        "owner": spec.get("title") or spec.get("h1") or "",
        "owner_content_id": spec.get("content_id") or spec.get("slug") or "",
        "owner_kind": "plan",
        "owner_status": "",
        "owner_url": "",
        "evidence": evidence,
        "scope_includes": scope_includes,
        "scope_excludes": scope_excludes,
    }


def _upsert_entries(registry, new_entries):
    """Merge new entries into the registry, keyed on (canonical_key, market). Last
    write wins on owner/scope; evidence is unioned. Returns a NEW registry dict."""
    out = dict(registry)
    by_key = {}
    for e in out.get("entries", []):
        by_key[(e.get("canonical_key"), e.get("market"))] = dict(e)
    for e in new_entries:
        if not e.get("canonical_key"):
            continue
        k = (e["canonical_key"], e["market"])
        if k in by_key:
            merged = by_key[k]
            merged["evidence"] = sorted(set(merged.get("evidence", []) + e.get("evidence", [])))
            for fld in ("owner", "owner_content_id", "owner_kind", "owner_status", "owner_url",
                        "canonical_intent", "need_signature",
                        "entity", "entity_family", "intent_frame", "cross_market"):
                if e.get(fld):
                    merged[fld] = e[fld]
            if e.get("scope_includes"):
                merged["scope_includes"] = e["scope_includes"]
            if e.get("scope_excludes"):
                merged["scope_excludes"] = e["scope_excludes"]
        else:
            by_key[k] = dict(e)
    out["entries"] = sorted(by_key.values(),
                            key=lambda e: (e.get("intent_frame", ""), e.get("canonical_key", ""), e.get("market", "")))
    out["updated_at"] = _today()
    return out


# ── selftest (golden set §2.6) ────────────────────────────────────────────

def cmd_selftest(args):
    registry = _load_json(args.registry)
    families = registry.get("entity_families", [])
    golden = _load_json(args.golden)
    specs = golden.get("specs", {})
    pairs = golden.get("pairs", [])
    captured = golden.get("captured_keys", {})

    failures = []
    checked_det = 0
    checked_key = 0

    def fam(sid):
        return resolve_entity_family(specs[sid].get("entity", ""), families)

    def frame(sid):
        return _norm(specs[sid].get("intent_frame", ""))

    def mkt(sid):
        s = specs[sid]
        raw = [_norm(m) for m in [s.get("market", "")] if _norm(m)]
        is_cross = (not [m for m in raw if "cross" not in m]) or any("cross" in m for m in raw)
        prim = next((m for m in raw if "cross" not in m), CROSS_MARKET)
        return is_cross, prim

    for p in pairs:
        a, b = p["a"], p["b"]
        if a not in specs or b not in specs:
            failures.append(f"pair references unknown spec: {a} / {b}")
            continue

        same_frame = frame(a) == frame(b)
        # Invariant 1 — the frame pre-filter: cross-frame pairs must never compare.
        if p.get("shares_bucket") is False:
            checked_det += 1
            if same_frame:
                ac, am = mkt(a)
                bc, bm = mkt(b)
                if market_compatible(ac, am, bc, bm):
                    failures.append(f"[frame-prefilter] {a} <-> {b}: expected separated by "
                                    f"frame but both compare (frame {frame(a)!r} == {frame(b)!r})")
            continue  # frame-killed pairs have no key expectation

        # same-bucket pairs: market must actually be compatible for the test to mean
        # anything (cross-market overlaps specific markets).
        ac, am = mkt(a)
        bc, bm = mkt(b)
        compatible = same_frame and market_compatible(ac, am, bc, bm)
        if not compatible:
            failures.append(f"[bucketing] {a} <-> {b}: golden says shares_bucket=true but "
                            f"frame/market are not compatible ({frame(a)}/{am} vs {frame(b)}/{bm})")
            continue

        # Invariant 2 — the deterministic family net.
        if p.get("deterministic_family"):
            checked_det += 1
            if fam(a) is None or fam(b) is None or fam(a) != fam(b):
                failures.append(f"[entity_family] {a} <-> {b}: expected same family, got "
                                f"{fam(a)!r} vs {fam(b)!r} — add the synonym to entity_families")
        if p.get("expect_same_key") is False:
            # distinct same-bucket pairs must NOT collide on the free net
            checked_det += 1
            if fam(a) is not None and fam(a) == fam(b):
                failures.append(f"[entity_family] {a} <-> {b}: distinct pair wrongly shares "
                                f"family {fam(a)!r} — tighten the synonym net or entity wording")

        # Invariant 3 — canonical_key (only when the normalizer has been captured).
        if captured and a in captured and b in captured:
            checked_key += 1
            same_key = captured[a] == captured[b]
            want = p.get("expect_same_key")
            if want is True and not same_key:
                failures.append(f"[canonical_key] {a} <-> {b}: expected SAME key, got "
                                f"{captured[a]!r} vs {captured[b]!r}")
            if want is False and same_key:
                failures.append(f"[canonical_key] {a} <-> {b}: expected DIFFERENT keys, both {captured[a]!r}")

    print(f"selftest: {len(pairs)} golden pair(s); deterministic checks={checked_det}, "
          f"canonical_key checks={checked_key}"
          f"{' (captured_keys empty — run reconcile --golden to populate)' if not captured else ''}",
          file=sys.stderr)
    if failures:
        print("FAIL:", file=sys.stderr)
        for f in failures:
            print("  - " + f, file=sys.stderr)
        return 1
    print("OK — all golden invariants hold.", file=sys.stderr)
    return 0


# ── cli ──────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bucket", help="enrich + partition specs; emit the reconcile workload")
    b.add_argument("worklist")
    b.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    b.add_argument("--out", default="")
    b.set_defaults(func=cmd_bucket)

    a = sub.add_parser("apply", help="apply workflow verdicts; write reconciled worklist + report")
    a.add_argument("worklist")
    a.add_argument("adjudications")
    a.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    a.add_argument("--mode", choices=["suggest", "auto"], default="suggest")
    a.add_argument("--out-dir", default="")
    a.set_defaults(func=cmd_apply)

    s = sub.add_parser("selftest", help="run the golden-set regression test (§2.6)")
    s.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    s.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    s.set_defaults(func=cmd_selftest)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
