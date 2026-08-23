"""How alike two finished cards look, measured from the images themselves.

The assignment pass in `choose` spreads motifs, tones and grounds so that no page
is dominated by one of anything. That is a check on the *intent*: it knows which
direction each post was given, not what the direction then drew. A motif that
ignores its subject draws the same picture every time, so a page can hold three
different direction names and still read as one card repeated — which is exactly
what a corpus review found.

So this asks the question the reader asks. It walks each cover the way `audit`
does — same parser, same transforms, same clip handling — and reduces it to a
coarse map of where ink landed. Two covers whose ink lands in the same cells at the
same weight look alike whatever their motifs are called, and two whose ink lands
differently do not, whatever they share.

Deliberately not a raster hash. Rasterising needs a browser or a native library,
which would make a build step that runs everywhere depend on one that does not, and
a perceptual hash of a rendered PNG would answer the same question with more
machinery and a new failure mode. The geometry is already in the file.
"""
from . import audit
from .constants import H, W

#: The map is coarse on purpose. At this resolution it records composition — where
#: the instrument sits, how far it spreads, where the type block is — and ignores
#: which way a tick points. Finer, and two genuinely different arrangements of the
#: same parts start reading as different when a reader would call them the same.
COLS, ROWS = 12, 7

#: A shape this large is the page, the inset or a full-width wash, and it lands in
#: every cell of every card. Counting it makes every signature more alike than the
#: pictures are.
GROUND_AREA = W * H * 0.5

#: Text is a small part of a card's area and most of what tells two of them apart,
#: so a text box counts for more per unit than a drawn shape does.
TEXT_WEIGHT = 2.4

#: Below this two covers are the same picture with different words. There is no
#: threshold that is right for every skin, because this measures composition and
#: nothing else: a skin whose cards are told apart mainly by colour scores low here
#: while reading as varied, and a skin whose colour is semantic and narrow — where
#: two cards really are the same drawing — scores exactly the same way and is not.
#: So this is a starting point a consumer calibrates against its own corpus, and the
#: build gate is off unless that consumer passes `--alike`.
TOO_ALIKE = 0.03

#: How many cards a reader compares at once. Matches `choose.FEED_WINDOW`: two cards
#: that look alike matter when they land on one page and barely matter otherwise.
WINDOW = 10


def signature(svg_text):
    """A coarse map of where one card put its ink, as `COLS * ROWS` floats in 0..1."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(svg_text)
    texts, shapes, order = [], [], [0]
    audit._walk(root, [], order, texts, shapes, audit._gradients(root),
                audit._clips(root))

    cw, ch = W / COLS, H / ROWS
    cells = [0.0] * (COLS * ROWS)
    marks = [(box, TEXT_WEIGHT) for _z, box, _c, _s, _f, _fill in texts]
    marks += [(box, 1.0) for _z, box, _fill, _ap in shapes if box.area < GROUND_AREA]
    for box, weight in marks:
        xs = [pt[0] for pt in box.pts]
        ys = [pt[1] for pt in box.pts]
        c0 = max(0, int(min(xs) // cw))
        c1 = min(COLS - 1, int(max(xs) // cw))
        r0 = max(0, int(min(ys) // ch))
        r1 = min(ROWS - 1, int(max(ys) // ch))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                cell = audit.rect_quad(c * cw, r * ch, (c + 1) * cw, (r + 1) * ch)
                cells[r * COLS + c] += box.overlap(cell) / (cw * ch) * weight
    peak = max(cells) or 1.0
    return [min(1.0, v / peak) for v in cells]


def distance(a, b):
    """How different two signatures are, 0 (identical) to 1 (nothing in common)."""
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def pairs(signatures, order=None, window=WINDOW, threshold=TOO_ALIKE):
    """Every pair of cards that look alike, closest first.

    `order` is the published feed order. With one, only cards a reader can see on
    the same page are compared — two lookalikes twenty posts apart are not a fault,
    and reporting them as one buries the pairs that are.
    """
    slugs = list(signatures)
    if order:
        at = {slug: i for i, slug in enumerate(order)}
        tail = len(order)
        for slug in slugs:
            if slug not in at:
                at[slug] = tail
                tail += 1
        slugs.sort(key=lambda s: at[s])
    out = []
    for i, a in enumerate(slugs):
        for j in range(i + 1, len(slugs)):
            if order and window and j - i >= window:
                break
            d = distance(signatures[a], signatures[slugs[j]])
            if d < threshold:
                out.append((d, a, slugs[j]))
    out.sort()
    return out


def report(signatures, order=None, threshold=0.0):
    """One line on how far apart the corpus reads, for the build's own output."""
    slugs = list(signatures)
    if len(slugs) < 2:
        return "1 card, nothing to compare"
    nearest = sorted(min(distance(signatures[a], signatures[b])
                         for b in slugs if b != a) for a in slugs)
    mid = nearest[len(nearest) // 2]
    line = (f"nearest-neighbour distance min {nearest[0]:.3f}, "
            f"median {mid:.3f}, worst-apart {nearest[-1]:.3f}")
    if threshold > 0:
        line += (f"; {len(pairs(signatures, order, threshold=threshold))} pair(s) "
                 f"under {threshold:.3f} on the same page")
    return line
