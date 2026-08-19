"""Candidate directions, not yet in `DIRECTIONS`.

Fifteen more answers to the question §7 of HEROART.md asks: *which way of seeing is
not yet in the set?* Each starts from a visual device — measured length, nested scale,
sequence along a line, attrition, two-axis position, derivation, physical quantity,
weighing, place, depth, a single instrument, an official record, a decision, a signal
over time, certification — and is bound to the same `Subject` every other direction
consumes.

They live apart from the shipping set until they have been looked at, because adding a
direction changes the assignment of every post in a corpus, not only the posts that
take the new motif.
"""
import math

from .constants import H, MONO, SANS, SERIF, W
from .directions import Direction
from .draw import (COVER_PAD, MIN_LABEL, clip, fit, fit_all, seedof, shadow_def,
                   text_width, txt, txt_fit, variant, wrap)


def _shares(s, n):
    """Proportions for n items: real when the subject carried numbers, else a gentle
    decreasing ramp. Never a fabricated quantity — the ramp is visibly a ranking, not
    a measurement, and directions that use it say so by labelling position, not value.
    """
    if s.weights and len(s.weights) >= n:
        total = sum(abs(v) for v in s.weights[:n]) or 1
        return [abs(v) / total for v in s.weights[:n]]
    ramp = [1.0 - 0.16 * i for i in range(n)]
    total = sum(ramp)
    return [v / total for v in ramp]


