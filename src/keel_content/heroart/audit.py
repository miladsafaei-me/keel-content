"""Geometry checks run against the SVG a direction actually produced.

Every layout fault this project has shipped was invisible to the code that caused
it: a label sized to its own text but wider than the plate behind it, a decorative
tile painted over a word, a step label that left the frame, type that shrank past
legibility. None of them can be caught by reading a direction in isolation, because
each is a relationship between two elements that no single call site knows about.

So this reads the finished image instead of the intent behind it. It walks the SVG,
resolves transforms, gives every text run a box using the same metrics the renderer
used to place it, and then asks four questions a person would ask looking at the
card:

* is every word inside the frame, and inside the cover safe area;
* does any word sit on top of another word;
* is any word painted over by something drawn after it;
* is any word too small to read at the size the card is displayed.

A direction whose idea *is* leaving the frame declares `bleeds = True` and is
exempted from the safe-area question only — never from the others.
"""
import re
import xml.etree.ElementTree as ET

from .constants import H, MONO, SANS, SERIF, W
from .draw import BREATH, COVER_PAD, MAX_LABEL, text_width

SVG_NS = "{http://www.w3.org/2000/svg}"

#: Below this a *content* label stops being readable once the cover is displayed at
#: listing size — a 1200 px canvas renders about 340 px wide there.
MIN_TYPE = 20
#: The small-caps eyebrows are set in mono and are meant to sit well under the
#: content; they carry a head word, not the message, so they have their own floor.
MIN_EYEBROW = 11
#: How much of a text box another element may cover before the word is unreadable.
OBSCURED = 0.22
#: Text boxes touching by less than this are kerning noise, not a collision.
TOUCH = 3.0
#: An element this transparent does not hide what is behind it.
SEE_THROUGH = 0.55
#: Text under this opacity is a watermark — several directions set a huge ghost
#: numeral behind the composition — so it neither collides nor obscures.
GHOST = 0.4
#: Longest a content label may be on a cover — shared with the renderer so the check
#: and the thing it checks cannot drift apart.
MAX_LABEL_CHARS = MAX_LABEL
#: All the content text one cover may carry. Four names and a heading is a card; a
#: paragraph broken into lines is an article, and belongs in the hero.
MAX_COVER_CHARS = 150


class Quad:
    """Four corners in canvas space, kept as a polygon rather than a box.

    Several motifs tilt their elements, and the axis-aligned box around a tilted
    strip is far larger than the strip: a 765x66 label plate turned seven degrees
    has a box 158 tall. Measured that way the glass stack looks like every label
    overlaps every other, which is a fault in the ruler rather than in the image.
    """
    __slots__ = ("pts",)

    def __init__(self, pts):
        self.pts = pts

    @property
    def area(self):
        pts = self.pts
        return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                       - pts[(i + 1) % len(pts)][0] * pts[i][1]
                       for i in range(len(pts)))) / 2

    def overlap(self, other):
        """Area shared with another convex polygon (Sutherland-Hodgman).

        Both polygons are wound the same way first: the corners arrive from four
        different code paths and a reversed winding turns the clip inside out, which
        reports every element as outside the frame rather than inside it.
        """
        out = _wound(self.pts)
        clip = _wound(other.pts)
        for i in range(len(clip)):
            a, b = clip[i], clip[(i + 1) % len(clip)]
            ex, ey = b[0] - a[0], b[1] - a[1]

            def side(pt):
                return ex * (pt[1] - a[1]) - ey * (pt[0] - a[0])

            clipped, prev = [], out[-1] if out else None
            for cur in out:
                if side(cur) >= 0:
                    if side(prev) < 0:
                        clipped.append(_cut(prev, cur, a, b))
                    clipped.append(cur)
                elif side(prev) >= 0:
                    clipped.append(_cut(prev, cur, a, b))
                prev = cur
            out = clipped
            if not out:
                return 0.0
        return Quad(out).area

    def grown(self, by):
        return self.shrunk(-by)

    def shrunk(self, by):
        """The same quad pulled in towards its centre by roughly `by` units."""
        cx = sum(p[0] for p in self.pts) / len(self.pts)
        cy = sum(p[1] for p in self.pts) / len(self.pts)
        span = max((abs(p[0] - cx) + abs(p[1] - cy)) for p in self.pts) or 1
        k = max(0.0, 1 - by / span)
        return Quad([(cx + (p[0] - cx) * k, cy + (p[1] - cy) * k) for p in self.pts])

    def __repr__(self):
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        return f"({min(xs):.0f},{min(ys):.0f})-({max(xs):.0f},{max(ys):.0f})"


