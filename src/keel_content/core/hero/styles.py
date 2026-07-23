"""The five hero style painters.

Each style renders the same abstract motif (nodes / links / cards) in its own
visual language. A style is a swappable component: pick one per post. No blur or
drop-shadow filters anywhere (CWV) -- depth/glow come from gradients only.

    minimal      flat thin-line motif, maximal negative space (the baseline)
    isometric    motif as dimensional iso tiles
    infographic  motif as labeled boxes + arrows (explanatory)
    glow         gradient field + radial-gradient halos (premium)
    network      a faint signal-network field, one path lit up (atmospheric)
"""

from __future__ import annotations

from .chrome import base_background, cubic, esc
from .elements import Card, Link, Motif, Node
from .tokens import (
    BLUE, GREEN, GREEN_AA, NAVY_0, NAVY_1, NAVY_2, TEXT_MAIN, TEXT_SECONDARY, W, H,
)


def _bow(l: Link, kind: str) -> float:
    """Link curvature by motif: near-straight for a horizontal pipeline, a gentle arc otherwise."""
    if kind == "pipeline":
        return 14
    if kind == "hub_spokes":
        return 34
    return 28


def _label(cx: float, cy: float, text: str, fill: str, size: int = 19, weight: int = 700) -> str:
    return (
        f'<text x="{cx:.0f}" y="{cy + size * 0.34:.0f}" font-family="Manrope" font-weight="{weight}" '
        f'font-size="{size}" fill="{fill}" text-anchor="middle">{esc(text)}</text>'
    )


def _text(x: float, y: float, text: str, fill: str, size: int = 15, weight: int = 600, anchor: str = "middle") -> str:
    return (
        f'<text x="{x:.0f}" y="{y + size * 0.34:.0f}" font-family="Manrope" font-weight="{weight}" '
        f'font-size="{size}" fill="{fill}" text-anchor="{anchor}">{esc(text)}</text>'
    )


def _node_caption(n: Node, kind: str) -> str:
    """Place a node's content label where it reads cleanly for that motif."""
    if not n.label:
        return ""
    if kind == "pipeline":
        if n.role == "leaf":            # stacked inputs on the left → caption to their left
            return _text(n.x - 24, n.y, n.label, TEXT_SECONDARY, 15, 600, "end")
        col = GREEN_AA if n.role == "accent" else TEXT_MAIN
        return _text(n.x, n.y + (52 if n.role == "hub" else 64), n.label, col, 15, 700, "middle")
    if kind in ("hub_spokes", "nodes"):
        if n.role == "leaf":            # spokes on the right → caption to their right
            return _text(n.x + 24, n.y, n.label, TEXT_SECONDARY, 15, 600, "start")
        return _text(n.x, n.y - 40, n.label, TEXT_MAIN, 16, 700, "middle")
    if kind == "device_signal":
        return _text(n.x, n.y + 30, n.label, GREEN_AA, 15, 700, "middle")
    return ""


def _node_captions(m: Motif) -> str:
    return "".join(_node_caption(n, m.kind) for n in m.nodes)


def _connector(p1: tuple[float, float], p2: tuple[float, float], color: str = GREEN, *, dot: bool = True) -> str:
    """A straight connector between two anchor points, with a node at its midpoint.

    Endpoints come from a style's ``card_anchor`` so the line always lands on the
    real shape edges (correct position, source, destination, and length).
    """
    (x1, y1), (x2, y2) = p1, p2
    line = f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{color}" stroke-width="2.5"/>'
    node = f'<circle cx="{(x1 + x2) / 2:.0f}" cy="{(y1 + y2) / 2:.0f}" r="6" fill="{color}"/>' if dot else ""
    return line + node