class MeasuredBars(Direction):
    """Length as the whole argument: how much of the thing each item accounts for."""

    key = "bars"
    name = "Measured bars"
    fits = "a comparison where one item is plainly bigger than the others"
    cover_items = 4
    hero_items = 4

    def defs(self, p, uid, s, big):
        return (f'<linearGradient id="{uid}bar" x1="0" y1="0" x2="1" y2="0">'
                f'<stop offset="0" stop-color="{p["accent"]}"/>'
                f'<stop offset="1" stop-color="{p["hot"]}"/></linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 34 if big else 21
        rowh = h / n
        bar = min(rowh * 0.34, 30 if big else 20)
        shares = _shares(s, n)
        peak = max(shares) or 1
        # Names sit above their own bar on the open ground; nothing is printed on a
        # lit surface, and the bar underneath is free to run the full width.
        gutter = w * 0.66
        size, wrapped = fit_all(s.items[:n], gutter, SANS, label, MIN_LABEL,
                                max_lines=1, weight=700)
        out = ""
        for i in range(n):
            ty = y + i * rowh + rowh * 0.34
            lit = (i == 0)
            out += txt(x, ty, wrapped[i][0] if wrapped[i] else "", size,
                       p["ink"] if lit else p["dim"], 700, SANS)
            if s.weights:
                out += txt(x + w, ty, f"{shares[i] * 100:.0f}%", size * 0.92,
                           p["hot"] if lit else p["faint"], 700, MONO, anchor="end")
            else:
                out += txt(x + w, ty, f"{i + 1:02d}", size * 0.82,
                           p["hot"] if lit else p["faint"], 700, MONO, anchor="end")
            by = ty + size * 0.5
            out += (f'<rect x="{x:.0f}" y="{by:.0f}" width="{w:.0f}" '
                    f'height="{bar:.0f}" rx="{bar / 2:.0f}" fill="{p["mid"]}" '
                    f'opacity="0.55"/>')
            out += (f'<rect x="{x:.0f}" y="{by:.0f}" '
                    f'width="{max(w * shares[i] / peak, bar):.0f}" '
                    f'height="{bar:.0f}" rx="{bar / 2:.0f}" '
                    f'fill="{f"url(#{uid}bar)" if lit else p["lift"]}" '
                    f'opacity="{1 if lit else 0.8}"/>')
        return out


class NestedRings(Direction):
    """Scope as containment: each ring holds everything the rings inside it hold."""

    key = "rings"
    name = "Nested rings"
    fits = "widening scope: what sits inside what, from narrowest to broadest"
    cover_items = 4
    hero_items = 4
    mirrorable = False

    def defs(self, p, uid, s, big):
        return (f'<radialGradient id="{uid}core" cx="0.5" cy="0.5" r="0.5">'
                f'<stop offset="0" stop-color="{p["hot"]}" stop-opacity="0.85"/>'
                f'<stop offset="1" stop-color="{p["accent"]}" stop-opacity="0.15"/>'
                f'</radialGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 30 if big else 19
        # The rings take the right of the frame and the names take the left, one per
        # row with a rule reaching across to its own ring. Names on a ring itself
        # would sit on a curve and collide with the ring outside it.
        col = w * 0.54
        cx, cy = x + w - h * 0.40, y + h / 2
        rmax = min(h * 0.46, w * 0.26)
        out = ""
        for i in range(n - 1, -1, -1):
            r = rmax * (1 - i * 0.19)
            out += (f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" '
                    f'fill="{p["mid"]}" opacity="{0.30 + 0.14 * (n - i)}"/>'
                    f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="none" '
                    f'stroke="{p["hot"] if i == 0 else p["faint"]}" '
                    f'stroke-opacity="{0.8 if i == 0 else 0.4}" stroke-width="2"/>')
        out += (f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{rmax * 0.20:.0f}" '
                f'fill="url(#{uid}core)"/>')
        size_gap = label * 1.9
        rowh = min(h / n, label * 3.0)
        top = cy - (n - 1) * rowh / 2
        size, wrapped = fit_all(s.items[:n], col - size_gap, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            ry = top + i * rowh
            out += txt(x, ry, f"{i + 1:02d}", size * 0.6, p["hot"] if i == 0
                       else p["faint"], 700, MONO, ls=1.4)
            for j, line in enumerate(wrapped[i]):
                out += txt(x + size_gap, ry + j * size * 1.1, line, size,
                           p["ink"] if i == 0 else p["dim"], 700, SANS)
        return out


class StationTrack(Direction):
    """A line with stops: the same journey every reader takes, in order."""

    key = "track"
    name = "Station track"
    fits = "an ordered run of stages a reader passes through once"
    cover_items = 4
    hero_items = 3

    def defs(self, p, uid, s, big):
        return (f'<linearGradient id="{uid}rail" x1="0" y1="0" x2="1" y2="0">'
                f'<stop offset="0" stop-color="{p["hot"]}"/>'
                f'<stop offset="1" stop-color="{p["faint"]}"/></linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 30 if big else 18
        ry = y + h / 2
        step = w / n
        dot = 15 if big else 10
        # Names alternate above and below the rail. Side by side they would need a
        # full station's width each; alternating gives each one two.
        out = (f'<rect x="{x:.0f}" y="{ry - 4:.0f}" width="{w:.0f}" height="8" rx="4" '
               f'fill="url(#{uid}rail)" opacity="0.75"/>')
        # A name centred on its stop must stay there: shifting it sideways to keep it
        # in frame walks it into the next stop's name. Its width gives way instead.
        rooms = [min(step * 1.55, 2 * min(x + step * (i + 0.5) - x,
                                          x + w - (x + step * (i + 0.5))))
                 for i in range(n)]
        size, wrapped = fit_all(s.items[:n], rooms, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            sx = x + step * (i + 0.5)
            up = (i % 2 == 0)
            lit = (i == 0)
            out += (f'<circle cx="{sx:.0f}" cy="{ry:.0f}" r="{dot * 1.9:.0f}" '
                    f'fill="{p["accent"] if lit else p["mid"]}" opacity="0.35"/>'
                    f'<circle cx="{sx:.0f}" cy="{ry:.0f}" r="{dot:.0f}" '
                    f'fill="{p["hot"] if lit else p["dim"]}"/>')
            lines = wrapped[i]
            base = (ry - dot * 2.6 - (len(lines) - 1) * size * 1.1 if up
                    else ry + dot * 2.6 + size)
            out += txt(sx, base - size * 1.5 if up else base + len(lines) * size * 1.1,
                       f"{i + 1:02d}", size * 0.6,
                       p["hot"] if lit else p["faint"], 700, MONO, anchor="middle")
            for j, line in enumerate(lines):
                out += txt(sx, base + j * size * 1.1, line, size,
                           p["ink"] if lit else p["dim"], 700, SANS, anchor="middle")
        return out


class NarrowingFunnel(Direction):
    """What survives each step: the shape is the attrition."""

    key = "funnel"
    name = "Narrowing funnel"
    fits = "a filter that removes candidates at every stage"
    cover_items = 4
    hero_items = 4
    mirrorable = False

    def defs(self, p, uid, s, big):
        return (f'<linearGradient id="{uid}fn" x1="0" y1="0" x2="0" y2="1">'
                f'<stop offset="0" stop-color="{p["lift"]}"/>'
                f'<stop offset="1" stop-color="{p["accent"]}"/></linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 34 if big else 20
        band = h / n
        wide = w * 0.36
        cx = x + wide / 2 + 10
        out = ""
        # Names run down the right of the funnel, one per band, so a slice never has
        # to carry text across its own sloping edge.
        col = x + wide + 56
        size, wrapped = fit_all(s.items[:n], x + w - col, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            top = y + i * band
            wt = wide * (1 - i * 0.19)
            wb = wide * (1 - (i + 1) * 0.19)
            out += (f'<path d="M{cx - wt / 2:.0f} {top:.0f} H{cx + wt / 2:.0f} '
                    f'L{cx + wb / 2:.0f} {top + band - 8:.0f} '
                    f'H{cx - wb / 2:.0f} Z" fill="url(#{uid}fn)" '
                    f'opacity="{0.95 - i * 0.16}"/>')
            lines = wrapped[i]
            base = top + band / 2 - (len(lines) - 1) * size * 0.56
            out += txt(col, base - size * 0.95, f"{i + 1:02d}", size * 0.6,
                       p["hot"] if i == 0 else p["faint"], 700, MONO, ls=1.4)
            for j, line in enumerate(lines):
                out += txt(col, base + j * size * 1.12, line, size,
                           p["ink"] if i == 0 else p["dim"], 700, SANS)
        return out


class QuadrantMatrix(Direction):
    """Two questions at once: where each thing falls on both axes."""

    key = "matrix"
    name = "Quadrant matrix"
    fits = "options that differ on two independent axes rather than on one scale"
    cover_items = 4
    hero_items = 4
    mirrorable = False

    def defs(self, p, uid, s, big):
        return (f'<radialGradient id="{uid}q" cx="0.5" cy="0.5" r="0.5">'
                f'<stop offset="0" stop-color="{p["hot"]}" stop-opacity="0.5"/>'
                f'<stop offset="1" stop-color="{p["accent"]}" stop-opacity="0"/>'
                f'</radialGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 28 if big else 18
        # The frame is 16:9 and the quadrants take all of it. A square matrix centred
        # in a wide frame leaves two dead margins and shrinks the names to fit a box
        # half the size of the one available.
        qw, qh = w / 2, h / 2
        ox, oy = x, y
        out = (f'<rect x="{ox:.0f}" y="{oy:.0f}" width="{w:.0f}" height="{h:.0f}" '
               f'rx="18" fill="{p["mid"]}" opacity="0.32"/>'
               f'<line x1="{ox + qw:.0f}" y1="{oy:.0f}" x2="{ox + qw:.0f}" '
               f'y2="{oy + h:.0f}" stroke="{p["hot"]}" stroke-width="2" '
               f'stroke-opacity="0.5"/>'
               f'<line x1="{ox:.0f}" y1="{oy + qh:.0f}" x2="{ox + w:.0f}" '
               f'y2="{oy + qh:.0f}" stroke="{p["hot"]}" stroke-width="2" '
               f'stroke-opacity="0.5"/>')
        # One name per quadrant, wrapped inside it. Four quadrants is exactly four
        # slots, which is why this direction never takes more than four items.
        spots = [(0, 0), (1, 0), (0, 1), (1, 1)]
        turn = variant(s.key, "quad", (0, 1, 2, 3))
        pad = 30
        size, wrapped = fit_all(s.items[:n], qw - pad * 2, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            col, row = spots[(i + turn) % 4]
            qx, qy = ox + col * qw, oy + row * qh
            lit = (i == 0)
            if lit:
                out += (f'<rect x="{qx + 3:.0f}" y="{qy + 3:.0f}" '
                        f'width="{qw - 6:.0f}" height="{qh - 6:.0f}" rx="14" '
                        f'fill="url(#{uid}q)"/>')
            lines = wrapped[i]
            base = qy + qh / 2 - (len(lines) - 1) * size * 0.56
            out += txt(qx + qw / 2, base - size * 1.25, f"{i + 1:02d}", size * 0.62,
                       p["hot"] if lit else p["faint"], 700, MONO, anchor="middle",
                       ls=1.4)
            for j, line in enumerate(lines):
                out += txt(qx + qw / 2, base + j * size * 1.12, line, size,
                           p["ink"] if lit else p["dim"], 700, SANS, anchor="middle")
        return out




class BranchSpine(Direction):
    """One trunk, several branches: what comes off what."""

    key = "tree"
    name = "Branch spine"
    fits = "things that all derive from one source: sub-types, offshoots, tiers of a scheme"
    cover_items = 4
    hero_items = 4

    def defs(self, p, uid, s, big):
        return (f'<linearGradient id="{uid}tr" x1="0" y1="0" x2="0" y2="1">'
                f'<stop offset="0" stop-color="{p["hot"]}"/>'
                f'<stop offset="1" stop-color="{p["accent"]}"/></linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 32 if big else 20
        trunk = x + w * 0.16
        rowh = h / n
        node = 16 if big else 10
        head = label * 1.6
        out = (f'<rect x="{trunk - 8:.0f}" y="{y + head:.0f}" width="16" '
               f'height="{h - head:.0f}" rx="5" fill="url(#{uid}tr)" opacity="0.9"/>')
        out += txt(trunk, y + head * 0.55, clip(s.head, 14).upper(), label * 0.52,
                   p["dim"], 700, MONO, anchor="middle", ls=2.4)
        col = x + w - (trunk + node * 3) - 10
        size, wrapped = fit_all(s.items[:n], col, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            cy = y + head + (h - head) / n * (i + 0.5)
            lit = (i == 0)
            # Each branch leaves the trunk on its own row and its name starts where
            # the branch ends, so no two names share a horizontal band.
            out += (f'<path d="M{trunk:.0f} {cy - rowh * 0.36:.0f} '
                    f'Q{trunk:.0f} {cy:.0f} {trunk + node * 3:.0f} {cy:.0f}" '
                    f'fill="none" stroke="{p["hot"] if lit else p["faint"]}" '
                    f'stroke-opacity="{0.9 if lit else 0.5}" stroke-width="3"/>'
                    f'<circle cx="{trunk + node * 3:.0f}" cy="{cy:.0f}" '
                    f'r="{node:.0f}" fill="{p["hot"] if lit else p["dim"]}"/>')
            lines = wrapped[i]
            base = cy - (len(lines) - 1) * size * 0.56 + size * 0.34
            for j, line in enumerate(lines):
                out += txt(trunk + node * 3 + 22, base + j * size * 1.12, line, size,
                           p["ink"] if lit else p["dim"], 700, SANS)
        return out


class TokenStacks(Direction):
    """Quantity you could pick up: how much of each, as a physical pile."""

    key = "coins"
    name = "Token stacks"
    fits = "amounts, balances and anything counted rather than ranked"
    #: Three columns, not four: a pile needs width to read as a pile, and the name
    #: under it needs the same width again.
    cover_items = 3
    hero_items = 3

    def defs(self, p, uid, s, big):
        return (f'<linearGradient id="{uid}cn" x1="0" y1="0" x2="1" y2="0">'
                f'<stop offset="0" stop-color="{p["accent"]}"/>'
                f'<stop offset="0.5" stop-color="{p["hot"]}"/>'
                f'<stop offset="1" stop-color="{p["accent"]}"/></linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 30 if big else 19
        colw = w / n
        shares = _shares(s, n)
        peak = max(shares) or 1
        disc = 21 if big else 13
        floor = y + h - label * 2.6
        out = ""
        # Names sit in a row under the piles, each inside its own column, so the
        # widest name can never reach the pile or the name beside it.
        size, wrapped = fit_all(s.items[:n], colw - 20, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            cx = x + colw * (i + 0.5)
            lit = (i == 0)
            count = max(2, round(8 * shares[i] / peak))
            rx = min(colw * 0.40, 92 if big else 52)
            for k in range(count):
                cy = floor - 16 - k * disc
                out += (f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rx:.0f}" '
                        f'ry="{disc * 0.62:.0f}" '
                        f'fill="{f"url(#{uid}cn)" if lit else p["lift"]}" '
                        f'opacity="{1 if lit else 0.62 + k * 0.02}"/>'
                        f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rx:.0f}" '
                        f'ry="{disc * 0.62:.0f}" fill="none" stroke="{p["deep"]}" '
                        f'stroke-opacity="0.35" stroke-width="1"/>')
            lines = wrapped[i]
            for j, line in enumerate(lines):
                out += txt(cx, floor + label * 0.9 + j * size * 1.1, line, size,
                           p["ink"] if lit else p["dim"], 700, SANS, anchor="middle")
        return out


class WeighingBeam(Direction):
    """A beam that hangs heavier on one side: the trade-off made physical."""

    key = "scale"
    name = "Weighing beam"
    fits = "a trade-off where the point is which side carries more"
    cover_items = 3
    hero_items = 3
    mirrorable = False

    def defs(self, p, uid, s, big):
        return shadow_def(uid, dy=12, blur=16, op=0.45)

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(3, s.n)
        label = 32 if big else 20
        shares = _shares(s, n)
        peak = max(shares) or 1
        cx = x + w / 2
        top = y + h * 0.16
        beam = w * 0.78
        tilt = variant(s.key, "beamtilt", (-4, -3, 3, 4))
        out = (f'<path d="M{cx:.0f} {top:.0f} L{cx - 22:.0f} {y + h - 20:.0f} '
               f'H{cx + 22:.0f} Z" fill="{p["mid"]}" opacity="0.7"/>'
               f'<g transform="rotate({tilt} {cx:.0f} {top:.0f})">'
               f'<rect x="{cx - beam / 2:.0f}" y="{top - 5:.0f}" width="{beam:.0f}" '
               f'height="10" rx="5" fill="{p["hot"]}" opacity="0.85"/></g>'
               f'<circle cx="{cx:.0f}" cy="{top:.0f}" r="{14 if big else 10}" '
               f'fill="{p["lift"]}"/>')
        colw = beam / n
        size, wrapped = fit_all(s.items[:n], colw - 16, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            px = cx - beam / 2 + colw * (i + 0.5)
            lit = (i == 0)
            drop = top + 40 + shares[i] / peak * (h * 0.26)
            pan = min(colw * 0.72, 150 if big else 96)
            out += (f'<line x1="{px:.0f}" y1="{top:.0f}" x2="{px:.0f}" '
                    f'y2="{drop:.0f}" stroke="{p["faint"]}" stroke-width="2"/>'
                    f'<g filter="url(#{uid}sh)"><path d="M{px - pan / 2:.0f} '
                    f'{drop:.0f} H{px + pan / 2:.0f} L{px + pan * 0.34:.0f} '
                    f'{drop + 26:.0f} H{px - pan * 0.34:.0f} Z" '
                    f'fill="{p["accent"] if lit else p["lift"]}" '
                    f'opacity="{1 if lit else 0.72}"/></g>')
            lines = wrapped[i]
            for j, line in enumerate(lines):
                out += txt(px, drop + 62 + j * size * 1.1, line, size,
                           p["ink"] if lit else p["dim"], 700, SANS, anchor="middle")
        return out


class PinField(Direction):
    """Scattered across a territory rather than ranked on a list."""

    key = "pins"
    name = "Field of pins"
    fits = "places, jurisdictions, venues — things spread out rather than ordered"
    cover_items = 3
    hero_items = 3

    def defs(self, p, uid, s, big):
        return (f'<radialGradient id="{uid}pin" cx="0.5" cy="0.35" r="0.6">'
                f'<stop offset="0" stop-color="{p["hot"]}"/>'
                f'<stop offset="1" stop-color="{p["accent"]}"/></radialGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 30 if big else 19
        colw = w / n
        rnd = seedof(s.key)
        # Contours behind, then one pin per column at a height of its own. Columns
        # are what keep the names apart; the varied heights are what stop the row
        # reading as a chart.
        out = ""
        for k in range(4):
            ry = y + h * (0.18 + k * 0.21)
            out += (f'<path d="M{x:.0f} {ry:.0f} Q{x + w * 0.28:.0f} '
                    f'{ry - 26 + k * 9:.0f} {x + w * 0.55:.0f} {ry + 8:.0f} '
                    f'T{x + w:.0f} {ry - 12:.0f}" fill="none" stroke="{p["faint"]}" '
                    f'stroke-opacity="0.6" stroke-width="2"/>')
        size, wrapped = fit_all(s.items[:n], colw - 18, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            cx = x + colw * (i + 0.5)
            lift = [0.30, 0.52, 0.24, 0.46][(i + rnd) % 4]
            py = y + h * lift
            lit = (i == 0)
            r = (26 if big else 15) * (1.22 if lit else 1)
            out += (f'<path d="M{cx:.0f} {py + r * 2.4:.0f} '
                    f'C{cx - r * 1.3:.0f} {py + r * 0.7:.0f} {cx - r:.0f} {py:.0f} '
                    f'{cx:.0f} {py:.0f} C{cx + r:.0f} {py:.0f} {cx + r * 1.3:.0f} '
                    f'{py + r * 0.7:.0f} {cx:.0f} {py + r * 2.4:.0f} Z" '
                    f'fill="{f"url(#{uid}pin)" if lit else p["dim"]}" '
                    f'opacity="{1 if lit else 0.72}"/>'
                    f'<circle cx="{cx:.0f}" cy="{py + r * 0.15:.0f}" '
                    f'r="{r * 0.34:.0f}" fill="{p["deep"]}" opacity="0.75"/>')
            lines = wrapped[i]
            for j, line in enumerate(lines):
                out += txt(cx, py + r * 3.6 + j * size * 1.1, line, size,
                           p["ink"] if lit else p["dim"], 700, SANS, anchor="middle")
        return out


class SteppedStrata(Direction):
    """Layers in section: what sits under what, cut open."""

    key = "strata"
    name = "Stepped strata"
    fits = "a stack of layers, from surface detail down to what underlies it"
    cover_items = 4
    hero_items = 4
    mirrorable = False

    def defs(self, p, uid, s, big):
        return (f'<linearGradient id="{uid}st" x1="0" y1="0" x2="1" y2="0">'
                f'<stop offset="0" stop-color="{p["accent"]}"/>'
                f'<stop offset="1" stop-color="{p["mid"]}"/></linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 32 if big else 20
        bandh = h / n
        inset = (w * 0.10) / max(1, n - 1)
        out = ""
        # Every layer starts further right than the one above, so each keeps a strip
        # of its own left edge clear. The name goes in that strip, on the layer it
        # belongs to and never on the layer below.
        size, wrapped = fit_all(s.items[:n], w * 0.72, SANS, label, MIN_LABEL,
                                max_lines=1, weight=700)
        for i in range(n):
            ly = y + i * bandh
            lx = x + i * inset
            lit = (i == 0)
            out += (f'<rect x="{lx:.0f}" y="{ly:.0f}" width="{x + w - lx:.0f}" '
                    f'height="{bandh - 8:.0f}" rx="10" '
                    f'fill="{f"url(#{uid}st)" if lit else p["mid"]}" '
                    f'opacity="{0.95 if lit else 0.72 - i * 0.10}"/>'
                    f'<rect x="{lx:.0f}" y="{ly:.0f}" width="{x + w - lx:.0f}" '
                    f'height="3" fill="{p["hot"]}" '
                    f'opacity="{0.8 if lit else 0.28}"/>')
            out += txt(lx + 24, ly + bandh * 0.42, f"{i + 1:02d}", size * 0.56,
                       p["deep"] if lit else p["faint"], 700, MONO, ls=1.5)
            out += txt(lx + 24 + size * 1.7, ly + bandh * 0.42,
                       wrapped[i][0] if wrapped[i] else "", size,
                       p["deep"] if lit else p["ink"], 700, SANS)
        return out


class SingleDial(Direction):
    """One instrument, read once: the reading is the headline."""

    key = "dial"
    name = "Single dial"
    fits = "one measure that matters, with the rest of the field as its scale"
    cover_items = 4
    hero_items = 4
    mirrorable = False

    def defs(self, p, uid, s, big):
        return (f'<linearGradient id="{uid}dl" x1="0" y1="1" x2="1" y2="0">'
                f'<stop offset="0" stop-color="{p["accent"]}"/>'
                f'<stop offset="1" stop-color="{p["hot"]}"/></linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 34 if big else 21
        shares = _shares(s, n)
        cx = x + w / 2
        cy = y + h * 0.58
        r = min(h * 0.40, w * 0.26)
        sweep = 220.0
        start = 180 + (180 - sweep) / 2

        def point(frac, radius):
            a = math.radians(start + sweep * frac)
            return cx + radius * math.cos(a), cy + radius * math.sin(a)

        out = ""
        for k in range(13):
            f0 = k / 12
            x0, y0 = point(f0, r)
            x1, y1 = point(f0, r * (0.86 if k % 3 else 0.78))
            out += (f'<line x1="{x0:.0f}" y1="{y0:.0f}" x2="{x1:.0f}" y2="{y1:.0f}" '
                    f'stroke="{p["faint"]}" stroke-opacity="{0.8 if k % 3 == 0 else 0.4}" '
                    f'stroke-width="{3 if k % 3 == 0 else 1.5}"/>')
        frac = min(max(shares[0] / (max(shares) or 1), 0.08), 0.96)
        ax, ay = point(frac, r * 1.02)
        bx, by = point(0, r * 1.02)
        big_arc = 1 if sweep * frac > 180 else 0
        out += (f'<path d="M{bx:.0f} {by:.0f} A{r * 1.02:.0f} {r * 1.02:.0f} 0 '
                f'{big_arc} 1 {ax:.0f} {ay:.0f}" fill="none" '
                f'stroke="url(#{uid}dl)" stroke-width="{16 if big else 11}" '
                f'stroke-linecap="round"/>')
        nx, ny = point(frac, r * 0.70)
        out += (f'<line x1="{cx:.0f}" y1="{cy:.0f}" x2="{nx:.0f}" y2="{ny:.0f}" '
                f'stroke="{p["ink"]}" stroke-width="4" stroke-linecap="round"/>'
                f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{13 if big else 9}" '
                f'fill="{p["hot"]}"/>')
        # The named reading sits under the dial's own pivot, where the face is empty;
        # the rest of the field is the scale, and a scale is numbers, not names.
        size, lines = fit(s.items[0], w * 0.62, SANS, label * 1.15, MIN_LABEL,
                          max_lines=2, weight=800)
        base = cy + (56 if big else 40) + size
        out += txt(cx, base - size * 1.35, clip(s.head, 14).upper(), size * 0.5,
                   p["dim"], 700, MONO, anchor="middle", ls=2.4)
        for j, line in enumerate(lines):
            out += txt(cx, base + j * size * 1.1, line, size, p["ink"], 800, SANS,
                       anchor="middle")
        out += txt(cx, y + h * 0.10, f"{n} ON THE SCALE", label * 0.44, p["faint"],
                   700, MONO, anchor="middle", ls=2.6)
        return out


class RecordCard(Direction):
    """An official record: fields on a document, filled in."""

    key = "passport"
    name = "Record card"
    fits = "checks, entries and anything read off a register or an agreement"
    cover_items = 4
    hero_items = 4
    mirrorable = False

    def defs(self, p, uid, s, big):
        return (shadow_def(uid, dy=20, blur=26, op=0.5)
                + f'<linearGradient id="{uid}pp" x1="0" y1="0" x2="0.6" y2="1">'
                  f'<stop offset="0" stop-color="{p["lift"]}"/>'
                  f'<stop offset="1" stop-color="{p["mid"]}"/></linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 30 if big else 19
        cw = min(w * 0.86, h * 1.62)
        ch = h * 0.92
        cx = x + (w - cw) / 2
        cy = y + (h - ch) / 2
        out = (f'<g filter="url(#{uid}sh)"><rect x="{cx:.0f}" y="{cy:.0f}" '
               f'width="{cw:.0f}" height="{ch:.0f}" rx="20" '
               f'fill="url(#{uid}pp)"/></g>'
               f'<rect x="{cx:.0f}" y="{cy:.0f}" width="{cw:.0f}" height="{ch:.0f}" '
               f'rx="20" fill="none" stroke="{p["hot"]}" stroke-opacity="0.4" '
               f'stroke-width="1.5"/>'
               f'<rect x="{cx:.0f}" y="{cy:.0f}" width="{cw:.0f}" '
               f'height="{ch * 0.20:.0f}" rx="20" fill="{p["deep"]}" '
               f'opacity="0.72"/>'
               f'<rect x="{cx:.0f}" y="{cy + ch * 0.14:.0f}" width="{cw:.0f}" '
               f'height="{ch * 0.06:.0f}" fill="{p["deep"]}" opacity="0.72"/>')
        out += txt(cx + 30, cy + ch * 0.13, clip(s.head, 22).upper(), label * 0.56,
                   p["hot"], 700, MONO, ls=3)
        rows = (ch * 0.80) / n
        # Every field sits on the card that backs it, which is the one surface in the
        # picture. The mono field number is the ruled line a form would print.
        size, wrapped = fit_all(s.items[:n], cw - 110, SANS, label, MIN_LABEL,
                                max_lines=1, weight=700)
        for i in range(n):
            ry = cy + ch * 0.20 + rows * (i + 0.62)
            out += txt(cx + 30, ry, f"{i + 1:02d}", size * 0.58, p["hot"], 700, MONO,
                       ls=1.5)
            out += txt(cx + 30 + size * 1.9, ry, wrapped[i][0] if wrapped[i] else "",
                       size, p["ink"] if i == 0 else p["dim"], 700, SANS)
            if i < n - 1:
                out += (f'<line x1="{cx + 30:.0f}" y1="{ry + rows * 0.34:.0f}" '
                        f'x2="{cx + cw - 30:.0f}" y2="{ry + rows * 0.34:.0f}" '
                        f'stroke="{p["deep"]}" stroke-opacity="0.28" '
                        f'stroke-width="1.5" stroke-dasharray="3 6"/>')
        return out


class CompassRose(Direction):
    """Four bearings from one point: which way each option pulls."""

    key = "compass"
    name = "Compass rose"
    fits = "options that pull in different directions rather than along one scale"
    cover_items = 4
    hero_items = 4
    mirrorable = False

    def defs(self, p, uid, s, big):
        return (f'<radialGradient id="{uid}rose" cx="0.5" cy="0.5" r="0.5">'
                f'<stop offset="0" stop-color="{p["hot"]}" stop-opacity="0.7"/>'
                f'<stop offset="1" stop-color="{p["accent"]}" stop-opacity="0"/>'
                f'</radialGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 30 if big else 19
        cx, cy = x + w / 2, y + h / 2
        arm = min(h * 0.20, w * 0.16)
        # Four fixed bearings, so the names have four homes that cannot collide:
        # above, below, and one on each side with the frame's whole width to use.
        homes = [(0, -1), (1, 0), (0, 1), (-1, 0)]
        turn = variant(s.key, "bearing", (0, 1, 2, 3))
        out = (f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{arm * 1.5:.0f}" '
               f'fill="url(#{uid}rose)"/>'
               f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{arm * 1.15:.0f}" fill="none" '
               f'stroke="{p["faint"]}" stroke-opacity="0.7" stroke-width="2.5"/>')
        # The budget has to allow for the offset the label is pushed out by, or a
        # west-facing name is measured against room it never gets.
        side = w / 2 - arm * 1.6 - 40
        sizes = []
        for i in range(n):
            dx, dy = homes[(i + turn) % 4]
            sizes.append(side if dx else w * 0.40)
        size, wrapped = fit_all(s.items[:n], sizes, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            dx, dy = homes[(i + turn) % 4]
            lit = (i == 0)
            tipx, tipy = cx + dx * arm, cy + dy * arm
            out += (f'<path d="M{cx:.0f} {cy:.0f} L{tipx - dy * 16:.0f} '
                    f'{tipy + dx * 16:.0f} L{cx + dx * arm * 1.45:.0f} '
                    f'{cy + dy * arm * 1.45:.0f} L{tipx + dy * 16:.0f} '
                    f'{tipy - dx * 16:.0f} Z" '
                    f'fill="{p["hot"] if lit else p["lift"]}" '
                    f'opacity="{1 if lit else 0.7}"/>')
            lines = wrapped[i]
            anchor = "middle" if dx == 0 else ("start" if dx > 0 else "end")
            lx = cx + dx * (arm * 1.6 + 30)
            block = (len(lines) - 1) * size * 1.12
            if dy == 0:
                ly = cy - block / 2 + size * 0.3
            else:
                ly = cy + dy * (arm * 1.6 + size * 1.5) - (block / 2 if dy < 0 else 0)
                # The cover box starts four pixels above the safe area, so a clamp
                # to the box alone leaves a north-facing name just outside it.
                ly = min(max(ly, y + size * 0.8 + 8),
                         y + h - block - size * 0.4)
            for j, line in enumerate(lines):
                out += txt(lx, ly + j * size * 1.12, line, size,
                           p["ink"] if lit else p["dim"], 700, SANS, anchor=anchor)
        out += (f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{12 if big else 8}" '
                f'fill="{p["deep"]}"/>')
        return out


class SignalRows(Direction):
    """The same stretch of time, once per option: shape, not size."""

    key = "pulse"
    name = "Signal rows"
    fits = "behaviour over time — how each option moves, not how big it is"
    cover_items = 4
    hero_items = 3

    def defs(self, p, uid, s, big):
        return (f'<linearGradient id="{uid}ps" x1="0" y1="0" x2="1" y2="0">'
                f'<stop offset="0" stop-color="{p["accent"]}" stop-opacity="0.2"/>'
                f'<stop offset="1" stop-color="{p["hot"]}"/></linearGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 30 if big else 19
        rowh = h / n
        gutter = w * 0.40
        rnd = seedof(s.key)
        out = ""
        # The name owns the left gutter and the trace owns the rest of the row, so a
        # long name shortens the trace rather than running across it.
        size, wrapped = fit_all(s.items[:n], gutter - 24, SANS, label, MIN_LABEL,
                                max_lines=1, weight=700)
        for i in range(n):
            ry = y + rowh * (i + 0.5)
            lit = (i == 0)
            out += txt(x, ry + size * 0.34, wrapped[i][0] if wrapped[i] else "", size,
                       p["ink"] if lit else p["dim"], 700, SANS)
            tx = x + gutter
            tw = x + w - tx
            amp = rowh * (0.30 if lit else 0.20)
            steps = 9
            pts = []
            for k in range(steps + 1):
                seed = (rnd >> ((i * 5 + k) % 40)) % 100
                pts.append((tx + tw * k / steps, ry - amp * (seed / 50 - 1)))
            path = "M" + " L".join(f"{px:.0f} {py:.0f}" for px, py in pts)
            out += (f'<line x1="{tx:.0f}" y1="{ry:.0f}" x2="{tx + tw:.0f}" '
                    f'y2="{ry:.0f}" stroke="{p["faint"]}" stroke-opacity="0.35" '
                    f'stroke-width="1.5" stroke-dasharray="3 7"/>'
                    f'<path d="{path}" fill="none" stroke="url(#{uid}ps)" '
                    f'stroke-width="{4 if lit else 2.5}" stroke-linejoin="round" '
                    f'opacity="{1 if lit else 0.65}"/>'
                    f'<circle cx="{pts[-1][0]:.0f}" cy="{pts[-1][1]:.0f}" '
                    f'r="{7 if lit else 5}" fill="{p["hot"] if lit else p["dim"]}"/>')
        return out


class SealRow(Direction):
    """Stamped and countersigned: a row of marks, one per thing checked."""

    key = "seal"
    name = "Seal row"
    fits = "approvals, licences and anything a body grants or withholds"
    cover_items = 4
    hero_items = 3

    def defs(self, p, uid, s, big):
        return (shadow_def(uid, dy=14, blur=18, op=0.45)
                + f'<radialGradient id="{uid}sl" cx="0.4" cy="0.35" r="0.7">'
                  f'<stop offset="0" stop-color="{p["hot"]}"/>'
                  f'<stop offset="1" stop-color="{p["accent"]}"/></radialGradient>')

    def motif(self, p, uid, s, box, big):
        if s.n < 2:
            return ""
        x, y, w, h = box
        n = min(4, s.n)
        label = 30 if big else 19
        colw = w / n
        r = min(colw * 0.36, h * 0.24)
        cy = y + h * 0.36
        out = ""
        size, wrapped = fit_all(s.items[:n], colw - 18, SANS, label, MIN_LABEL,
                                max_lines=2, weight=700)
        for i in range(n):
            cx = x + colw * (i + 0.5)
            lit = (i == 0)
            pts = []
            for k in range(20):
                a = math.radians(k * 18)
                rad = r * (1.0 if k % 2 == 0 else 0.90)
                pts.append(f"{cx + rad * math.cos(a):.0f} {cy + rad * math.sin(a):.0f}")
            out += (f'<g filter="url(#{uid}sh)"><polygon points="{" ".join(pts)}" '
                    f'fill="{f"url(#{uid}sl)" if lit else p["lift"]}" '
                    f'opacity="{1 if lit else 0.66}"/></g>'
                    f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r * 0.72:.0f}" '
                    f'fill="none" stroke="{p["deep"]}" stroke-opacity="0.45" '
                    f'stroke-width="2"/>')
            out += txt(cx, cy + r * 0.22, f"{i + 1:02d}", r * 0.62,
                       p["deep"] if lit else p["dim"], 800, MONO, anchor="middle")
            lines = wrapped[i]
            for j, line in enumerate(lines):
                out += txt(cx, cy + r + label * 1.5 + j * size * 1.1, line, size,
                           p["ink"] if lit else p["dim"], 700, SANS, anchor="middle")
        return out


PROPOSED = [MeasuredBars(), NestedRings(), StationTrack(), NarrowingFunnel(),
            QuadrantMatrix(), BranchSpine(), TokenStacks(), WeighingBeam(),
            PinField(), SteppedStrata(), SingleDial(), RecordCard(), CompassRose(),
            SignalRows(), SealRow()]
