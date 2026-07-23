"""Compose a hero from a spec: chrome + chosen style + motif, then embed the font.

``build_hero_svg`` returns the raw SVG (renders with the system Manrope, e.g.
cairosvg for the og raster). ``build_hero`` returns the shippable on-page SVG
with the font embedded so it renders correctly when loaded via ``<img>``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .chrome import base_background, baseline_accent, category_chip, dot_grid, headline, logo_lockup, svg_wrap
from .elements import build_motif
from .fonts import embed_fonts
from .styles import STYLES

# Freeform visual-element zone (the right side; the headline owns the left). An
# agent-authored element is clipped to this so it can never collide with the
# headline / chip / logo. The clip is a generous collision guard, NOT the target
# zone: for visual balance authors keep art inside the safe content zone
# x in [700, 1120], y in [150, 560] (~brand margin on the right), centred near
# (910, 360) -- see content-pipeline/prompts/agent-author-brief.md. The clip stays
# wide so the few heroes whose axis/baseline reaches ~1140 are not cut off.
_ELEMENT_CLIP = '<clipPath id="heroclip"><rect x="656" y="104" width="544" height="500"/></clipPath>'
_FREEFORM_HEAD = {"y0": 322, "lh": 74, "size": 62}

# Drop tags that are unsafe, non-CWV (filters/blur), or won't survive WebP raster.
_BLOCK_RE = re.compile(r"<(script|foreignObject|filter|iframe|image|use)\b.*?</\1>", re.I | re.S)
_BLOCK_SELF_RE = re.compile(r"<(script|foreignObject|filter|iframe|image|use|animate\w*|set)\b[^>]*/?>", re.I)
_ON_ATTR_RE = re.compile(r"\son\w+\s*=\s*\"[^\"]*\"", re.I)
_EXT_HREF_RE = re.compile(r"\s(?:xlink:)?href\s*=\s*\"(?!#)[^\"]*\"", re.I)


def sanitize_svg_element(markup: str) -> str:
    """Strip script/filter/external-ref/handler constructs from an agent-authored SVG element.

    The element is trusted-ish (our pipeline) but is raw model output, so we enforce
    the brand/CWV guardrails deterministically: no <script>/<filter>/<image>/<use>,
    no inline event handlers, no remote hrefs. Gradients/shapes/paths/text stay.
    """
    s = markup or ""
    s = _BLOCK_RE.sub("", s)
    s = _BLOCK_SELF_RE.sub("", s)
    s = _ON_ATTR_RE.sub("", s)
    s = _EXT_HREF_RE.sub("", s)
    return s


@dataclass
class HeroSpec:
    style: str                                  # key in STYLES (fallback painter when no svg_element)
    category: str                               # chip label, e.g. "Copy Trading"
    headline_lines: list                        # [[(text, color|None), ...], ...] -- two lines, accent run in GREEN
    motif: str = "hub_spokes"                   # kind in MOTIFS (fallback painter)
    motif_params: dict = field(default_factory=dict)
    title: str | None = None                    # <title> for a11y/SEO; defaults to headline text
    head_size: int | None = None                # optional cap on headline font-size (long titles)
    svg_element: str | None = None              # agent-designed visual element (freeform path)


def _plain(headline_lines) -> str:
    return " ".join("".join(t for t, _ in line) for line in headline_lines).strip()


def _chrome(spec: HeroSpec, head: dict, *, defs: str = "", background: str = "") -> str:
    return (
        (f"<defs>{defs}</defs>" if defs else "")
        + (background or base_background())
        + dot_grid()
        + category_chip(spec.category)
        + logo_lockup()
        + headline(spec.headline_lines, **head)
        + baseline_accent()
    )


def build_hero_svg(spec: HeroSpec) -> str:
    # Freeform path: the brand chrome is fixed; the agent designs the visual element.
    if spec.svg_element:
        head = dict(_FREEFORM_HEAD)
        if spec.head_size:
            head["size"] = min(head["size"], spec.head_size)
        body = (
            _chrome(spec, head, defs=_ELEMENT_CLIP)
            + f'<g clip-path="url(#heroclip)">{sanitize_svg_element(spec.svg_element)}</g>'
        )
        return svg_wrap(body, title=spec.title or _plain(spec.headline_lines))

    # Fallback path: deterministic preset style + motif (kept for specs with no element).
    style = STYLES.get(spec.style) or STYLES["minimal"]
    motif = build_motif(spec.motif, **spec.motif_params)
    extra_defs = style.defs()
    head = dict(style.head)
    if spec.head_size:
        head["size"] = min(head["size"], spec.head_size)
    body = (
        (f"<defs>{extra_defs}</defs>" if extra_defs else "")
        + style.background()
        + dot_grid()
        + category_chip(spec.category)
        + logo_lockup()
        + style.behind_headline()
        + headline(spec.headline_lines, **head)
        + baseline_accent(style.baseline_y)
        + style.paint(motif)
    )
    return svg_wrap(body, title=spec.title or _plain(spec.headline_lines))


def build_hero(spec: HeroSpec, *, woff2_path: str | Path | None = None) -> str:
    """The shippable, self-contained on-page SVG (font embedded)."""
    return embed_fonts(build_hero_svg(spec), woff2_path)
