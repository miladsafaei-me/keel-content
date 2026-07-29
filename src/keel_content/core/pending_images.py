"""Deferred NB2 images — the machine-producible visuals a post lands without.

The content pipeline used to render the in-article NB2 photoreal images (and the
bespoke hero) inside the generation run. Measured on an 11-article cluster that
cost ~123 minutes of per-article chain for output nothing else in the run consumes,
so both moved to a standalone pass that runs AFTER ``content_import``.

That split needs the marker positions to survive import. This module is the
mechanism, and it deliberately mirrors :mod:`keel_content.core.asset_requests`:

* At import, :func:`defer_images` swaps each ``[[IMAGE:<id>]]`` marker for an
  INVISIBLE anchor. Invisible matters — a post accidentally published before its
  images exist shows a small gap, never a broken block or a raw ``[[IMAGE:...]]``
  token. The post is recorded ``images_ready=False`` with the work order on
  ``pending_visuals``.
* The standalone pass renders the images, then :func:`apply_rendered_images` swaps
  each anchor for the final ``<figure>`` markup and the post flips
  ``images_ready=True``.

The difference from ``asset_requests`` is who fills the hole: an asset request waits
for a human (a real screenshot, a funded-account video), a pending image waits for
the machine. They must not share a flag — ``needs_human_assets`` means "a person is
blocked on this", and a pending NB2 image never is.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from keel_content.core.figures import figure_html
from keel_content.core.images import normalize_images, store_image_file

# The author's in-body marker, alone on its own line: [[IMAGE:img-1]]
_MARKER_RE = re.compile(r"^\s*\[\[IMAGE:([A-Za-z0-9_-]+)\]\]\s*$", re.MULTILINE)

_ANCHOR_HTML = '<span class="pending-image-anchor" id="pending-image-{id}"></span>'

# Matches the anchor back out of stored / RE-SERIALIZED HTML. Attribute-order
# independent for the same reason the asset anchor is: the article-prep pass
# re-serializes tags through BeautifulSoup and may reorder attributes, so the
# anchor has to be recognized by lookaheads rather than by adjacency.
_ANCHOR_RE = re.compile(
    r'<span(?=[^>]*\bclass="[^"]*pending-image-anchor[^"]*")'
    r'(?=[^>]*\bid="pending-image-(?P<id>[A-Za-z0-9_-]+)")[^>]*>\s*</span>'
)


@dataclass
class PendingImageReport:
    deferred: list[str] = field(default_factory=list)   # markers turned into anchors
    placed: list[str] = field(default_factory=list)     # anchors filled with a figure
    unmatched: list[str] = field(default_factory=list)  # anchor with no rendered image


def normalize_image_requests(raw: Any) -> list[dict[str, Any]]:
    """Coerce a bundle's ``image_requests`` into the work order the standalone pass
    needs. Entries without an id are dropped — an image with no id has no marker to
    come back to."""
    out: list[dict[str, Any]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        iid = str(entry.get("id") or "").strip()
        if not iid:
            continue
        item = dict(entry)
        item["id"] = iid
        out.append(item)
    return out


def has_pending_anchors(rendered_html: str) -> bool:
    """True when stored HTML still carries at least one un-filled image anchor."""
    return bool(_ANCHOR_RE.search(rendered_html or ""))


def defer_images(body: str, image_requests: Any) -> tuple[str, list[dict[str, Any]], PendingImageReport]:
    """Replace every ``[[IMAGE:<id>]]`` marker with an invisible anchor.

    Returns ``(body, work_order, report)``. Called at import time ONLY when the
    bundle carries image requests but no rendered images — when the images are
    already rendered, ``keel_content.core.images.apply_images`` runs instead and
    this module never sees the body.

    An unmatched marker (a marker whose id has no request) still becomes an anchor
    rather than being stripped: the standalone pass can then decide what to do with
    it, and a stray token never reaches rendered prose either way.
    """
    requests = normalize_image_requests(image_requests)
    known = {r["id"] for r in requests}
    report = PendingImageReport()

    def _sub(match: re.Match) -> str:
        iid = match.group(1)
        report.deferred.append(iid)
        if iid not in known:
            report.unmatched.append(iid)
        return _ANCHOR_HTML.format(id=html.escape(iid))

    body = _MARKER_RE.sub(_sub, body or "")
    return body, requests, report


def apply_rendered_images(
    rendered_html: str, images: Any, *, bundle_dir: Path | None, slug: str
) -> tuple[str, PendingImageReport]:
    """Fill each pending-image anchor in STORED HTML with its final ``<figure>``.

    The inverse of :func:`defer_images`, run by the standalone images pass once the
    WebPs exist. Idempotent by construction: an anchor is consumed when it is
    filled, so re-running finds nothing left to do. An anchor with no matching
    rendered image is LEFT IN PLACE (not stripped) and reported — dropping it would
    silently lose the author's chosen position for that visual.
    """
    normalized = normalize_images(images)
    by_id = {im["id"]: im for im in normalized}
    report = PendingImageReport()

    def _sub(match: re.Match) -> str:
        iid = match.group("id")
        im = by_id.get(iid)
        if im is None or bundle_dir is None:
            report.unmatched.append(iid)
            return match.group(0)
        src_file = Path(bundle_dir) / im["file"]
        if not src_file.is_file():
            report.unmatched.append(iid)
            return match.group(0)
        url, _size = store_image_file(src_file, slug, iid)
        report.placed.append(iid)
        return figure_html(
            src=url,
            alt=im["alt"],
            caption=im["caption"],
            width=im["width"],
            height=im["height"],
            figure_id=iid,
        )

    return _ANCHOR_RE.sub(_sub, rendered_html or ""), report
