"""Django glue: turn a blog Post into a hero asset and attach it.

The pure-SVG library (``build_hero``) stays Django-free; this module is the
boundary that touches settings/MEDIA_ROOT and the Post model. It is the
"independent task at the end of the content pipeline": derive a per-post style +
motif + headline, render the SVG, write it to MEDIA_ROOT under a content-hashed
name (so a regenerated hero never collides with a CDN-cached old one), and set
``Post.featured_image_url``.

Style/motif/headline are chosen by ``derive_spec`` from the post's concept. v1 is
deterministic (motif from the topic, style by affinity + a stable per-slug
rotation, headline from the title); the ``LLM brief`` seam below is where an
intelligent hook-writer slots in later.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .build import HeroSpec, build_hero
from .tokens import GREEN

# Concept -> motif. First matching keyword group wins; order matters.
_MOTIF_RULES = [
    ("paired", ("mt4", "mt5", "metatrader", "connector", " vs ", "versus")),
    ("device_signal", ("app", "mobile", "phone", "ios", "android")),
    ("ranked", ("best ", "top ", "compare", "comparison", "ranked", "alternatives")),
    ("hub_spokes", ("copy trading", "copy-trading", "mirror", "social trading", "telegram", "broadcast")),
    ("pipeline", ("algorithm", "automat", "bot", "how ", "what is", "guide", "explained")),
]

# Motif -> styles that suit it, best first. A stable per-slug index rotates
# within the list so sibling posts don't all look identical.
_STYLE_AFFINITY = {
    "hub_spokes": ["network", "glow", "minimal"],
    "pipeline": ["glow", "minimal", "isometric"],
    "ranked": ["infographic", "minimal"],
    "paired": ["isometric", "infographic"],
    "device_signal": ["minimal", "glow"],
    "nodes": ["network", "minimal"],
}

_SHORT_CATEGORY = {"trading bots & automation": "Trading Bots"}


def _slug_index(slug: str, n: int) -> int:
    return int(hashlib.sha1(slug.encode()).hexdigest(), 16) % max(1, n)


def _pick_motif(text: str) -> str:
    t = text.lower()
    for motif, keys in _MOTIF_RULES:
        if any(k in t for k in keys):
            return motif
    return "hub_spokes"


def _pick_style(motif: str, slug: str, override: str | None) -> str:
    if override:
        return override
    choices = _STYLE_AFFINITY.get(motif, ["minimal"])
    return choices[_slug_index(slug, len(choices))]


_TITLE_CHAR_CAP = 64  # hard cap so even a pathological title can be sized to fit
_ZONE_BUDGET = 650    # ~ text-zone width in px the headline must fit within


def _headline_from_title(title: str):
    """Split a (length-capped) title into two balanced lines; accent line two green.

    Deterministic fallback only -- a real curiosity hook is the LLM brief's job.
    """
    clean = re.sub(r"[?:]+\s*$", "", title).strip()
    clean = re.sub(r"^(what is|what are|how to|how do|the)\s+", "", clean, flags=re.I).strip() or title
    words = clean.split()
    # cap total length (whole words) so the headline can always be sized to fit
    capped, used = [], 0
    for w in words:
        if used + len(w) + 1 > _TITLE_CHAR_CAP and capped:
            break
        capped.append(w)
        used += len(w) + 1
    words = capped
    if len(words) <= 1:
        return [[(words[0] if words else clean, GREEN)]]
    total = sum(len(w) for w in words) + len(words) - 1
    acc, cut = 0, len(words) - 1
    for i, w in enumerate(words):
        acc += len(w) + 1
        if acc >= total / 2:
            cut = i + 1
            break
    return [[(" ".join(words[:cut]), None)], [(" ".join(words[cut:]), GREEN)]]


def _headline_size(lines) -> int:
    """Largest font-size (<=62) that keeps the longest line within the text zone."""
    longest = max((sum(len(t) for t, _ in line) for line in lines), default=10)
    fit = int(_ZONE_BUDGET / (longest * 0.62)) if longest else 62
    return max(26, min(62, fit))


def short_category(name: str) -> str:
    return _SHORT_CATEGORY.get((name or "").strip().lower(), name or "Insights")


def derive_spec(*, title: str, category: str, slug: str, excerpt: str = "",
                style: str | None = None, motif: str | None = None,
                headline=None) -> HeroSpec:
    """Choose style + motif + headline for a post's hero (deterministic v1)."""
    kind = motif or _pick_motif(f"{title} {category} {excerpt}")
    chosen_style = _pick_style(kind, slug, style)
    lines = headline or _headline_from_title(title)
    params = {}
    if kind == "paired" and "mt" in title.lower():
        params = {"labels": ("MT4", "MT5"), "sublabel": "ONE ENGINE"}
    return HeroSpec(
        chosen_style, short_category(category), lines, kind,
        motif_params=params, title=title, head_size=_headline_size(lines),
    )


