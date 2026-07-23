"""``./manage.py blog_add_figures --slug <slug> --manifest <figures.json>`` —
insert pipeline-drawn figures into an ALREADY-IMPORTED post.

Posts imported before the figures stage existed have no ``[[FIGURE:<id>]]``
markers; this retrofits them: it copies each WebP into media storage (the
content-hashed ``blog/figures/<Y>/<m>/`` convention) and inserts the final
``<figure>`` markup into ``content_raw`` at a position addressed by heading id,
then refreshes ``content_rendered``. Placement mechanics + manifest shape are
shared with ``blog_add_images`` — see :mod:`keel_content.core.retrofit`.

``after_paragraphs`` counts the ``<p>`` siblings after the heading; the figure
lands after the Nth one. Idempotent: an entry whose ``data-figure-id`` already
exists in the body is skipped (``--replace`` to swap). All entries are validated
before anything is written.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content.core.figures import store_figure_file
from keel_content.core.retrofit import retrofit_visuals


class Command(BaseCommand):
    help = "Insert pipeline-drawn in-article figures into an already-imported post."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="Post slug to retrofit.")
        parser.add_argument("--manifest", required=True, help="Path to the figures JSON manifest.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Validate + report placements without writing anything.",
        )
        parser.add_argument(
            "--replace", action="store_true",
            help="If a manifest figure id already exists in the body, remove the old "
            "<figure> block and insert the new one (default: skip existing ids).",
        )

    def handle(self, *args, **opts):
        manifest_path = Path(opts["manifest"]).expanduser()
        try:
            entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CommandError(f"unreadable manifest {manifest_path}: {exc}") from exc
        retrofit_visuals(
            slug=opts["slug"], entries=entries, store_fn=store_figure_file,
            dry=opts["dry_run"], replace=opts["replace"],
            write=self.stdout.write, noun="figure",
        )
