#!/usr/bin/env python3
"""Turn a /seo-clustering SCAFFOLD spec JSON into a content-pipeline worklist.

The keyword-clustering skill classifies each content INTO the fixed scaffold and
persists a spec JSON (``docs/seo/clusters/<base>.spec.json``) that
``cluster_xlsx.py write --scaffold`` renders. In scaffold mode each *keyword
cluster* is one content (a planned page) carrying its own facet slugs; this script
reconstructs each as one worklist spec — the SAME shape
``tools/content_pipeline/parse_top_pages.py`` emits — so
``manage.py contentplan_ingest --source-type keyword_clustering`` deposits them into
the ContentPlan roadmap exactly like a top-pages worklist. Reading the structured
spec JSON (not the rendered xlsx) keeps the parse robust.

Facets pass through as the scaffold SLUGS the spec carries; ``contentplan_ingest``'s
resolver matches a Category / Market / Audience / Tag by slug OR name. The demand
signal here is keyword volume — the clustering path has no competitor URLs/traffic,
so ``priority`` is set to the cluster's total search volume (a sane queue-ordering
proxy).

The current clustering workflow also CRAFTS each content's ``title`` / ``h1`` /
``slug`` / ``intent_frame`` / ``entity`` (the intent sentence is a user need, not a
publishable title). This parser passes those through verbatim and carries the
cluster's ``keywords`` (``[{keyword, volume}]``) into the worklist so they reach the
ContentPlan row and, later, the author brief. Legacy specs without a crafted title
fall back to the intent sentence (pre-scaffold behavior) — re-cluster rather than
ship that fallback for real production.

Pure standard library.

Usage:
  parse_clusters.py <spec.json> [--top N] [--cluster NAME ...] [--date YYYY-MM-DD] [--out path.json]
"""

import argparse
import datetime
import json
import re
import sys


def _slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def _parse_volume(raw):
    """Best-effort integer volume from int / '1,200' / '1.2K' style cells."""
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw or "").strip().lower().replace(",", "")
    if not s:
        return 0
    mult = 1
    if s.endswith("k"):
        mult, s = 1000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def _read_contents(spec):
    """Yield one spec dict per content (keyword cluster) across every topic."""
    contents = []
    # Review-only buckets the cluster-market workflow appends (keywords not assigned to
    # any intent, dropped as out-of-scope, or diverted as a non-article Product/Tool/Review
    # surface) are never blog content — skip them so they can never accidentally ingest as
    # a blog row even if left in the spec. Kept in sync with cluster_xlsx.BUCKET_TOPIC_NAMES.
    _skip_topics = {"unclustered", "out of scope", "non-blog content"}
    for topic in spec.get("topic_clusters", []):
        topic_name = str(topic.get("name", "")).strip()
        if topic_name.lower() in _skip_topics:
            continue
        # A topic aligned to an existing TopicCluster carries its slug — the ingest
        # resolver joins that exact cluster (route-independent content spine).
        topic_slug = str(topic.get("slug", "")).strip().lower()
        for ci, content in enumerate(topic.get("keyword_clusters", [])):
            # The scaffold spec carries a crafted title; legacy specs only have the
            # intent sentence (a user need, not a publishable title) as fallback.
            title = (content.get("title") or content.get("intent") or content.get("name") or "").strip()
            if not title:
                continue
            kws = content.get("keywords", []) or []
            total_volume = sum(_parse_volume(k.get("volume")) for k in kws)
            keywords = [
                {"keyword": str(k.get("keyword", "")).strip(),
                 "volume": _parse_volume(k.get("volume"))}
                for k in kws
                if str(k.get("keyword", "")).strip()
            ]
            keywords.sort(key=lambda k: -k["volume"])
            contents.append({
                "topic_cluster": topic_name,
                "topic_cluster_slug": topic_slug,
                "title": title,
                "h1": (content.get("h1") or "").strip(),
                "intent": content.get("intent") or "",
                "intent_frame": str(content.get("intent_frame", "")).strip().lower(),
                "search_intent": "informational",
                "entity": (content.get("entity") or "").strip(),
                "content_type": str(content.get("content_type", "blog")).strip().lower() or "blog",
                "role": str(content.get("role", "")).strip().lower(),
                "categories": list(content.get("categories") or []),
                "markets": list(content.get("markets") or []),
                "audience_roles": list(content.get("audience_roles") or []),
                "audience_levels": list(content.get("audience_levels") or []),
                "glossary_terms": list(content.get("glossary_terms") or []),
                "priority": total_volume,
                # intent_clarity (1-3) crafted by the clustering workflow — a winnability
                # signal that rides into ContentPlan.clarity and the priority composite.
                "clarity": int(content.get("intent_clarity") or 0) or 0,
                "competitors": 0,
                "traffic": 0,
                "keyword_volume": total_volume,
                "keywords": keywords,
                # SERP-verify's sampled ranking URLs (spec `serp_urls`) become the
                # brief stage's crawl evidence — same field/semantics the top-pages
                # route uses: "pages that rank for this need".
                "competitor_urls": list(content.get("serp_urls") or []),
                # A crafted slug from the clustering stage wins; _slugify(title)
                # fills it in main() otherwise.
                "slug": _slugify(content.get("slug") or ""),
                # Cannibalization-prevention fields — empty at parse; the reconcile
                # step fills observed_intent / canonical_key / scopes.
                "observed_intent": "",
                "canonical_key": "",
                "scope_includes": [],
                "scope_excludes": [],
                "canonical_owner": "",
            })
    return contents


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="A /seo-clustering scaffold spec .json")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--cluster", action="append", default=[])
    ap.add_argument("--date", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    contents = _read_contents(spec)

    if args.cluster:
        wanted = set(args.cluster)
        contents = [c for c in contents if c["topic_cluster"] in wanted]
    if args.top:
        contents = sorted(contents, key=lambda c: -c["priority"])[: args.top]

    date_prefix = args.date or datetime.date.today().isoformat()
    for c in contents:
        c["slug"] = c.get("slug") or _slugify(c["title"])
        c["content_id"] = f"{date_prefix}-{c['slug']}"[:80]

    worklist = {
        "source": args.spec,
        "generated_date": date_prefix,
        "count": len(contents),
        "contents": contents,
    }
    text = json.dumps(worklist, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"Wrote {len(contents)} content specs -> {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