_SVG_NS = "http://www.w3.org/2000/svg"


def _repair_svg_fragment(frag: str | None) -> str | None:
    """Return ``frag`` re-serialized as well-formed XML, or the original if it is
    already valid / unrepairable.

    The agent-designed ``svg_element`` is occasionally malformed (a stray ``</g>``,
    a tag closed out of order). Wrapped into the frame it then produces an invalid
    hero SVG that renders blank AND fails ``svg->webp`` rasterization — so the post
    ships with a broken featured image. libxml2's recovery parser fixes the common
    cases (drops the stray close, reorders) without touching valid markup; we only
    swap in the repaired string when it actually parses clean, so a valid fragment
    is never altered and an unrepairable one falls through untouched (best-effort).
    """
    if not frag or not frag.strip():
        return frag
    wrapped = f'<svg xmlns="{_SVG_NS}">{frag}</svg>'
    try:
        from lxml import etree
    except Exception:  # noqa: BLE001 — lxml missing: leave the fragment as-is
        return frag
    # If it already parses strictly, don't touch it.
    try:
        etree.fromstring(wrapped.encode("utf-8"))
        return frag
    except Exception:  # noqa: BLE001
        pass
    try:
        root = etree.fromstring(wrapped.encode("utf-8"), etree.XMLParser(recover=True))
        if root is None:
            return frag
        inner = "".join(etree.tostring(c, encoding="unicode") for c in root)
        # Strip the default-namespace decoration lxml adds on standalone children;
        # build_hero re-embeds them inside a namespaced <svg>, so they re-inherit it.
        inner = inner.replace(f' xmlns="{_SVG_NS}"', "")
        # Confirm the repair is actually well-formed before trusting it.
        etree.fromstring(f'<svg xmlns="{_SVG_NS}">{inner}</svg>'.encode("utf-8"))
        return inner
    except Exception:  # noqa: BLE001
        return frag


def spec_from_dict(entry: dict, *, title: str = "", category: str = "") -> HeroSpec:
    """Build a HeroSpec from a portable dict (bundle ``hero`` field / --manifest entry).

    Primary (freeform) shape — the agent designs the visual element itself::

        {"svg_element": "<...raw SVG...>", "head": [[text, color], ...], "category"?}

    Legacy/fallback shape (deterministic preset)::

        {"style", "motif", "params"?, "head": [[text, color], ...]}

    ``color`` is ``"g"`` for the green accent run, else null.
    """
    lines = [[(t, GREEN if c == "g" else None)] for t, c in entry["head"]]
    return HeroSpec(
        entry.get("style", "minimal"),
        entry.get("category") or short_category(category),
        lines,
        entry.get("motif", "hub_spokes"),
        motif_params=entry.get("params", {}) or {},
        title=title or None,
        head_size=entry.get("head_size"),
        svg_element=_repair_svg_fragment(entry.get("svg_element")),
    )


def render_and_store(spec: HeroSpec, slug: str) -> str:
    """Build the hero SVG and write it under MEDIA_ROOT with a content-hashed name."""
    svg = build_hero(spec).encode("utf-8")
    digest = hashlib.sha1(svg).hexdigest()[:8]
    now = timezone.now()
    rel = Path("blog/featured") / f"{now:%Y}" / f"{now:%m}" / f"{slug}.{digest}.svg"
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(svg)
    # og:image raster sibling (social cards can't render SVG); best-effort.
    from .raster import svg_to_webp
    svg_to_webp(svg, dest.with_suffix(".webp"))
    return "/media/" + rel.as_posix()


def attach_hero_to_post(post, *, force: bool = False, style: str | None = None,
                        motif: str | None = None) -> str | None:
    """Generate + attach a hero to a blog Post. No-op if one exists (unless force)."""
    if post.featured_image_url and not force:
        return None
    spec = derive_spec(
        title=post.title,
        category=getattr(post.category, "name", "") or "",
        slug=post.slug,
        excerpt=getattr(post, "excerpt", "") or "",
        style=style,
        motif=motif,
    )
    url = render_and_store(spec, post.slug)
    post.featured_image_url = url
    post.save(update_fields=["featured_image_url"])
    return url
