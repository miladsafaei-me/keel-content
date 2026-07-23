"""Asset-request placeholders — the human-supplied elements an LLM author cannot make.

When the author (following the brief) decides a section needs an element it cannot
produce — a YouTube walkthrough video, a real platform screenshot, first-party data —
it emits a structured entry in the bundle's ``asset_requests`` list and drops a
matching ``[[ASSET:<id>]]`` marker on its own line in ``body_markdown``:

    asset_requests: [{"id": "ar-1", "type": "video",
                      "description": "YouTube walkthrough of installing the MT5 connector",
                      "placement": "after the 'Installation' H2"}]

At import, :func:`apply_asset_requests` (called from ``publish_from_bundle``) replaces
each marker with an INVISIBLE, empty anchor (``<span id="asset-<id>">``) — a reader of
the published page never sees the request, and its text never reaches the public HTML.
The request details live only in the structured ``Post.asset_requests`` list: the
admin post editor shows them with a jump link to each anchor, and the STAFF PREVIEW
(:func:`inject_preview_placeholders`, applied by ``PostPreviewView`` at render time)
expands each anchor into the visible dashed box so editors see exactly where every
element belongs. The publisher flags the Post (``needs_human_assets=True``) so the
content team can filter for it in ``/admin-os/blog/``. Deterministic and idempotent:
markers are recomputed from the bundle on every (re-)import.

Types are advisory, not validated against a closed set — ``video`` / ``screenshot`` /
``photo`` / ``data`` / ``chart`` cover the expected cases.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

# Matches a marker that stands alone on its own line: [[ASSET:ar-1]]
_MARKER_RE = re.compile(r"^\s*\[\[ASSET:([A-Za-z0-9_-]+)\]\]\s*$", re.MULTILINE)

# What the PUBLIC page carries: an empty, invisible anchor. No description text —
# a published article must never expose its own production gaps. The id lets the
# admin editor and the staff preview jump to / render at the exact location.
_ANCHOR_HTML = '<span class="asset-request-anchor" id="asset-{id}" data-asset-type="{type}"></span>'

# Matches the anchor back out of stored/RE-SERIALIZED HTML (preview-time
# expansion). Attribute-order-independent on purpose: the article-prep pass
# (BeautifulSoup in blog.views._prepare_body) re-serializes tags and reorders
# attributes, so the anchor must be recognized by lookaheads, not adjacency.
_ANCHOR_RE = re.compile(
    r'<span(?=[^>]*\bclass="[^"]*asset-request-anchor[^"]*")'
    r'(?=[^>]*\bid="asset-(?P<id>[A-Za-z0-9_-]+)")[^>]*>\s*</span>'
)

# What the STAFF PREVIEW shows in place of each anchor. Styled by
# ``.asset-request-placeholder`` in blog-news.css; no inline styles per CSS rules.
_PREVIEW_HTML = (
    '<div class="asset-request-placeholder" data-asset-id="{id}">'
    '<span class="asset-request-placeholder__type">{type}</span>'
    "<p>Content element needed: {description}</p>"
    "{placement}"
    "</div>"
)
_PREVIEW_PLACEMENT_HTML = '<p class="asset-request-placeholder__placement">Planned placement: {placement}</p>'


@dataclass
class AssetRequestReport:
    placed: list[str] = field(default_factory=list)      # marker ids rendered
    unmatched_markers: list[str] = field(default_factory=list)  # marker without a request
    unplaced_requests: list[str] = field(default_factory=list)  # request without a marker


def normalize_asset_requests(raw: Any) -> list[dict[str, str]]:
    """Coerce a bundle's ``asset_requests`` into clean ``{id,type,description,placement}``
    dicts; entries without an id or description are dropped."""
    out: list[dict[str, str]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        rid = str(entry.get("id") or "").strip()
        desc = str(entry.get("description") or "").strip()
        if not rid or not desc:
            continue
        out.append({
            "id": rid,
            "type": str(entry.get("type") or "asset").strip().lower() or "asset",
            "description": desc,
            "placement": str(entry.get("placement") or "").strip(),
        })
    return out


def apply_asset_requests(
    body: str, requests: Any
) -> tuple[str, list[dict[str, str]], AssetRequestReport]:
    """Replace ``[[ASSET:<id>]]`` markers with invisible location anchors.

    Returns ``(body, normalized_requests, report)``. An unmatched marker (no request
    with that id) is still replaced — with an anchor — so a stray token never leaks
    into rendered prose; it is surfaced in the report for the operator. A request
    without a marker stays in the structured list (the admin badge still fires) and
    is reported as unplaced. The public page never shows the request text; the staff
    preview expands the anchors via :func:`inject_preview_placeholders`.
    """
    normalized = normalize_asset_requests(requests)
    by_id = {r["id"]: r for r in normalized}
    report = AssetRequestReport()
    seen: set[str] = set()

    def _sub(match: re.Match) -> str:
        rid = match.group(1)
        seen.add(rid)
        req = by_id.get(rid)
        if req is None:
            report.unmatched_markers.append(rid)
            return _ANCHOR_HTML.format(id=html.escape(rid), type="asset")
        report.placed.append(rid)
        return _ANCHOR_HTML.format(
            id=html.escape(req["id"]), type=html.escape(req["type"])
        )

    body = _MARKER_RE.sub(_sub, body or "")
    report.unplaced_requests = [r["id"] for r in normalized if r["id"] not in seen]
    return body, normalized, report


def inject_preview_placeholders(rendered_html: str, requests: Any) -> str:
    """Expand asset anchors into visible dashed boxes — STAFF PREVIEW only.

    Takes stored/rendered HTML containing ``asset-request-anchor`` spans and returns
    it with each anchor followed by the full request card (type, description,
    planned placement) so an editor sees exactly where every human-supplied element
    belongs. The anchor itself is kept so ``#asset-<id>`` fragment links from the
    admin editor land here. Never call this on a public render.
    """
    if not rendered_html or "asset-request-anchor" not in rendered_html:
        return rendered_html
    by_id = {r["id"]: r for r in normalize_asset_requests(requests)}

    def _sub(match: re.Match) -> str:
        rid = match.group("id")
        req = by_id.get(rid)
        if req is None:
            description = "(no matching asset_requests entry — describe what belongs here)"
            rtype, placement = "asset", ""
        else:
            description = req["description"]
            rtype, placement = req["type"], req["placement"]
        placement_html = (
            _PREVIEW_PLACEMENT_HTML.format(placement=html.escape(placement))
            if placement
            else ""
        )
        return match.group(0) + _PREVIEW_HTML.format(
            id=html.escape(rid),
            type=html.escape(rtype),
            description=html.escape(description),
            placement=placement_html,
        )

    return _ANCHOR_RE.sub(_sub, rendered_html)
