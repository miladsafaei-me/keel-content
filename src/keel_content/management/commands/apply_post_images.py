"""Apply a finished images batch back onto its posts and flip ``images_ready``.

Second half of the standalone images pass (first half: ``export_pending_visuals``;
middle: ``tools/images.workflow.js``). Reads the work-order bundles the images
workflow just patched and, per post:

* renders the authored hero SVG and points ``featured_image_url`` at it, replacing
  the generic fallback ``content_import`` attached at draft time;
* fills every pending-image anchor left in the stored body with the final
  ``<figure>`` markup for its rendered WebP, then refreshes ``content_rendered``
  from it — that derived field is what the page serves, so skipping the refresh
  leaves every reader looking at the empty anchor;
* sets ``images_ready=True`` and clears ``pending_visuals``.

    manage.py apply_post_images /tmp/visuals

Safe to re-run: anchors are consumed as they are filled, and a post whose bundle
carries neither a hero nor an image is reported and left alone rather than being
marked ready on false pretences.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from keel_content import host
from keel_content.core.pending_images import apply_rendered_images, has_pending_anchors
from keel_content.host import post_model


class Command(BaseCommand):
    help = "Apply hero + NB2 images from a finished work-order dir; flip images_ready."

    def add_arguments(self, parser):
        parser.add_argument("bundles_dir", help="the dir export_pending_visuals wrote")
        parser.add_argument("--dry-run", action="store_true", help="report without writing")
        parser.add_argument(
            "--force-ready",
            action="store_true",
            help="mark a post ready even when its bundle produced no hero and no image "
                 "(use for posts that legitimately need neither)",
        )

    def handle(self, *args, **opts):
        work_dir = Path(opts["bundles_dir"])
        if not work_dir.is_dir():
            raise CommandError(f"no such dir: {work_dir}")

        Post = post_model()
        if not hasattr(Post, "images_ready"):
            raise CommandError(
                "the post model has no images_ready field — apply the keel-cms migration "
                "that adds it (0002_post_images_ready) first"
            )

        from keel_content.core.hero.pipeline import render_and_store, spec_from_dict

        dry = opts["dry_run"]
        ready = skipped = failed = 0

        for path in sorted(work_dir.glob("*.bundle.json")):
            try:
                bundle = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.stderr.write(self.style.ERROR(f"  ! unreadable {path.name}: {exc}"))
                failed += 1
                continue

            slug = bundle.get("slug") or path.name.replace(".bundle.json", "")
            post = Post.all_objects.filter(slug=slug).first()
            if post is None:
                self.stderr.write(self.style.WARNING(f"  ! no post for slug {slug}"))
                failed += 1
                continue

            hero_spec = bundle.get("hero") if isinstance(bundle.get("hero"), dict) else None
            images = bundle.get("images") or []
            if not hero_spec and not images and not opts["force_ready"]:
                self.stdout.write(
                    f"  = skip   {slug} (bundle carries no hero and no rendered image; "
                    "--force-ready to mark it done anyway)"
                )
                skipped += 1
                continue

            notes = []
            with transaction.atomic():
                update_fields = ["images_ready", "pending_visuals"]

                if hero_spec:
                    # force-overwrite: the URL currently on the post is the generic
                    # deterministic fallback content_import attached, and the whole
                    # point of this pass is to replace it with the bespoke hero.
                    spec = spec_from_dict(
                        hero_spec,
                        title=post.title,
                        category=getattr(post.category, "name", "") or "",
                    )
                    if not dry:
                        post.featured_image_url = render_and_store(spec, post.slug)
                        update_fields.append("featured_image_url")
                    notes.append("hero")

                if images:
                    filled, report = apply_rendered_images(
                        post.content_raw or "", images, bundle_dir=path.parent, slug=post.slug
                    )
                    if not dry:
                        post.content_raw = filled
                        update_fields.append("content_raw")
                        # The editable markdown source carries the same deferred
                        # anchors. Fill them here too, otherwise it keeps the empty
                        # anchor forever and a later Markdown-tab edit re-serializes
                        # that gap over the figure — silently dropping the image
                        # while ``images_ready`` says the post is done. store_image_file
                        # is content-hashed + idempotent, so applying the same bundle
                        # to both fields in one run resolves to the same media URL.
                        md_src = post.content_markdown_source or ""
                        if has_pending_anchors(md_src):
                            md_filled, _ = apply_rendered_images(
                                md_src, images, bundle_dir=path.parent, slug=post.slug
                            )
                            post.content_markdown_source = md_filled
                            update_fields.append("content_markdown_source")
                    notes.append(f"{len(report.placed)} image(s)")
                    if report.unmatched:
                        notes.append(f"{len(report.unmatched)} anchor(s) still unfilled")

                still_pending = has_pending_anchors(post.content_raw or "")
                if not dry:
                    post.images_ready = not still_pending or opts["force_ready"]
                    post.pending_visuals = {}
                    post.save(update_fields=sorted(set(update_fields)))
                    if images:
                        # ``content_raw`` is the source, but the page serves
                        # ``content_rendered`` (``Post.content`` prefers it). Without
                        # this refresh the figures exist only in the source and every
                        # reader still sees the empty anchor — while ``images_ready``
                        # says the post is cleared. Same call ``retrofit`` makes after
                        # it writes ``content_raw``.
                        host.refresh_article_rendered(post)
                        notes.append("rendered refreshed")

            state = "ready" if (not has_pending_anchors(post.content_raw or "") or opts["force_ready"]) else "STILL PENDING"
            prefix = "  ~ dry  " if dry else "  + done "
            self.stdout.write(f"{prefix} {slug}: {', '.join(notes)} -> {state}")
            ready += 1

        self.stdout.write("")
        verb = "would apply" if dry else "applied"
        self.stdout.write(f"{verb}: {ready} post(s), {skipped} skipped, {failed} failed")
        if not dry and ready:
            self.stdout.write("posts with images_ready=True are cleared for the publish review")
