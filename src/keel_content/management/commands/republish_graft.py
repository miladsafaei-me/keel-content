"""``manage.py republish_graft <payload.json>`` — put one visual into a post
that already exists.

The republish route does not assume one source page becomes one article. Its
smallest useful output is a single visual: a chart or a comparison lifted from
somewhere, rebuilt as one of our components or drawn as our own figure, and
dropped into an article published months ago. No new URL, no rewrite.

The block goes into **both** bodies a post keeps — ``content_rendered`` (what
the page shows) and ``content_markdown_source`` (what an editor sees) — so the
two never disagree. Every graft carries a ``data-graft-id``: running the same
payload again replaces its own block instead of stacking a second copy.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.html import escape

from keel_content import host


def _fence(visual: dict) -> str:
    return "```cp-component\n" + json.dumps(visual, ensure_ascii=False) + "\n```"


def _component_html(visual: dict, graft_id: str) -> str:
    from keel_ui import render as render_component
    from keel_ui.registry import ComponentNotFound
    from keel_ui.renderer import RenderError, SpecValidationError
    try:
        inner = render_component(visual["component_id"], visual.get("spec") or {},
                                 prune_additional=True)
    except (ComponentNotFound, SpecValidationError, RenderError) as exc:
        raise CommandError(f"component {visual['component_id']}: {exc}") from None
    return _wrap(inner, visual.get("eyebrow"), visual.get("caption"), graft_id, "embed")


def _figure_html(figure: dict, graft_id: str) -> str:
    """Copy a drawn WebP into media and return its <figure>, mirroring the
    convention ``keel_content.core.figures`` uses for pipeline figures."""
    src = Path(figure["file"])
    if not src.exists():
        raise CommandError(f"figure file not found: {src}")
    digest = hashlib.sha1(src.read_bytes()).hexdigest()[:8]
    now = datetime.utcnow()
    rel = Path("blog/figures") / f"{now:%Y}" / f"{now:%m}" / f"{graft_id}.{digest}.webp"
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    url = f"{settings.MEDIA_URL.rstrip('/')}/{rel.as_posix()}"
    img = (f'<img src="{escape(url)}" alt="{escape(figure["alt"])}" '
           f'width="{figure.get("width", 1200)}" height="{figure.get("height", 675)}" '
           f'loading="lazy" decoding="async">')
    return _wrap(img, figure.get("eyebrow"), figure.get("caption"), graft_id, "image")


def _wrap(inner: str, eyebrow, caption, graft_id: str, variant: str) -> str:
    eye = f'<div class="cp-figure__eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    cap = (f'<figcaption class="cp-figure__caption">{escape(caption)}</figcaption>'
           if caption else "")
    return (f'<figure class="cp-figure cp-figure--{variant}" '
            f'data-graft-id="{escape(graft_id)}">{eye}{inner}{cap}</figure>')


def _strip_existing(text: str, graft_id: str) -> str:
    text = re.sub(
        r'<figure class="cp-figure cp-figure--(?:embed|image)" data-graft-id="'
        + re.escape(graft_id) + r'">.*?</figure>\s*', "", text, flags=re.DOTALL)
    return re.sub(
        r"<!--graft:" + re.escape(graft_id) + r"-->\n(?:```cp-component\n.*?\n```|"
        r"!\[[^\]]*\]\([^)]*\))\s*", "", text, flags=re.DOTALL)


def _md_heading(text, needle):
    return re.search(r"^#{2,4}\s+" + re.escape(needle) + r".*$", text, re.MULTILINE)


def _html_heading(text, needle):
    return re.search(r"<h[2-4][^>]*>\s*" + re.escape(needle) + r"\s*</h[2-4]>",
                     text, re.IGNORECASE)


def _insert(text, block, anchor, finder):
    if anchor["mode"] == "end":
        return text.rstrip() + "\n\n" + block + "\n", True
    m = finder(text, anchor["text"])
    if not m:
        return text, False
    at = m.start() if anchor["mode"] == "before_heading" else m.end()
    return text[:at] + "\n\n" + block + "\n\n" + text[at:], True


class Command(BaseCommand):
    help = "Graft one rendered visual into an existing post."

    def add_arguments(self, parser):
        parser.add_argument("payload", help="A graft payload written by compose().")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        path = Path(options["payload"])
        if not path.exists():
            raise CommandError(f"no such payload: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        slug = payload["target_slug"]
        graft_id = payload["graft_id"]
        anchor = payload["anchor"]

        Post = host.post_model()
        try:
            post = Post.objects.get(slug=slug)
        except Post.DoesNotExist:
            raise CommandError(f"no post with slug {slug!r}") from None

        if payload.get("visual"):
            block = _component_html(payload["visual"], graft_id)
            md_block = "<!--graft:%s-->\n%s" % (graft_id, _fence(payload["visual"]))
            what = payload["visual"]["component_id"]
        elif payload.get("figure"):
            fig = payload["figure"]
            block = _figure_html(fig, graft_id)
            md_block = ("<!--graft:%s-->\n![%s](%s)"
                        % (graft_id, fig["alt"], fig["file"]))
            what = f"figure/{fig.get('builder', 'drawn')}"
        else:
            raise CommandError("payload carries neither a visual nor a figure")

        html = _strip_existing(post.content_rendered or "", graft_id)
        md = _strip_existing(post.content_markdown_source or "", graft_id)
        html, html_ok = _insert(html, block, anchor, _html_heading)
        md, md_ok = _insert(md, md_block, anchor, _md_heading)

        if not html_ok:
            raise CommandError(
                f"anchor heading {anchor['text']!r} not found in {slug} "
                f"(mode={anchor['mode']})")
        if not md_ok:
            self.stdout.write(self.style.WARNING(
                "  anchor not found in the markdown source; rendered body updated only"))

        from keel_cms.models import read_time_minutes_for
        minutes = read_time_minutes_for(html)

        if options["dry_run"]:
            self.stdout.write(f"would graft {graft_id} ({what}) into {slug} "
                              f"{anchor['mode']} {anchor['text']!r}")
            self.stdout.write(f"  read time {post.read_time_minutes} -> {minutes}")
            return

        post.content_rendered = html
        post.content_markdown_source = md
        post.read_time_minutes = minutes
        post.save(update_fields=["content_rendered", "content_markdown_source",
                                 "read_time_minutes"])
        self.stdout.write(self.style.SUCCESS(
            f"grafted {graft_id} ({what}) into {slug} "
            f"{anchor['mode']} {anchor['text']!r}"))
