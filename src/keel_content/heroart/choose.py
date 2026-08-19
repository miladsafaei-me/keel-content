"""Choosing a direction for each piece of content — deterministically.

Named `choose` rather than `select`: a module called `select.py` shadows the
standard library the moment its own directory lands on `sys.path`, which
happens as soon as anyone runs a script from inside the package. `subprocess`
imports `select`, so the failure surfaces far from its cause.

Design note, 2026-08-19: an earlier version asked Sonnet subagents to pick a
direction per post. Measured against this scorer the agents added no quality: they
read the same signals (data shape, vocabulary, item count) and then converged hard —
one run put 40 of 153 posts on the same direction and 83 in one colour world — so a
mechanical balancing pass had to overrule 93 of their choices anyway. Rules that
encode the same reasoning cost nothing, run in milliseconds over the whole corpus,
are reviewable, and stay stable across runs. A manifest is still honoured, so any
post can be hand-pinned; nothing here has to be re-derived to override one image.

The scorer runs in two stages:

1. score every direction against one subject, from the shape of its data;
2. assign across the whole corpus, best score first, enforcing a per-direction and
   per-world cap so no single motif or colour takes over the feed.

Both stages are pure functions of the content plus a hash of the slug, so the same
corpus always yields the same assignment.
"""
import json
import pathlib

from .draw import seedof
from .worlds import allocate, allocate_surfaces

#: No direction may hold more than this share of a corpus...
CAP_SHARE = 0.18
#: ...and none may fall below this share, so a direction never quietly dies out.
FLOOR_SHARE = 0.05
#: How many posts inside one cluster may share a direction before it is penalised.
#: Without this the head-word signal alone makes a cluster look like one article
#: repeated, because sibling posts tend to share a table header.
CLUSTER_REPEAT = 2
#: How many consecutive posts in the published feed are treated as one screenful.
#: /academy paginates ten at a time, so ten cards is what a reader compares at once.
FEED_WINDOW = 10
#: How many of those ten may share a motif. Corpus-wide balance says nothing about
#: what lands together on one page: the first production run held every global target
#: and still put five `glass` cards on page seven.
WINDOW_REPEAT = 3

# The table's own column header is the single most reliable signal we have: a head
# of "Rail" or "Method" is a list of ways to get paid, "Tier" is an ordered ladder,
# "Exchange" or "Market" is a field of named entities. Surveyed across the corpus,
# ~20 heads cover two thirds of it; the rest fall through to shape and vocabulary.
HEAD_MAP = {
    "model": ("flow", "stack", "split"),
    "structure": ("flow", "stack"),
    "deal structure": ("flow", "stack"),
    "payout structure": ("flow", "tape"),
    "execution model": ("glass", "flow"),
    "program type": ("stack", "flow"),
    "offer": ("stack", "split"),
    "deal element": ("stack", "glass"),
    "deal component": ("stack", "glass"),
    "tier": ("ladder",),
    "stage": ("ladder",),
    "level": ("ladder",),
    "phase": ("ladder",),
    "step": ("ladder",),
    "factor": ("glass", "gauge"),
    "criterion": ("glass", "gauge"),
    "dimension": ("glass", "orbit"),
    "element": ("glass", "orbit"),
    "input": ("gauge", "glass"),
    "metric": ("gauge", "glass"),
    "category (weight)": ("gauge",),
    "check": ("tape", "grid"),
    "what to check": ("tape", "grid"),
    "what to ask for": ("tape", "grid"),
    "signal": ("grid", "tape"),
    "red flag": ("grid", "tape"),
    "rail": ("tape",),
    "method": ("tape", "glass"),
    "source": ("orbit", "grid"),
    "source type": ("orbit", "grid"),
    "channel": ("orbit", "grid"),
    "market": ("grid", "split"),
    "vertical": ("grid", "split"),
    "exchange": ("grid", "stack"),
    "platform": ("glass", "grid"),
    "broker attribute": ("glass", "grid"),
    "instrument type": ("grid", "orbit"),
    "role": ("orbit", "stack"),
    "ib type": ("orbit", "stack"),
    "trader profile": ("orbit", "split"),
    "scenario": ("split", "stack"),
    "situation": ("split", "stack"),
    "clause": ("tape", "stack"),
    "risk": ("split", "grid"),
    "bucket": ("grid", "split"),
    "area": ("orbit", "glass"),
    "key points": ("plate", "stack"),
}

PAYMENT_WORDS = ("payout", "payment", "fee", "commission", "invoice", "settle",
                 "withdraw", "threshold", "rebate", "cpa", "rail", "revenue",
                 "split", "share", "earning")
ORDER_WORDS = ("tier", "level", "stage", "step", "band", "grade", "phase", "ladder",
               "escalat", "progress", "maturity")