def _signed_area(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
               - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2


def _wound(pts):
    """The same corners, always in positive-area order."""
    return list(pts) if _signed_area(pts) >= 0 else list(reversed(pts))


def _cut(p, q, a, b):
    """Where segment p-q crosses the line through a-b."""
    r = (q[0] - p[0], q[1] - p[1])
    e = (b[0] - a[0], b[1] - a[1])
    den = e[0] * r[1] - e[1] * r[0]
    if not den:
        return q
    t = (e[0] * (a[1] - p[1]) - e[1] * (a[0] - p[0])) / den
    return (p[0] + r[0] * t, p[1] + r[1] * t)


def rect_quad(x0, y0, x1, y1):
    return Quad([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _num(el, name, default=0.0):
    try:
        return float(el.get(name, default))
    except (TypeError, ValueError):
        return default


def _family(raw):
    """Map the font-family string back to the stack the metrics were built for."""
    if not raw:
        return SANS
    head = raw.split(",")[0].strip().strip("'\"").lower()
    if "serif" in head or "georgia" in head or "times" in head:
        return SERIF
    if "mono" in head or "plex" in head or "source code" in head:
        return MONO
    return SANS


ROTATE = re.compile(r"rotate\(\s*(-?[\d.]+)(?:[ ,]+(-?[\d.]+)[ ,]+(-?[\d.]+))?\s*\)")
TRANSLATE = re.compile(r"translate\(\s*(-?[\d.]+)(?:[ ,]+(-?[\d.]+))?\s*\)")
SKEW = re.compile(r"skew([XY])\(\s*(-?[\d.]+)\s*\)")


def _apply(transform, x, y):
    """Point after one element's transform attribute. Only what the engine emits."""
    if not transform:
        return x, y
    import math

    # `transform="A B C"` composes as A(B(C(p))), so the last listed op acts first.
    # Applying them left to right is harmless while every transform holds a single
    # op, and silently wrong the moment one holds three — which is how a correctly
    # placed staircase came to be reported as broken.
    for kind, m in reversed(_ops(transform)):
        if kind == "t":
            x, y = x + m[0], y + m[1]
        elif kind == "sx":
            x = x + y * math.tan(math.radians(m[0]))
        elif kind == "sy":
            y = y + x * math.tan(math.radians(m[0]))
        else:
            a, cx, cy = m
            rad = math.radians(a)
            dx, dy = x - cx, y - cy
            x = cx + dx * math.cos(rad) - dy * math.sin(rad)
            y = cy + dx * math.sin(rad) + dy * math.cos(rad)
    return x, y


def _ops(transform):
    """The transform attribute as operations, in the order the engine applies them.

    Only what these directions emit — a skew missing from this list is not ignored
    harmlessly: every box under it is then measured in the wrong place, and the
    checks built on those boxes quietly stop meaning anything.
    """
    out = []
    for m in re.finditer(r"(rotate|translate|skewX|skewY)\([^)]*\)", transform):
        piece = m.group(0)
        if piece.startswith("translate"):
            g = TRANSLATE.match(piece)
            out.append(("t", (float(g.group(1)), float(g.group(2) or 0))))
        elif piece.startswith("skew"):
            g = SKEW.match(piece)
            out.append(("sx" if g.group(1) == "X" else "sy", (float(g.group(2)),)))
        else:
            g = ROTATE.match(piece)
            out.append(("r", (float(g.group(1)), float(g.group(2) or 0),
                              float(g.group(3) or 0))))
    return out


def _moved(corners, chain):
    """Corners after every transform on the way down to this element."""
    out = []
    for cx, cy in corners:
        for t in reversed(chain):
            cx, cy = _apply(t, cx, cy)
        out.append((cx, cy))
    return out


def _text_box(el, chain):
    """Where a text run lands, in canvas coordinates."""
    content = "".join(el.itertext())
    size = _num(el, "font-size", 12)
    fam = _family(el.get("font-family"))
    weight = int(_num(el, "font-weight", 400))
    width = text_width(content, size, fam, weight)
    anchor = el.get("text-anchor", "start")
    x, y = _num(el, "x"), _num(el, "y")
    if anchor == "middle":
        x -= width / 2
    elif anchor == "end":
        x -= width
    corners = [(x, y - size * 0.80), (x + width, y - size * 0.80),
               (x + width, y + size * 0.22), (x, y + size * 0.22)]
    return Quad(_moved(corners, chain)), content, size, fam


def _shape_box(el, chain):
    """A filled shape's box, or None when it cannot hide anything."""
    tag = el.tag.replace(SVG_NS, "")
    fill = (el.get("fill") or "").lower()
    if fill in ("none", "") or fill.startswith("url(#") and "grad" not in fill:
        pass
    if fill == "none":
        return None
    op = _num(el, "opacity", 1.0)
    fop = _num(el, "fill-opacity", 1.0)
    if op * fop < SEE_THROUGH:
        return None
    if tag == "rect":
        x, y = _num(el, "x"), _num(el, "y")
        x1, y1 = x + _num(el, "width"), y + _num(el, "height")
    elif tag == "circle":
        cx, cy, r = _num(el, "cx"), _num(el, "cy"), _num(el, "r")
        x, y, x1, y1 = cx - r, cy - r, cx + r, cy + r
    elif tag == "ellipse":
        cx, cy = _num(el, "cx"), _num(el, "cy")
        rx, ry = _num(el, "rx"), _num(el, "ry")
        x, y, x1, y1 = cx - rx, cy - ry, cx + rx, cy + ry
    else:
        return None
    return Quad(_moved([(x, y), (x1, y), (x1, y1), (x, y1)], chain))


def _walk(node, chain, order, texts, shapes):
    for el in node:
        tag = el.tag.replace(SVG_NS, "")
        if tag == "defs":
            continue
        sub = chain + ([el.get("transform")] if el.get("transform") else [])
        if tag == "text":
            box, content, size, fam = _text_box(el, sub)
            if content.strip() and _num(el, "opacity", 1.0) >= GHOST:
                texts.append((order[0], box, content, size, fam))
        elif tag == "g":
            _walk(el, sub, order, texts, shapes)
            continue
        else:
            box = _shape_box(el, sub)
            if box is not None:
                shapes.append((order[0], box))
        order[0] += 1


def check(svg_text, kind="cover", bleeds=False, safe_pad=COVER_PAD):
    """Every layout fault in one rendered image, as a list of strings."""
    root = ET.fromstring(svg_text)
    texts, shapes, order = [], [], [0]
    _walk(root, [], order, texts, shapes)
    faults = []

    frame = rect_quad(0, 0, W, H)
    safe = rect_quad(safe_pad, safe_pad, W - safe_pad, H - safe_pad)
    for _, box, content, size, fam in texts:
        label = content[:34]
        # A declared bleed covers both edges of the same idea: ChapterPlate's numeral
        # is cropped on purpose, and SplitPanels' fields run past the frame.
        if not bleeds:
            if box.overlap(frame) < box.area - 1:
                faults.append(f"leaves the frame: {label!r} at {box}")
            elif kind == "cover" and box.overlap(safe) < box.area - 1:
                faults.append(f"outside the cover safe area: {label!r} at {box}")
        floor = MIN_EYEBROW if fam is MONO else MIN_TYPE
        if size < floor and kind == "cover":
            faults.append(f"type too small ({size:.0f}px): {label!r}")

    for i, (_, a, ca, _s, _f) in enumerate(texts):
        for _, b, cb, _s2, _f2 in texts[i + 1:]:
            if a.shrunk(TOUCH).overlap(b.shrunk(TOUCH)) > TOUCH * TOUCH:
                faults.append(f"text over text: {ca[:28]!r} and {cb[:28]!r}")

    # A word rests on whatever was painted last beneath it. That surface is meant to
    # be its own plate, and a plate contains the word it backs. When the nearest
    # surface underneath is something the label merely landed on — a lit step panel,
    # a tile from the field behind — the label is on the wrong ground, and it reads
    # that way whether the surface arrived before the word or after it.
    ground_area = W * H * 0.5
    for zt, box, content, _size, _fam in texts:
        if not box.area:
            continue
        over = sum(sbox.overlap(box) for zs, sbox in shapes
                   if zs > zt and sbox.area < ground_area)
        if over / box.area > OBSCURED:
            faults.append(f"painted over ({over / box.area:.0%}): {content[:28]!r}")
            continue
        beneath = [(zs, sbox) for zs, sbox in shapes
                   if zs < zt and sbox.area < ground_area
                   and sbox.overlap(box) > box.area * OBSCURED]
        if beneath:
            _z, nearest = max(beneath, key=lambda item: item[0])
            if nearest.overlap(box) < box.area * 0.92:
                faults.append(f"lands on a surface that is not its own "
                              f"({nearest.overlap(box) / box.area:.0%}): "
                              f"{content[:28]!r}")

    # A loose decoration parked against the plate a label sits on reads as crowding
    # even though nothing overlaps a word — the grid's lit tiles landing on the
    # shortlist plate is the case this exists for. Only free-floating elements count:
    # a motif's own panels touch and overlap its labels by design, so anything that
    # overlaps the plate, or is no smaller than it, is structure rather than clutter.
    ground_area = W * H * 0.5
    plates = {}
    for _z, box, _c, _s, _f in texts:
        holders = [(sbox.area, i) for i, (_zs, sbox) in enumerate(shapes)
                   if sbox.overlap(box) > box.area * 0.92 and sbox.area < ground_area]
        if holders:
            plates.setdefault(min(holders)[1], []).append(box)
    for index in plates:
        plate = shapes[index][1]
        air = plate.grown(BREATH)
        for i, (_zs, sbox) in enumerate(shapes):
            if i == index or sbox.area >= plate.area or sbox.overlap(plate) > 1:
                continue
            if sbox.overlap(air) > BREATH * BREATH:
                faults.append(f"crowds the label plate: {sbox} sits inside its air")
                break

    if kind == "cover":
        body = 0
        for _z, _box, content, _size, fam in texts:
            words = content.strip()
            if fam is MONO:
                continue
            body += len(words)
            if len(words) > MAX_LABEL_CHARS:
                faults.append(f"label too long ({len(words)} chars): {words[:40]!r}")
        # A wrapped label reaches the file as one short line per row, so no single
        # run breaks the rule above while the card as a whole is a paragraph. The
        # total is what tells a card being seen from a card being read.
        if body > MAX_COVER_CHARS:
            faults.append(f"too much text on the card ({body} chars)")
    return faults
