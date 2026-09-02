"""Screenshots from a YouTube video — the visual half of the YouTube intake route.

``youtube_transcript`` answers what was *said*; this answers what was *shown*. For
a walkthrough video — a chart being marked up, a platform being configured, a
result being read off the screen — the picture carries what no amount of prose
from the transcript can, and until now the route produced articles from such
videos with no image of the thing being taught.

Three things make the output usable rather than a bag of random stills:

1. **Moments are chosen from the timestamped transcript before anything is
   downloaded**, so only a few seconds of low-resolution video are ever fetched
   instead of a whole file.
2. **Each moment yields a burst of frames, not one.** The exact second a sentence
   begins is very often the presenter's face, a cursor mid-move, or a cross-fade;
   sampling either side and then choosing gets a usable frame nearly every time.
3. **The busiest frames are shortlisted mechanically** — a chart full of candles,
   gridlines and text does not compress well, so JPEG size ranks detailed frames
   above empty ones — and the final pick is a judgement call left to the caller.

Deliberately Django-free and runnable on its own, because capture needs ``yt-dlp``
and ``ffmpeg``, which live on a workstation and not in the production container::

    python -m keel_content.core.youtube_frames plan     --url <url> --out <dir>
    python -m keel_content.core.youtube_frames capture  --url <url> --out <dir> --moments m.json
    python -m keel_content.core.youtube_frames finalize --out <dir> --slug <slug> --selection s.json

``finalize`` writes WebPs plus ``figures-manifest.json`` in exactly the shape
``./manage.py blog_add_figures --slug <slug> --manifest <file>`` consumes, so the
screenshots land in an already-imported draft through the existing retrofit path
rather than through a second one built only for video.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# Video-only and height-capped: frames are read for charts and panels, and audio
# would double the download for nothing.
_FORMAT = "bv*[height<=720][ext=mp4]/bv*[height<=720]/best[height<=720]/best"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SECOND_RE = re.compile(r"_(\d+)s\.jpg$")


class FrameCaptureError(RuntimeError):
    """Capture failed in a way the caller must see; the message names the fix."""


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    raise FrameCaptureError(
        f"{name} is required for video screenshots but was not found "
        "(yt-dlp: `pip install -U yt-dlp`; ffmpeg: your package manager)."
    )


def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def slugify(text: str, *, max_length: int = 60) -> str:
    """A lowercase ASCII slug safe as a filename."""
    slug = _SLUG_RE.sub("-", str(text or "").lower()).strip("-")
    return slug[:max_length].strip("-") or "frame"


def parse_timecode(value: str) -> float:
    """``MM:SS``, ``HH:MM:SS`` or a bare second count, as seconds."""
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        numbers = [float(part) for part in text.split(":")]
    except ValueError:
        return 0.0
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def burst_offsets(count: int, spread: float) -> list[float]:
    """``count`` offsets in seconds, centred on zero and spanning +/- ``spread``."""
    if count <= 1:
        return [0.0]
    step = (2 * spread) / (count - 1)
    return [round(-spread + step * i, 2) for i in range(count)]


def detail_score(path: Path) -> int:
    """How much visual detail a JPEG holds, approximated by its encoded size."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def second_from_name(path: Path) -> float:
    """The absolute video second encoded in a candidate filename."""
    match = _SECOND_RE.search(path.name)
    return float(match.group(1)) if match else 0.0


def jpeg_size(path: Path) -> tuple[int, int]:
    """``(width, height)`` of a JPEG, read from its own header.

    Avoids depending on Pillow, and on ffprobe - which is not bundled with the
    pip-installable ffmpeg and so cannot be assumed present.
    """
    with path.open("rb") as fh:
        if fh.read(2) != b"\xff\xd8":
            raise FrameCaptureError(f"{path.name} is not a JPEG")
        while True:
            marker = fh.read(2)
            if len(marker) < 2 or marker[0] != 0xFF:
                raise FrameCaptureError(f"could not read the size of {path.name}")
            # SOF0..SOF15, minus the three markers in that range that are not
            # frame headers (DHT, JPG, DAC).
            if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                fh.read(3)
                height, width = struct.unpack(">HH", fh.read(4))
                return width, height
            (length,) = struct.unpack(">H", fh.read(2))
            fh.seek(length - 2, 1)


