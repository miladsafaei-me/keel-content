"""``./manage.py blog_add_images --slug <slug> --manifest <images.json>`` —
insert already-rendered NB2 photoreal images into an ALREADY-IMPORTED post.

The NB2 counterpart of ``blog_add_figures``: same placement mechanics and the
same ``<figure class="cp-figure cp-figure--image">`` markup, but the WebP is
copied into the images media store (``blog/images/<Y>/<m>/``). Render each image
first with the pipeline (``render_on_server.sh … nb2_image``), then feed the
resulting ``<id>.webp`` path + placement here.

Manifest shape + ``after_heading_id`` / ``after_paragraphs`` semantics are shared
with ``blog_add_figures`` — see :mod:`keel_content.core.retrofit`.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content.core.images import store_image_file
from keel_content.core.retrofit import retrofit_visuals


class Command(BaseCommand):
    help = "Insert already-rendered NB2 photoreal images into an already-imported post."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="Post slug to retrofit.")
        parser.add_argument("--manifest", required=True, help="Path to the images JSON manifest.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Validate + report placements without writing anything.",
        )
        parser.add_argument(
            "--replace", action="store_true",
            help="If a manifest image id already exists in the body, remove the old "
            "<figure> block and insert the new one (default: skip existing ids).",
        )

    def handle(self, *args, **opts):
        manifest_path = Path(opts["manifest"]).expanduser()
        try:
            entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CommandError(f"unreadable manifest {manifest_path}: {exc}") from exc
        retrofit_visuals(
            slug=opts["slug"], entries=entries, store_fn=store_image_file,
            dry=opts["dry_run"], replace=opts["replace"],
            write=self.stdout.write, noun="image",
        )
