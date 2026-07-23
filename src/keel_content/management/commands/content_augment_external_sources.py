"""``./manage.py content_augment_external_sources <path>`` — APPEND extra external
"Sources & Further Reading" links to existing posts **without removing the ones
already there**.

This is the additive sibling of ``content_add_external_sources``. That command
rebuilds the whole Sources list from the JSON it is given (re-verifying every
link and re-applying the Wikipedia cap), so it can *drop* a currently-published
link. This command instead keeps every existing link **verbatim** and only
appends new, verified ones — used to widen the outbound-domain diversity of
already-published posts after the fast-lane allowlist grew.

``<path>`` is a JSON file shaped as::

    [
      {"slug": "...", "add": [
        {"url": "https://...", "anchor": "Source name — what it covers", "role": "further_reading"}
      ]},
      ...
    ]

For each post: the existing Sources section is parsed and preserved as-is; each
proposed ``add`` link is dropped if it duplicates an existing URL or points at
Wikipedia (we append only *diversifying* domains), then the survivors are run
through the same deterministic gate as ``content_import`` (allowlist / vetted +
live HTTP 200) and appended after the existing links. Idempotent: a second run
re-dedupes new links against what is now already present.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content import host
from keel_content.core.external_links import (
    SourceCheck,
    domain_of,
    render_sources_markdown,
    strip_sources_section,
    verify_sources,
)

Post = host.post_model()

_SECTION_RE = re.compile(r"(?is)^#{2,3}[ \t]+sources\b.*", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_NORM = lambda u: u.rstrip("/").lower()  # noqa: E731


def _existing_links(markdown: str) -> list[tuple[str, str]]:
    """Return [(anchor, url)] parsed from the post's existing Sources section."""
    m = _SECTION_RE.search(markdown or "")
    if not m:
        return []
    return [(a.strip(), u.strip()) for a, u in _LINK_RE.findall(markdown[m.start():])]


class Command(BaseCommand):
    help = "Append extra verified external sources to existing posts without removing current links."

    def add_arguments(self, parser):
        parser.add_argument("path", help="JSON file: [{slug, add:[{url,anchor,role}]}]")
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
            raise CommandError("top-level JSON must be a list of {slug, add}")

        updated = skipped = missing = added_total = 0
        for entry in entries:
            slug = (entry or {}).get("slug")
            add = (entry or {}).get("add") or []
            if not slug:
                self.stderr.write(self.style.ERROR("  ! entry without a slug; skipped"))
                continue
            post = Post.all_objects.filter(slug=slug).first()
            if post is None:
                self.stderr.write(self.style.ERROR(f"  ! {slug}: no such post"))
                missing += 1
                continue

            md = post.content_markdown_source or ""
            existing = _existing_links(md)
            existing_urls = {_NORM(u) for _, u in existing}

            # Only genuinely-new, non-Wikipedia domains get appended.
            candidates = []
            for raw in add:
                url = (raw.get("url") or "").strip()
                if not url:
                    continue
                if _NORM(url) in existing_urls:
                    self.stdout.write(f"      skip  {url} — already present")
                    continue
                if "wikipedia.org" in domain_of(url):
                    self.stdout.write(f"      skip  {url} — Wikipedia (append only diversifying domains)")
                    continue
                candidates.append(raw)

            report = verify_sources(candidates)
            for d in report.dropped:
                self.stdout.write(f"      drop  {d.url or '(no url)'} — {d.reason}")

            new_checks = report.verified
            if not new_checks:
                self.stdout.write(self.style.WARNING(f"  = {slug}: 0 new verified — left unchanged"))
                skipped += 1
                continue

            # Preserve every existing link verbatim (no re-verify, no cap), append new.
            preserved = [
                SourceCheck(url=u, anchor=a, role="further_reading", ok=True) for a, u in existing
            ]
            combined = preserved + new_checks
            new_md = strip_sources_section(md) + "\n\n" + render_sources_markdown(combined)

            for v in new_checks:
                self.stdout.write(f"      add   {v.url}")
            if dry:
                self.stdout.write(
                    f"  ~ {slug}: would append {len(new_checks)} (keep {len(preserved)} existing)"
                )
                added_total += len(new_checks)
                continue

            post.content_markdown_source = new_md
            post.content_raw = host.prepare_pipeline_content_for_storage(new_md)
            post.save(update_fields=["content_markdown_source", "content_raw"])
            host.refresh_article_rendered(post)
            updated += 1
            added_total += len(new_checks)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  * {slug}: +{len(new_checks)} new (kept {len(preserved)} existing)"
                )
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"done: {updated} updated, {skipped} unchanged, {missing} missing, "
                f"{added_total} links appended"
            )
        )
