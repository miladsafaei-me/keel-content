"""YouTube transcript extraction — the fetch half of the YouTube-transcript intake
route (path 4 into ``blog.ContentPlan``).

Zero-cost, no API key: shells out to ``yt-dlp`` to pull the video's existing
captions (manual first, else YouTube auto-captions) in the ``json3`` subtitle
format, then parses them into clean running text. The transcript becomes the
PRIMARY source material the generator writes the article from — see
``contentplan_ingest_youtube`` and the ``source_transcript`` field on ContentPlan.

If a video has NO caption track, :func:`extract` raises ``TranscriptUnavailable``
— that is the case a future Whisper audio-transcription fallback would cover; it
is intentionally out of scope for phase 1.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

_YOUTUBE_ID_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:[^#\s]*&)?v=|embed/|shorts/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)
_WS_RE = re.compile(r"\s+")


class TranscriptUnavailable(RuntimeError):
    """Raised when yt-dlp finds no usable caption track for the video."""


def video_id(url: str) -> str:
    """The 11-char YouTube id from any watch/short/embed/youtu.be URL (or "")."""
    m = _YOUTUBE_ID_RE.search(str(url or ""))
    return m.group(1) if m else ""


def canonical_url(url: str) -> str:
    """Normalize any YouTube URL form to the canonical ``watch?v=<id>`` form."""
    vid = video_id(url)
    return f"https://www.youtube.com/watch?v={vid}" if vid else str(url or "").strip()


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def fetch_metadata(url: str, *, timeout: int = 120) -> dict:
    """Return ``{id, title, channel, duration, upload_date}`` via one yt-dlp call."""
    fmt = "%(id)s\t%(title)s\t%(channel)s\t%(duration_string)s\t%(upload_date)s"
    proc = _run(["yt-dlp", "--skip-download", "--print", fmt, url], timeout)
    if proc.returncode != 0:
        raise TranscriptUnavailable(
            f"yt-dlp could not read metadata for {url!r}: {proc.stderr.strip()[:300]}"
        )
    parts = (proc.stdout.strip().split("\t") + [""] * 5)[:5]
    vid, title, channel, duration, upload_date = parts
    return {
        "id": vid or video_id(url),
        "title": title,
        "channel": channel,
        "duration": duration,
        "upload_date": upload_date,
    }


def _download_json3(url: str, lang: str, workdir: str, timeout: int) -> Path | None:
    """Try manual subs for ``lang``, then auto-captions. Return a json3 path or None."""
    base = str(Path(workdir) / "cap")
    for sub_flag in ("--write-subs", "--write-auto-subs"):
        _run(
            [
                "yt-dlp", "--skip-download", sub_flag,
                "--sub-langs", f"{lang},{lang}-orig,{lang}.*",
                "--sub-format", "json3",
                "-o", base + ".%(ext)s", url,
            ],
            timeout,
        )
        hits = sorted(
            Path(workdir).glob("cap*.json3"),
            # prefer the exact-lang file over the -orig alias when both exist
            key=lambda p: (f".{lang}." not in p.name, len(p.name)),
        )
        if hits:
            return hits[0]
    return None


def _parse_json3_segments(path: Path) -> list[tuple[float, str]]:
    """json3 -> ``[(start_second, text)]``.

    The start time of each caption line is kept rather than discarded, because it
    is the only thing connecting a sentence to a second of video - which is what
    the screenshot stage (:mod:`keel_content.core.youtube_frames`) needs in order
    to know where to look. Immediate duplicate phrases are dropped: YouTube's
    auto-captions scroll, so each event tends to restate the tail of the one
    before it.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[tuple[float, str]] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = _WS_RE.sub(" ", "".join(s.get("utf8", "") for s in segs).replace("\n", " ")).strip()
        if not text:
            continue
        if out and (text == out[-1][1] or text in out[-1][1]):
            continue
        if out and out[-1][1] in text:
            out[-1] = (out[-1][0], text)
            continue
        out.append((int(ev.get("tStartMs", 0)) / 1000.0, text))
    return out


def _parse_json3(path: Path) -> str:
    """json3 -> clean running text, timestamps dropped."""
    return " ".join(text for _, text in _parse_json3_segments(path)).strip()


def timecode(seconds: float) -> str:
    """Seconds as ``MM:SS``, growing an hours field only once past an hour."""
    total = int(max(0.0, seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def thin_index(segments: list[tuple[float, str]], *, every_seconds: float = 30.0) -> str:
    """A ``[MM:SS] text`` index at roughly one line per ``every_seconds``.

    A forty-minute video's full transcript is far too long to hand a model just to
    ask which moments deserve a picture; this keeps enough wording to tell what is
    happening when, at a fraction of the tokens.
    """
    lines: list[str] = []
    next_at = 0.0
    for start, text in segments:
        if start >= next_at:
            lines.append(f"[{timecode(start)}] {text}")
            next_at = start + every_seconds
    return "\n".join(lines)


def extract_segments(url: str, *, lang: str = "en", timeout: int = 120) -> dict:
    """Like :func:`extract`, but the transcript also comes back as timestamped
    ``segments`` - the form the screenshot stage needs."""
    url = str(url or "").strip()
    if not video_id(url):
        raise TranscriptUnavailable(f"not a recognizable YouTube URL: {url!r}")

    meta = fetch_metadata(url, timeout=timeout)
    with tempfile.TemporaryDirectory() as tmp:
        cap = _download_json3(url, lang, tmp, timeout)
        if cap is None:
            raise TranscriptUnavailable(
                f"no {lang} caption track for {url!r} (a Whisper audio fallback would "
                "be needed - out of scope for phase 1)"
            )
        segments = _parse_json3_segments(cap)
    if not segments:
        raise TranscriptUnavailable(f"caption file for {url!r} parsed to empty text")

    transcript = " ".join(text for _, text in segments)
    return {
        "video_id": meta["id"],
        "url": canonical_url(url),
        "title": meta["title"],
        "channel": meta["channel"],
        "duration": meta["duration"],
        "upload_date": meta["upload_date"],
        "transcript": transcript,
        "segments": segments,
        "words": len(transcript.split()),
    }


def extract(url: str, *, lang: str = "en", timeout: int = 120) -> dict:
    """Extract transcript + metadata for one YouTube URL.

    Returns ``{video_id, url, title, channel, duration, upload_date, transcript,
    words}``. Raises :class:`TranscriptUnavailable` if the video has no caption
    track or yt-dlp fails.
    """
    url = str(url or "").strip()
    if not video_id(url):
        raise TranscriptUnavailable(f"not a recognizable YouTube URL: {url!r}")

    meta = fetch_metadata(url, timeout=timeout)
    with tempfile.TemporaryDirectory() as tmp:
        cap = _download_json3(url, lang, tmp, timeout)
        if cap is None:
            raise TranscriptUnavailable(
                f"no {lang} caption track for {url!r} (a Whisper audio fallback would "
                "be needed — out of scope for phase 1)"
            )
        transcript = _parse_json3(cap)
    if not transcript:
        raise TranscriptUnavailable(f"caption file for {url!r} parsed to empty text")

    return {
        "video_id": meta["id"],
        "url": canonical_url(url),
        "title": meta["title"],
        "channel": meta["channel"],
        "duration": meta["duration"],
        "upload_date": meta["upload_date"],
        "transcript": transcript,
        "words": len(transcript.split()),
    }
