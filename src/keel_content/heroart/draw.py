"""Drawing primitives every direction shares: text metrics, grounds, shadows.

Two rules encoded here rather than left to each direction:

* The SVG root carries `style="direction:ltr"`. An inline SVG inherits `direction`
  from its host page, and under RTL every `text-anchor` flips, so text renders from
  the wrong edge and collides. The academy's own pages are LTR, but review pages and
  admin screens are not, and the failure is silent.
* Every gradient and filter id is namespaced with a per-image `uid`. Many of these
  end up inline on one page, where a duplicated id makes every later SVG quietly use
  the first one's definition.
"""
import hashlib
import html
import re

from .constants import H, MONO, SANS, SERIF, W

# Safe area for card covers. Nothing may sit outside it unless leaving the frame is
# the point of that direction (see SplitPanels, whose panels are meant to bleed).
COVER_PAD = 84
#: Smallest a content label may be set on the 1200 px canvas. A cover renders about
#: 340 px wide in the listing, so anything under this is texture rather than a word.
#: `heroart.audit` enforces the same number against the finished image.
MIN_LABEL = 20
#: Longest a content label may be on a cover. Past this the card is being read
#: rather than seen, which is what the hero is for. `heroart.audit` holds the
#: finished image to the same number.
MAX_LABEL = 34
#: Air a decorative element must leave around a label plate. Effects pressed against
#: the words is what makes a card feel crowded even when nothing actually overlaps.
BREATH = 26
# Exactly the safe area, so a motif that fills its box is correct by construction.
# It used to start four pixels above the margin and end four below, which every
# direction then had to compensate for by hand.
SAFE_BOX = (COVER_PAD, COVER_PAD, W - 2 * COVER_PAD, H - 2 * COVER_PAD)


def esc(s):
    return html.escape(str(s), quote=True)


MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
MD_EMPHASIS = re.compile(r"[*_`]{1,3}")


def squeeze(s):
    """Collapse whitespace and strip markdown, which leaks in from post bodies."""
    text = MD_LINK.sub(r"\1", str(s))
    text = MD_EMPHASIS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


CLAUSE_MARKS = ("—", " – ", " - ", ";", ":", ",")


def clip(s, n):
    """Trim to `n` characters, ending on a whole word.

    Cutting mid-word turns a label into a fragment — "Regulated activit…" says less
    than "Regulated…" and reads as a bug. Where the text is a sentence rather than a
    label, its leading clause is usually the label it was going to be trimmed to
    anyway, so that is preferred over any cut.
    """
    s = squeeze(s)
    if len(s) <= n:
        return s
    for mark in CLAUSE_MARKS:
        head = s.split(mark)[0].strip()
        if 4 <= len(head) <= n:
            return head
    cut = s[:n].rstrip()
    if " " in cut:
        cut = cut[:cut.rindex(" ")]
    cut = _tidy(cut)
    return (cut or _tidy(s[:n - 1])) + "…"


#: Words that carry nothing when they are the last thing before an ellipsis.
DANGLING = {"a", "an", "and", "or", "of", "the", "to", "for", "in", "on", "at",
            "by", "with", "from", "as", "vs", "per", "its", "your", "their"}


def _tidy(cut):
    """Drop what a trim leaves dangling: an opened bracket, a joining word.

    "Advertised pass rate (or…" reads as a bug rather than as a shortened label —
    the reader is left holding a bracket that never closes and a conjunction with
    nothing after it. Ending one word earlier says the same thing and looks intended.
    """
    cut = cut.rstrip(" ,;:—-")
    while cut:
        words = cut.split()
        last = words[-1] if words else ""
        stripped = last.strip("([{\"'").lower()
        opens = last.count("(") - last.count(")")
        if last.strip("([{") == "" or opens > 0 or stripped in DANGLING:
            cut = " ".join(words[:-1]).rstrip(" ,;:—-([{")
            continue
        break
    return cut


def seedof(key):
    """Stable integer seed. The same slug must always produce the same image."""
    return int(hashlib.blake2b(str(key).encode(), digest_size=8).hexdigest(), 16)


def variant(key, axis, options):
    """Pick one option for one post, stably.

    Composition variants are how two posts that land on the same motif stop looking
    like the same picture with different words: the fan tilts the other way, the
    light sits on the other side, the panels are mirrored. `axis` names the choice
    so two axes on one post do not correlate.
    """
    return options[seedof(f"{key}|{axis}") % len(options)]


def advance(fam, weight):
    per = 0.505 if fam is SERIF else 0.60 if fam is MONO else 0.545
    return per + (0.012 if weight >= 700 else 0)


def text_width(s, size, fam=SANS, weight=400):
    return len(str(s)) * size * advance(fam, weight)


def wrap(text, max_px, size, fam=SANS, weight=400, max_lines=4, hard=False):
    """Break text to `max_px`, marking the cut when it does not all fit.

    Dropping the overflowing lines silently is worse than an ellipsis: the reader
    has no way to tell a label that ended from a sentence that was cut, and the
    image quietly claims something the article did not say.

    `hard` also cuts a single word too long for the column. It is off by default
    because `fit` shrinks the type until the word fits, and a wrap that quietly cut
    it first would report success at every size and stop `fit` ever shrinking.
    """
    words, lines, cur = squeeze(text).split(), [], ""
    per = advance(fam, weight)
    for word in words:
        cand = (cur + " " + word).strip()
        if len(cand) * size * per <= max_px or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,;:—-") + "…"
    if not hard:
        return lines
    # A word longer than the whole column is placed anyway by the loop above, because
    # there is nowhere else to put it — and then it runs over whatever is beside it.
    # Once the type is as small as it may go, cutting it is the only way left to keep
    # the promise this function makes about width.
    room = max(int(max_px / (size * per)), 3)
    return [ln if len(ln) <= room else ln[:room - 1].rstrip() + "…" for ln in lines]


