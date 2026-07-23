"""``./manage.py content_add_external_sources <path>`` — append a verified
external "Sources & Further Reading" list to existing blog posts.

``<path>`` is a JSON file shaped as::

    [
      {"slug": "...", "external_sources": [
        {"url": "https://...", "anchor": "Source name — what it covers", "role": "citation"},
        {"url": "https://...", "anchor": "...", "role": "further_reading"}
      ]},
      ...
    ]

For each post, the proposed sources are run through the same deterministic gate as
``content_import`` (authoritative-domain allowlist + live HTTP 200), then the
survivors are appended to the post's Markdown body, re-rendered, and saved. The
append is idempotent — re-running replaces the section rather than duplicating it.

Use this to retrofit posts that predate external linking; new generation batches
get the section automatically via ``content_import`` / ``publish_from_bundle``.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host
from keel_content.core.external_links import apply_external_sources

Post = host.post_model()


class Command(BaseCommand):
    help = "Append a verified external Sources & Further Reading list to existing posts."

    def add_arguments(self, parser):
        parser.add_argument("path", help="JSON file: [{slug, external_sources:[{url,anchor,role}]}]")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Verify links and report, but do not write to the DB.",
        )

    def handle(self, *args, **opts):
        path = Path(opts["path"]).expanduser()
        dry = opts["dry_run"]
        if not path.is_file():
            raise CommandError(f"path not found: {path}")
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CommandError(f"unreadable JSON: {exc}")
        if not isinstance(entries, list):
            raise CommandError("top-level JSON must be a list of {slug, external_sources}")

        updated = skipped = missing = 0
        for entry in entries:
            slug = (entry or {}).get("slug")
            sources = (entry or {}).get("external_sources") or []
            if not slug:
                self.stderr.write(self.style.ERROR("  ! entry without a slug; skipped"))
                continue
            post = Post.all_objects.filter(slug=slug).first()
            if post is None:
                self.stderr.write(self.style.ERROR(f"  ! {slug}: no such post"))
                missing += 1
                continue

            new_md, report = apply_external_sources(post.content_markdown_source or "", sources)
            for d in report.dropped:
                self.stdout.write(f"      drop  {d.url or '(no url)'} — {d.reason}")
            for v in report.verified:
                self.stdout.write(f"      ok    {v.url}")

            if not report.verified:
                self.stdout.write(self.style.WARNING(f"  = {slug}: 0 verified — left unchanged"))
                skipped += 1
                continue
            if dry:
                self.stdout.write(f"  ~ {slug}: would append {len(report.verified)} source(s)")
                continue

            post.content_markdown_source = new_md
            post.content_raw = host.prepare_pipeline_content_for_storage(new_md)
            post.save(update_fields=["content_markdown_source", "content_raw"])
            host.refresh_article_rendered(post)
            updated += 1
            self.stdout.write(
                self.style.SUCCESS(f"  * {slug}: {report.summary}")
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"done: {updated} updated, {skipped} unchanged, {missing} missing"
            )
        )
