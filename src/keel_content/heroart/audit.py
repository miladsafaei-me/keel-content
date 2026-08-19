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
import math
import re
import xml.etree.ElementTree as ET

from .constants import H, MONO, SANS, SERIF, W
from .draw import BREATH, COVER_PAD, MAX_LABEL, text_width
from .worlds import luminance

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
#: An element this transparent does not hide what is behind it, so nothing can be
#: said to be printed *on* it.
SEE_THROUGH = 0.55
#: But it is still drawn, and still occupies the frame. A field of faint tiles is most
#: of what a screening grid is; measuring composition without it reported the motif as
#: filling half the frame it actually covers.
VISIBLE = 0.10
#: Text under this opacity is a watermark — several directions set a huge ghost
#: numeral behind the composition — so it neither collides nor obscures.
GHOST = 0.4
#: Longest a content label may be on a cover — shared with the renderer so the check
#: and the thing it checks cannot drift apart.
MAX_LABEL_CHARS = MAX_LABEL
#: Least contrast a word may have against what it is printed on. Below this the
#: label is present in the file and absent from the picture. WCAG's large-text
#: threshold, which every label here clears comfortably when the palette is right.
MIN_CONTRAST = 3.0

#: How much of the safe area the drawn content has to reach across each axis. Below
#: this the motif is a small picture marooned in a large frame — the composition is
#: compressed and the rest of the card is wasted.
#: Set where a centred motif — a dial, a rose, a ring — can still meet it without
#: being stretched into something it is not. Pushed higher, every round composition
#: had to become an ellipse to pass, which is the check dictating the design.
MIN_SPREAD_X, MIN_SPREAD_Y = 0.74, 0.66
#: And how close any drawn element may come to the edge of the safe area. Content
#: pressed against the margin reads as crowded even when it is technically inside.
EDGE = 4.0

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


#: How many numbers each path command takes, and which of them are a point. `H` and
#: `V` take one number that is an x or a y alone — reading a path as alternating x,y
#: pairs mis-assigns every coordinate after the first of those, which inflates the
#: box in the wrong direction and reports collisions that are not there.
PATH_ARITY = {"M": 2, "L": 2, "T": 2, "H": 1, "V": 1, "S": 4, "Q": 4, "C": 6, "A": 7,
              "Z": 0}


