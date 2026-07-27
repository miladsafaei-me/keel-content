"""Report cp-component usage distribution across the blog corpus.

A read-only diversity monitor for the content pipeline: it classifies every
embedded ``cp-figure--embed`` component in each post's rendered body and reports
frequency, concentration, never-used catalog components, and per-post counts —
so a drift toward a narrow set of over-used "furniture" components (or a starved
analytical tail) is caught early rather than discovered by eye.

Business-blind: the component catalog universe comes from the installed
``keel_ui`` package; the blog model comes from the host via ``keel_content.host``.

Usage:
    manage.py component_usage_report            # human-readable report
    manage.py component_usage_report --json     # machine-readable JSON
    manage.py component_usage_report --status published
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from keel_content import host

_SLUG_RE = re.compile(r"cp-html-block-([a-z0-9-]+)")
_FIG_SPLIT = re.compile(r'<figure class="cp-figure cp-figure--embed">')
# Root-class rules for components that do NOT use the cp-html-block-<slug> wrapper.
# Most specific first; each maps a distinctive rendered class to a component id.
_ROOT_RULES = [
    ("cp-table", "comparison_table"),
    ("cp-doughnut", "chart_doughnut"),
    ("cp-stackbar", "chart_stacked_bar"),
    ("cp-figure-mermaid--state", "mermaid_state"),
    ("cp-figure-seq", "mermaid_sequence"),
    ("cp-figure-mermaid", "mermaid_flowchart"),
    ("cp-bar-wrapper", "chart_bar"),
]


def _catalog():
    """Return (slug2id, root_id_set, id2category) from the installed keel_ui package."""
    import keel_ui

    comp_dir = os.path.join(os.path.dirname(keel_ui.__file__), "components")
    slug2id: dict[str, str] = {}
    id2cat: dict[str, str] = {}
    for cat in sorted(os.listdir(comp_dir)):
        catp = os.path.join(comp_dir, cat)
        if not os.path.isdir(catp):
            continue
        for comp in sorted(os.listdir(catp)):
            d = os.path.join(catp, comp)
            tpl = os.path.join(d, "template.html")
            man = os.path.join(d, "manifest.json")
            if not os.path.exists(tpl):
                continue
            cid = comp.replace("-", "_")
            if os.path.exists(man):
                try:
                    with open(man, encoding="utf-8") as fh:
                        cid = json.load(fh).get("id", cid)
                except Exception:
                    pass
            id2cat[cid] = cat
            with open(tpl, encoding="utf-8") as fh:
                head = fh.read()
            for slug in set(_SLUG_RE.findall(head)):
                slug2id[slug] = cid
    return slug2id, id2cat


def _classify(frag: str, slug2id: dict[str, str]) -> str:
    m = _SLUG_RE.search(frag)
    if m and m.group(1) in slug2id:
        return slug2id[m.group(1)]
    for tok, cid in _ROOT_RULES:
        if tok in frag:
            return cid
    if "cp-figure-chart-interactive" in frag:
        return "chart_area"
    return "UNKNOWN"


class Command(BaseCommand):
    help = "Report cp-component usage distribution across the blog corpus (diversity monitor)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
        parser.add_argument(
            "--status", default=None,
            help="Restrict to posts with this status (e.g. published, draft).")

    def handle(self, *args, **opts):
        slug2id, id2cat = _catalog()
        Post = host.post_model()
        manager = getattr(Post, "objects")
        qs = manager.all()
        if opts.get("status"):
            qs = qs.filter(status=opts["status"])
        posts = list(qs.order_by("id"))

        total = Counter()
        posts_with = Counter()
        per_post: dict[int, list[str]] = {}
        for p in posts:
            body = getattr(p, "content_rendered", "") or ""
            ids = [_classify(frag[:4000], slug2id) for frag in _FIG_SPLIT.split(body)[1:]]
            per_post[p.pk] = ids
            for cid in ids:
                total[cid] += 1
            for cid in set(ids):
                posts_with[cid] += 1

        npost = len(posts)
        tot = sum(total.values())
        used = {k for k in total if k != "UNKNOWN"}
        never = sorted(set(id2cat) - used)
        cat_total = Counter()
        for cid, n in total.items():
            cat_total[id2cat.get(cid, "?")] += n

        def concentration(k):
            return round(100 * sum(n for _, n in total.most_common(k)) / tot, 1) if tot else 0.0

        if opts.get("json"):
            payload = {
                "posts": npost,
                "total_instances": tot,
                "avg_per_post": round(tot / npost, 2) if npost else 0.0,
                "catalog_size": len(id2cat),
                "used": len(used),
                "never_used": never,
                "frequency": [
                    {"component": cid, "instances": n, "posts": posts_with[cid],
                     "pct_posts": round(100 * posts_with[cid] / npost, 1) if npost else 0.0,
                     "pct_of_all": round(100 * n / tot, 1) if tot else 0.0}
                    for cid, n in total.most_common()
                ],
                "by_category": dict(cat_total.most_common()),
                "concentration": {f"top_{k}": concentration(k) for k in (3, 5, 8, 10)},
            }
            self.stdout.write(json.dumps(payload, indent=2))
            return

        w = self.stdout.write
        cpp = [len(v) for v in per_post.values()] or [0]
        w(f"Corpus: {npost} posts | {tot} component instances | "
          f"avg {tot / npost:.1f}/post (min {min(cpp)}, max {max(cpp)})" if npost else "No posts.")
        if not npost:
            return
        w("")
        w(f"{'component':30s} {'inst':>5} {'posts':>6} {'%posts':>7} {'%ofall':>7}")
        for cid, n in total.most_common():
            w(f"{cid:30s} {n:5d} {posts_with[cid]:6d} "
              f"{100 * posts_with[cid] / npost:6.0f}% {100 * n / tot:6.1f}%")
        w("")
        w("By category: " + ", ".join(f"{c} {n}" for c, n in cat_total.most_common()))
        w(f"Concentration: top-3 {concentration(3)}%  top-5 {concentration(5)}%  "
          f"top-8 {concentration(8)}%  top-10 {concentration(10)}%")
        w(f"Catalog: {len(id2cat)} components, {len(used)} used, {len(never)} never used")
        w("Never used: " + (", ".join(never) if never else "(none)"))
        if "UNKNOWN" in total:
            w(f"\nNote: {total['UNKNOWN']} instance(s) could not be classified "
              "(update _ROOT_RULES / slug map if a new component was added).")
