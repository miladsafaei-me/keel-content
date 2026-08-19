"""The ten hero directions.

Each one is a Direction: it draws a motif into a box, and the shared frames place
that motif either beside the title (hero) or across the safe area (card cover). A
direction therefore never hard-codes a canvas position, which is what lets the same
class serve a 1200x675 hero, a listing cover, and any future size.

Contract every direction keeps:

* Words come from the Subject, never from the direction.
* Numbers are drawn only when `subject.weights` exists; nothing is ever invented.
* Inside a cover, everything stays within the safe box (draw.COVER_PAD on each side)
  unless leaving the frame is the idea of that direction — SplitPanels bleeds because
  edge-to-edge colour is the point, and ChapterPlate crops its numeral on purpose.
  Both say so in their docstring.

See docs/blog/hero-art-spec.md for how to invent an eleventh.
"""
import math

from .constants import H, MONO, SANS, SERIF, W
from .draw import (BREATH, COVER_PAD, MAX_LABEL, MIN_LABEL, SAFE_BOX, advance,
                   clip, fit, fit_all,
                   ground,
                   seedof,
                   shadow_def, svg, text_width, txt, txt_fit, variant, wordmark,
                   wrap)


def title_block(p, post_title, kicker, subject, x=72, width=430, hi=42, lo=26,
                centre=300, lines_max=4):
    size, lines = fit(post_title, width, SANS, hi, lo, max_lines=lines_max)
    lh = int(size * 1.16)
    y = centre - (len(lines) - 1) * lh // 2
    out = txt(x, 92, kicker, 11.5, p["accent"], 700, MONO, ls=2.6)
    for line in lines:
        out += txt(x, y, line, size, p["ink"], 800, SANS)
        y += lh
    if subject:
        head = subject.head.upper()
        label = (f"{subject.n} COMPARED" if head.startswith("COMPARED")
                 else f"{head}  ·  {subject.n} COMPARED")
        out += txt(x, y + 30, label, 12, p["dim"], 600, MONO, ls=2.4)
    return out


class Direction:
    key = ""
    name = ""
    #: what kind of article this fits — read by the selector and by the picking agent
    fits = ""
    hero_box = (596, 100, 548, 476)
    cover_box = SAFE_BOX
    hero_glow = (900, 300, 470)
    cover_glow = (600, 320, 540)
    hero_items = 4
    cover_items = 4
    #: A ceiling, not a target: item text is sized to fit its slot by `txt_fit`, and
    #: these only bound how much of the article's own wording reaches the renderer.
    #: The cover is the tighter of the two on purpose — a listing card is seen, not
    #: read, and `heroart.audit.MAX_LABEL_CHARS` holds the finished image to it.
    hero_maxlen = 64
    cover_maxlen = 34
    title_width = 430
    #: False for directions whose composition is tied to one side of the frame.
    mirrorable = True
    #: True only where leaving the cover safe area IS the idea (hard rule 3). It
    #: exempts a direction from the safe-area check and from nothing else.
    bleeds = False

    def defs(self, p, uid, s, big):
        return ""

    def background(self, p, uid, big, box):
        """Light follows the motif, and its offset varies per post."""
        x, y, w, h = box
        radius = 540 if big else 470
        gx = x + w * 0.5 + (0 if big else 0)
        gy = y + h * 0.5
        gx += variant(str(box) + p["ink"], "glowx", (-80, -30, 20, 70))
        return ground(p, uid, glow=(gx, gy, radius))

    def motif(self, p, uid, s, box, big):
        raise NotImplementedError

    def hero_layout(self, key):
        """Where the title and the motif sit. Mirrored for roughly half of posts."""
        bx, by, bw, bh = self.hero_box
        mirrored = self.mirrorable and variant(key, "mirror", (False, True, True, False))
        centre = variant(key, "titley", (286, 300, 314))
        if not mirrored:
            return (bx, by, bw, bh), 72, centre
        return (W - bx - bw, by, bw, bh), W - 72 - self.title_width, centre

    def hero(self, subject, p, uid):
        s = subject.truncated(self.hero_items, self.hero_maxlen)
        box, title_x, centre = self.hero_layout(subject.key)
        d, g = self.background(p, uid, False, box)
        d += self.defs(p, uid, s, False)
        body = g + self.motif(p, uid, s, box, False)
        body += title_block(p, subject.title, subject.kicker, s, x=title_x,
                            width=self.title_width, centre=centre)
        return svg(d, body + wordmark(p))

    def cover(self, subject, p, uid):
        s = subject.truncated(self.cover_items, self.cover_maxlen)
        d, g = self.background(p, uid, True, self.cover_box)
        d += self.defs(p, uid, s, True)
        return svg(d, g + self.motif(p, uid, s, self.cover_box, True))