STRUCTURE_WORDS = ("network", "structure", "hierarchy", "ecosystem", "chain",
                   "master ib", "sub-ib", "sub ib", "funnel", "stack")
TOOL_WORDS = ("tool", "platform", "dashboard", "software", "tracking", "crm",
              "portal", "link", "postback", "attribution", "report")
SHORTLIST_WORDS = ("best", "top ", "choose", "shortlist", "screen", "vet", "audit",
                   "checklist", "criteria", "red flag", "compare", "which")
PILLAR_WORDS = ("guide", "explained", "complete", "everything", "framework",
                "playbook", "map")


def _subject_text(subject):
    """What the article actually compares — the strongest signal we have."""
    return (subject.head + " " + " ".join(subject.items) + " "
            + " ".join(subject.notes)).lower()


def _framing_text(subject):
    """How the article frames itself. Weaker: titles use money words loosely."""
    return f"{subject.title} {subject.kicker} {subject.takeaway}".lower()


def _hits(words, *texts):
    """3 when the item list itself matches, 1 when only the framing does."""
    strong, weak = texts[0], texts[1] if len(texts) > 1 else ""
    if any(w in strong for w in words):
        return 3
    return 1 if any(w in weak for w in words) else 0


#: Where a subject whose items are statements rather than names has to go. Motifs
#: that print one line per item can only cut a sentence down to a fragment; the
#: chapter plate is typographic — a count, a head and the title — so it says what the
#: article compares without pretending the statements are labels.
PROSE_HOME = "plate"


def score(subject, direction_key, role=""):
    """How well one direction suits one subject. Higher wins; ties break on slug."""
    subj = _subject_text(subject)
    frame = _framing_text(subject)
    n = subject.n
    numeric = bool(subject.weights)
    longest = max((len(i) for i in subject.items), default=0)
    prose = not subject.named
    s = 0.0

    # Head-word routing first, then shape, then framing vocabulary.
    preferred = HEAD_MAP.get(subject.head.strip().lower(), ())
    if direction_key in preferred:
        s += 7 - 2 * preferred.index(direction_key)

    if direction_key == "gauge":
        # Needles are meaningless without real figures, so this is a hard gate.
        if not numeric:
            return -100.0
        s += 6 + (2 if n <= 3 else 0)
    elif direction_key == "flow":
        s += 4 if numeric else 1
        s += _hits(PAYMENT_WORDS, subj, frame)
        s += 1 if 2 <= n <= 4 else -1
    elif direction_key == "plate":
        # The loudest motif in the feed, so it is reserved for hub articles.
        s += 5 if role == "pillar" else 0
        s += 2 if any(w in frame for w in PILLAR_WORDS) else 0
        s -= 2 if role == "spoke" else 0
    elif direction_key == "ladder":
        s += _hits(ORDER_WORDS, subj, frame)
        s += 2 if 3 <= n <= 5 else 0
        s += 1 if any(i[:2].rstrip(".").isdigit() for i in subject.items) else 0
    elif direction_key == "orbit":
        s += _hits(STRUCTURE_WORDS, subj, frame)
        s += 2 if 3 <= n <= 4 else 0
    elif direction_key == "split":
        s += 5 if 2 <= n <= 3 else -3
        s += 2 if longest <= 16 else -1
        s += 1 if " vs " in frame or "versus" in frame else 0
    elif direction_key == "glass":
        s += _hits(TOOL_WORDS, subj, frame)
        s += 1 if 3 <= n <= 4 else 0
    elif direction_key == "grid":
        s += 4 if any(w in frame for w in SHORTLIST_WORDS) else 0
        s += 2 if n >= 4 else 0
    elif direction_key == "tape":
        s += _hits(PAYMENT_WORDS[:9], subj, frame)
        s += 2 if n >= 3 else 0
        s += 1 if "threshold" in subj or "invoice" in subj else 0
    elif direction_key == "stack":
        # The generalist: always workable, never the strongest signal.
        s += 3 + (1 if 2 <= n <= 4 else 0)
        s += 1 if longest <= 20 else 0

    # Whether the items are names or statements is a shape, not a topic, and it
    # outranks the topic: a fragment of the right motif says less than the plain
    # count and heading of a motif that never promised to label anything.
    if prose:
        s += 12 if direction_key == PROSE_HOME else -12

    # A small stable jitter breaks ties differently per slug, so two posts with
    # identical shape do not always land on the same motif.
    return s + (seedof(f"{subject.key}|{direction_key}") % 100) / 250.0


def fallback_direction(subject, keys, role=""):
    """Best-scoring direction for one subject, ignoring corpus-level balance."""
    return max(keys, key=lambda k: score(subject, k, role))


#: Directions whose idea is running to the frame, which is exactly what a container
#: surface takes away from them.
NO_CONTAINER = ("split", "plate")


