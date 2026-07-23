"""Rasterize ONE pipeline in-article figure: SVG -> PNG (judge preview) + WebP.

The container-native replacement for ``tools/content_pipeline/figure_rasterize.sh``
(which shelled out to flatpak Chromium + ImageMagick). Rendering uses the in-image
Playwright Chromium via :mod:`keel_content.core.html_raster` (full SVG
fidelity — the judge sees exactly the pixels that ship) and WebP transcode uses
Pillow, so it runs unchanged inside the web container where the render stages now
execute over SSH.

Writes ``<figure>.png`` and ``<figure>.webp`` next to the input SVG and prints a
one-line JSON result identical to the old script:
``{"png": ..., "webp": ..., "width": W, "height": H, "webp_bytes": N}``.

Usage::

    python manage.py figure_raster --svg <figure.svg> [--width 1520]
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from keel_content.core.html_raster import rasterize_html

# The style guide mandates viewBox-only SVGs (no width/height attrs), so the
# intrinsic aspect ratio comes from the viewBox.
_VIEWBOX_RE = re.compile(
    r'viewBox\s*=\s*["\']\s*[\d.+-]+[\s,]+[\d.+-]+[\s,]+([\d.]+)[\s,]+([\d.]+)'
)


class Command(BaseCommand):
    help = "Rasterize one in-article figure SVG to PNG + WebP (white background)."

    def add_arguments(self, parser):
        parser.add_argument("--svg", required=True, help="path to the figure .svg")
        parser.add_argument("--width", type=int, default=1520, help="target width (16:9-agnostic; height follows viewBox)")

    def handle(self, *args, **opts):
        svg_in = Path(opts["svg"]).resolve()
        if not svg_in.is_file():
            raise CommandError(f"no such file: {svg_in}")
        svg = svg_in.read_text(encoding="utf-8")
        m = _VIEWBOX_RE.search(svg)
        if not m:
            raise CommandError("figure SVG must carry a viewBox (and no width/height attributes)")
        vb_w, vb_h = float(m.group(1)), float(m.group(2))
        width = int(opts["width"])
        height = round(width * vb_h / vb_w)

        out_png = svg_in.with_suffix(".png")
        out_webp = svg_in.with_suffix(".webp")

        # Wrap the SVG in a minimal white shell so it paints at exactly the target
        # size on white — the figure editorial framework is white-background. The
        # SVG is inlined directly (single <svg> root, viewBox-scaled by the CSS).
        html = (
            "<!doctype html><html><head><meta charset='utf-8'><style>"
            "html,body{margin:0;padding:0;background:#ffffff}"
            "svg{display:block;width:%dpx;height:%dpx}"
            "</style></head><body>%s</body></html>" % (width, height, svg)
        )
        png = rasterize_html(html, width=width, height=height, settle_ms=1500)
        if not png:
            raise CommandError("Chromium produced no PNG for the figure")
        out_png.write_bytes(png)

        # Flatten onto white (kill any stray alpha) then transcode to WebP.
        from PIL import Image
        img = Image.open(out_png).convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        flat = Image.alpha_composite(bg, img).convert("RGB")
        flat.save(out_png, "PNG")
        flat.save(out_webp, "WEBP", quality=82, method=6)

        self.stdout.write(json.dumps({
            "png": str(out_png), "webp": str(out_webp),
            "width": width, "height": height, "webp_bytes": out_webp.stat().st_size,
        }))
