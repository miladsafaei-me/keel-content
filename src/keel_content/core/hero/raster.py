"""Rasterize a hero SVG to a WebP for og:image.

Social cards (Twitter/Telegram/LinkedIn/Slack) can't display an SVG, so every
hero needs a raster sibling for ``og:image`` / JSON-LD. We render with cairosvg
-- text uses the system Manrope faces installed in the image (the SVG's own
font-family is "Manrope") -- and transcode to WebP with Pillow.

Best-effort by design: any failure returns ``None`` and never blocks SVG hero
generation or publishing (the on-page hero is the SVG; only the social preview
depends on this).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

W, H = 1200, 630


def svg_to_webp(svg: str | bytes, dest: str | Path, *, width: int = W, height: int = H, quality: int = 86) -> Path | None:
    try:
        import cairosvg
        from PIL import Image
    except Exception as exc:  # noqa: BLE001 -- rasterizer optional; degrade quietly
        logger.warning("hero.raster: rasterizer unavailable (%s); skipping og webp", exc)
        return None
    data = svg.encode("utf-8") if isinstance(svg, str) else svg
    try:
        png = cairosvg.svg2png(bytestring=data, output_width=width, output_height=height)
        img = Image.open(io.BytesIO(png)).convert("RGB")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "WEBP", quality=quality, method=6)
        return dest
    except Exception as exc:  # noqa: BLE001
        logger.warning("hero.raster: svg->webp failed (%s)", exc)
        return None