def assign(entries, keys, order=None, surfaces=("tinted",)):
    """Assign a direction and a hue to every item, spread across the corpus.

    `entries` is a list of (subject, cluster, role). `order` is the slugs in the
    order the feed publishes them, which is what decides which cards a reader sees
    side by side. Returns {slug: (direction, hue)}.

    Four pressures act at once: the per-item score decides what each post wants, a
    corpus cap and floor keep any one motif from taking over or dying out, a
    per-cluster penalty stops sibling posts — which usually share a table header, so
    usually score identically — from all landing on the same motif, and a feed-window
    limit stops one motif from filling a single page even when every corpus-wide
    number looks healthy.
    """
    cap = max(4, int(len(entries) * CAP_SHARE))
    order = order or [s.key for s, _c, _r in entries]
    at = {slug: i for i, slug in enumerate(order)}
    tail = len(order)
    for subject, _c, _r in entries:
        if subject.key not in at:
            at[subject.key] = tail
            tail += 1

    ranked = []
    for subject, cluster, role in entries:
        scores = sorted(((score(subject, k, role), k) for k in keys), reverse=True)
        margin = scores[0][0] - (scores[1][0] if len(scores) > 1 else 0)
        ranked.append((margin, subject, cluster, role, [k for _, k in scores]))
    ranked.sort(key=lambda r: (-r[0], r[1].key))

    used, per_cluster, out = {}, {}, {}
    taken_at = {}   # direction -> feed positions already holding it

    def crowds(key, pos, limit):
        """True when `key` already fills a window around this feed position."""
        near = sum(1 for q in taken_at.get(key, ())
                   if abs(q - pos) < FEED_WINDOW)
        return near >= limit

    def abuts(key, pos):
        """True when `key` already sits in the card immediately above or below.

        The window limit alone does not see this: three of ten is a healthy page and
        still reads as a repeat when the two land side by side.
        """
        return any(abs(q - pos) == 1 for q in taken_at.get(key, ()))

    for _, subject, cluster, role, order_keys in ranked:
        pos = at[subject.key]
        chosen = None
        for allowance, window, apart in ((CLUSTER_REPEAT, WINDOW_REPEAT, True),
                                        (CLUSTER_REPEAT * 3, WINDOW_REPEAT, True),
                                        (CLUSTER_REPEAT * 3, WINDOW_REPEAT + 2, False),
                                        (len(entries), len(entries), False)):
            chosen = next((k for k in order_keys
                           if used.get(k, 0) < cap
                           and per_cluster.get((cluster, k), 0) < allowance
                           and not crowds(k, pos, window)
                           and not (apart and abuts(k, pos))), None)
            if chosen:
                break
        chosen = chosen or order_keys[0]
        used[chosen] = used.get(chosen, 0) + 1
        per_cluster[(cluster, chosen)] = per_cluster.get((cluster, chosen), 0) + 1
        taken_at.setdefault(chosen, []).append(pos)
        out[subject.key] = chosen

    # A cap alone lets weak-signal directions die out. Promote the candidate that
    # loses least by moving, not the one that gains most — and never into a window
    # the starved direction already crowds, which would undo the page-level spread.
    floor = max(2, int(len(entries) * FLOOR_SHARE))
    subjects = {s.key: (s, r) for s, _c, r in entries}
    for _ in range(len(entries)):
        counts = {k: sum(1 for d in out.values() if d == k) for k in keys}
        starved = min(counts, key=lambda k: counts[k])
        if counts[starved] >= floor:
            break
        donors = [slug for slug, d in out.items()
                  if counts[d] > floor
                  and not crowds(starved, at[slug], WINDOW_REPEAT)
                  and not abuts(starved, at[slug])]
        if not donors:
            break

        def cost(slug):
            subject, role = subjects[slug]
            return score(subject, out[slug], role) - score(subject, starved, role)

        best = min(donors, key=cost)
        if score(subjects[best][0], starved, subjects[best][1]) <= -50:
            break
        taken_at[out[best]].remove(at[best])
        taken_at.setdefault(starved, []).append(at[best])
        out[best] = starved

    # Hue last, walked in feed order rather than per post, so the colours a reader
    # sees together are the ones held apart.
    walk = sorted(out, key=lambda slug: at[slug])
    hues = allocate(walk)
    skins = allocate_surfaces([(slug, out[slug]) for slug in walk], list(surfaces),
                              blocked={"panel": NO_CONTAINER})
    return {slug: (direction, hues[slug], skins[slug])
            for slug, direction in out.items()}


def load_manifest(path):
    """Optional hand-written overrides: {slug: {direction, world|hue}}."""
    if not path:
        return {}
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    if isinstance(data, list):
        return {row["slug"]: row for row in data if row.get("slug")}
    return data