def download_section(url: str, start: float, end: float, workdir: Path, name: str,
                     *, timeout: int = 600) -> Path:
    """Download ``[start, end]`` of the video and return the local clip.

    ``--force-keyframes-at-cuts`` makes the clip begin exactly at ``start``;
    without it yt-dlp cuts at the previous keyframe and every later seek is off by
    an unknown amount.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    start = max(0.0, start)
    proc = _run([
        _tool("yt-dlp"), "--quiet", "--no-warnings",
        "--download-sections", f"*{start:.2f}-{end:.2f}",
        "--force-keyframes-at-cuts",
        "-f", _FORMAT,
        "-o", str(workdir / (name + ".%(ext)s")),
        url,
    ], timeout=timeout)
    hits = sorted(workdir.glob(name + ".*"))
    if not hits:
        raise FrameCaptureError(
            f"yt-dlp downloaded no video for {start:.0f}-{end:.0f}s: {proc.stderr.strip()[-300:]}"
        )
    return hits[0]


def grab_frame(clip: Path, offset: float, out_path: Path, *, timeout: int = 120) -> Path | None:
    """One JPEG at ``offset`` seconds into ``clip``, or None if there is no frame."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run([
        _tool("ffmpeg"), "-y", "-loglevel", "error",
        "-ss", f"{max(0.0, offset):.2f}", "-i", str(clip),
        "-frames:v", "1", "-q:v", "2", str(out_path),
    ], timeout=timeout)
    return out_path if out_path.is_file() and out_path.stat().st_size > 0 else None


def capture_moment(url: str, second: float, key: str, workdir: Path, *,
                   count: int = 5, spread: float = 6.0,
                   duration: float | None = None) -> list[Path]:
    """Candidate frames around one moment, most detailed first.

    Returns an empty list when the section cannot be fetched, so one bad moment
    never aborts a whole video.
    """
    section_start = max(0.0, second - spread - 2.0)
    section_end = second + spread + 2.0
    if duration:
        section_end = min(section_end, duration)
    if section_end <= section_start:
        return []

    # A re-run costs nothing: frames already captured for this moment are reused.
    existing = sorted((workdir / "candidates").glob(f"{key}_*.jpg"))
    if existing:
        return sorted(existing, key=detail_score, reverse=True)

    try:
        clip = download_section(url, section_start, section_end, workdir / "sections", key)
    except FrameCaptureError:
        return []

    frames: list[Path] = []
    for offset in burst_offsets(count, spread):
        absolute = second + offset
        if absolute < 0 or (duration and absolute > duration):
            continue
        got = grab_frame(clip, absolute - section_start,
                         workdir / "candidates" / f"{key}_{int(round(absolute))}s.jpg")
        if got:
            frames.append(got)
    return sorted(frames, key=detail_score, reverse=True)


def to_webp(src: Path, dest: Path, *, width: int = 1520, quality: int = 82) -> tuple[int, int]:
    """Convert a candidate JPEG to the WebP the figures pipeline stores.

    Returns the final ``(width, height)``, computed the same way ffmpeg's ``-2``
    computes it. The figure markup needs exact integers and ffprobe may not be
    installed, so the numbers are derived rather than probed back.
    """
    source_width, source_height = jpeg_size(src)
    target_width = min(width, source_width)
    target_height = max(2, int(round(source_height * target_width / source_width / 2)) * 2)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = _run([
        _tool("ffmpeg"), "-y", "-loglevel", "error", "-i", str(src),
        "-vf", f"scale={target_width}:-2", "-c:v", "libwebp", "-q:v", str(quality),
        str(dest),
    ], timeout=180)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise FrameCaptureError(
            f"ffmpeg produced no WebP for {src.name}: {proc.stderr.strip()[-300:]}"
        )
    return target_width, target_height