class CardStack(Direction):
    """Options as physical cards, each leaving its own name strip exposed."""

    key = "stack"
    name = "Deck of options"
    fits = "a straight choice between named options"
    cover_items = 3

    def defs(self, p, uid, s, big):
        return (shadow_def(uid, dy=28 if big else 24, blur=30 if big else 24, op=0.6)
                + f'<linearGradient id="{uid}front" x1="0" y1="0" x2="0.6" y2="1">'
                  f'<stop offset="0" stop-color="{p["lift"]}"/>'
                  f'<stop offset="1" stop-color="{p["mid"]}"/></linearGradient>'
                  f'<linearGradient id="{uid}back" x1="0" y1="0" x2="0.6" y2="1">'
                  f'<stop offset="0" stop-color="{p["mid"]}"/>'
                  f'<stop offset="1" stop-color="{p["lift"]}" stop-opacity="0.75"/>'
                  f'</linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = s.n
        band = (132 if big else 70) + variant(s.key, "band", (-8, 0, 10))
        ch = min(h - (n - 1) * band, 250 if big else 232)
        cw = min(w * (0.6 if big else 0.72), 620 if big else 396)
        step_x = (62 if big else 40) * variant(s.key, "fan", (1, -1))
        ox = x + (w - cw - (n - 1) * step_x) / 2
        oy = y + h - ch
        label = 48 if big else 23
        out = ""
        for i in range(n - 1, -1, -1):
            cx = ox + i * step_x
            cy = oy - i * band
            front = (i == 0)
            fill = f"url(#{uid}front)" if front else f"url(#{uid}back)"
            out += (f'<g filter="url(#{uid}sh)"><rect x="{cx:.0f}" y="{cy:.0f}" '
                    f'width="{cw:.0f}" height="{ch:.0f}" rx="18" fill="{fill}"/></g>')
            out += (f'<rect x="{cx:.0f}" y="{cy:.0f}" width="{cw:.0f}" height="{ch:.0f}" '
                    f'rx="18" fill="none" stroke="{p["hot"] if front else p["faint"]}" '
                    f'stroke-opacity="{0.5 if front else 0.3}" stroke-width="1.5"/>')
            out += (f'<line x1="{cx + 22:.0f}" y1="{cy + 1:.0f}" '
                    f'x2="{cx + cw - 22:.0f}" y2="{cy + 1:.0f}" stroke="{p["hot"]}" '
                    f'stroke-opacity="0.38" stroke-width="2"/>')
            tx = cx + 26
            out += txt(tx, cy + band * 0.30, f"{i + 1:02d}", label * 0.44,
                       p["accent"] if front else p["faint"], 700, MONO, ls=1.5)
            out += txt(tx + label * 1.25, cy + band * 0.30, s.head.upper()[:12],
                       label * 0.36, p["dim"], 600, MONO, ls=2,
                       op=0.75 if front else 0.45)
            out += txt_fit(tx, cy + band * 0.78, s.items[i], cw - 52,
                           label, MIN_LABEL,
                           p["ink"] if front else p["dim"], 700, SANS,
                           op=1 if front else 0.8)
            if front and not big and s.notes[i]:
                for k, line in enumerate(wrap(s.notes[i], cw - 52, 14, SANS, 400, 2)):
                    out += txt(tx, cy + band + 34 + k * 19, line, 14, p["dim"], 400,
                               SANS, op=0.85)
        return out


class MoneyFlow(Direction):
    """One source opening into shares. Widths are real only when the data is."""

    key = "flow"
    name = "Revenue split"
    fits = "money splitting: commission, payout, revenue share"
    hero_glow = (700, 340, 480)
    cover_glow = (520, 338, 560)

    def defs(self, p, uid, s, big):
        d = ""
        for i in range(max(1, s.n)):
            t = i / max(1, s.n - 1)
            c0 = p["accent"] if i == 0 else p["faint"]
            c1 = p["hot"] if i == 0 else p["mid"]
            d += (f'<linearGradient id="{uid}r{i}" x1="0" y1="0" x2="1" y2="0">'
                  f'<stop offset="0" stop-color="{c0}" stop-opacity="{0.85 - t * 0.3:.2f}"/>'
                  f'<stop offset="1" stop-color="{c1}" stop-opacity="{0.95 - t * 0.35:.2f}"/>'
                  f'</linearGradient>')
        return d

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        label = 40 if big else 19
        widest = max(text_width(i, label, SANS, 700) for i in s.items)
        x0 = x + (26 if big else 0)
        x1 = x + w - widest - (34 if big else 26)
        cy = y + h / 2
        span = h * 0.86
        n = s.n
        weights = s.weights or [1.0] * n
        total = sum(weights)
        shares = [v / total for v in weights]
        src_h = span * variant(s.key, "source", (0.34, 0.42, 0.52))
        gap = (44 if big else 26) + variant(s.key, "fangap", (-8, 0, 12))
        out = ""
        cursor = cy - src_h / 2
        ends = []
        end_total = sum(max(20, span * 0.78 * sh) for sh in shares) + gap * (n - 1)
        etop = cy - end_total / 2
        for i, sh in enumerate(shares):
            h0 = src_h * sh
            h1 = max(20, span * 0.78 * sh)
            y0, y1 = cursor, etop
            cursor += h0
            etop += h1 + gap
            ends.append((y1, h1))
            mx = (x0 + x1) / 2
            path = (f'M{x0:.0f} {y0:.1f} C {mx:.0f} {y0:.1f} {mx:.0f} {y1:.1f} '
                    f'{x1:.0f} {y1:.1f} L{x1:.0f} {y1 + h1:.1f} C {mx:.0f} '
                    f'{y1 + h1:.1f} {mx:.0f} {y0 + h0:.1f} {x0:.0f} {y0 + h0:.1f} Z')
            out += f'<path d="{path}" fill="url(#{uid}r{i})" opacity="0.9"/>'
        out += (f'<rect x="{x0 - 20:.0f}" y="{cy - src_h / 2:.0f}" '
                f'width="{18 if big else 14}" height="{src_h:.0f}" rx="4" '
                f'fill="{p["hot"]}" opacity="0.92"/>')
        out += txt(x0 - 20, cy - src_h / 2 - 20, s.head.upper(), 14 if big else 11.5,
                   p["dim"], 700, MONO, ls=2.6)
        for i, (y1, h1) in enumerate(ends):
            out += (f'<rect x="{x1 - 3:.0f}" y="{y1:.1f}" width="6" height="{h1:.1f}" '
                    f'fill="{p["hot"] if i == 0 else p["dim"]}" opacity="0.9"/>')
            out += txt_fit(x1 + 18, y1 + h1 / 2 + label * 0.34, s.items[i],
                           x + w - x1 - 26, label, MIN_LABEL,
                           p["ink"] if i == 0 else p["dim"], 700, SANS)
            if s.weights:
                out += txt(x1 + 18, y1 + h1 / 2 + label * 1.45,
                           f"{shares[i] * 100:.0f}%", label * 0.62,
                           p["accent"] if i == 0 else p["faint"], 600, MONO)
        return out


class ChapterPlate(Direction):
    """A magazine chapter opener. The numeral is cropped by the frame on purpose."""

    key = "plate"
    name = "Chapter plate"
    bleeds = True
    fits = "pillar and hub articles that should stand out in the feed"

    def background(self, p, uid, big, box):
        cx = box[0] + box[2] * 0.5 + variant(p["ink"] + str(big), "platex", (-90, 0, 90))
        cy = box[1] + box[3] * 0.55
        d = (f'<linearGradient id="{uid}f" x1="0.1" y1="0" x2="0.9" y2="1">'
             f'<stop offset="0" stop-color="{p["lift"]}"/>'
             f'<stop offset="0.55" stop-color="{p["mid"]}"/>'
             f'<stop offset="1" stop-color="{p["deep"]}"/></linearGradient>'
             f'<radialGradient id="{uid}hot" cx="0.5" cy="0.5" r="0.5">'
             f'<stop offset="0" stop-color="{p["accent"]}" stop-opacity="0.5"/>'
             f'<stop offset="1" stop-color="{p["accent"]}" stop-opacity="0"/>'
             f'</radialGradient>'
             f'<filter id="{uid}grain2" x="0" y="0" width="100%" height="100%">'
             f'<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" '
             f'seed="3" result="n"/><feColorMatrix in="n" type="saturate" values="0"/>'
             f'</filter>')
        b = (f'<rect width="{W}" height="{H}" fill="url(#{uid}f)"/>'
             f'<ellipse cx="{cx}" cy="{cy}" rx="520" ry="430" fill="url(#{uid}hot)"/>'
             f'<rect width="{W}" height="{H}" filter="url(#{uid}grain2)" opacity="0.06"/>')
        return d, b

    def motif(self, p, uid, s, box, big):
        n = s.n or 3
        head = s.head.upper()
        if big:
            out = txt(880, 640, f"{n}", 700, p["ink"], 700, SERIF, anchor="middle",
                      op=0.16)
            out += txt(COVER_PAD, 300, f"{n}", 210, p["ink"], 700, SERIF)
            wnum = text_width(str(n), 210, SERIF, 700)
            lx = COVER_PAD + wnum + 26
            if head.startswith("COMPARED"):
                out += txt(lx, 276, "COMPARED", 34, p["hot"], 700, MONO, ls=3)
            else:
                out += txt(lx, 250, head, 34, p["hot"], 700, MONO, ls=3)
                out += txt(lx, 300, "COMPARED", 34, p["dim"], 700, MONO, ls=3)
            # However many items fit the line whole. Three short names read as a
            # list; three statements read as one sentence cut off, so the count
            # gives way before the text does — and where the items are statements
            # rather than names, the line is dropped rather than started.
            room = W - 2 * COVER_PAD
            listed = ""
            if s.named:
                for take in (3, 2, 1):
                    candidate = " · ".join(s.items[:take])
                    if (len(candidate) <= MAX_LABEL
                            and text_width(candidate, 30, SANS, 500) <= room):
                        listed = candidate
                        break
            if listed:
                out += txt_fit(COVER_PAD, 400, listed, room, 30, MIN_LABEL,
                               p["dim"], 500, SANS, op=0.9)
            out += (f'<line x1="{COVER_PAD}" y1="452" x2="{COVER_PAD + 216}" y2="452" '
                    f'stroke="{p["accent"]}" stroke-width="6"/>')
            return out
        return txt(1010, 560, f"{n}", 560, p["ink"], 700, SERIF, anchor="middle",
                   op=0.13)

    def hero(self, subject, p, uid):
        s = subject.truncated(self.hero_items, self.hero_maxlen)
        box, title_x, centre = self.hero_layout(subject.key)
        d, g = self.background(p, uid, False, box)
        body = g + self.motif(p, uid, s, box, False)
        size, lines = fit(subject.title, 620, SERIF, 52, 32, max_lines=3)
        y = centre - (len(lines) - 1) * int(size * 1.22) // 2
        body += txt(72, 92, subject.kicker, 11.5, p["hot"], 700, MONO, ls=2.6)
        for line in lines:
            body += txt(72, y, line, size, p["ink"], 700, SERIF)
            y += int(size * 1.22)
        body += (f'<line x1="72" y1="{y + 18}" x2="152" y2="{y + 18}" '
                 f'stroke="{p["accent"]}" stroke-width="4"/>')
        head = s.head.upper()
        body += txt(72, y + 58, f"{s.n} COMPARED" if head.startswith("COMPARED")
                    else f"{head}  ·  {s.n} COMPARED", 13, p["dim"], 600, MONO, ls=2.4)
        return svg(d, body + wordmark(p))


class TierLadder(Direction):
    """A staircase in perspective: options that have an order, not just a list."""

    key = "ladder"
    name = "Tier ladder"
    fits = "levels, tiers, stages or anything with a natural order"
    #: Lower than the shared ceiling: a step label is centred over its own tread
    #: with a neighbour either side, so a name that runs long has nowhere to go.
    cover_maxlen = 26
    hero_maxlen = 38

    def defs(self, p, uid, s, big):
        return (shadow_def(uid, dy=14, blur=16, op=0.5)
                + f'<linearGradient id="{uid}st" x1="0" y1="0" x2="1" y2="0">'
                  f'<stop offset="0" stop-color="{p["accent"]}" stop-opacity="0.95"/>'
                  f'<stop offset="1" stop-color="{p["hot"]}" stop-opacity="0.35"/>'
                  f'</linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = s.n
        label = 32 if big else 19
        sw = w / (n + 0.9)
        # Two lines of label plus air have to fit above the tallest step, or the top
        # label is shifted down onto the lit panel — the one bright surface in the
        # picture, and the worst possible ground for white type.
        band = label * 3.6 + 30
        lift = abs(math.tan(math.radians(max(9, 9))) * w / 2)
        rise = min(h / (n + 1.6), (h - band - lift) / (n + 0.15))
        skew = variant(s.key, "skew", (-9, -7, -5))
        # Skew about the middle of the box rather than its left edge. Skewing from
        # the edge lifts the far side by the full width times the slope, which is
        # what pushed the tallest step's label out of the frame and then, once it was
        # shifted back in, onto the step itself.
        mid = w / 2
        out = (f'<g transform="translate({x + mid:.0f} {y:.0f}) skewY({skew}) '
               f'translate({-mid:.0f} 0)">')
        for i in range(n - 1, -1, -1):
            k = n - 1 - i
            bx = k * sw
            bh = rise * (k + 1.15)
            by = h - bh
            top = (i == 0)
            out += (f'<rect x="{bx:.0f}" y="{by:.0f}" width="{sw * 0.94:.0f}" '
                    f'height="{bh:.0f}" rx="6" '
                    f'fill="{f"url(#{uid}st)" if top else p["mid"]}" '
                    f'opacity="{1 if top else 0.9}"/>')
            out += (f'<rect x="{bx:.0f}" y="{by:.0f}" width="{sw * 0.94:.0f}" '
                    f'height="9" rx="4" fill="{p["hot"]}" '
                    f'opacity="{0.9 if top else 0.35}"/>')
        out += "</g>"
        # Every step label is set at one size, decided by the longest of them. The
        # label is centred on its own step and stays there: sliding it sideways to
        # keep it in frame pushed the outer labels into their neighbours, so its
        # width is cut to whatever the frame leaves on the narrower side instead.
        rooms = []
        for i in range(n):
            cxi = x + (n - 1 - i) * sw + sw * 0.47
            rooms.append(min(sw * 0.96, 2 * min(cxi - x, x + w - cxi)))
        size, wrapped = fit_all(s.items[:n], rooms, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            k = n - 1 - i
            bx = x + k * sw + sw * 0.47
            # Labels are drawn outside the skewed group, so where the step's top
            # edge actually ended up has to be worked out here. This used to assume
            # a fixed slope while the skew varies per post, which left the label
            # standing on the step for every value but the middle one.
            by = (y + h - rise * (k + 1.15)
                  + (bx - x - mid) * math.tan(math.radians(skew)))
            # A step label is centred over its own tread and the steps are close
            # together, so its room is roughly one step wide and two lines tall.
            # Sizing the type to that keeps a longer name whole; anything past two
            # lines at the smallest size is trimmed rather than allowed to run into
            # the label on the next step.
            lines = wrapped[i]
            half = max(text_width(ln, size, SANS, 700) for ln in lines) / 2
            # A label centred on its own step still reaches over the step beside it,
            # and the one to the right is always the taller. So it clears the highest
            # edge under its whole width, not only the edge of the step it names.
            ceiling = by
            for kk in (k, k + 1):
                if kk >= n:
                    continue
                left, right = x + kk * sw, x + kk * sw + sw * 0.94
                if bx + half > left and bx - half < right:
                    reach = min(bx + half, right) - x
                    ceiling = min(ceiling, y + h - rise * (kk + 1.15)
                                  + (reach - mid) * math.tan(math.radians(skew)))
            top = ceiling - 30 - (len(lines) - 1) * size * 1.12
            shift = max(0.0, (y + size) - top)
            for j, line in enumerate(lines):
                out += txt(bx, top + shift + j * size * 1.12, line,
                           size, p["ink"] if i == 0 else p["dim"], 700, SANS,
                           anchor="middle", op=1 if i == 0 else 0.85)
        return out


class OrbitSystem(Direction):
    """A lit core with satellites: a structure, rather than a list of choices."""

    key = "orbit"
    name = "Orbit"
    fits = "a structure with a centre: networks, hierarchies, ecosystems"
    #: Fewer and shorter than the shared ceiling. A satellite label runs outward from
    #: its dot, so the ring's own diameter is the whole budget: four long names have
    #: no arrangement that keeps them off each other and off the lit core.
    cover_items = 3
    cover_maxlen = 24
    hero_box = (600, 90, 540, 500)

    def defs(self, p, uid, s, big):
        return (f'<radialGradient id="{uid}core" cx="0.5" cy="0.5" r="0.5">'
                f'<stop offset="0" stop-color="{p["hot"]}"/>'
                f'<stop offset="0.6" stop-color="{p["accent"]}"/>'
                f'<stop offset="1" stop-color="{p["accent"]}" stop-opacity="0.25"/>'
                f'</radialGradient>'
                f'<filter id="{uid}soft"><feGaussianBlur stdDeviation="10"/></filter>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        cx, cy = x + w * 0.52, y + h * 0.5
        # The ring is set in from the frame so a satellite has room for its name
        # outside it: the label runs outward, so the gap to the edge is its budget.
        rx, ry = w * 0.27, h * 0.34
        label = 30 if big else 18
        rnd = seedof(s.key)
        tip = variant(s.key, "tip", (-26, -16, -6, 8))
        out = ""
        for k in (1.0, 0.72, 0.45):
            out += (f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rx * k:.0f}" '
                    f'ry="{ry * k:.0f}" fill="none" stroke="{p["faint"]}" '
                    f'stroke-opacity="0.4" stroke-width="1.5" '
                    f'transform="rotate({tip} {cx:.0f} {cy:.0f})"/>')
        out += (f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{min(rx, ry) * 0.62:.0f}" '
                f'fill="{p["accent"]}" opacity="0.22" filter="url(#{uid}soft)"/>')
        out += (f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{min(rx, ry) * 0.30:.0f}" '
                f'fill="url(#{uid}core)"/>')
        out += txt(cx, cy + label * 0.34, clip(s.head, 10).upper(), label * 0.62, p["deep"],
                   800, MONO, anchor="middle", ls=1.4)
        # Satellites are evenly spaced, but where the ring starts decides whether two
        # labels print across each other. So the start angle is chosen rather than
        # taken: candidates are tried in a fixed order and scored on the labels they
        # would actually produce, not on the angles.
        def layout(start):
            spots, boxes = [], []
            for i in range(s.n):
                a = math.radians(start + i * (360.0 / s.n))
                # Only a crowded ring needs an inner lane. With three satellites the
                # inner one sits close enough to the middle that its label runs back
                # across the lit core, so all three stay on the outer ring.
                k = [1.0, 0.78, 1.0, 0.78][i % 4] if s.n > 3 else 1.0
                ex = cx + rx * k * math.cos(a) * 0.96
                ey = cy + ry * k * math.sin(a) * 0.96
                dot = (13 if big else 9) * (1.45 if i == 0 else 1.0)
                wide = text_width(s.items[i], label, SANS, 700)
                # Always outward, away from the middle. Turning a long label inward
                # to keep it in frame is what sent it back across the lit core; the
                # label is sized to the room it has instead, which is what `txt_fit`
                # is for.
                lead = "start" if ex >= cx else "end"
                off = dot + 14 if lead == "start" else -(dot + 14)
                x0 = ex + off if lead == "start" else ex + off - wide
                spots.append((ex, ey, lead, off))
                boxes.append((x0, ey - label * 0.8, x0 + wide, ey + label * 0.4))
            # The core is a lit disc with its own label, and a satellite reaching
            # inward prints straight across both, so it takes part in the scoring
            # like the rest. Its glow is the wider of the two and sets the size.
            core = max(text_width(clip(s.head, 10).upper(), label * 0.62, MONO, 800),
                       min(rx, ry) * 1.24)
            boxes.append((cx - core / 2, cy - min(rx, ry) * 0.62,
                          cx + core / 2, cy + min(rx, ry) * 0.62))
            return spots, boxes

        def collisions(boxes):
            bad = 0.0
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    ow = min(a[2], b[2]) - max(a[0], b[0])
                    oh = min(a[3], b[3]) - max(a[1], b[1])
                    if ow > 0 and oh > 0:
                        bad += ow * oh
            return bad

        start = min(range(-180, 180, 5),
                    key=lambda a: (collisions(layout(a)[1]), abs(a)))
        spots, _boxes = layout(start)
        for i in range(s.n):
            ex, ey, anchor, off = spots[i]
            dot = (13 if big else 9) * (1.45 if i == 0 else 1.0)
            col = p["hot"] if i == 0 else p["dim"]
            out += (f'<circle cx="{ex:.0f}" cy="{ey:.0f}" r="{dot * 2.4:.0f}" '
                    f'fill="{col}" opacity="0.16" filter="url(#{uid}soft)"/>')
            out += f'<circle cx="{ex:.0f}" cy="{ey:.0f}" r="{dot:.0f}" fill="{col}"/>'
            # The side each label takes was decided with the start angle, above,
            # because it is part of what makes two labels collide.
            room = (x + w - (ex + off)) if anchor == "start" else (ex + off - x)
            out += txt_fit(ex + off, ey + label * 0.34, s.items[i], max(room, 60),
                           label, MIN_LABEL,
                           p["ink"] if i == 0 else p["dim"], 700, SANS, anchor=anchor)
        return out


class SplitPanels(Direction):
    """Colour fields, one per option. On the cover the panels bleed by design."""

    key = "split"
    name = "Split panels"
    bleeds = True
    fits = "a two- or three-way comparison, loudest at card size"
    cover_items = 3
    hero_items = 3
    hero_box = (600, 78, 552, 520)

    def defs(self, p, uid, s, big):
        d = ""
        for i in range(min(3, max(1, s.n))):
            a = p["accent"] if i == 0 else p["mid"]
            b = p["lift"] if i == 0 else p["deep"]
            d += (f'<linearGradient id="{uid}p{i}" x1="0" y1="0" x2="0.4" y2="1">'
                  f'<stop offset="0" stop-color="{a}" stop-opacity="{0.9 if i == 0 else 1}"/>'
                  f'<stop offset="1" stop-color="{b}"/></linearGradient>')
        return d

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        n = min(3, s.n)
        x, y, w, h = (0, 0, W, H) if big else box
        pw = w / n
        out = ""
        lit = variant(s.key, "lit", (0, 0, n - 1))
        for i in range(n):
            px = x + i * pw
            out += (f'<rect x="{px:.0f}" y="{y:.0f}" width="{pw + 1:.0f}" '
                    f'height="{h:.0f}" rx="{0 if big else 10}" '
                    f'fill="url(#{uid}p{0 if i == lit else 1})"/>')
            if i:
                out += (f'<line x1="{px:.0f}" y1="{y:.0f}" x2="{px:.0f}" '
                        f'y2="{y + h:.0f}" stroke="{p["hot"]}" stroke-opacity="0.45" '
                        f'stroke-width="2"/>')
        for i in range(n):
            cx = x + i * pw + pw / 2
            size, lines = fit(s.items[i], pw - (56 if big else 30), SANS,
                              58 if big else 34, MIN_LABEL if big else 11,
                              max_lines=4 if big else 5)
            ly = y + h / 2 - (len(lines) - 1) * int(size * 1.12) // 2
            out += txt(cx, ly - size * 1.6, f"{i + 1:02d}", max(size * 0.36, 12),
                       p["deep"] if i == lit else p["dim"], 700, MONO,
                       anchor="middle", ls=2)
            for line in lines:
                out += txt(cx, ly, line, size, p["deep"] if i == lit else p["ink"],
                           800, SANS, anchor="middle")
                ly += int(size * 1.12)
        return out


class GlassPanels(Direction):
    """Frosted sheets at an angle: the product-and-platform read."""

    key = "glass"
    name = "Frosted glass"
    fits = "tools, platforms, dashboards and anything software-shaped"

    def defs(self, p, uid, s, big):
        return (shadow_def(uid, dy=18, blur=22, op=0.45)
                + f'<linearGradient id="{uid}gl" x1="0" y1="0" x2="0.7" y2="1">'
                  f'<stop offset="0" stop-color="{p["hot"]}" stop-opacity="0.22"/>'
                  f'<stop offset="1" stop-color="{p["accent"]}" stop-opacity="0.06"/>'
                  f'</linearGradient>'
                  f'<linearGradient id="{uid}gf" x1="0" y1="0" x2="0.7" y2="1">'
                  f'<stop offset="0" stop-color="{p["hot"]}" stop-opacity="0.42"/>'
                  f'<stop offset="1" stop-color="{p["accent"]}" stop-opacity="0.16"/>'
                  f'</linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 30 if big else 19

        # The sheets fan up and to the right, each one a full step above the sheet in
        # front of it, so every sheet keeps a clear band along its own top edge. Its
        # name goes in that band and nowhere else: a sheet the reader can see and a
        # name they can read are the same object, which is the whole idea of the
        # motif. Two earlier versions lost that. Tilting each name plate about its
        # own sheet's centre moved every plate by a different amount and slid them
        # into one another; answering that by lifting the names out into one shared
        # column fixed the collisions and broke the meaning, because four bars
        # spanning four sheets belong to none of them.
        chip = label * 2.2
        step_y = chip + (14 if big else 10)
        pw = w * (0.55 if big else 0.64)
        step_x = (w - pw) / max(1, n - 1)
        # The whole arrangement is tilted at the end, and a tilt lifts whatever is
        # furthest from the middle: at this width the top chip rose clean out of the
        # cover's safe area. So the stack gives that lift back before it is laid out.
        tilt = variant(s.key, "spin", (-3, -2, 2, 3))
        lift = abs(math.sin(math.radians(tilt))) * w / 2
        ph = h - (n - 1) * step_y - 2 * lift

        # One type size for every name, set by the longest, so the sheets read as a
        # set rather than as four unrelated cards.
        room = pw - 40 - label * 1.7
        size, wrapped = fit_all(s.items[:n], room, SANS, label * 0.92, MIN_LABEL,
                                max_lines=1, weight=700)

        sheets, chips = "", ""
        for i in range(n - 1, -1, -1):
            px = x + i * step_x
            py = y + lift + (n - 1 - i) * step_y
            front = (i == 0)
            sheets += (f'<g filter="url(#{uid}sh)"><rect x="{px:.0f}" y="{py:.0f}" '
                       f'width="{pw:.0f}" height="{ph:.0f}" rx="22" '
                       f'fill="url(#{uid}{"gf" if front else "gl"})"/></g>'
                       f'<rect x="{px:.0f}" y="{py:.0f}" width="{pw:.0f}" '
                       f'height="{ph:.0f}" rx="22" fill="none" stroke="{p["hot"]}" '
                       f'stroke-opacity="{0.55 if front else 0.25}" '
                       f'stroke-width="1.5"/>')
            # The chip hugs its own name rather than running the width of the sheet,
            # so it reads as a tag on that sheet instead of a bar across the picture.
            line = wrapped[i][0] if wrapped[i] else ""
            cw = min(pw - 24, label * 1.7 + text_width(line, size, SANS, 700) + 36)
            cx, cy = px + 20, py + (step_y - chip) / 2
            chips += (f'<rect x="{cx:.0f}" y="{cy:.0f}" width="{cw:.0f}" '
                      f'height="{chip:.0f}" rx="{chip / 2:.0f}" fill="{p["deep"]}" '
                      f'opacity="{0.95 if front else 0.88}"/>'
                      + txt(cx + 20, cy + chip * 0.62, f"{i + 1:02d}", label * 0.5,
                            p["hot"] if front else p["faint"], 700, MONO, ls=1.5)
                      + txt(cx + 20 + label * 1.7, cy + chip * 0.62, line, size,
                            p["ink"], 700, SANS, op=1 if front else 0.92))

        # One tilt for the whole arrangement, about the middle of the box, so the
        # sheets and the names they carry move together.
        return (f'<g transform="rotate({tilt} {x + w / 2:.0f} {y + h / 2:.0f})">'
                f'{sheets}{chips}</g>')


class ScreeningGrid(Direction):
    """Many considered, a few lit: the shortlist read."""

    key = "grid"
    name = "Screening grid"
    fits = "picking a few out of a large field: broker shortlists, screening"

    def defs(self, p, uid, s, big):
        return f'<filter id="{uid}soft2"><feGaussianBlur stdDeviation="12"/></filter>'

    def motif(self, p, uid, s, box, big):
        x, y, w, h = box
        cols = (11 if big else 8) + variant(s.key, "cols", (-2, 0, 2))
        rows = 6 + variant(s.key, "rows", (-1, 0, 1))
        gap = 10 if big else 8
        tw = (w - gap * (cols - 1)) / cols
        th = (h - gap * (rows - 1)) / rows
        rnd = seedof(s.key)
        n = max(2, min(4, s.n))
        label = 40
        lines = s.items[:3] if (big and s.n) else []
        yy = y + h * 0.5 - (max(len(lines), 1) - 1) * label * 0.72
        # The plate's footprint, plus the air it needs, is known before the field is
        # drawn — so a lit tile is never chosen there. Picking tiles blind is what
        # put a highlight against the plate's edge and another behind a word.
        plate = (x - 12 - BREATH, yy - label * 1.5 - BREATH,
                 x - 12 + w * 0.56 + BREATH,
                 yy - label * 1.5 + len(lines) * label * 1.44 + 60 + BREATH)

        def clear(r, c):
            if not lines:
                return True
            tx, ty = x + c * (tw + gap), y + r * (th + gap)
            return not (tx < plate[2] and tx + tw > plate[0]
                        and ty < plate[3] and ty + th > plate[1])

        free = [(r, c) for r in range(rows) for c in range(cols) if clear(r, c)]
        picks = set()
        for i in range(min(n, len(free))):
            picks.add(free[(rnd >> (i * 5 + 1)) % len(free)])
        out = ""
        for r in range(rows):
            for c in range(cols):
                tx = x + c * (tw + gap)
                ty = y + r * (th + gap)
                lit = (r, c) in picks
                if lit:
                    out += (f'<rect x="{tx:.0f}" y="{ty:.0f}" width="{tw:.0f}" '
                            f'height="{th:.0f}" rx="8" fill="{p["accent"]}" '
                            f'opacity="0.25" filter="url(#{uid}soft2)"/>')
                out += (f'<rect x="{tx:.0f}" y="{ty:.0f}" width="{tw:.0f}" '
                        f'height="{th:.0f}" rx="8" '
                        f'fill="{p["hot"] if lit else p["mid"]}" '
                        f'opacity="{0.95 if lit else 0.30 + ((rnd >> (r * 3 + c)) % 4) * 0.05}"/>')
        if lines:
            out += (f'<rect x="{x - 12:.0f}" y="{yy - label * 1.5:.0f}" '
                    f'width="{w * 0.56:.0f}" '
                    f'height="{len(lines) * label * 1.44 + 60:.0f}" rx="16" '
                    f'fill="{p["deep"]}" opacity="0.82"/>')
            out += txt(x + 20, yy - label * 0.6, f"{s.n} SHORTLISTED", label * 0.42,
                       p["hot"], 700, MONO, ls=3)
            for i, item in enumerate(lines):
                out += txt_fit(x + 20, yy + label * 0.9 + i * label * 1.4, item,
                               w * 0.56 - 44, label, MIN_LABEL,
                               p["ink"] if i == 0 else p["dim"], 700, SANS)
        return out


class GaugeCluster(Direction):
    """An instrument cluster. Needles move only when the source had numbers."""

    key = "gauge"
    name = "Gauge cluster"
    fits = "scores, ranges and rates — strongest when the article has figures"
    hero_items = 3
    cover_items = 3

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(3, s.n)
        r = min(w / (n * 2.5), h * 0.30)
        cy = y + h * 0.46
        total = sum(s.weights[:n]) if s.weights else None
        out = ""
        for i in range(n):
            cx = x + w * (i + 0.5) / n
            frac = (s.weights[i] / total) if total else (0.72 - i * 0.18)
            span = variant(s.key, "sweep", (230, 250, 280))
            start = variant(s.key, "start", (135, 145, 155))
            out += self._arc(cx, cy, r, start, start + span, p["mid"], r * 0.24, 1)
            out += self._arc(cx, cy, r, start, start + span * frac,
                             p["hot"] if i == 0 else p["accent"], r * 0.24,
                             1 if i == 0 else 0.75)
            centre = f"{frac * 100:.0f}%" if total else f"{i + 1:02d}"
            out += txt(cx, cy + r * 0.17, centre, r * (0.52 if total else 0.5),
                       p["ink"] if i == 0 else p["dim"], 800, MONO, anchor="middle")
            for k, line in enumerate(wrap(s.items[i], w / n - 24, 26 if big else 16,
                                          SANS, 700, 2)):
                out += txt(cx, cy + r * 1.5 + k * (30 if big else 19), line,
                           26 if big else 16, p["ink"] if i == 0 else p["dim"], 700,
                           SANS, anchor="middle")
        out += txt(x + w / 2, y + (40 if big else 26), s.head.upper(),
                   20 if big else 13, p["hot"], 700, MONO, anchor="middle", ls=3.4)
        return out

    @staticmethod
    def _arc(cx, cy, r, deg0, deg1, col, width, op):
        a0, a1 = math.radians(deg0), math.radians(deg1)
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        large = 1 if (deg1 - deg0) > 180 else 0
        return (f'<path d="M{x0:.1f} {y0:.1f} A{r:.0f} {r:.0f} 0 {large} 1 '
                f'{x1:.1f} {y1:.1f}" fill="none" stroke="{col}" '
                f'stroke-width="{width:.1f}" stroke-linecap="round" opacity="{op}"/>')


class LedgerTape(Direction):
    """A printed slip — the field's own object, for anything about getting paid."""

    key = "tape"
    name = "Ledger tape"
    fits = "settlement, invoicing, thresholds, anything that ends in a payment"

    def defs(self, p, uid, s, big):
        return (shadow_def(uid, dy=20, blur=24, op=0.55)
                + f'<linearGradient id="{uid}pap" x1="0" y1="0" x2="0.3" y2="1">'
                  f'<stop offset="0" stop-color="{p["ink"]}" stop-opacity="0.97"/>'
                  f'<stop offset="1" stop-color="{p["dim"]}" stop-opacity="0.82"/>'
                  f'</linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        rowh = 64 if big else 46
        label = 28 if big else 20
        tw = min(w * (0.62 if big else 0.98), 600 if big else 500)
        th = min(h, 120 + n * rowh)
        tx = x + (w - tw) * (0.5 if big else 0.62)
        ty = y + (h - th) / 2
        zig = "".join(f"L{tx + i * (tw / 12):.0f} {ty + (8 if i % 2 else 0)} "
                      for i in range(13))
        zig2 = "".join(f"L{tx + tw - i * (tw / 12):.0f} {ty + th - (8 if i % 2 else 0)} "
                       for i in range(13))
        path = f"M{tx:.0f} {ty:.0f} {zig}L{tx + tw:.0f} {ty + th:.0f} {zig2}Z"
        lie = variant(s.key, "lie", (-5, -3, 2, 4))
        out = (f'<g transform="rotate({lie} {tx + tw / 2:.0f} {ty + th / 2:.0f})">'
               f'<g filter="url(#{uid}sh)"><path d="{path}" fill="url(#{uid}pap)"/></g>')
        out += txt(tx + 30, ty + 54, s.head.upper(), label * 0.62, p["deep"], 700,
                   MONO, ls=2.6)
        out += (f'<line x1="{tx + 30:.0f}" y1="{ty + 72:.0f}" x2="{tx + tw - 30:.0f}" '
                f'y2="{ty + 72:.0f}" stroke="{p["deep"]}" stroke-opacity="0.35" '
                f'stroke-width="2"/>')
        for i in range(n):
            ry = ty + 112 + i * rowh
            out += txt(tx + 30, ry, f"{i + 1:02d}", label * 0.66, p["accent"], 700, MONO)
            out += txt_fit(tx + 30 + label * 2.2, ry, s.items[i],
                           tw - 60 - label * 2.2, label, MIN_LABEL,
                           p["deep"], 700, SANS)
            out += (f'<line x1="{tx + 30:.0f}" y1="{ry + rowh * 0.34:.0f}" '
                    f'x2="{tx + tw - 30:.0f}" y2="{ry + rowh * 0.34:.0f}" '
                    f'stroke="{p["deep"]}" stroke-opacity="0.18" stroke-width="1.5" '
                    f'stroke-dasharray="2 7"/>')
        return out + "</g>"


DIRECTIONS = [CardStack(), MoneyFlow(), ChapterPlate(), TierLadder(), OrbitSystem(),
              SplitPanels(), GlassPanels(), ScreeningGrid(), GaugeCluster(),
              LedgerTape()]
BY_KEY = {d.key: d for d in DIRECTIONS}
