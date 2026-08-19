"""Colour: one palette per post, generated, not one palette per category.

The first build mapped category to one of four fixed palettes. Measured across 204
posts that produced only 39 distinct (motif, colour) pairs, and the small categories
came out monochrome — compliance was 6 of 6 in the same red, payments 6 of 6 in the
same teal. Category-as-colour is exactly what made a category look like one article
repeated.

So a palette is now *derived per post* from its slug: a hue is picked off a curated
wheel and the nine palette roles are generated from it at fixed saturation and
lightness. Every post can have its own colour while the whole feed still reads as one
system, because only the hue moves — the tonal structure never does.

Roles, unchanged, so no direction has to know any of this:

    deep   darkest ground, also the occluding fill
    mid    panel and object bodies
    lift   the lit face of an object
    ink    near-white body text
    dim    secondary text
    faint  structure that must stay behind the content
    accent the post's colour, spent on the focal element only
    hot    the accent's light end: edges, glows, the single lit thing
    good   the one semantic positive, held constant across every palette
"""
import colorsys

from .constants import H, MONO, SANS, SERIF, W  # noqa: F401  (re-exported)
from .draw import seedof

#: The hues that survive this treatment, as a continuous arc from teal through blue,
#: violet, magenta and red to orange. Curated rather than a full circle: the
#: yellow-green and olive bands go muddy at these lightnesses, so the arc simply
#: stops at 30 and picks up again at 156.
#:
#: The step is finer than the eye needs on its own — two neighbours here are not
#: meant to be told apart. The wheel's job is to give `allocate` somewhere to land
#: once it has decided where the colours of a page should sit; the separation itself
#: comes from how those positions are chosen, not from the spacing of the wheel.
ARC_START, ARC_SPAN = 156, 234
HUE_WHEEL = tuple(h % 360 for h in range(ARC_START, ARC_START + ARC_SPAN + 1, 6))

#: Cards per page in the Academy listing, which is the set a reader compares at once.
PAGE = 10

GOOD = "#34d399"


def _rgb(h, s, light):
    return colorsys.hls_to_rgb((h % 360) / 360.0, light, s)


def _luma(rgb):
    """Relative luminance, so two hues can be matched by how bright they look."""
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _hex_at(hue, sat, target):
    """The colour at this hue and saturation whose luminance matches `target`.

    Equal HSL lightness is not equal apparent brightness: at L=63% a magenta reads
    far lighter than a blue, which is why hue-rotating a palette naively washes half
    the wheel out. Solving for luminance instead keeps every palette in the same
    tonal register, so only the hue changes.
    """
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if _luma(_rgb(hue, sat, mid)) < target:
            lo = mid
        else:
            hi = mid
    r, g, b = _rgb(hue, sat, (lo + hi) / 2)
    return "#%02x%02x%02x" % (int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


#: role -> (saturation, target luminance). The luminances are those of the original
#: violet palette, so the whole wheel now matches the tone that was signed off.
ROLES = dict(
    deep=(0.42, 0.0045),
    mid=(0.46, 0.0180),
    lift=(0.46, 0.0430),
    ink=(0.55, 0.8600),
    dim=(0.32, 0.4450),
    faint=(0.22, 0.1250),
    accent=(0.72, 0.2450),
    hot=(0.86, 0.5600),
)


def palette(hue):
    """The nine roles at one hue, matched to a fixed tonal register."""
    out = {role: _hex_at(hue, sat, target) for role, (sat, target) in ROLES.items()}
    out["good"] = GOOD
    out["hue"] = hue
    return out


def hue_distance(a, b):
    """Separation between two hues in degrees, the short way round the circle."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def allocate(order, page=PAGE):
    """Give every slug a hue, spread across each page and balanced over the wheel.

    `order` is the slugs in the order the reader meets them — newest first, the way
    /academy paginates. The unit of work is one page, because that is the set of
    cards a reader compares. Each page is handed an evenly-spaced comb of hues across
    the usable arc, so ten cards land about 23 degrees apart by construction; the
    comb is rotated a little on each successive page, so the whole wheel gets used
    instead of the same slots coming round every time.

    Two earlier shapes failed, and the comb is the answer to both. Allocating per
    post against a fixed per-hue quota stopped working once the quota ran out — 22
    hues at three posts each covered 66 of 153 posts, and everything after fell back
    to the raw hash, which is why every page of the live feed carried two identical
    colours. Replacing that with a greedy least-used pick under a minimum-gap rule
    removed the duplicates but could strand itself: taking the least-used hue first
    sometimes left no legal position for the cards still to be placed, so the rule
    had to be relaxed and near-duplicates came back. A comb cannot strand itself,
    because every position is decided before any card is placed.
    """
    used, out = {}, {}
    blocks = [order[i:i + page] for i in range(0, len(order), page)]
    for index, block in enumerate(blocks):
        # Walk the wheel in strides so the page's hues are evenly spaced by
        # construction: ten cards at a stride of four wheel steps sit 24 degrees
        # apart and span 216 of the 234-degree arc. Snapping an evenly-spaced comb
        # onto the wheel instead would round neighbouring positions together and put
        # two cards 18 degrees apart, which is where the previous attempt landed.
        stride = max(len(HUE_WHEEL) // max(len(block), 1), 1)
        # Rotating the start by three slots per page — coprime with the wheel — walks
        # every hue into use instead of reusing one evenly-spaced set on every page.
        start = (index * 3) % len(HUE_WHEEL)
        picked = [HUE_WHEEL[(start + k * stride) % len(HUE_WHEEL)]
                  for k in range(len(block))]
        # The page owns a set of hues; which post gets which is then decided by the
        # post itself, so a slug keeps a colour near the one its hash asks for.
        pool = list(picked)
        for slug in sorted(block, key=lambda s: seedof(f"{s}|hue")):
            want = HUE_WHEEL[seedof(f"{slug}|hue") % len(HUE_WHEEL)]
            hue = min(pool, key=lambda h: (hue_distance(h, want), h))
            pool.remove(hue)
            used[hue] = used.get(hue, 0) + 1
            out[slug] = hue
    return out


#: Named families kept only for previews, docs and hand-pinning through --manifest.
WORLDS = {
    "violet": palette(262),
    "indigo": palette(232),
    "teal": palette(178),
    "ember": palette(354),
    "amber": palette(32),
    "magenta": palette(316),
}
DEFAULT_WORLD = "violet"


def world_for(name):
    return WORLDS.get(name, WORLDS[DEFAULT_WORLD])