def fit(text, max_px, fam, hi, lo, max_lines=3, weight=700):
    """Largest size in [lo, hi] at which `text` fits in `max_lines` AND in width.

    Checking the line count alone is not enough: a single unbreakable word longer
    than `max_px` wraps to one line and then overflows the frame.
    """
    for size in range(int(hi), int(lo) - 1, -2):
        lines = wrap(text, max_px, size, fam, weight, max_lines=14)
        widest = max((text_width(ln, size, fam, weight) for ln in lines), default=0)
        if len(lines) <= max_lines and widest <= max_px:
            return size, lines
    return lo, wrap(text, max_px, lo, fam, weight, max_lines, hard=True)


def fit_all(items, max_px, fam, hi, lo, max_lines=2, weight=700):
    """One size that suits every item, and each item's lines at that size.

    Fitting each label on its own gives a card as many type sizes as it has labels,
    which reads as carelessness rather than as emphasis — and the tall ones then
    reach into their neighbours. One size for the set keeps the card even, and makes
    the longest item the one that decides how big the type can be.
    """
    if not items:
        return lo, []
    widths = max_px if isinstance(max_px, (list, tuple)) else [max_px] * len(items)
    size = min(fit(item, room, fam, hi, lo, max_lines, weight)[0]
               for item, room in zip(items, widths))
    return size, [wrap(item, room, size, fam, weight, max_lines, hard=True)
                  for item, room in zip(items, widths)]


def txt(x, y, s, size, fill, weight=400, fam=SANS, anchor="start", ls=0, op=None):
    a = f' letter-spacing="{ls}"' if ls else ""
    o = f' opacity="{op}"' if op is not None else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-family="{fam}" '
            f'font-size="{size:.1f}" font-weight="{weight}" fill="{fill}"{a}{o}>'
            f'{esc(s)}</text>')


def txt_fit(x, y, s, max_px, hi, lo, fill, weight=400, fam=SANS, anchor="start",
            ls=0, op=None):
    """One line of text at the largest size in [lo, hi] that fits within `max_px`.

    Item labels are the article's own words, so their length is not ours to choose:
    "Tier" and "Firm reference number" arrive at the same slot from two different
    tables. Fixing the type size and trimming to a character count made the second
    one a fragment; sizing the type to the label keeps it whole instead, and only a
    label that will not fit even at `lo` is trimmed — on a word boundary, so what
    survives still reads as words.
    """
    text = squeeze(s)
    size = hi
    while size > lo and text_width(text, size, fam, weight) > max_px:
        size -= 1
    if text_width(text, size, fam, weight) > max_px:
        text = clip(text, max(6, int(max_px / (advance(fam, weight) * size))))
    return txt(x, y, text, size, fill, weight, fam, anchor, ls, op)


def svg(defs, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'width="{W}" height="{H}" role="img" '
            f'style="direction:ltr;unicode-bidi:isolate">'
            f'<defs>{defs}</defs>{body}</svg>')


def ground(p, uid, glow=(760, 300, 520)):
    """The quiet field every direction sits on.

    One flat page with the faintest tonal lift towards the light, and nothing else.
    The earlier version laid a wide accent ellipse over it, which at any real opacity
    tinted a white sheet lavender and a dark one violet — the ground ended up carrying
    the colour that was supposed to belong to what is drawn on it.
    """
    gx, gy, gr = glow
    defs = (f'<radialGradient id="{uid}g" cx="{gx / W:.3f}" cy="{gy / H:.3f}" r="0.9">'
            f'<stop offset="0" stop-color="{p["faint"] if p.get("light") else p["mid"]}" '
            f'stop-opacity="0.30"/>'
            f'<stop offset="1" stop-color="{p["page"]}" stop-opacity="0"/>'
            f'</radialGradient>')
    body = (f'<rect width="{W}" height="{H}" fill="{p["page"]}"/>'
            f'<rect width="{W}" height="{H}" fill="url(#{uid}g)"/>')
    return defs, body


def inset_for(p, box):
    """The motif's box. Kept as a seam so a surface can reshape it without every
    direction learning about surfaces."""
    return box


#: Every direction asks for a shadow with its own numbers, from a time when depth was
#: made of shadow. They are scaled down here rather than in twenty-two call sites, so
#: the register stays one decision: a shadow is a hint that something is above
#: something else, not an effect.
SHADOW_LIFT, SHADOW_BLUR, SHADOW_OPACITY = 0.28, 0.55, 0.22


def shadow_def(uid, dy=26, blur=24, op=0.55):
    """A soft, minimal shadow. The arguments are a direction's intent, not its output."""
    return (f'<filter id="{uid}sh" x="-40%" y="-40%" width="190%" height="200%">'
            f'<feDropShadow dx="0" dy="{dy * SHADOW_LIFT:.1f}" '
            f'stdDeviation="{blur * SHADOW_BLUR:.1f}" '
            f'flood-color="#000" flood-opacity="{op * SHADOW_OPACITY:.3f}"/></filter>')


def wordmark(p, x=72, y=622, size=19):
    return (f'<text x="{x}" y="{y}" font-family="{SANS}" font-size="{size}" '
            f'font-weight="700" fill="{p["ink"]}" opacity="0.92">Revenika'
            f'<tspan fill="{p["accent"]}">.</tspan></text>')