def _path_extent(d):
    """Bounding extent of a path's on-curve points, or None if it cannot be read."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:e-?\d+)?", d or "")
    xs, ys, cx, cy, cmd = [], [], 0.0, 0.0, None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd, i = t, i + 1
            if cmd in "Zz":
                continue
        if cmd is None:
            return None
        arity = PATH_ARITY.get(cmd.upper())
        if not arity or i + arity > len(tokens):
            return None
        try:
            args = [float(v) for v in tokens[i:i + arity]]
        except ValueError:
            return None
        i += arity
        rel = cmd.islower()
        if cmd.upper() == "H":
            cx = cx + args[0] if rel else args[0]
        elif cmd.upper() == "V":
            cy = cy + args[0] if rel else args[0]
        else:
            px, py = args[-2], args[-1]
            cx, cy = (cx + px, cy + py) if rel else (px, py)
        xs.append(cx)
        ys.append(cy)
    if len(xs) < 2:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _shape_box(el, chain, grads=None):
    """A drawn shape's box, or None when nothing is drawn.

    `path` and `polygon` come back as `(quad, True)` — approximate, because every
    coordinate in the data is treated as a point on the outline and a control point
    pushes the box outwards. That is good enough for asking what a word is printed on
    and not good enough for asking whether two things collide, so the caller uses it
    for the first question only.
    """
    tag = el.tag.replace(SVG_NS, "")
    fill = (el.get("fill") or "").lower()
    stroked = (el.get("stroke") or "none").lower() not in ("none", "")
    # A stroked outline is drawn and therefore occupies the frame, but it is not a
    # surface anything can be printed on. It is measured so composition is judged on
    # everything visible, flagged approximate so the geometry checks leave it alone,
    # and given no fill so the contrast check never consults it.
    if fill in ("none", "") and not stroked:
        return None
    alpha = _num(el, "opacity", 1.0) * _num(el, "fill-opacity", 1.0)
    if alpha < VISIBLE:
        return None
    faint = alpha < SEE_THROUGH
    if fill.startswith("url(#") and grads is not None and fill[5:].rstrip(")") not in grads:
        return None
    approx = faint or fill in ("none", "")
    if tag == "rect":
        x, y = _num(el, "x"), _num(el, "y")
        x1, y1 = x + _num(el, "width"), y + _num(el, "height")
    elif tag in ("circle", "ellipse"):
        cx, cy = _num(el, "cx"), _num(el, "cy")
        if tag == "circle":
            rx = ry = _num(el, "r")
        else:
            rx, ry = _num(el, "rx"), _num(el, "ry")
        # An ellipse under rotation needs its own extent. Rotating the four corners of
        # its box instead over-states it badly — a wide ellipse tipped 26 degrees came
        # out 600 units tall where the shape is 366, which reported a ring as leaving
        # a frame it sits comfortably inside.
        turn = math.radians(sum(m[0] for t in chain for kind, m in _ops(t)
                                if kind == "r"))
        hw = math.hypot(rx * math.cos(turn), ry * math.sin(turn))
        hh = math.hypot(rx * math.sin(turn), ry * math.cos(turn))
        moved = _moved([(cx, cy)], chain)[0]
        quad = Quad([(moved[0] - hw, moved[1] - hh), (moved[0] + hw, moved[1] - hh),
                     (moved[0] + hw, moved[1] + hh), (moved[0] - hw, moved[1] + hh)])
        # This branch returns early, so it has to carry the flag itself — without it a
        # stroked ring counted as a solid surface and every label crossing one was
        # reported as landing on something it merely passes over.
        return (quad, True) if approx else quad
    elif tag == "line":
        x, y = _num(el, "x1"), _num(el, "y1")
        x1, y1 = _num(el, "x2"), _num(el, "y2")
        approx = True
    elif tag in ("polygon", "polyline"):
        nums = [float(v) for v in re.findall(r"-?\d*\.?\d+", el.get("points", ""))]
        if len(nums) < 4:
            return None
        x, y = min(nums[0::2]), min(nums[1::2])
        x1, y1 = max(nums[0::2]), max(nums[1::2])
        approx = True
    elif tag == "path":
        span = _path_extent(el.get("d", ""))
        if span is None:
            return None
        x, y, x1, y1 = span
        approx = True
    else:
        return None
    quad = Quad(_moved([(min(x, x1), min(y, y1)), (max(x, x1), min(y, y1)),
                        (max(x, x1), max(y, y1)), (min(x, x1), max(y, y1))], chain))
    return (quad, True) if approx else quad


def _walk(node, chain, order, texts, shapes, grads=None):
    for el in node:
        tag = el.tag.replace(SVG_NS, "")
        if tag == "defs":
            continue
        sub = chain + ([el.get("transform")] if el.get("transform") else [])
        if tag == "text":
            box, content, size, fam = _text_box(el, sub)
            if content.strip() and _num(el, "opacity", 1.0) >= GHOST:
                texts.append((order[0], box, content, size, fam, el.get("fill", "")))
        elif tag == "g":
            _walk(el, sub, order, texts, shapes, grads)
            continue
        else:
            box = _shape_box(el, sub, grads)
            if box is not None:
                approx = isinstance(box, tuple)
                if approx:
                    box = box[0]
                fill = el.get("fill", "")
                solid = not approx and fill.lower() not in ("none", "")
                shapes.append((order[0], box, fill if solid else "", approx))
        order[0] += 1


def _contrast(fill, under, grads=None):
    """WCAG contrast between two solid colours, or None when either is not solid.

    A gradient or a filter reference cannot be resolved from the markup, and guessing
    at one would report failures that are not there — which is how a check stops being
    believed. Unresolvable pairs are simply not judged.
    """
    grads = grads or {}
    a, b = _resolve(fill, grads), _resolve(under, grads)
    if a is None or b is None:
        return None
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _gradients(root):
    """Every gradient's mean stop colour, by id.

    Most fills in these images are gradients, so a contrast check that gives up on
    `url(#…)` gives up on almost everything and quietly passes the pairings it was
    written to catch. A gradient is not one colour, but its mean is a fair stand-in
    for asking whether type can be read on it.
    """
    out = {}
    for grad in root.iter():
        tag = grad.tag.replace(SVG_NS, "")
        if tag not in ("linearGradient", "radialGradient"):
            continue
        lums, ops = [], []
        for stop in grad:
            value = luminance(stop.get("stop-color", ""))
            opacity = float(stop.get("stop-opacity", 1) or 1)
            ops.append(opacity)
            if value is not None and opacity >= 0.5:
                lums.append(value)
        # A gradient that is mostly transparent is a wash over whatever is behind it,
        # not a surface of its own. Counting it as one reports a word as unreadable
        # against a glow it is merely sitting near.
        if lums and sum(ops) / len(ops) >= SEE_THROUGH:
            out[grad.get("id", "")] = sum(lums) / len(lums)
    return out


def _resolve(fill, grads):
    """Luminance of a fill, following one level of gradient reference."""
    if not fill:
        return None
    if fill.startswith("url(#"):
        return grads.get(fill[5:].rstrip(")"))
    return luminance(fill)


def check(svg_text, kind="cover", bleeds=False, safe_pad=COVER_PAD, page=None):
    """Every layout fault in one rendered image, as a list of strings."""
    root = ET.fromstring(svg_text)
    texts, shapes, order = [], [], [0]
    page = page or ""
    grads = _gradients(root)
    _walk(root, [], order, texts, shapes, grads)
    faults = []

    frame = rect_quad(0, 0, W, H)
    safe = rect_quad(safe_pad, safe_pad, W - safe_pad, H - safe_pad)
    for _, box, content, size, fam, _f in texts:
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

    for i, (_, a, ca, _s, _f, _c) in enumerate(texts):
        for _, b, cb, _s2, _f2, _c2 in texts[i + 1:]:
            if a.shrunk(TOUCH).overlap(b.shrunk(TOUCH)) > TOUCH * TOUCH:
                faults.append(f"text over text: {ca[:28]!r} and {cb[:28]!r}")

    # A word rests on whatever was painted last beneath it. That surface is meant to
    # be its own plate, and a plate contains the word it backs. When the nearest
    # surface underneath is something the label merely landed on — a lit step panel,
    # a tile from the field behind — the label is on the wrong ground, and it reads
    # that way whether the surface arrived before the word or after it.
    ground_area = W * H * 0.5
    for zt, box, content, _size, _fam, fill in texts:
        if not box.area:
            continue
        over = sum(sbox.overlap(box) for zs, sbox, _sf, ap in shapes
                   if zs > zt and not ap and sbox.area < ground_area)
        if over / box.area > OBSCURED:
            faults.append(f"painted over ({over / box.area:.0%}): {content[:28]!r}")
            continue
        # An approximate box over-states a curved shape, so it has to clearly contain
        # the word before it is treated as the ground under it. Judged at the same
        # threshold as a rectangle it claims words that merely sit near a ribbon.
        beneath = [(zs, sbox, sfill, ap) for zs, sbox, sfill, ap in shapes
                   if zs < zt and sbox.area < ground_area
                   and sbox.overlap(box) > box.area * (0.75 if ap else OBSCURED)]
        if beneath:
            _z, nearest, nfill, approx = max(beneath, key=lambda item: item[0])
            if not approx and nearest.overlap(box) < box.area * 0.92:
                faults.append(f"lands on a surface that is not its own "
                              f"({nearest.overlap(box) / box.area:.0%}): "
                              f"{content[:28]!r}")
                continue
            under = nfill
        else:
            # Nothing small sits under the word, but a motif whose object fills most
            # of the frame has made that object the ground — a printed slip, a field of
            # panels. Ask the largest filled thing that contains the word before
            # falling back to the page behind everything.
            wide = [(zs, sfill) for zs, sbox, sfill, ap in shapes
                    if zs < zt and sfill and sbox.overlap(box) > box.area * 0.92]
            under = max(wide, key=lambda item: item[0])[1] if wide else page

        # A word the same brightness as what it is printed on is in the file and not
        # in the picture. This is the failure a neutral-ground surface invites: the
        # palette roles keep their names while their values flip, so a plate that was
        # dark under light type becomes light under light type.
        ratio = _contrast(fill, under, grads)
        if ratio is not None and ratio < MIN_CONTRAST:
            faults.append(f"too little contrast ({ratio:.1f}:1, needs "
                          f"{MIN_CONTRAST:.0f}): {content[:28]!r} on {under}")

    # A loose decoration parked against the plate a label sits on reads as crowding
    # even though nothing overlaps a word — the grid's lit tiles landing on the
    # shortlist plate is the case this exists for. Only free-floating elements count:
    # a motif's own panels touch and overlap its labels by design, so anything that
    # overlaps the plate, or is no smaller than it, is structure rather than clutter.
    ground_area = W * H * 0.5
    plates = {}
    for _z, box, _c, _s, _f, _fill in texts:
        holders = [(sbox.area, i) for i, (_zs, sbox, _sf, ap) in enumerate(shapes)
                   if not ap and sbox.overlap(box) > box.area * 0.92
                   and sbox.area < ground_area]
        if holders:
            plates.setdefault(min(holders)[1], []).append(box)
    for index in plates:
        plate = shapes[index][1]
        air = plate.grown(BREATH)
        for i, (_zs, sbox, _sf, ap) in enumerate(shapes):
            if ap or i == index or sbox.area >= plate.area or sbox.overlap(plate) > 1:
                continue
            if sbox.overlap(air) > BREATH * BREATH:
                faults.append(f"crowds the label plate: {sbox} sits inside its air")
                break

    # Composition: what the drawn content occupies, against what it was given. Both
    # failures are spacing failures and they pull in opposite directions — one is
    # content marooned in the middle of a frame, the other is content shoved against
    # its edge — so they are measured together from the same box.
    if kind == "cover" and not bleeds:
        drawn = [box for _z, box, _c, _s, _f, _fill in texts]
        drawn += [sbox for _z, sbox, _sf, ap in shapes
                  if sbox.area < W * H * 0.55 and not ap] or []
        drawn += [sbox for _z, sbox, _sf, ap in shapes if ap]
        if drawn:
            xs = [pt[0] for q in drawn for pt in q.pts]
            ys = [pt[1] for q in drawn for pt in q.pts]
            left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
            span_x = (right - left) / (W - safe_pad * 2)
            span_y = (bottom - top) / (H - safe_pad * 2)
            if span_x < MIN_SPREAD_X or span_y < MIN_SPREAD_Y:
                faults.append(f"content leaves the frame half empty "
                              f"({span_x:.0%} wide, {span_y:.0%} tall)")
            if (left < safe_pad - EDGE or right > W - safe_pad + EDGE
                    or top < safe_pad - EDGE or bottom > H - safe_pad + EDGE):
                faults.append(f"content presses the margin: "
                              f"({left:.0f},{top:.0f})-({right:.0f},{bottom:.0f})")

    if kind == "cover":
        body = 0
        for _z, _box, content, _size, fam, _fill in texts:
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
