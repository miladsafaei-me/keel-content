"""Make a hero SVG self-contained for ``<img>`` use by embedding Manrope.

An SVG loaded via ``<img>`` is isolated -- it can't see the page web font, so
``<text font-family="Manrope">`` would fall back to a system sans. We inline the
repository's *variable* Manrope woff2 as a single weight-range ``@font-face``
data-URI; the browser then resolves each ``font-weight`` (600 / 800) from the one
embedded file. Verified to render correct weights in real `<img>` context.

Embedding a font (not a raster) keeps the SVG vector/crisp, and using the
committed variable woff2 directly means no runtime font tooling (no subsetting,
no system-font install).
"""

from __future__ import annotations

import base64
import functools
import re
from pathlib import Path

# fonts.py lives at keel_content/core/hero/ -> parents[2] == the keel_content package root,
# which ships fonts/manrope/manrope-latin.woff2 (alongside fonts/montserrat/). Resolve from the
# PACKAGE, not a host repo layout: the old parents[3]/"core/static/..." assumed the in-repo
# backend/content_pipeline/ path and broke after the keel migration (it pointed at a nonexistent
# site-packages/core/static/...). Callers may still pass an explicit woff2_path to override.
DEFAULT_WOFF2 = Path(__file__).resolve().parents[2] / "fonts/manrope/manrope-latin.woff2"

_SVG_OPEN = re.compile(r"(<svg\b[^>]*>)")


@functools.lru_cache(maxsize=4)
def _font_b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def font_face_style(woff2_path: str | Path | None = None) -> str:
    b64 = _font_b64(str(woff2_path or DEFAULT_WOFF2))
    return (
        "<style>@font-face{font-family:'Manrope';font-style:normal;font-weight:200 800;"
        f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}</style>"
    )


def embed_fonts(svg: str, woff2_path: str | Path | None = None) -> str:
    """Inject the Manrope ``@font-face`` as a ``<defs>`` right after the ``<svg>`` tag."""
    style = f"<defs>{font_face_style(woff2_path)}</defs>"
    return _SVG_OPEN.sub(lambda m: m.group(1) + style, svg, count=1)
