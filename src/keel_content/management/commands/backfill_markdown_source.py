"""``./manage.py backfill_markdown_source`` — give an HTML-only corpus a Markdown
body, but only where the conversion is provably reversible. No model involved.

Posts migrated from another CMS carry rendered HTML in ``content_raw`` and nothing
in ``content_markdown_source``. Every Markdown-based tool here is then a silent
no-op on them. This command closes that gap deterministically.

It is deliberately conservative, because the downside is asymmetric: writing a
Markdown source makes the publish path regenerate the VISIBLE body from it, so a
lossy conversion is a silent, permanent downgrade of a live article. Each post is
therefore converted, rendered back through the host's own renderer, and compared
with the original (see ``core/html_to_markdown.py`` for what the comparison
covers). A post that fails is left byte-for-byte untouched and reported.

**This command never rewrites ``content_raw`` or ``content_rendered``.** It only
fills ``content_markdown_source``, so the live page is unchanged the moment it
runs. The visible body changes later, on the next real edit — which is exactly
when it should.

    ./manage.py backfill_markdown_source --dry-run     # measure first, always
    ./manage.py backfill_markdown_source --report /tmp/skipped.json
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from keel_content import host
from keel_content.core.html_to_markdown import convert_checked


class Command(BaseCommand):
    help = "Fill empty content_markdown_source from content_raw where the round trip is faithful."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Measure; write nothing.")
        parser.add_argument("--limit", type=int, default=0, help="Cap posts processed (0 = all).")
        parser.add_argument(
            "--slug", default="", help="Only this slug (for inspecting one failure)."
        )
        parser.add_argument(
            "--report", default="", help="Write the skipped-post reasons to this JSON path."
        )
        parser.add_argument(
            "--overwrite", action="store_true",
            help="Also convert posts that ALREADY have a Markdown source. Off by "
                 "default: an authored Markdown body is the source of truth and must "
                 "never be silently replaced by one reverse-engineered from HTML.",
        )

    def handle(self, *args, **opts):
        Post = host.post_model()
        qs = Post.objects.exclude(content_raw="").order_by("slug")
        if not opts["overwrite"]:
            qs = qs.filter(content_markdown_source="")
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        render = host.markdown_to_blog_html
        converted = skipped = 0
        skipped_rows = []
        for post in qs:
            markdown, faithful, report = convert_checked(post.content_raw or "", render)
            if not faithful:
                skipped += 1
                skipped_rows.append({"slug": post.slug, **report})
                continue
            converted += 1
            if not opts["dry_run"]:
                # content_raw / content_rendered are deliberately NOT touched: the
                # live page must not move as a side effect of a backfill.
                post.content_markdown_source = markdown
                post.save(update_fields=["content_markdown_source"])

        if opts["report"] and skipped_rows:
            Path(opts["report"]).expanduser().write_text(
                json.dumps(skipped_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            self.stderr.write(f"skipped-post detail -> {opts['report']}")

        total = converted + skipped
        pct = (100 * converted // total) if total else 0
        tail = " [dry-run]" if opts["dry_run"] else ""
        self.stderr.write(self.style.SUCCESS(
            f"converted {converted} of {total} ({pct}%), skipped {skipped} as not "
            f"losslessly convertible{tail}"
        ))
        if skipped:
            self.stderr.write(self.style.WARNING(
                f"{skipped} post(s) keep HTML-only bodies and stay invisible to every "
                "Markdown-based pass (content_relink included). That is the safe "
                "outcome, not a failure — Markdown cannot represent their structure."
            ))
