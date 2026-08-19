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


#: A palette has two independent decisions: which hue, and what the hue is allowed to
#: touch. The second is the surface.
#:
#: `tinted` puts the hue in everything, ground included — the original treatment, and
#: the reason a feed of it reads as one colour per card however much the hue moves.
#: The other three hold the ground neutral and spend the hue on what is drawn on it:
#: `slate` on a near-black page, `paper` on a near-white one, and `panel` on a
#: near-black page carrying one saturated container that the motif sits inside.
#:
#: The pairing that holds on every surface, and the one thing to get right when
#: writing a direction: `ink` is the type that reads on `page`, `mid` and `lift`;
#: `onink` is the type that reads on `deep` and `accent`. Pick from the wrong pair and
#: the label is in the file and not in the picture — on one surface only, which is why
#: the audit checks contrast rather than trusting the author.
#:
#: Roles keep their meaning across all four — `ink` is always the text that reads on
#: the page, `onink` always the text that reads on a `deep` or `accent` fill. On a dark
#: surface those are the same colour; on `paper` they are opposites, which is exactly
#: the mistake the audit's contrast check exists to catch.
SURFACES = {
    "tinted": dict(
        page=(0.42, 0.0045), deep=(0.42, 0.0045), mid=(0.46, 0.0180),
        lift=(0.46, 0.0430), ink=(0.55, 0.8600), onink=(0.55, 0.8600),
        dim=(0.32, 0.4450), faint=(0.22, 0.1250), accent=(0.72, 0.2450),
        hot=(0.86, 0.5600),
    ),
    "slate": dict(
        page=(0.00, 0.0100), deep=(0.06, 0.0180), mid=(0.55, 0.0700),
        lift=(0.62, 0.1500), ink=(0.06, 0.8600), onink=(0.06, 0.8600),
        dim=(0.16, 0.4200), faint=(0.10, 0.1100), accent=(0.85, 0.3200),
        hot=(0.92, 0.6000),
    ),
    "paper": dict(
        page=(0.03, 0.9000), deep=(0.70, 0.0400), mid=(0.45, 0.5000),
        lift=(0.34, 0.6800), ink=(0.30, 0.0300), onink=(0.06, 0.9200),
        dim=(0.30, 0.1800), faint=(0.16, 0.7000), accent=(0.85, 0.1500),
        hot=(0.88, 0.3000),
    ),
    "panel": dict(
        page=(0.02, 0.0620), deep=(0.55, 0.0060), mid=(0.60, 0.0280),
        lift=(0.58, 0.0600), ink=(0.55, 0.8600), onink=(0.55, 0.8600),
        dim=(0.32, 0.4450), faint=(0.24, 0.1300), accent=(0.80, 0.2600),
        hot=(0.88, 0.5600),
    ),
}
#: How much of the hue the ground itself is allowed to carry as a soft light. It is
#: the glow, not the page colour, that made the neutral surfaces still read as one
#: colour per card: a wide accent ellipse at any real opacity tints a white sheet
#: lavender and a black one violet.
GLOW = {"tinted": 1.0, "slate": 0.0, "paper": 0.0, "panel": 0.30}

DEFAULT_SURFACE = "tinted"

#: Surfaces that hold the ground neutral. The container surface is listed here too:
#: its page is neutral even though what sits on it is not.
NEUTRAL = ("slate", "paper", "panel")


def palette(hue, surface=DEFAULT_SURFACE):
    """The palette roles at one hue, on one surface, in one tonal register."""
    roles = SURFACES.get(surface, SURFACES[DEFAULT_SURFACE])
    out = {role: _hex_at(hue, sat, target) for role, (sat, target) in roles.items()}
    out["good"] = GOOD
    out["hue"] = hue
    out["surface"] = surface
    out["light"] = surface == "paper"
    out["glow"] = GLOW.get(surface, 1.0)
    # What the content is actually drawn over, which is not always the page: on the
    # container surface the motif sits on the container, and judging its contrast
    # against the sheet behind would measure the wrong pair.
    out["ground"] = out["mid"] if surface == "panel" else out["page"]
    return out


def luminance(hex_colour):
    """Relative luminance of a #rrggbb string, for contrast checks."""
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        rgb = tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None
    return _luma(rgb)


def allocate_surfaces(order, choices, page=PAGE, blocked=()):
    """Give every slug a surface, mixed within each page of the feed.

    The surface is a second axis of variety and behaves like the first: spread it over
    the page the reader opens, not over the corpus. Each page walks the choices in a
    rotating order so no page is all one treatment and no two consecutive pages start
    on the same one.

    `blocked` is {surface: {direction keys}} for pairings that contradict themselves —
    a direction whose idea is running to the frame has nothing to say inside a
    container — and those fall back to the first choice.
    """
    out = {}
    if len(choices) < 2:
        return {slug: choices[0] for slug, _d in order}
    for index in range(0, len(order), page):
        block = order[index:index + page]
        start = (index // page) % len(choices)
        for i, (slug, direction) in enumerate(block):
            pick = choices[(start + i) % len(choices)]
            if direction in blocked.get(pick, ()):
                pick = choices[0]
            out[slug] = pick
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
