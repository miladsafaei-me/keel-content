"""``./manage.py anchor_registry_report [--cluster NAME] [--out PATH]`` — the
site-wide anchor-conflict report.

Every published post's body already carries whatever internal links earlier
generation/linking passes put there. Nothing today checks whether two of those
links, planned independently by two different cluster passes that never saw each
other, claimed the *same anchor phrase* for two *different* targets — cluster A's
pass links "copy trading" to `/blog/copy-trading`, cluster B's pass (run weeks
later, blind to A) links the same phrase to `/trading-glossary/copy-trading`, and
nothing surfaces the collision until a human happens to read both articles.

This command runs `core/anchor_registry.py`'s scan over every published post,
normalizes every internal-link anchor it finds (Unicode-correct: two of the five
consuming projects publish Persian), groups by target, and prints every anchor
that resolved to more than one distinct target — sorted by how many times the
anchor was used in total, so the highest-traffic collision surfaces first.

Run this:
- after any internal-linking pass (cluster-internal-links, the future
  cross-cluster pass, or a manual `content_relink apply`) to confirm it did not
  introduce a new collision;
- periodically as a standing site-health check, the same way
  `content_outbound_domains` is run periodically to watch the external-link
  profile.

**Report only.** This command reads; it never writes to a Post. Resolving a
conflict (repointing one of the competing links) is a human decision followed by
a separate, deliberate edit — see `intent-gate-rollout.md` P1.1's hard
constraint. `core.anchor_registry.claimed_target()` is the lookup a *linking*
pass calls before proposing a new edge, so future edges stop adding to this
report instead of only being caught by it after the fact.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from keel_content.core.anchor_registry import scan_anchor_registry


class Command(BaseCommand):
    help = "Report anchor phrases that resolve to more than one internal-link target."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            default="",
            help="Write the JSON report here (default: stdout).",
        )
        parser.add_argument(
            "--cluster",
            default=None,
            help="Limit the scan to one TopicCluster.name instead of the whole site.",
        )

    def handle(self, *args, **opts):
        registry = scan_anchor_registry(cluster=opts["cluster"])
        conflicts = registry.conflicts()

        report = {
            "cluster": opts["cluster"] or "(site-wide)",
            "distinct_anchors_scanned": len(registry.counts),
            "conflicting_anchors": len(conflicts),
            "conflicts": conflicts,
        }
        text = json.dumps(report, indent=2, ensure_ascii=False)

        if opts["out"]:
            Path(opts["out"]).expanduser().write_text(text + "\n", encoding="utf-8")
            self.stderr.write(
                self.style.WARNING(
                    f"{len(conflicts)} conflicting anchor(s) out of {len(registry.counts)} "
                    f"scanned -> {opts['out']}"
                )
                if conflicts
                else self.style.SUCCESS(
                    f"0 conflicts across {len(registry.counts)} scanned anchors -> {opts['out']}"
                )
            )
        else:
            self.stdout.write(text)
