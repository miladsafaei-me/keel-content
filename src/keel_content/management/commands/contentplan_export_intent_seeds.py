"""``./manage.py contentplan_export_intent_seeds --out <path>`` — dump the rows
that still have no declared ``intent``, in batches an authoring agent can judge.

``contentplan_backfill`` reconstructs a ContentPlan row per live post, but it
cannot author an ``intent``: the one-line statement of the exact user need a page
owns is a judgement, not a derivation. Every backfilled corpus therefore lands
with ``intent=""`` — and both downstream stages silently degrade when it is
missing. Reconcile's adjudicator loses its strongest signal, and the linking pass
falls back to topical relatedness, which is the precise failure
``content-standard.md`` §4's anchor rule exists to prevent.

This command is the read half of the fix. It emits the minimum a judge needs
(title, h1, excerpt, cluster, role, and the article's opening prose) and nothing
more, so an authoring pass stays cheap. Feed each batch to an agent, collect the
manifest, then apply it with ``contentplan_ingest_intents`` — the write half,
which is fully deterministic and never calls a model.

    ./manage.py contentplan_export_intent_seeds --out /tmp/seeds.json --batch-size 25
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from keel_content import host

_TAG_RE = re.compile(r"<[^>]+>")


def _plain(text: str, limit: int) -> str:
    """Strip markup/whitespace down to a short prose sample."""
    flat = _TAG_RE.sub(" ", text or "")
    flat = re.sub(r"[#*`_>\[\]()|-]+", " ", flat)
    flat = re.sub(r"\s+", " ", flat).strip()
    return flat[:limit]


class Command(BaseCommand):
    help = "Export ContentPlan rows lacking an intent, batched for an authoring agent."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="Path to write the seed JSON.")
        parser.add_argument(
            "--batch-size", type=int, default=25,
            help="Rows per batch (default 25). One batch = one agent task.",
        )
        parser.add_argument(
            "--limit", type=int, default=0, help="Cap total rows (0 = no cap)."
        )
        parser.add_argument(
            "--all", action="store_true",
            help="Include rows that already have an intent (default: only blank ones).",
        )

    def handle(self, *args, **opts):
        ContentPlan = host.content_plan_model()
        qs = ContentPlan.objects.select_related("topic_cluster", "produced_post")
        if not opts["all"]:
            qs = qs.filter(intent="")
        qs = qs.order_by("topic_cluster__slug", "slug")
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        rows = []
        for plan in qs:
            post = plan.produced_post
            rows.append({
                "slug": plan.slug,
                "title": plan.title or "",
                "h1": plan.h1 or "",
                "role": plan.role or "",
                "cluster": getattr(plan.topic_cluster, "slug", "") or "",
                "excerpt": _plain(getattr(post, "excerpt", "") or "", 300),
                # The opening prose disambiguates titles that read alike; capped
                # hard so a 339-row corpus stays one cheap agent pass, not a
                # full-corpus read.
                "opening": _plain(getattr(post, "content_markdown_source", "") or "", 700),
            })

        size = max(1, opts["batch_size"])
        batches = [rows[i : i + size] for i in range(0, len(rows), size)]
        payload = {"count": len(rows), "batch_size": size, "batches": batches}
        Path(opts["out"]).expanduser().write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self.stderr.write(self.style.SUCCESS(
            f"Wrote {len(rows)} row(s) in {len(batches)} batch(es) -> {opts['out']}"
        ))
