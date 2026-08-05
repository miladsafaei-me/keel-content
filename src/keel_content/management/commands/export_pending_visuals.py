"""Export the work orders for posts whose machine-produced visuals do not exist yet.

First half of the standalone images pass. The generation pipeline no longer draws the
bespoke hero or renders the in-article NB2 photoreal images (they added ~123 minutes of
per-article chain for output nothing in the run consumes), so a freshly imported post
lands with ``images_ready=False`` and its work order on ``pending_visuals``.

This command rehydrates one bundle-shaped JSON per pending post into a work dir, so the
EXISTING hero / NB2 agents run against exactly the file shape they already expect — the
images workflow needs no new prompt, and ``render_on_server.sh`` needs no new mode.

    manage.py export_pending_visuals --out /tmp/visuals
    # -> /tmp/visuals/<slug>.bundle.json (one per post) + /tmp/visuals/manifest.json

Then run ``tools/images.workflow.js`` over the manifest's ``contents`` and finish with
``manage.py apply_post_images /tmp/visuals``.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content.core import visual_queue
from keel_content.host import content_plan_model, post_model


class Command(BaseCommand):
    help = "Export bundle-shaped work orders for posts with images_ready=False."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="directory to write the work orders into")
        parser.add_argument("--slug", action="append", default=[],
                            help="limit to these slugs (repeatable); default = every pending post")
        parser.add_argument("--cluster",
                            help="limit to the posts produced by one topic cluster. The "
                                 "autopilot images a cluster right after it produces it, "
                                 "so a cluster becomes publishable before the next starts.")
        parser.add_argument("--limit", type=int, default=0,
                            help="cap how many posts to export this batch (0 = no cap)")
        parser.add_argument("--include-published", action="store_true",
                            help="also export published posts (default: drafts only — a "
                                 "published post missing its visuals is a separate cleanup)")
        parser.add_argument("--include-blocked", action="store_true",
                            help="also export posts marked blocked by flag_stuck_visuals "
                                 "(default: skipped — they are waiting on a human)")

    def handle(self, *args, **opts):
        out_dir = Path(opts["out"])
        out_dir.mkdir(parents=True, exist_ok=True)

        Post = post_model()
        if not hasattr(Post, "images_ready"):
            raise CommandError(
                "the post model has no images_ready field — apply the keel-cms migration "
                "that adds it (0002_post_images_ready) before running the images pass"
            )

        qs = visual_queue.pending_posts(
            Post,
            include_published=opts["include_published"],
            include_blocked=opts["include_blocked"],
        )
        if opts["slug"]:
            qs = qs.filter(slug__in=opts["slug"])
        if opts["cluster"]:
            ids = visual_queue.post_ids_for_cluster(content_plan_model(), opts["cluster"])
            if not ids:
                raise CommandError(
                    f"no produced post belongs to topic cluster '{opts['cluster']}'"
                )
            qs = qs.filter(id__in=ids)
        qs = qs.order_by("created_at")
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        contents = []
        for post in qs:
            work = post.pending_visuals or {}
            image_requests = work.get("image_requests") or []
            hero_needed = bool(work.get("hero_needed", True))
            if not image_requests and not hero_needed:
                # Nothing machine-producible is missing — the flag is stale (e.g. the
                # post was hand-edited). Say so; apply_post_images will settle it.
                self.stdout.write(f"  = nothing pending  {post.slug} (flag is stale)")
                continue

            bundle = {
                "content_id": post.slug,
                "slug": post.slug,
                "title": post.title,
                "h1": post.h1 or post.title,
                "meta_description": post.meta_description or "",
                # The images/hero agents read the body to decide WHAT to draw. The
                # markdown source is kept on the work order at import precisely so
                # they see the same prose the generation-time agents would have.
                "body_markdown": work.get("body_markdown") or post.content_raw or "",
                "image_requests": image_requests,
            }
            (out_dir / f"{post.slug}.bundle.json").write_text(
                json.dumps(bundle, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            contents.append({
                "slug": post.slug,
                "content_id": post.slug,
                "hero_needed": hero_needed,
                "image_count": len(image_requests),
            })
            self.stdout.write(
                f"  + work order  {post.slug}  (hero={'yes' if hero_needed else 'no'}, "
                f"images={len(image_requests)})"
            )

        (out_dir / "manifest.json").write_text(
            json.dumps({"count": len(contents), "contents": contents}, indent=1),
            encoding="utf-8",
        )
        self.stdout.write("")
        self.stdout.write(f"wrote {len(contents)} work order(s) -> {out_dir}")
        if contents:
            self.stdout.write(
                "next: run tools/images.workflow.js over manifest.contents, "
                f"then `manage.py apply_post_images {out_dir}`"
            )
