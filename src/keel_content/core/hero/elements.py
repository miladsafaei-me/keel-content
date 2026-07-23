"""Concept motifs as abstract element layouts.

A motif lays out typed elements (nodes, links, cards) in the right-hand motif
zone; each *style* decides how those elements look. So one layout renders in
five visual languages, and any post's concept can be shown in any style.

Motif kinds map to common blog concepts:
- ``hub_spokes``    one -> many broadcast (copy trading, signal delivery)
- ``pipeline``      inputs -> engine -> output (algo trading, "how X works")
- ``ranked``        a leaderboard / comparison (best brokers, best apps)
- ``paired``        two things, one accented (MT4 vs MT5, connectors)
- ``device_signal`` a device receiving a signal (trading apps, mobile)
- ``nodes``         generic relay fallback
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    x: float
    y: float
    role: str = "leaf"  # hub | leaf | accent
    label: str = ""     # optional content label rendered beside the node


@dataclass
class Link:
    x1: float
    y1: float
    x2: float
    y2: float
    role: str = "flow"


@dataclass
class Card:
    x: float
    y: float
    w: float
    h: float
    label: str = ""
    role: str = "secondary"  # primary | secondary


@dataclass
class Motif:
    kind: str
    nodes: list = field(default_factory=list)
    links: list = field(default_factory=list)
    cards: list = field(default_factory=list)
    sublabel: str | None = None
    box_labels: tuple = ()  # infographic 3-box pipeline labels (inputs, engine, out)


def _as_list(v):
    return list(v) if isinstance(v, (list, tuple)) else ([] if v is None else [v])


def hub_spokes(n: int = 3, hub_label: str = "", leaf_labels=None, **_) -> Motif:
    hub = (858, 440)
    leaves = [(1045, 330), (1064, 442), (1062, 548)][:n]
    leaf_labels = _as_list(leaf_labels)
    return Motif(
        kind="hub_spokes",
        nodes=[Node(*hub, "hub", hub_label)]
        + [Node(x, y, "leaf", leaf_labels[i] if i < len(leaf_labels) else "") for i, (x, y) in enumerate(leaves)],
        links=[Link(hub[0], hub[1], x, y) for x, y in leaves],
    )


def pipeline(in_labels=None, engine_label: str = "", out_label: str = "", **_) -> Motif:
    inputs = [(792, 372), (792, 432), (792, 492)]
    engine = (968, 432)
    out = (1116, 432)
    in_labels = _as_list(in_labels)
    in_nodes = [Node(x, y, "leaf", in_labels[i] if i < len(in_labels) else "") for i, (x, y) in enumerate(inputs)]
    return Motif(
        kind="pipeline",
        nodes=in_nodes + [Node(*engine, "hub", engine_label), Node(*out, "accent", out_label)],
        links=[Link(x, y, *engine) for x, y in inputs] + [Link(*engine, *out)],
        box_labels=(in_labels[0] if in_labels else "Inputs", engine_label or "Engine", out_label or "Trade"),
    )


def ranked(labels=None, **_) -> Motif:
    labels = _as_list(labels)
    roles = ["primary", "secondary", "secondary"]
    ys = [330, 410, 490]
    return Motif(
        kind="ranked",
        cards=[Card(788, y, 344, 56, labels[i] if i < len(labels) else "", roles[i]) for i, y in enumerate(ys)],
    )


def paired(labels=("MT4", "MT5"), sublabel: str | None = None, **_) -> Motif:
    a, b = (tuple(labels) + ("", ""))[:2]
    # No hard-coded connector: each style draws it via card_anchor so it lands on
    # the facing edges of the two cards exactly (correct position + length per style).
    return Motif(
        kind="paired",
        cards=[Card(792, 392, 150, 118, a, "secondary"), Card(978, 392, 150, 118, b, "primary")],
        sublabel=sublabel,
    )


def device_signal(signal_label: str = "", **_) -> Motif:
    return Motif(
        kind="device_signal",
        cards=[Card(900, 316, 150, 248, "", "primary")],
        nodes=[Node(1052, 388, "accent", signal_label)],
    )


MOTIFS = {
    "hub_spokes": hub_spokes,
    "pipeline": pipeline,
    "ranked": ranked,
    "paired": paired,
    "device_signal": device_signal,
    "nodes": hub_spokes,
}


def build_motif(kind: str, **params) -> Motif:
    return MOTIFS.get(kind, hub_spokes)(**params)