class Style:
    key = "base"
    head = {"y0": 322, "lh": 74, "size": 62}
    baseline_y = 556

    def defs(self) -> str:
        return ""

    def background(self) -> str:
        return base_background()

    def card_anchor(self, c, side: str) -> tuple[float, float]:
        """Where a connector meets a card, as THIS style draws it (default: rect edges)."""
        cx, cy = c.x + c.w / 2, c.y + c.h / 2
        return {
            "right": (c.x + c.w, cy), "left": (c.x, cy),
            "top": (cx, c.y), "bottom": (cx, c.y + c.h), "center": (cx, cy),
        }[side]

    def paired_connector(self, m) -> str:
        """Connector bridging the two paired cards, anchored to their facing edges."""
        if m.kind != "paired" or len(m.cards) < 2:
            return ""
        a, b = m.cards[0], m.cards[1]
        return _connector(self.card_anchor(a, "right"), self.card_anchor(b, "left"))

    def behind_headline(self) -> str:
        return ""

    def paint(self, m: Motif) -> str:
        raise NotImplementedError


class Minimal(Style):
    key = "minimal"

    def paint(self, m: Motif) -> str:
        if m.kind == "device_signal":
            return _device(m, screen=_pulse_line(GREEN), waves=GREEN)
        out = []
        for l in m.links:
            out.append(f'<path d="{cubic(l.x1, l.y1, l.x2, l.y2, _bow(l, m.kind))}" fill="none" stroke="{GREEN}" stroke-width="2.5" opacity="0.9"/>')
        out.append(self._cards(m))
        out.append(self.paired_connector(m))
        out.append(self._nodes(m))
        out.append(_node_captions(m))
        return "".join(out)

    def _nodes(self, m: Motif) -> str:
        if m.kind == "device_signal":
            return ""
        s = []
        for n in m.nodes:
            if n.role == "hub":
                if m.kind == "pipeline":
                    s.append(f'<path d="{_hexagon(n.x, n.y, 30)}" fill="{NAVY_1}" stroke="{GREEN}" stroke-width="3"/>'
                             f'<path d="M{n.x-10:.0f} {n.y:.0f} l7 7 l13 -15" fill="none" stroke="{GREEN}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
                else:
                    s.append(f'<circle cx="{n.x}" cy="{n.y}" r="20" fill="{NAVY_1}" stroke="{GREEN}" stroke-width="3"/><circle cx="{n.x}" cy="{n.y}" r="7" fill="{GREEN}"/>')
            elif n.role == "accent" and m.kind == "pipeline":
                s.append(f'<line x1="{n.x}" y1="{n.y-76}" x2="{n.x}" y2="{n.y+76}" stroke="{GREEN}" stroke-width="3"/>'
                         f'<rect x="{n.x-16}" y="{n.y-40}" width="32" height="86" rx="4" fill="{GREEN}"/>')
            else:
                s.append(f'<circle cx="{n.x}" cy="{n.y}" r="9" fill="{GREEN}"/>')
        return "".join(s)

    def _cards(self, m: Motif) -> str:
        if m.kind == "ranked":
            return _ranked_minimal(m)
        if m.kind == "paired":
            return _paired_minimal(m)
        return ""


class Isometric(Style):
    key = "isometric"
    head = {"y0": 322, "lh": 64, "size": 54}
    baseline_y = 430
    ISO_W, ISO_D = 0.46, 0.34  # top-face half-width / half-depth as a fraction of the card

    def card_anchor(self, c, side: str) -> tuple[float, float]:
        cx, cy = c.x + c.w / 2, c.y + c.h / 2
        w, d = c.w * self.ISO_W, c.h * self.ISO_D
        return {
            "right": (cx + w, cy), "left": (cx - w, cy),
            "top": (cx, cy - d), "bottom": (cx, cy + d), "center": (cx, cy),
        }[side]

    def paint(self, m: Motif) -> str:
        if m.kind == "device_signal":
            return _device(m, screen=_pulse_line(GREEN), waves=GREEN)
        out = [self.paired_connector(m)]
        # iso links: straight lines between element top-centers
        for l in m.links:
            out.append(f'<line x1="{l.x1}" y1="{l.y1}" x2="{l.x2}" y2="{l.y2}" stroke="{GREEN}" stroke-width="2.5" opacity="0.8"/>')
        for c in m.cards:
            cx, cy = c.x + c.w / 2, c.y + c.h / 2
            # Flatter top face (depth < width) reads as iso; label is centered ON it.
            out.append(_iso_tile(cx, cy, c.w * self.ISO_W, c.h * self.ISO_D, GREEN if c.role == "primary" else NAVY_1, NAVY_2, GREEN))
            if c.label:
                out.append(_label(cx, cy, c.label, NAVY_0 if c.role == "primary" else TEXT_SECONDARY, 22, 800))
        for n in m.nodes:
            r = 46 if n.role == "hub" else 30
            top = GREEN if n.role == "hub" else NAVY_1
            out.append(_iso_tile(n.x, n.y, r, r * 0.52, top, NAVY_2, GREEN))
            if n.role == "hub":
                out.append(f'<circle cx="{n.x}" cy="{n.y}" r="6" fill="{NAVY_0}"/>')
        out.append(_node_captions(m))
        return "".join(out)


class Infographic(Style):
    key = "infographic"
    head = {"y0": 250, "lh": 58, "size": 50}
    baseline_y = 556

    def defs(self) -> str:
        return f'<marker id="iar" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="{GREEN}"/></marker>'

    def background(self) -> str:
        return base_background(glow_cx=0.78, glow_cy=0.5)

    def paint(self, m: Motif) -> str:
        if m.kind == "ranked":
            return _ranked_infographic(m)
        if m.kind == "paired":
            return _paired_minimal(m) + self.paired_connector(m)
        if m.kind == "device_signal":
            return _device(m, screen=_pulse_line(GREEN), waves=GREEN)
        # node motifs -> labelled boxes with arrows from the source box to the rest
        boxes = _nodes_as_boxes(m)
        src = boxes[0]
        sx, sy = src.x + src.w, src.y + src.h / 2
        out = []
        for c in boxes[1:]:
            out.append(f'<path d="{cubic(sx, sy, c.x, c.y + c.h / 2, 0)}" fill="none" stroke="{GREEN}" stroke-width="2.5" opacity="0.85" marker-end="url(#iar)"/>')
        for c in boxes:
            out.append(_info_box(c))
        if m.sublabel:
            out.append(_label(sx + 56, src.y - 14, m.sublabel, TEXT_SECONDARY, 16, 600))
        return "".join(out)


class Glow(Style):
    key = "glow"

    def defs(self) -> str:
        return (
            f'<radialGradient id="halo" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="{GREEN}" stop-opacity="0.85"/>'
            f'<stop offset="0.4" stop-color="{GREEN}" stop-opacity="0.22"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0"/></radialGradient>'
            f'<radialGradient id="bhalo" cx="0.4" cy="0.35" r="0.7"><stop offset="0" stop-color="{BLUE}" stop-opacity="0.20"/><stop offset="1" stop-color="{BLUE}" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="beam" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{GREEN}" stop-opacity="0.1"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0.95"/></linearGradient>'
        )

    def background(self) -> str:
        return base_background() + f'<rect width="{W}" height="{H}" fill="url(#bhalo)"/>'

    def paint(self, m: Motif) -> str:
        if m.kind == "device_signal":
            return _device(m, screen=_pulse_line(GREEN), waves=GREEN, glow=True)
        out = []
        for l in m.links:
            out.append(f'<path d="{cubic(l.x1, l.y1, l.x2, l.y2, _bow(l, m.kind))}" fill="none" stroke="url(#beam)" stroke-width="3"/>')
        out.append(self._cards(m))
        out.append(self.paired_connector(m))
        for n in m.nodes:
            if n.role == "hub":
                out.append(_halo(n.x, n.y, 40) + f'<circle cx="{n.x}" cy="{n.y}" r="22" fill="{NAVY_0}" stroke="{GREEN}" stroke-width="2.5"/><circle cx="{n.x}" cy="{n.y}" r="8" fill="{GREEN}"/>')
            else:
                out.append(_halo(n.x, n.y, 26) + f'<circle cx="{n.x}" cy="{n.y}" r="8" fill="{GREEN}"/>')
        out.append(_node_captions(m))
        return "".join(out)

    def _cards(self, m: Motif) -> str:
        s = []
        for c in m.cards:
            primary = c.role == "primary"
            stroke = GREEN if primary else "#ffffff"
            op = "" if primary else ' stroke-opacity="0.16"'
            if primary:
                s.append(_halo(c.x + c.w / 2, c.y + c.h / 2, max(c.w, c.h) * 0.55))
            s.append(f'<rect x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" rx="14" fill="{NAVY_1}" stroke="{stroke}"{op} stroke-width="{3 if primary else 2}"/>')
            if c.label:
                s.append(_label(c.x + c.w / 2, c.y + c.h / 2, c.label, GREEN if primary else TEXT_SECONDARY, 30, 800))
        return "".join(s)


class Network(Style):
    key = "network"

    def background(self) -> str:
        return base_background() + _network_field() + f'<rect x="0" y="232" width="720" height="210" fill="{NAVY_0}" fill-opacity="0.55"/>'

    def paint(self, m: Motif) -> str:
        if m.kind == "device_signal":
            return _device(m, screen=_pulse_line(GREEN), waves=GREEN)
        out = []
        for l in m.links:
            out.append(f'<path d="{cubic(l.x1, l.y1, l.x2, l.y2, _bow(l, m.kind))}" fill="none" stroke="{GREEN}" stroke-width="2.5"/>')
        out.append(Minimal()._cards(m))
        out.append(self.paired_connector(m))
        for n in m.nodes:
            if n.role == "hub":
                out.append(f'<circle cx="{n.x}" cy="{n.y}" r="19" fill="{NAVY_0}" stroke="{GREEN}" stroke-width="3"/><circle cx="{n.x}" cy="{n.y}" r="6.5" fill="{GREEN}"/>')
            else:
                out.append(f'<circle cx="{n.x}" cy="{n.y}" r="8" fill="{GREEN}"/>')
        out.append(_node_captions(m))
        return "".join(out)


# Shared drawing helpers

def _hexagon(cx: float, cy: float, r: float) -> str:
    import math
    pts = [f"{cx + r * math.cos(math.radians(60 * i)):.0f} {cy + r * math.sin(math.radians(60 * i)):.0f}" for i in range(6)]
    return "M" + " L".join(pts) + " Z"


def _halo(cx: float, cy: float, r: float) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#halo)"/>'


def _iso_tile(cx: float, cy: float, w: float, d: float, top_fill: str, side: str, edge: str, drop: float = 22) -> str:
    top = f'{cx} {cy-d} {cx+w} {cy} {cx} {cy+d} {cx-w} {cy}'
    left = f'{cx-w} {cy} {cx} {cy+d} {cx} {cy+d+drop} {cx-w} {cy+drop}'
    right = f'{cx+w} {cy} {cx} {cy+d} {cx} {cy+d+drop} {cx+w} {cy+drop}'
    return (
        f'<polygon points="{left}" fill="{side}"/>'
        f'<polygon points="{right}" fill="{NAVY_0}"/>'
        f'<polygon points="{top}" fill="{top_fill}" stroke="{edge}" stroke-width="2"/>'
    )


def _info_box(c: Card) -> str:
    primary = c.role == "primary"
    stroke = GREEN if primary else "#ffffff"
    op = "" if primary else ' stroke-opacity="0.18"'
    tcol = GREEN if primary else TEXT_SECONDARY
    label = _label(c.x + c.w / 2, c.y + c.h / 2, c.label, tcol, 19, 700) if c.label else ""
    return (
        f'<rect x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" rx="12" fill="{NAVY_1}" stroke="{stroke}"{op} stroke-width="{3 if primary else 2}"/>{label}'
    )


def _nodes_as_boxes(m: Motif) -> list:
    """Turn a node-based motif into labelled boxes for the infographic style.

    Box labels come from the motif's content labels when present, falling back to
    generic stage names so an unlabelled spec still renders.
    """
    if m.kind == "pipeline":
        bl = m.box_labels or ("Inputs", "Engine", "Trade")
        return [
            Card(700, 404, 150, 56, bl[0] or "Inputs", "secondary"),
            Card(900, 404, 136, 56, bl[1] or "Engine", "primary"),
            Card(1086, 404, 110, 56, bl[2] or "Trade", "secondary"),
        ]
    # hub_spokes -> lead + followers (use the motif's hub/leaf labels when set)
    leaves = [n for n in m.nodes if n.role == "leaf"]
    hub = next((n for n in m.nodes if n.role == "hub"), None)
    lead = (hub.label if hub and hub.label else "Lead")
    ys = [360, 430, 500]
    boxes = [Card(700, 394, 148, 56, lead, "primary")]
    for i, y in enumerate(ys):
        lbl = leaves[i].label if i < len(leaves) and leaves[i].label else "Follower"
        boxes.append(Card(980, y, 168, 52, lbl, "secondary"))
    return boxes


def _ranked_minimal(m: Motif) -> str:
    s = []
    for c in m.cards:
        cy = c.y + c.h / 2
        if c.role == "primary":
            s.append(f'<rect x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" rx="12" fill="{NAVY_1}" stroke="{GREEN}" stroke-width="3"/>')
            s.append(f'<circle cx="{c.x + c.w - 32}" cy="{cy}" r="15" fill="{GREEN}"/>')
            s.append(f'<path d="M{c.x + c.w - 39:.0f} {cy:.0f} l5 5 l9 -10" fill="none" stroke="{NAVY_0}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
            if c.label:
                s.append(_text(c.x + 22, cy, c.label, GREEN_AA, 20, 700, "start"))
            else:
                s.append(f'<rect x="{c.x + 20}" y="{cy - 6}" width="150" height="12" rx="6" fill="{GREEN}" opacity="0.8"/>')
        else:
            s.append(f'<rect x="{c.x + 8}" y="{c.y}" width="{c.w - 16}" height="{c.h}" rx="12" fill="{NAVY_1}" stroke="#ffffff" stroke-opacity="0.12" stroke-width="2"/>')
            if c.label:
                s.append(_text(c.x + 28, cy, c.label, TEXT_MAIN, 19, 600, "start"))
            else:
                s.append(f'<rect x="{c.x + 28}" y="{cy - 6}" width="110" height="12" rx="6" fill="#ffffff" fill-opacity="0.18"/>')
    return "".join(s)


def _ranked_infographic(m: Motif) -> str:
    """A leaderboard with rank badges + bars; the top row accented and checked."""
    s = []
    for i, c in enumerate(m.cards):
        cy = c.y + c.h / 2
        primary = c.role == "primary"
        stroke = GREEN if primary else "#ffffff"
        op = "" if primary else ' stroke-opacity="0.18"'
        bx = c.x + 32
        bar_fill = f'fill="{GREEN}" opacity="0.85"' if primary else 'fill="#ffffff" fill-opacity="0.18"'
        bar_w = 150 if primary else 110
        s.append(f'<rect x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" rx="12" fill="{NAVY_1}" stroke="{stroke}"{op} stroke-width="{3 if primary else 2}"/>')
        s.append(f'<circle cx="{bx}" cy="{cy:.0f}" r="15" fill="{GREEN if primary else NAVY_0}" stroke="{GREEN}" stroke-opacity="{1 if primary else 0.35}" stroke-width="2"/>')
        s.append(_label(bx, cy, str(i + 1), NAVY_0 if primary else TEXT_SECONDARY, 18, 800))
        if c.label:
            s.append(_text(c.x + 62, cy, c.label, GREEN_AA if primary else TEXT_MAIN, 19, 700, "start"))
        else:
            s.append(f'<rect x="{c.x + 62}" y="{cy - 6:.0f}" width="{bar_w}" height="12" rx="6" {bar_fill}/>')
        if primary:
            s.append(f'<circle cx="{c.x + c.w - 30:.0f}" cy="{cy:.0f}" r="14" fill="{GREEN}"/>')
            s.append(f'<path d="M{c.x + c.w - 37:.0f} {cy:.0f} l5 5 l9 -10" fill="none" stroke="{NAVY_0}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    return "".join(s)


def _paired_minimal(m: Motif) -> str:
    s = []
    for c in m.cards:
        primary = c.role == "primary"
        stroke = GREEN if primary else "#ffffff"
        op = "" if primary else ' stroke-opacity="0.14"'
        s.append(f'<rect x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" rx="18" fill="{NAVY_1}" stroke="{stroke}"{op} stroke-width="{3 if primary else 2}"/>')
        s.append(_label(c.x + c.w / 2, c.y + c.h / 2, c.label, GREEN if primary else TEXT_SECONDARY, 34, 800))
    # the connector is drawn by the style's paired_connector (anchored to edges)
    if m.sublabel:
        s.append(_label(960, 556, m.sublabel, TEXT_SECONDARY, 18, 600))
    return "".join(s)


def _device(m: Motif, *, screen: str, waves: str, glow: bool = False) -> str:
    c = m.cards[0] if m.cards else Card(900, 316, 150, 248)
    cx = c.x + c.w / 2
    s = [f'<rect x="{c.x}" y="{c.y}" width="{c.w}" height="{c.h}" rx="26" fill="{NAVY_1}" stroke="#ffffff" stroke-opacity="0.16" stroke-width="2"/>']
    s.append(f'<rect x="{cx - 19:.0f}" y="{c.y + 16:.0f}" width="38" height="6" rx="3" fill="#ffffff" fill-opacity="0.2"/>')
    s.append(screen.replace("__CX__", f"{cx:.0f}").replace("__CY__", f"{c.y + 154:.0f}"))
    s.append(f'<g stroke="{waves}" stroke-width="2" fill="none" opacity="0.55"><path d="M{c.x + c.w + 16:.0f} {c.y + 44:.0f} a40 40 0 0 1 0 56"/><path d="M{c.x + c.w + 36:.0f} {c.y + 32:.0f} a64 64 0 0 1 0 80"/></g>')
    for n in m.nodes:
        if glow:
            s.append(_halo(n.x, n.y, 22))
        s.append(f'<circle cx="{n.x}" cy="{n.y}" r="7" fill="{GREEN}"/>')
    return "".join(s)


def _pulse_line(color: str) -> str:
    """A heartbeat/signal pulse centered at the __CX__,__CY__ tokens (filled by _device)."""
    pts = "-62,12 -34,12 -20,-30 0,40 16,-4 34,-4 60,-4"
    return (
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="3.5" '
        f'stroke-linecap="round" stroke-linejoin="round" transform="translate(__CX__,__CY__)"/>'
        f'<circle cx="-20" cy="-30" r="6" fill="{color}" transform="translate(__CX__,__CY__)"/>'
    )


def _network_field() -> str:
    import math
    rnd = _Rng(7)
    pts = [(rnd.uniform(60, W - 60), rnd.uniform(70, H - 50)) for _ in range(46)]
    lines = []
    for i, (x1, y1) in enumerate(pts):
        for x2, y2 in pts[i + 1:]:
            if math.hypot(x2 - x1, y2 - y1) < 150:
                lines.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}"/>')
    dots = "".join(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="2.5"/>' for x, y in pts)
    return (
        f'<g stroke="#ffffff" stroke-opacity="0.06" stroke-width="1">{"".join(lines)}</g>'
        f'<g fill="#ffffff" fill-opacity="0.10">{dots}</g>'
    )


class _Rng:
    """Tiny deterministic LCG so the network field is stable without Math.random."""

    def __init__(self, seed: int):
        self.s = seed & 0xFFFFFFFF

    def uniform(self, a: float, b: float) -> float:
        self.s = (1103515245 * self.s + 12345) & 0x7FFFFFFF
        return a + (self.s / 0x7FFFFFFF) * (b - a)


STYLES = {
    "minimal": Minimal(),
    "isometric": Isometric(),
    "infographic": Infographic(),
    "glow": Glow(),
    "network": Network(),
}
