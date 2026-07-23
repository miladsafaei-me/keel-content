"""YouTube video embeds — LLM-sourced video elements, deterministically verified.

When the brief calls for a video element, the author FIRST tries to source a real
YouTube video from a credible channel (official platform/broker channels,
established educators — never competitor signal-sellers) instead of handing the
work to a human. The bundle carries:

    video_embeds: [{"id": "vid-1", "url": "https://www.youtube.com/watch?v=...",
                    "title": "Installing the MT5 connector", "channel": "MetaQuotes",
                    "placement": "inside the 'Installation' H2"}]

with a matching ``[[VIDEO:<id>]]`` marker on its own line in ``body_markdown``.

At import, :func:`apply_video_embeds` (called from ``publish_from_bundle``, outside
the DB transaction) verifies each video via YouTube's oEmbed endpoint — the same
LLM-proposes / deterministic-code-verifies split as ``external_links``:

- 2xx  -> embeddable; the marker becomes a privacy-enhanced ``youtube-nocookie.com``
  iframe (no cookies before play, per the site's consent policy) wrapped in
  ``.video-embed`` (styled in blog-news.css).
- definitive 4xx -> the video is gone/unembeddable; the marker is downgraded to an
  ``[[ASSET:<id>]]`` placeholder + a synthetic asset request, so the draft is
  flagged "Needs assets" and a human supplies the element.
- network error -> kept on trust (rendered) with a report warning — the reviewer's
  real browser is the final verifier, mirroring VERIFY_EXEMPT_DOMAINS.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

_MARKER_RE = re.compile(r"^\s*\[\[VIDEO:([A-Za-z0-9_-]+)\]\]\s*$", re.MULTILINE)

# watch?v=ID | youtu.be/ID | shorts/ID | embed/ID — the 11-char YouTube video id.
_VIDEO_ID_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:[^#\s]*&)?v=|embed/|shorts/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)

_OEMBED_ENDPOINT = "https://www.youtube.com/oembed"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# Privacy-enhanced embed: youtube-nocookie.com sets no cookies until playback, so
# the embed complies with the consent policy (only analytics may pre-consent).
_EMBED_HTML = (
    '<div class="video-embed" data-video-id="{vid}">'
    '<iframe src="https://www.youtube-nocookie.com/embed/{vid}" '
    'title="{title}" loading="lazy" '
    'allow="accelerometer; encrypted-media; picture-in-picture" '
    "allowfullscreen></iframe>"
    '<p class="video-embed__caption">{caption}</p>'
    "</div>"
)


@dataclass
class VideoEmbedReport:
    embedded: list[str] = field(default_factory=list)        # marker ids rendered
    kept_on_trust: list[str] = field(default_factory=list)   # network error, rendered anyway
    downgraded: list[tuple[str, str]] = field(default_factory=list)  # (id, reason) -> asset request
    unmatched_markers: list[str] = field(default_factory=list)


def extract_video_id(url: str) -> str:
    m = _VIDEO_ID_RE.search(str(url or ""))
    return m.group(1) if m else ""


def _oembed_check(url: str) -> tuple[str, dict[str, Any]]:
    """Return ("ok" | "gone" | "unknown", oembed_payload)."""
    try:
        resp = requests.get(
            f"{_OEMBED_ENDPOINT}?{urlencode({'url': url, 'format': 'json'})}",
            headers={"User-Agent": _UA},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("video_embeds: oEmbed unreachable for %s (%s)", url, exc)
        return "unknown", {}
    if 200 <= resp.status_code < 300:
        try:
            return "ok", resp.json()
        except (ValueError, json.JSONDecodeError):
            return "ok", {}
    if 400 <= resp.status_code < 500:
        return "gone", {}
    return "unknown", {}


def normalize_video_embeds(raw: Any) -> list[dict[str, str]]:
    """Coerce a bundle's ``video_embeds`` into clean dicts; entries without an id
    or a parseable YouTube URL are dropped."""
    out: list[dict[str, str]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        rid = str(entry.get("id") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not rid or not extract_video_id(url):
            continue
        out.append({
            "id": rid,
            "url": url,
            "title": str(entry.get("title") or "").strip(),
            "channel": str(entry.get("channel") or "").strip(),
            "placement": str(entry.get("placement") or "").strip(),
        })
    return out


def apply_video_embeds(
    body: str, embeds: Any, *, verify: bool = True
) -> tuple[str, list[dict[str, str]], VideoEmbedReport]:
    """Replace ``[[VIDEO:<id>]]`` markers with verified YouTube embeds.

    Returns ``(body, fallback_asset_requests, report)``. A failed verification
    downgrades the marker to ``[[ASSET:<id>]]`` and emits a matching synthetic
    asset request — ``apply_asset_requests`` (which must run AFTER this pass)
    renders the placeholder and the post gets flagged for the content team.
    An unmatched marker downgrades the same way (never leaks into prose).
    """
    normalized = normalize_video_embeds(embeds)
    by_id = {e["id"]: e for e in normalized}
    report = VideoEmbedReport()
    fallbacks: list[dict[str, str]] = []

    def _downgrade(rid: str, entry: dict[str, str] | None, reason: str) -> str:
        report.downgraded.append((rid, reason))
        fallback_id = f"video-{rid}"
        fallbacks.append({
            "id": fallback_id,
            "type": "video",
            "description": (
                (entry or {}).get("title")
                or "a video the author proposed could not be verified"
            ) + f" (proposed: {(entry or {}).get('url', 'no url')}; {reason})",
            "placement": (entry or {}).get("placement", ""),
        })
        return f"[[ASSET:{fallback_id}]]"

    def _sub(match: re.Match) -> str:
        rid = match.group(1)
        entry = by_id.get(rid)
        if entry is None:
            report.unmatched_markers.append(rid)
            return _downgrade(rid, None, "no matching video_embeds entry")
        vid = extract_video_id(entry["url"])
        title, channel = entry["title"], entry["channel"]
        if verify:
            status, payload = _oembed_check(entry["url"])
            if status == "gone":
                return _downgrade(rid, entry, "YouTube oEmbed says gone/unembeddable")
            if status == "unknown":
                report.kept_on_trust.append(rid)
            else:
                title = payload.get("title") or title
                channel = payload.get("author_name") or channel
        report.embedded.append(rid)
        caption = title + (f" — {channel}" if channel else "")
        return _EMBED_HTML.format(
            vid=html.escape(vid),
            title=html.escape(title or "Video"),
            caption=html.escape(caption),
        )

    body = _MARKER_RE.sub(_sub, body or "")
    return body, fallbacks, report
