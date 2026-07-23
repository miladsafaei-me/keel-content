"""In-article NB2 images — photoreal scenes drawn by the ``image-nb2`` engine.

The pipeline's in-article visuals split by class (see ``VISUALIZATION.md`` §1):

* **drawn** diagrams/flows/comparisons → the SVG ``figures`` engine
  (:mod:`keel_content.core.figures`) or a typed ``cp-component``;
* **captured/rendered** photoreal scenes → the ``image-nb2`` engine here.

An ``image-nb2`` visual is a Gemini "nano banana" photoreal scene with a crisp
SVG brand/text overlay composited on top, rasterized to WebP — the same hybrid
used for blog covers, but *per-paragraph* rather than from the article title.
The author stage decides *where* a photoreal image (not a diagram) earns a place,
emits a ``[[IMAGE:<id>]]`` marker line plus a structured ``image_requests`` entry
(a per-paragraph scene brief + the exact in-image ``overlay_text``); the images
generation stage renders each one and patches an ``images`` array into the
bundle::

    images: [{"id": "img-1", "file": "<content_id>.images/img-1.webp",
              "scene": "<content_id>.images/img-1.scene.png",   # archived NB2 scene
              "svg":   "<content_id>.images/img-1.svg",          # archived overlay
              "width": 1520, "height": 855,
              "alt": "...", "caption": "..."}]

``file``/``scene``/``svg`` are relative to the bundle's own directory. At import,
:func:`apply_images` (called from ``publish_from_bundle``) copies each WebP under
``MEDIA_ROOT/blog/images/<year>/<month>/`` with a content-hashed name and replaces
the marker with the shared ``<figure class="cp-figure cp-figure--image">`` markup
(reused from :mod:`~keel_content.core.figures` — an in-article image is an
in-article image regardless of how it was drawn).

**Token-cost budget.** NB2 images cost image-model tokens, so the whole post is
capped at :data:`NB2_IMAGES_PER_1000_WORDS` per 1000 body words — a *global*
ceiling (:func:`nb2_cap`), never a per-section one: a 400-word span may carry 3
images as long as the whole-post total stays within the ceiling. The cap is
enforced in code by :func:`image_violations`, not left to the author's judgement.

:func:`image_violations` is the always-on integrity gate at import: marker ↔ entry
mismatches, missing files, missing alt/caption, and the over-budget check all
block the bundle before anything is written.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

from .figures import figure_html

# Matches a marker that stands alone on its own line: [[IMAGE:img-1]]
MARKER_RE = re.compile(r"^\s*\[\[IMAGE:([A-Za-z0-9_-]+)\]\]\s*$", re.MULTILINE)

# Whole-post ceiling on NB2 images: this many per full 1000 body words, floored
# by whole thousands (e.g. 3900 words -> 3 * 2 = 6). Global, not per-section.
NB2_IMAGES_PER_1000_WORDS = 2

# Baseline every post may carry regardless of length, so a sub-1000-word article
# can still ship 1-2 photoreal images (NB2 is the preferred in-article engine).
NB2_MIN_IMAGES = 2

# Strip these before counting words so the budget tracks real prose, not markup:
# fenced blocks (code / cp-component), placeholder markers, and HTML tags.
_FENCED_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKER_ANY_RE = re.compile(r"\[\[[A-Z]+:[A-Za-z0-9_-]+\]\]")
_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z'’-]*")


def count_words(body: str) -> int:
    """Approximate body word count used for the NB2 budget.

    Deterministic and dependency-free: drop fenced code/component blocks, drop
    ``[[...]]`` markers and HTML tags, then count word-like tokens. Numbers count
    as words (they read as words to a human scanning the article)."""
    text = _FENCED_RE.sub(" ", body or "")
    text = _MARKER_ANY_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    return len(_WORD_RE.findall(text))


def nb2_cap(word_count: int) -> int:
    """Max NB2 images allowed for a post of ``word_count`` words.

    Floored at :data:`NB2_MIN_IMAGES` so even a sub-1000-word post may carry 1-2
    photoreal images; longer posts scale up at :data:`NB2_IMAGES_PER_1000_WORDS`
    per full 1000 words (e.g. 3900 words -> ``max(2, 3 * 2)`` = 6)."""
    base = (max(0, int(word_count)) // 1000) * NB2_IMAGES_PER_1000_WORDS
    return max(NB2_MIN_IMAGES, base)


@dataclass
class ImageReport:
    placed: list[str] = field(default_factory=list)             # image ids rendered
    unmatched_markers: list[str] = field(default_factory=list)  # marker without an entry
    unplaced_images: list[str] = field(default_factory=list)    # entry without a marker


def normalize_images(raw: Any) -> list[dict[str, Any]]:
    """Coerce a bundle's ``images`` into clean dicts; entries without an id or
    file are dropped (they fail :func:`image_violations` anyway)."""
    out: list[dict[str, Any]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        iid = str(entry.get("id") or "").strip()
        file_rel = str(entry.get("file") or "").strip()
        if not iid or not file_rel:
            continue
        out.append({
            "id": iid,
            "file": file_rel,
            "width": entry.get("width"),
            "height": entry.get("height"),
            "alt": str(entry.get("alt") or "").strip(),
            "caption": str(entry.get("caption") or "").strip(),
        })
    return out


def marker_ids(body: str) -> list[str]:
    return MARKER_RE.findall(body or "")


def store_image_file(src: Path, slug: str, image_id: str) -> tuple[str, int]:
    """Copy one NB2 image WebP under MEDIA_ROOT with a content-hashed name.

    Returns ``(public_url, byte_size)``. Idempotent: same bytes → same name."""
    data = src.read_bytes()
    digest = hashlib.sha1(data).hexdigest()[:8]
    now = timezone.now()
    rel = Path("blog/images") / f"{now:%Y}" / f"{now:%m}" / f"{slug}.{image_id}.{digest}.webp"
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(data)
    return "/media/" + rel.as_posix(), len(data)


def apply_images(
    body: str, images: Any, *, bundle_dir: Path | None, slug: str
) -> tuple[str, ImageReport]:
    """Replace ``[[IMAGE:<id>]]`` markers with final ``<figure>`` markup.

    Copies each entry's WebP from the bundle directory into media storage. Mirrors
    :func:`keel_content.core.figures.apply_figures`; the shared
    ``cp-figure cp-figure--image`` markup is reused so in-article images render
    identically regardless of engine. Defensive: :func:`image_violations` runs
    first at import, so a mismatch here means a caller skipped the gate — an
    unmatched marker is stripped (never leaks into prose) and reported."""
    normalized = normalize_images(images)
    report = ImageReport()
    if not normalized and not MARKER_RE.search(body or ""):
        return body, report
    by_id = {im["id"]: im for im in normalized}
    seen: set[str] = set()

    def _sub(match: re.Match) -> str:
        iid = match.group(1)
        seen.add(iid)
        im = by_id.get(iid)
        if im is None or bundle_dir is None:
            report.unmatched_markers.append(iid)
            return ""
        src_file = Path(bundle_dir) / im["file"]
        if not src_file.is_file():
            report.unmatched_markers.append(iid)
            return ""
        url, _size = store_image_file(src_file, slug, iid)
        report.placed.append(iid)
        return figure_html(
            src=url, alt=im["alt"], caption=im["caption"],
            width=im["width"], height=im["height"], figure_id=iid,
        )

    body = MARKER_RE.sub(_sub, body or "")
    report.unplaced_images = [im["id"] for im in normalized if im["id"] not in seen]
    return body, report


def image_violations(bundle: dict | None, *, bundle_dir: Path | None) -> list[str]:
    """Always-on integrity checks for a bundle that carries NB2 images.

    A bundle with NO images and NO markers passes here — an article satisfies the
    at-least-one-visual floor (in ``content_import``) with either an NB2 image or
    an SVG figure. The whole-post NB2 budget (:func:`nb2_cap`) is enforced here as
    a hard ceiling."""
    if not isinstance(bundle, dict):
        return []
    body = bundle.get("body_markdown") or bundle.get("final_markdown") or ""
    entries = normalize_images(bundle.get("images"))
    raw_count = len([e for e in (bundle.get("images") or []) if isinstance(e, dict)])
    ids_in_body = marker_ids(body)
    out: list[str] = []

    if raw_count != len(entries):
        out.append("images: entry missing its id or file")
    dupes = {i for i in ids_in_body if ids_in_body.count(i) > 1}
    if dupes:
        out.append(f"images: duplicate [[IMAGE:...]] markers: {sorted(dupes)}")

    by_id = {e["id"]: e for e in entries}
    for iid in ids_in_body:
        if iid not in by_id:
            out.append(f"images: marker [[IMAGE:{iid}]] has no images entry")
    for iid in by_id:
        if iid not in ids_in_body:
            out.append(f"images: entry '{iid}' has no [[IMAGE:{iid}]] marker in the body")

    for e in entries:
        iid = e["id"]
        if not e["alt"]:
            out.append(f"images: '{iid}' is missing alt text")
        if not e["caption"]:
            out.append(f"images: '{iid}' is missing a caption")
        try:
            if int(e["width"] or 0) <= 0 or int(e["height"] or 0) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            out.append(f"images: '{iid}' is missing integer width/height")
        if not str(e["file"]).endswith(".webp"):
            out.append(f"images: '{iid}' file must be a .webp (got {e['file']!r})")
        elif bundle_dir is not None and not (Path(bundle_dir) / e["file"]).is_file():
            out.append(f"images: '{iid}' file not found next to the bundle: {e['file']}")

    # Whole-post token-cost budget: this is the hard ceiling, not the author's call.
    cap = nb2_cap(count_words(body))
    if len(entries) > cap:
        words = count_words(body)
        out.append(
            f"images: {len(entries)} NB2 images exceed the budget of {cap} for a "
            f"{words}-word post (max {NB2_IMAGES_PER_1000_WORDS} per 1000 words). "
            "Drop the lowest-value ones or render them as SVG figures instead."
        )
    return out
