"""Shared brand chrome + geometry helpers for hero SVGs.

The chrome (logo lockup, category chip, dot-grid texture, headline, accent
baseline) is identical across every style -- it is what makes all heroes one
family. Styles layer their own background + motif treatment on top.
"""

from __future__ import annotations

import html

from keel_content.config import brand as _brand
from .tokens import GREEN, NAVY_0, NAVY_1, TEXT_MAIN, TEXT_SECONDARY, W, H, MARGIN

# Brand logo mark (SVG polygon/path body) + its bounding box, both host-supplied via
# KEEL_CONTENT["brand"]. Default is empty: no mark is drawn, and the lockup falls back
# to the wordmark alone. logo_mark_viewbox is (xmin, ymin, width, height) in the mark's
# own coordinate space, used to scale + position it in the lockup.
_MARK_POLYS = _brand("logo_mark_svg") or ""
_MARK_VIEWBOX = _brand("logo_mark_viewbox") or (0.0, 0.0, 100.0, 100.0)
_MARK_XMIN, _MARK_YMIN, _MARK_W, _MARK_H = _MARK_VIEWBOX


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def svg_open() -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">'


def svg_wrap(body: str, title: str | None = None) -> str:
    t = f"<title>{esc(title)}</title>" if title else ""
    return f"{svg_open()}{t}{body}</svg>"


def bg_gradient_def(gid: str = "bg") -> str:
    return (
        f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{NAVY_0}"/><stop offset="1" stop-color="{NAVY_1}"/></linearGradient>'
    )


def base_background(glow_cx: float = 0.72, glow_cy: float = 0.42) -> str:
    """Navy gradient + a soft green glow -- the default flat background."""
    return (
        f'<defs>{bg_gradient_def("bg")}'
        f'<radialGradient id="glow" cx="{glow_cx}" cy="{glow_cy}" r="0.55">'
        f'<stop offset="0" stop-color="{GREEN}" stop-opacity="0.16"/>'
        f'<stop offset="1" stop-color="{GREEN}" stop-opacity="0"/></radialGradient></defs>'
        f'<rect width="{W}" height="{H}" fill="url(#bg)"/>'
        f'<rect width="{W}" height="{H}" fill="url(#glow)"/>'
    )


def logo_lockup() -> str:
    """Accent mark + wordmark, top-right, right-anchored.

    Both come from ``KEEL_CONTENT["brand"]``. With no wordmark and no mark set the
    lockup renders nothing; with a wordmark only, it renders the text alone.
    """
    wordmark = _brand("wordmark") or ""
    text_right = W - MARGIN
    text_size = 26
    text = (
        f'<text x="{text_right}" y="78" font-family="Manrope" font-weight="800" '
        f'font-size="{text_size}" fill="{TEXT_MAIN}" text-anchor="end">{esc(wordmark)}</text>'
        if wordmark
        else ""
    )
    if not _MARK_POLYS:
        return text
    mark_h = 30.0
    s = mark_h / _MARK_H
    text_w_est = text_size * 0.56 * len(wordmark)
    mark_right = text_right - text_w_est - 14
    mark_left = mark_right - _MARK_W * s
    tx = mark_left - _MARK_XMIN * s
    ty = 53 - _MARK_YMIN * s
    mark = f'<g transform="translate({tx:.2f},{ty:.2f}) scale({s:.4f})" fill="{GREEN}">{_MARK_POLYS}</g>'
    return mark + text


def category_chip(label: str) -> str:
    return (
        f'<circle cx="{MARGIN}" cy="69" r="6" fill="{GREEN}"/>'
        f'<text x="{MARGIN + 16}" y="75" font-family="Manrope" font-weight="600" font-size="22" '
        f'letter-spacing="3" fill="{TEXT_SECONDARY}">{esc(label.upper())}</text>'
    )


def dot_grid() -> str:
    dots = "".join(
        f'<circle cx="{MARGIN + col * 60}" cy="{132 + row * 60}" r="2"/>'
        for col in range(3) for row in range(4)
    )
    return f'<g fill="#ffffff" fill-opacity="0.05">{dots}</g>'


def baseline_accent(y: int = 556) -> str:
    return f'<rect x="{MARGIN}" y="{y}" width="120" height="4" rx="2" fill="{GREEN}"/>'


def headline(lines, *, y0: int = 322, lh: int = 74, size: int = 62) -> str:
    """Each line is a list of (text, color|None) runs; None -> white."""
    out = []
    for i, runs in enumerate(lines):
        spans = "".join(f'<tspan fill="{c or TEXT_MAIN}">{esc(t)}</tspan>' for t, c in runs)
        out.append(
            f'<text x="{MARGIN}" y="{y0 + i * lh}" font-family="Manrope" font-weight="800" '
            f'font-size="{size}" fill="{TEXT_MAIN}">{spans}</text>'
        )
    return "".join(out)


def cubic(x1: float, y1: float, x2: float, y2: float, bow: float = 0.0) -> str:
    """A cubic path from (x1,y1) to (x2,y2); ``bow`` lifts the control points."""
    mx = (x1 + x2) / 2
    return f'M{x1:.0f} {y1:.0f} C {mx:.0f} {y1 - bow:.0f}, {mx:.0f} {y2 - bow:.0f}, {x2:.0f} {y2:.0f}'
