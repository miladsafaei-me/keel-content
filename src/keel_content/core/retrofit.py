"""Shared retrofit logic: insert already-rendered in-article visuals (figures or
NB2 images) into an ALREADY-IMPORTED post's ``content_raw``.

The generation workflow places visuals at import time via ``[[FIGURE:<id>]]`` /
``[[IMAGE:<id>]]`` markers; posts imported before a stage existed have no markers,
so the ``blog_add_figures`` / ``blog_add_images`` commands retrofit them. Both use
the SAME placement mechanics (heading-anchored insertion, idempotency, up-front
validation) and the SAME ``<figure class="cp-figure cp-figure--image">`` markup —
they differ only in which media store the WebP is copied into. That single-axis
difference is the ``store_fn`` argument here.

Manifest — a JSON list, one entry per visual::

    [{"id": "img-1", "src": "/abs/path/img-1.webp",
      "width": 1520, "height": 855,
      "alt": "...", "caption": "...",
      "after_heading_id": "why-a-vpn-does-not-help",   # heading's id= anchor
      "after_paragraphs": 1}]                           # 0 = right under the heading
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup
from django.core.management.base import CommandError

from keel_content import host
from keel_content.core.figures import figure_html


def retrofit_visuals(
    *,
    slug: str,
    entries: list,
    store_fn: Callable[[Path, str, str], tuple[str, int]],
    dry: bool,
    replace: bool,
    write: Callable[[str], None],
    noun: str = "figure",
) -> int:
    """Validate + insert each manifest entry's WebP into the post ``slug``.

    ``store_fn(src, slug, id) -> (public_url, byte_size)`` copies the WebP into the
    right media store (figures vs images). Returns the number inserted. All entries
    are validated before any write — a bad entry aborts the whole run."""
    Post = host.post_model()
    manager = getattr(Post, "all_objects", Post._default_manager)
    post = manager.filter(slug=slug).first()
    if post is None:
        raise CommandError(f"no post with slug {slug!r}")
    if not isinstance(entries, list) or not entries:
        raise CommandError("manifest must be a non-empty JSON list")

    body = post.content_raw or ""
    soup = BeautifulSoup(body, "html.parser")

    plan: list[tuple[dict, object]] = []
    for e in entries:
        fid = str(e.get("id") or "").strip()
        if not fid:
            raise CommandError(f"entry without id: {e!r}")
        if f'data-figure-id="{fid}"' in body:
            if not replace:
                write(f"  = skip   {fid} (already present; --replace to swap)")
                continue
            for old in soup.find_all("figure", attrs={"data-figure-id": fid}):
                old.decompose()
            write(f"  - remove {fid} (replacing)")
        src = Path(str(e.get("src") or "")).expanduser()
        if not src.is_file() or src.suffix != ".webp":
            raise CommandError(f"{fid}: src must be an existing .webp (got {src})")
        for key in ("width", "height"):
            if not isinstance(e.get(key), int) or e[key] <= 0:
                raise CommandError(f"{fid}: {key} must be a positive integer")
        if not str(e.get("alt") or "").strip() or not str(e.get("caption") or "").strip():
            raise CommandError(f"{fid}: alt and caption are required")
        heading_id = str(e.get("after_heading_id") or "").strip()
        heading = soup.find(id=heading_id) if heading_id else None
        if heading is None:
            raise CommandError(f"{fid}: no element with id={heading_id!r} in content_raw")
        skip_p = int(e.get("after_paragraphs") or 0)
        anchor = heading
        seen_p = 0
        for sib in heading.find_next_siblings():
            if seen_p >= skip_p:
                break
            anchor = sib
            if sib.name == "p":
                seen_p += 1
        if seen_p < skip_p:
            raise CommandError(
                f"{fid}: only {seen_p} <p> sibling(s) after #{heading_id}, needed {skip_p}"
            )
        plan.append((e, anchor))
        write(
            f"  + place  {e['id']} after #{heading_id}"
            + (f" + {skip_p} paragraph(s)" if skip_p else "")
        )

    if not plan:
        write("nothing to do")
        return 0
    if dry:
        write(f"dry-run: {len(plan)} {noun}(s) would be inserted")
        return 0

    for e, anchor in plan:
        url, size = store_fn(Path(str(e["src"])).expanduser(), slug, e["id"])
        markup = figure_html(
            src=url, alt=str(e["alt"]).strip(), caption=str(e["caption"]).strip(),
            width=e["width"], height=e["height"], figure_id=e["id"],
        )
        anchor.insert_after(BeautifulSoup(markup, "html.parser"))
        write(f"      {e['id']} -> {url} ({size // 1024} KB)")

    post.content_raw = str(soup)
    post.save(update_fields=["content_raw"])
    host.refresh_article_rendered(post)
    write(f"done: {len(plan)} {noun}(s) inserted into {slug}; content_rendered refreshed")
    return len(plan)
