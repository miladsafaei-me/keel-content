"""Render ONE in-article ``image-nb2`` photoreal image for a generation bundle.

The ``image-nb2`` engine is the captured/rendered counterpart to the drawn
``figures`` engine (see ``VISUALIZATION.md`` §1): a Gemini "nano banana" photoreal
scene with a crisp SVG text overlay composited on top, delivered as a WebP. Unlike
the blog *cover* (``hero-svg``), an in-article image is built per-paragraph — its
``scene_brief`` and in-image ``overlay_text`` come from the author's
``image_requests`` entry, not from the article title.

This command is the mechanical half of the images stage (``author-images.md``):
it reads one ``image_requests`` entry from the bundle, generates the scene, adds
the SVG overlay, rasterizes to WebP, writes the files next to the bundle, and
patches a matching ``images`` entry back in. The stage agent orchestrates it per
request and vision-checks the output; the whole-post NB2 budget is enforced in
``core.images.image_violations`` at import.

Runs at GENERATION time (needs the image API key). Rasterization uses the
in-image Playwright Chromium via :mod:`keel_content.core.html_raster` and
WebP transcode uses Pillow — no flatpak, no ImageMagick — so this runs unchanged
inside the web container (where the render stages now execute over SSH). All I/O
and the network call live inside ``handle`` so importing this module stays cheap.

Usage::

    python manage.py nb2_image --bundle <path>/<content_id>.bundle.json --id img-1
    # optional: --out-dir <dir> (default <bundle_dir>/<content_id>.images/)
    #           --width 1520      (rasterized WebP width; height follows 16:9)
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content.core.html_raster import rasterize_html
from keel_content.config import brand as _brand
from keel_content.core.hero.chrome import (
    _MARK_H,
    _MARK_POLYS,
    _MARK_W,
    _MARK_XMIN,
    _MARK_YMIN,
)

# Brand identity held constant across every NB2 image — resolved from
# KEEL_CONTENT["brand"]; neutral defaults carry no host identity.
NAVY = _brand("navy_0")
GREEN = _brand("accent")

# Montserrat OTFs are vendored in the repo (shipped inside the image) so the
# overlay embeds them regardless of host; fall back to the Fedora system package
# path for a dev box that still has it installed.
_FONT_DIR = Path(__file__).resolve().parents[2] / "fonts" / "montserrat"
_LEGACY_FONT_DIR = Path("/usr/share/fonts/julietaula-montserrat-fonts")
FONT_NAMES = {
    800: "Montserrat-ExtraBold.otf",
    700: "Montserrat-Bold.otf",
    600: "Montserrat-SemiBold.otf",
}


def _font_path(name: str) -> Path:
    for base in (_FONT_DIR, _LEGACY_FONT_DIR):
        p = base / name
        if p.is_file():
            return p
    raise CommandError(f"Montserrat font not found: {name}")
SCENE_W, SCENE_H = 2752, 1536  # NB2 native 16:9 (2K); overlay viewBox matches

# Reference-free style spec — carries the whole visual identity in words so no
# style-reference image is needed (mirrors the tuned cover engine's NOREF path).
PREAMBLE = (
    "You are an expert art director creating a premium, high-end editorial "
    "illustration in a consistent house style. RENDER STYLE (match precisely): a "
    "photorealistic, ultra-detailed 3D render on ONE bright airy near-white seamless "
    "studio background; the subjects are built from glossy, translucent, frosted GLASS "
    "(glass-morphism) with realistic refraction, soft edges and delicate green "
    "rim-light; soft even studio lighting; tasteful shallow depth-of-field with subtle "
    "round bokeh light-orbs for depth; gentle mirror-like reflections on a clean glossy "
    "white floor. Elegant, calm, expensive, uncluttered — every element carries clear "
    "meaning in one cohesive scene.\n\n"
)
PALETTE = (
    "\nPALETTE & BRAND (follow exactly):\n"
    "- Background: bright near-white, ONE seamless continuous surface that runs flat "
    "and uninterrupted edge-to-edge — no vertical seam, band, panel edge or tonal split "
    "anywhere, including at the extreme LEFT and RIGHT edges of the frame.\n"
    "- Signature accent glow color: BRAND GREEN #41ffa0 (glows, connectors, arrows, rim "
    "light, highlights).\n"
    "- Depth, screens and small in-scene text labels: BRAND NAVY #070d1e.\n"
    "- If (and only if) a candlestick chart genuinely belongs, render candles glassy — "
    "UP #099981 / DOWN #f23645 — with both up and down candles.\n"
    "- Include SUBTLE, tasteful atmospheric bokeh light-orbs and soft glows for depth.\n"
    "- Glass materials, soft studio lighting, gentle reflections on a clean glossy floor.\n"
)
HARD = (
    "\nDo NOT render any large heading or title text anywhere. Keep in-scene text to ONLY "
    "the few tiny labels explicitly named in quotes in the brief — nothing more. Do NOT "
    "add callout or annotation labels with leader lines, and do NOT name objects in the "
    "image. No logo, no watermark, no real brand/government/regulator logos, no real human "
    "faces. Photorealistic, ultra-detailed, premium 3D render. 16:9 landscape."
)


def _reserve(subject_side: str) -> str:
    empty = "RIGHT" if subject_side == "LEFT" else "LEFT"
    return (
        "\nLAYOUT: compose ALL subjects, elements and labels toward the %s side, leaving "
        "roughly the %s 40%% of the frame as calm OPEN EMPTY negative space for a text "
        "overlay. CRITICAL: the whole background must be ONE single seamless continuous "
        "surface — NO visible vertical dividing line, seam, panel edge, border, band or "
        "abrupt tonal split anywhere; the empty negative space blends smoothly into the "
        "rest of the scene as one uninterrupted backdrop.\n" % (subject_side, empty)
    )


def _build_scene_prompt(scene_brief: str, text_side: str) -> str:
    subject_side = "RIGHT" if text_side == "left" else "LEFT"
    return PREAMBLE + scene_brief.strip() + _reserve(subject_side) + PALETTE + HARD


def _font_css() -> str:
    out = []
    for weight, name in FONT_NAMES.items():
        b64 = base64.b64encode(_font_path(name).read_bytes()).decode("ascii")
        out.append(
            "@font-face{font-family:'Montserrat';font-weight:%d;font-style:normal;"
            "src:url(data:font/otf;base64,%s) format('opentype');}" % (weight, b64)
        )
    return "\n".join(out)


def _scene_data_uri(raw: bytes) -> str:
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif raw[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    else:
        mime = "image/png"
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


def _logo_lockup_svg() -> str:
    """Fixed brand lockup in the TOP-LEFT corner: the mark in the brand accent + the
    wordmark in brand navy, with the shared soft white glow so both stay legible even
    if they graze the subject or a bokeh orb. The position is CONSTANT across every
    image and never collides with the vertically-centered overlay text. Both the mark
    and wordmark come from ``KEEL_CONTENT["brand"]``; with neither set, no lockup is
    drawn."""
    import html as _html

    wordmark = _brand("wordmark") or ""
    if not _MARK_POLYS and not wordmark:
        return ""
    x0, y0 = 110.0, 96.0
    mark_h = 64.0
    s = mark_h / _MARK_H
    mark_w = _MARK_W * s
    tx = x0 - _MARK_XMIN * s
    ty = y0 - _MARK_YMIN * s
    text_x = x0 + mark_w + 26
    # Wordmark baseline vertically centered against the mark (y0..y0+mark_h).
    word_y = y0 + mark_h * 0.72
    mark_svg = (
        "<g transform='translate(%.2f,%.2f) scale(%.4f)' fill='%s'>%s</g>"
        % (tx, ty, s, GREEN, _MARK_POLYS)
        if _MARK_POLYS
        else ""
    )
    text_svg = (
        "<text x='%d' y='%.0f' font-family='Montserrat' font-weight='800' font-size='58' "
        "fill='%s'>%s</text>" % (text_x, word_y, NAVY, _html.escape(wordmark))
        if wordmark
        else ""
    )
    return "<g filter='url(#tsh)'>%s%s</g>" % (mark_svg, text_svg)


def _overlay_svg(scene_raw: bytes, title_lines: list, text_side: str) -> str:
    """Compose the brand overlay: the fixed top-left logo/domain lockup plus the
    navy body text (with a green-on-navy accent chip) in the reserved negative
    space."""
    n = len([ln for ln in title_lines if str(ln[0]).strip()])
    fs, lh = (76, 112) if n <= 3 else (64, 94)
    total = max(1, n) * lh
    y0 = int((SCENE_H - total) / 2) + fs  # vertically centered block
    if text_side == "left":
        tx, anchor = 110, "start"
    else:
        tx, anchor = SCENE_W - 110, "end"

    p = [
        "<svg xmlns='http://www.w3.org/2000/svg' width='%d' height='%d' viewBox='0 0 %d %d'>"
        % (SCENE_W, SCENE_H, SCENE_W, SCENE_H),
        "<defs><style type='text/css'>%s</style>" % _font_css(),
        "<linearGradient id='chip' x1='0' y1='0' x2='1' y2='1'>"
        "<stop offset='0' stop-color='#101d3a'/><stop offset='1' stop-color='#05091a'/></linearGradient>"
        "<filter id='tsh' x='-25%' y='-25%' width='150%' height='150%'>"
        "<feDropShadow dx='0' dy='0' stdDeviation='16' flood-color='#ffffff' flood-opacity='0.92'/></filter>"
        "</defs>",
        "<image href='%s' x='0' y='0' width='%d' height='%d' preserveAspectRatio='xMidYMid slice'/>"
        % (_scene_data_uri(scene_raw), SCENE_W, SCENE_H),
    ]
    y = y0
    for text, is_accent in title_lines:
        text = str(text).strip()
        if not text:
            continue
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if is_accent:
            p.append("<rect rx='16' fill='%s'/>" % NAVY)  # chip, JS-sized to the text bbox
            p.append(
                "<text class='acc' x='%d' y='%d' text-anchor='%s' font-family='Montserrat' "
                "font-weight='800' font-size='%d' fill='%s'>%s</text>"
                % (tx, y, anchor, fs, GREEN, esc)
            )
        else:
            p.append(
                "<text x='%d' y='%d' text-anchor='%s' font-family='Montserrat' font-weight='800' "
                "font-size='%d' fill='%s' filter='url(#tsh)'>%s</text>"
                % (tx, y, anchor, fs, NAVY, esc)
            )
        y += lh
    p.append(_logo_lockup_svg())
    p.append("</svg>")
    return "".join(p)


_CHIP_JS = (
    "<script>document.fonts.ready.then(function(){var px=30,py=12;"
    "document.querySelectorAll('.acc').forEach(function(t){var b=t.getBBox();"
    "var r=t.previousElementSibling;r.setAttribute('x',b.x-px);r.setAttribute('y',b.y-py);"
    "r.setAttribute('width',b.width+2*px);r.setAttribute('height',b.height+2*py);});});</script>"
)


def _rasterize(svg: str, out_png: Path, width: int, height: int) -> None:
    """Render the overlay HTML (inline SVG + chip-sizing script) with the in-image
    Playwright Chromium (no flatpak, no host browser)."""
    # Scale the intrinsic 2752x1536 overlay SVG down to the target viewport so the
    # whole frame (incl. right-anchored text) is captured, not just the top-left.
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;overflow:hidden;}"
        "svg{display:block;width:%dpx;height:%dpx;}</style>"
        "</head><body>%s%s</body></html>" % (width, height, svg, _CHIP_JS)
    )
    png = rasterize_html(html, width=width, height=height, settle_ms=2000)
    if not png:
        raise CommandError("Chromium produced no screenshot for the overlay")
    out_png.write_bytes(png)


def _gemini_scene(scene_prompt: str) -> bytes:
    """Generate the raw photoreal scene via the host's shared inline image core
    (the Gemini image-gen HTTP core the host provides — keel-web ships one)."""
    from keel_content import host

    _gemini_image_request = host.gemini_image_request
    _extract_first_image_bytes = host.extract_first_image_bytes

    api_key = host.resolved_image_ai_api_key()
    if not api_key:
        raise CommandError(
            "No image API key. Set the inline image key in Admin OS → AI Settings or GEMINI_API_KEY."
        )
    url = host.gemini_image_generate_content_url_for_inline()
    base_cfg = {"responseModalities": ["TEXT", "IMAGE"]}
    # Prefer 2K for a crisp downscale; fall back to the model default if it 4xx's.
    for image_cfg in ({"aspectRatio": "16:9", "imageSize": "2K"}, {"aspectRatio": "16:9"}):
        payload = {
            "contents": [{"role": "user", "parts": [{"text": scene_prompt}]}],
            "generationConfig": {**base_cfg, "imageConfig": image_cfg},
        }
        try:
            data = _gemini_image_request(url, api_key, payload)
        except Exception as exc:  # noqa: BLE001 — try the simpler config before giving up
            last = exc
            continue
        raw = _extract_first_image_bytes(data)
        if raw:
            return raw
        last = RuntimeError("model returned no image")
    raise CommandError("NB2 scene generation failed: %r" % last)


class Command(BaseCommand):
    help = "Render one in-article image-nb2 photoreal image for a generation bundle."

    def add_arguments(self, parser):
        parser.add_argument("--bundle", required=True, help="path to <content_id>.bundle.json")
        parser.add_argument("--id", required=True, help="the image_requests id to render (e.g. img-1)")
        parser.add_argument("--out-dir", default=None, help="output dir (default <bundle_dir>/<content_id>.images/)")
        parser.add_argument("--width", type=int, default=1520, help="rasterized WebP width (16:9 height follows)")

    def handle(self, *args, **opts):
        bundle_path = Path(opts["bundle"]).resolve()
        if not bundle_path.is_file():
            raise CommandError(f"no such bundle: {bundle_path}")
        content_id = bundle_path.name[:-len(".bundle.json")] if bundle_path.name.endswith(".bundle.json") else bundle_path.stem
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

        req = next(
            (r for r in (bundle.get("image_requests") or [])
             if isinstance(r, dict) and str(r.get("id") or "").strip() == opts["id"]),
            None,
        )
        if req is None:
            raise CommandError(f"no image_requests entry with id {opts['id']!r} in the bundle")
        scene_brief = str(req.get("scene_brief") or "").strip()
        if not scene_brief:
            raise CommandError(f"image_requests[{opts['id']}] has no scene_brief")
        ov = req.get("overlay_text") or {}
        title_lines = ov.get("title_lines") or []
        side = str(ov.get("side") or "auto").strip().lower()
        text_side = "left" if side == "left" else ("right" if side == "right" else "right")

        out_dir = Path(opts["out_dir"]).resolve() if opts["out_dir"] else bundle_path.parent / f"{content_id}.images"
        out_dir.mkdir(parents=True, exist_ok=True)
        iid = opts["id"]
        scene_png = out_dir / f"{iid}.scene.png"
        svg_path = out_dir / f"{iid}.svg"
        png_path = out_dir / f"{iid}.png"
        webp_path = out_dir / f"{iid}.webp"

        width = int(opts["width"])
        height = round(width * SCENE_H / SCENE_W)

        # 1) photoreal scene -> 2) SVG brand/text overlay -> 3) rasterize -> 4) WebP
        scene_raw = _gemini_scene(_build_scene_prompt(scene_brief, text_side))
        scene_png.write_bytes(scene_raw)
        svg = _overlay_svg(scene_raw, title_lines, text_side)
        svg_path.write_text(svg, encoding="utf-8")
        _rasterize(svg, png_path, width, height)
        from PIL import Image
        Image.open(png_path).convert("RGB").save(
            webp_path, "WEBP", quality=82, method=6
        )
        webp_bytes = webp_path.stat().st_size

        # Patch the bundle's images array (append/replace by id) so the stage agent
        # only orchestrates + vision-checks; the file paths are bundle-relative.
        entry = {
            "id": iid,
            "file": f"{content_id}.images/{iid}.webp",
            "scene": f"{content_id}.images/{iid}.scene.png",
            "svg": f"{content_id}.images/{iid}.svg",
            "width": width,
            "height": height,
            "alt": str(req.get("alt") or "").strip(),
            "caption": str(req.get("caption") or "").strip(),
            "comprehension_job": str(req.get("comprehension_job") or "").strip(),
            "section": str(req.get("section") or "").strip(),
        }
        images = [im for im in (bundle.get("images") or []) if not (isinstance(im, dict) and im.get("id") == iid)]
        images.append(entry)
        bundle["images"] = images
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        self.stdout.write(json.dumps({
            "id": iid, "webp": str(webp_path), "scene": str(scene_png), "svg": str(svg_path),
            "width": width, "height": height, "webp_bytes": webp_bytes, "ok": True,
        }))
