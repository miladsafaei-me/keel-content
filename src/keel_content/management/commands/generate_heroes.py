"""``./manage.py generate_heroes`` -- the independent end-of-pipeline hero task.

Generates a code-authored SVG featured image (one of five styles, chosen per
post by concept) for blog posts and sets ``featured_image_url``. Run it after a
pipeline batch publishes, or to backfill existing posts.

    ./manage.py generate_heroes --missing            # pipeline posts with no hero
    ./manage.py generate_heroes --slug a-slug b-slug  # specific posts
    ./manage.py generate_heroes --all --force         # regenerate every pipeline post
    ./manage.py generate_heroes --slug x --style glow --motif hub_spokes  # manual override
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host
from keel_content.core.hero import MOTIFS, STYLES


class Command(BaseCommand):
    help = "Generate + attach SVG hero featured images for blog posts."

    def add_arguments(self, parser):
        parser.add_argument("--slug", nargs="*", default=[], help="Specific post slug(s).")
        parser.add_argument("--missing", action="store_true", help="Pipeline posts with no featured image.")
        parser.add_argument("--all", action="store_true", help="All pipeline-generated posts.")
        parser.add_argument("--force", action="store_true", help="Overwrite an existing featured image.")
        parser.add_argument("--style", choices=sorted(STYLES), help="Force a style for every selected post.")
        parser.add_argument("--motif", choices=sorted(MOTIFS), help="Force a motif for every selected post.")
        parser.add_argument(
            "--manifest",
            help="Path to a JSON map {slug: {style, motif, params, head:[[text,color],...], "
            "category?, head_size?}} of bespoke per-post hero specs. Implies --force.",
        )

    def handle(self, *args, **opts):
        Post = host.post_model()

        if opts.get("manifest"):
            return self._from_manifest(opts["manifest"])

        from keel_content.core.hero.pipeline import attach_hero_to_post

        qs = Post.objects.all()
        if opts["slug"]:
            qs = qs.filter(slug__in=opts["slug"])
        elif opts["missing"]:
            qs = qs.filter(is_pipeline_generated=True, featured_image_url="")
        elif opts["all"]:
            qs = qs.filter(is_pipeline_generated=True)
        else:
            raise CommandError("Pick a target: --slug <...>, --missing, or --all.")

        posts = list(qs.order_by("slug"))
        if not posts:
            self.stdout.write("No matching posts.")
            return

        done = skipped = 0
        for post in posts:
            url = attach_hero_to_post(post, force=opts["force"], style=opts["style"], motif=opts["motif"])
            if url:
                done += 1
                self.stdout.write(self.style.SUCCESS(f"  hero  {post.slug}  ->  {url}"))
            else:
                skipped += 1
                self.stdout.write(f"  skip  {post.slug} (already has a hero; use --force)")
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{done} generated, {skipped} skipped."))

    def _from_manifest(self, path: str) -> None:
        """Render bespoke, content-designed heroes from a slug→spec manifest (force-overwrite)."""
        Post = host.post_model()
        from keel_content.core.hero.pipeline import render_and_store, spec_from_dict

        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        done = missing = 0
        for slug, e in data.items():
            post = Post.all_objects.filter(slug=slug).first()
            if post is None:
                missing += 1
                self.stderr.write(self.style.WARNING(f"  ! no post for slug {slug}"))
                continue
            spec = spec_from_dict(e, title=post.title, category=getattr(post.category, "name", "") or "")
            url = render_and_store(spec, slug)
            post.featured_image_url = url
            post.save(update_fields=["featured_image_url"])
            done += 1
            kind = "freeform" if e.get("svg_element") else f"{e.get('style')}/{e.get('motif')}"
            self.stdout.write(self.style.SUCCESS(f"  hero  {slug}  ->  {kind}  {url}"))
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{done} generated, {missing} missing."))
