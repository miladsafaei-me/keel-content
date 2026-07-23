"""In-article figures — standalone explanatory images drawn by the pipeline.

The author stage decides *where* an image earns a place and emits a
``[[FIGURE:<id>]]`` marker line plus a structured ``figure_requests`` entry; a
post-generation stage draws each figure as an SVG, rasterizes it to WebP
(``tools/content_pipeline/figure_rasterize.sh``), vision-judges the pixels, and
patches a ``figures`` array into the bundle::

    figures: [{"id": "fig-1", "file": "<content_id>.figures/fig-1.webp",
               "svg": "<content_id>.figures/fig-1.svg",
               "width": 1520, "height": 855,
               "alt": "...", "caption": "..."}]

``file``/``svg`` are relative to the bundle's own directory. At import,
:func:`apply_figures` (called from ``publish_from_bundle``) copies each WebP
under ``MEDIA_ROOT/blog/figures/<year>/<month>/`` with a content-hashed name
(mirrors the hero convention) and replaces the marker with the final
``<figure class="cp-figure cp-figure--image">`` markup — explicit
``width``/``height`` (CLS), ``loading="lazy" decoding="async"`` (CWV), honest
``alt`` and a takeaway ``figcaption``.

:func:`figure_violations` is the always-on integrity gate at import: marker ↔
entry mismatches, missing files, or missing alt/caption block the bundle before
anything is written. The "at least one figure" floor is enforced separately in
``content_import`` (override: ``--allow-no-figures``).
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

# Matches a marker that stands alone on its own line: [[FIGURE:fig-1]]
MARKER_RE = re.compile(r"^\s*\[\[FIGURE:([A-Za-z0-9_-]+)\]\]\s*$", re.MULTILINE)

_FIGURE_HTML = (
    '<figure class="cp-figure cp-figure--image" data-figure-id="{fid}">'
    '<img src="{src}" alt="{alt}" width="{width}" height="{height}"'
    ' loading="lazy" decoding="async">'
    "<figcaption>{caption}</figcaption>"
    "</figure>"
)


@dataclass
class FigureReport:
    placed: list[str] = field(default_factory=list)        # figure ids rendered
    unmatched_markers: list[str] = field(default_factory=list)  # marker without an entry
    unplaced_figures: list[str] = field(default_factory=list)   # entry without a marker


def normalize_figures(raw: Any) -> list[dict[str, Any]]:
    """Coerce a bundle's ``figures`` into clean dicts; entries without an id or
    file are dropped (they fail :func:`figure_violations` anyway)."""
    out: list[dict[str, Any]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        fid = str(entry.get("id") or "").strip()
        file_rel = str(entry.get("file") or "").strip()
        if not fid or not file_rel:
            continue
        out.append({
            "id": fid,
            "file": file_rel,
            "width": entry.get("width"),
            "height": entry.get("height"),
            "alt": str(entry.get("alt") or "").strip(),
            "caption": str(entry.get("caption") or "").strip(),
        })
    return out


def marker_ids(body: str) -> list[str]:
    return MARKER_RE.findall(body or "")


def store_figure_file(src: Path, slug: str, figure_id: str) -> tuple[str, int]:
    """Copy one figure WebP under MEDIA_ROOT with a content-hashed name.

    Returns ``(public_url, byte_size)``. Idempotent: same bytes → same name.
    """
    data = src.read_bytes()
    digest = hashlib.sha1(data).hexdigest()[:8]
    now = timezone.now()
    rel = Path("blog/figures") / f"{now:%Y}" / f"{now:%m}" / f"{slug}.{figure_id}.{digest}.webp"
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(data)
    return "/media/" + rel.as_posix(), len(data)


def figure_html(*, src: str, alt: str, caption: str, width: Any, height: Any,
                figure_id: str) -> str:
    return _FIGURE_HTML.format(
        fid=html.escape(figure_id),
        src=html.escape(src),
        alt=html.escape(alt),
        width=int(width),
        height=int(height),
        caption=html.escape(caption),
    )


def apply_figures(
    body: str, figures: Any, *, bundle_dir: Path | None, slug: str
) -> tuple[str, FigureReport]:
    """Replace ``[[FIGURE:<id>]]`` markers with final ``<figure>`` markup.

    Copies each entry's WebP from the bundle directory into media storage.
    Defensive by design — :func:`figure_violations` runs first at import, so a
    mismatch here means a caller skipped the gate: an unmatched marker is
    stripped (never leaks into prose) and reported; an entry without a marker
    is reported as unplaced.
    """
    normalized = normalize_figures(figures)
    report = FigureReport()
    if not normalized and not MARKER_RE.search(body or ""):
        return body, report
    by_id = {f["id"]: f for f in normalized}
    seen: set[str] = set()

    def _sub(match: re.Match) -> str:
        fid = match.group(1)
        seen.add(fid)
        fig = by_id.get(fid)
        if fig is None or bundle_dir is None:
            report.unmatched_markers.append(fid)
            return ""
        src_file = Path(bundle_dir) / fig["file"]
        if not src_file.is_file():
            report.unmatched_markers.append(fid)
            return ""
        url, _size = store_figure_file(src_file, slug, fid)
        report.placed.append(fid)
        return figure_html(
            src=url, alt=fig["alt"], caption=fig["caption"],
            width=fig["width"], height=fig["height"], figure_id=fid,
        )

    body = MARKER_RE.sub(_sub, body or "")
    report.unplaced_figures = [f["id"] for f in normalized if f["id"] not in seen]
    return body, report


def figure_violations(bundle: dict | None, *, bundle_dir: Path | None) -> list[str]:
    """Always-on integrity checks for a bundle that carries figures.

    A bundle with NO figures and NO markers passes here — the "at least one
    figure" floor lives in ``content_import`` (blog bundles only, overridable
    with ``--allow-no-figures``) so news/legacy bundles stay importable.
    """
    if not isinstance(bundle, dict):
        return []
    body = bundle.get("body_markdown") or bundle.get("final_markdown") or ""
    entries = normalize_figures(bundle.get("figures"))
    raw_count = len([e for e in (bundle.get("figures") or []) if isinstance(e, dict)])
    ids_in_body = marker_ids(body)
    out: list[str] = []

    if raw_count != len(entries):
        out.append("figures: entry missing its id or file")
    dupes = {i for i in ids_in_body if ids_in_body.count(i) > 1}
    if dupes:
        out.append(f"figures: duplicate [[FIGURE:...]] markers: {sorted(dupes)}")

    by_id = {e["id"]: e for e in entries}
    for fid in ids_in_body:
        if fid not in by_id:
            out.append(f"figures: marker [[FIGURE:{fid}]] has no figures entry")
    for fid in by_id:
        if fid not in ids_in_body:
            out.append(f"figures: entry '{fid}' has no [[FIGURE:{fid}]] marker in the body")

    for e in entries:
        fid = e["id"]
        if not e["alt"]:
            out.append(f"figures: '{fid}' is missing alt text")
        if not e["caption"]:
            out.append(f"figures: '{fid}' is missing a caption")
        try:
            if int(e["width"] or 0) <= 0 or int(e["height"] or 0) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            out.append(f"figures: '{fid}' is missing integer width/height")
        if not str(e["file"]).endswith(".webp"):
            out.append(f"figures: '{fid}' file must be a .webp (got {e['file']!r})")
        elif bundle_dir is not None and not (Path(bundle_dir) / e["file"]).is_file():
            out.append(f"figures: '{fid}' file not found next to the bundle: {e['file']}")
    return out