def build_manifest(selections: list[dict], candidates: dict[str, list[Path]],
                   out_dir: Path, slug: str, *, width: int = 1520) -> list[dict]:
    """Convert chosen frames to WebP and return a ``blog_add_figures`` manifest.

    Each entry carries ``after_heading_id`` / ``after_paragraphs`` so the retrofit
    knows where in the post it belongs. A selection missing them is still emitted
    rather than dropped, so the gap shows up in review instead of the screenshot
    vanishing silently.
    """
    figures_dir = out_dir / f"{slug}.figures"
    manifest: list[dict] = []
    for index, choice in enumerate(selections, start=1):
        key = str(choice.get("key") or "").strip()
        files = candidates.get(key) or []
        if not files:
            continue
        winner = next((p for p in files if p.name == choice.get("winner")), files[0])
        figure_id = f"vid-{index}"
        dest = figures_dir / f"{figure_id}-{slugify(key)}.webp"
        final_width, final_height = to_webp(winner, dest, width=width)
        manifest.append({
            "id": figure_id,
            "src": str(dest.resolve()),
            "width": final_width,
            "height": final_height,
            "alt": str(choice.get("alt") or choice.get("caption") or "").strip(),
            "caption": str(choice.get("caption") or "").strip(),
            "after_heading_id": str(choice.get("after_heading_id") or "").strip(),
            "after_paragraphs": int(choice.get("after_paragraphs") or 1),
            "source_second": second_from_name(winner),
        })
    return manifest


def _load_json(path: str) -> dict:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _cmd_plan(args) -> int:
    from keel_content.core import youtube_transcript as yt

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    data = yt.extract_segments(args.url, lang=args.lang)
    segments = data.pop("segments")
    (out / "thin.txt").write_text(yt.thin_index(segments), encoding="utf-8")
    (out / "video.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{out / 'thin.txt'}  ({len(segments)} caption lines, {data['words']} words)")
    return 0


def _cmd_capture(args) -> int:
    out = Path(args.out).expanduser().resolve()
    moments = _load_json(args.moments).get("moments", [])
    if not moments:
        print("no moments given", file=sys.stderr)
        return 1

    duration = None
    video_json = out / "video.json"
    if video_json.is_file():
        duration = parse_timecode(
            json.loads(video_json.read_text(encoding="utf-8")).get("duration") or ""
        ) or None

    listing: dict[str, list[str]] = {}
    for entry in moments:
        key = slugify(entry.get("key") or entry.get("label") or "moment", max_length=40)
        second = parse_timecode(entry.get("timecode", ""))
        frames = capture_moment(args.url, second, key, out,
                                count=args.burst, spread=args.spread, duration=duration)
        listing[key] = [str(p) for p in frames[:max(1, args.shortlist)]]
        print(f"  {key} @ {second:.0f}s: {len(frames)} frames", file=sys.stderr)
    (out / "candidates.json").write_text(json.dumps(listing, indent=2), encoding="utf-8")
    print(json.dumps(listing, indent=2))
    return 0


def _cmd_finalize(args) -> int:
    out = Path(args.out).expanduser().resolve()
    selections = _load_json(args.selection).get("selections", [])
    listing = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
    candidates = {key: [Path(p) for p in paths] for key, paths in listing.items()}
    manifest = build_manifest(selections, candidates, out, args.slug, width=args.width)
    target = out / "figures-manifest.json"
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{target}  ({len(manifest)} figure(s))")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m keel_content.core.youtube_frames",
        description="Capture the screenshots that carry a YouTube video's meaning.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Write the thin timestamped transcript index.")
    plan.add_argument("--url", required=True)
    plan.add_argument("--out", required=True)
    plan.add_argument("--lang", default="en")
    plan.set_defaults(func=_cmd_plan)

    capture = sub.add_parser("capture", help="Capture candidate frames for chosen moments.")
    capture.add_argument("--url", required=True)
    capture.add_argument("--out", required=True)
    capture.add_argument("--moments", required=True, help='JSON: {"moments":[{timecode,key,label}]}')
    capture.add_argument("--burst", type=int, default=5)
    capture.add_argument("--shortlist", type=int, default=3)
    capture.add_argument("--spread", type=float, default=6.0)
    capture.set_defaults(func=_cmd_capture)

    finalize = sub.add_parser("finalize", help="Convert winners to WebP + write the figures manifest.")
    finalize.add_argument("--out", required=True)
    finalize.add_argument("--slug", required=True)
    finalize.add_argument("--selection", required=True,
                          help='JSON: {"selections":[{key,winner,alt,caption,'
                               'after_heading_id,after_paragraphs}]}')
    finalize.add_argument("--width", type=int, default=1520)
    finalize.set_defaults(func=_cmd_finalize)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FrameCaptureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
