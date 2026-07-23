"""Modular blog hero / featured-image generator.

Code-authored SVG heroes in one brand identity, per VISUALIZATION.md (blog
heroes are the *drawn* class -> SVG, never AI raster). Built as swappable
**style** components (the visual language) over concept **motifs** (what the
picture shows): any style can render any post's concept, so each blog picks the
style that best conveys its idea.

- ``STYLES``  -- the five style painters (minimal / isometric / infographic /
  glow / network). Pick one per post.
- ``MOTIFS``  -- concept motifs (hub_spokes / pipeline / ranked / paired /
  device_signal / nodes). Derived from the post's concept.
- ``build_hero(spec)`` -- compose a style + motif + headline into a final,
  font-embedded SVG string ready to ship as ``<img>`` and rasterize for og.

Pure python (no Django) so it renders + tests standalone; the pipeline glue
(media write, DB, LLM brief) lives in ``keel_content.core.hero.pipeline``.
"""

from __future__ import annotations

from .build import HeroSpec, build_hero, build_hero_svg
from .elements import MOTIFS
from .styles import STYLES

__all__ = ["HeroSpec", "build_hero", "build_hero_svg", "STYLES", "MOTIFS"]
