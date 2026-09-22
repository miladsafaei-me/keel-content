"""Replace every em dash with the punctuation its sentence actually needs, by rule.

An em dash does one of a handful of jobs, and each job has a plain replacement:

* a label and its explanation ("CySEC — investor warnings")  -> colon
* a soft continuation ("fast — so you never miss a call")     -> comma
* a second independent clause ("noise — it reads the trend")  -> full stop, next word capitalised
* an aside wrapped in a pair ("Ours — connector included — is free") -> commas, or brackets
  when the aside already carries a comma
* an empty table cell or placeholder ("—")                    -> hyphen
* a title's brand separator ("Pricing — SignalBots")          -> pipe

The rules read only the words touching the dash (the sentence it sits in, the first word
after it, the length of the part before it). A dash the rules cannot place with
confidence is returned as ``AMBIGUOUS`` so a caller can hand just that one sentence to a
reviewer; :func:`replace_em_dashes` resolves those with a safe default instead, which is
what the import-time normalizer uses.

Pure stdlib, no Django. Positions are indexes into the *analysis view* of a text. A
caller that analyses a cleaned view of raw source (Python string literals with their
quote joints removed, a template with its comments masked) builds the view with
:func:`build_view` and applies the result to the raw text with :func:`render`, which
maps every edit back through the view's character spans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

COMMA = "COMMA"
COLON = "COLON"
PERIOD = "PERIOD"
SEMICOLON = "SEMICOLON"
PAREN_OPEN = "PAREN_OPEN"
PAREN_CLOSE = "PAREN_CLOSE"
HYPHEN = "HYPHEN"
PIPE = "PIPE"
AMBIGUOUS = "AMBIGUOUS"

KINDS = (COMMA, COLON, PERIOD, SEMICOLON, PAREN_OPEN, PAREN_CLOSE, HYPHEN, PIPE)

# Every spelling an em dash takes in source: the glyph, HTML entities, and the
# unicode escape as it appears inside a Python or JavaScript string literal.
GLYPH_RE = re.compile(r"—|&mdash;|&#8212;|&#x2014;|\\u2014", re.IGNORECASE)

_CONNECTORS = frozenset(
    """
    so and but or yet nor not no never nothing none even including include especially
    particularly which who whose while whether just then plus without with before after
    because since instead unlike rather from only until though although like such where
    when whenever if unless as in on at for by via through across into over under inside
    outside within free also too both either neither all whatever wherever once still
    again now alongside straight directly exactly zero less more mostly mainly sometimes
    always regardless whichever thanks per up down out off about around beyond above below
    to than whereas otherwise almost nearly roughly usually often typically what's
    """.split()
)
_PRONOUN_SUBJECTS = frozenset(
    """
    it it's they they're they'll you you're you'll you've we we're we'll we've i i'm he
    she this these those that's there there's here here's nobody everyone everything
    """.split()
)
_IMPERATIVES = frozenset(
    """
    read see review message check open set pick follow contact start download install try
    get click tap join send visit learn use keep watch compare choose find grab claim add
    test ask write sign create register verify explore browse view go let make don't
    """.split()
)
_DETERMINERS = frozenset("a an the each every your our their its one two three his her".split())
_ANSWER_WORDS = frozenset(
    "yes no sure correct true false exactly absolutely partly partially rarely never".split()
)
_FINITE_VERBS = frozenset(
    """
    is are was were be has have had will can could should would do does did don't doesn't
    isn't aren't won't can't cannot may might must
    """.split()
)
_BRAND_RE = re.compile(r"^(?:SignalBots?(?:\.ai)?|SignalBotAi)\b", re.IGNORECASE)

# Where a sentence starts or stops for the purpose of reading its words. Deliberately
# generous: markup boundaries, attribute quotes, markdown table cells and list bullets
# all end the stretch of prose a dash belongs to.
_BOUNDARY_RE = re.compile(
    r"""
      [.!?]["')\]]*\s
    | \n[ \t]*\n
    | \n[ \t]*(?:[-*+]|\d+\.|\#{1,6})\s
    | </?(?:p|li|ul|ol|h[1-6]|div|td|th|tr|table|section|article|header|footer|br|dd|dt|
           figcaption|blockquote|summary|details|button|option|label|title|meta)\b[^>]*>
    | ="|='|"\s*>|'\s*>|"\s+[\w:-]+=
    | \s\|\s
    """,
    re.VERBOSE | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^<>]*>|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_VAR_RE = re.compile(r"\{\{.*?\}\}|\$\{[^}]*\}|%\([a-z_]+\)s|\{[a-z_]+\}", re.DOTALL | re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’/.+%-]*")


@dataclass
class Dash:
    """One em dash in the analysis view and what should replace it."""

    start: int  # glyph start (view index)
    end: int  # glyph end (view index, exclusive)
    kind: str = AMBIGUOUS
    rule: str = ""
    cap: int | None = None  # view index of the letter to upper-case (PERIOD only)
    sentence: tuple[int, int] = (0, 0)


def visible(fragment: str) -> str:
    """Return the words a reader sees in ``fragment``: markup dropped, variables kept as ``X``."""
    s = _TAG_RE.sub(" ", fragment)
    s = _VAR_RE.sub(" X ", s)
    s = s.replace("\\n", " ").replace("\\'", "'").replace('\\"', '"')
    s = re.sub(r"[*_`#]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _words(fragment: str) -> list[str]:
    return _WORD_RE.findall(visible(fragment))


def _sentence_bounds(view: str, pos: int) -> tuple[int, int]:
    start, end = 0, len(view)
    for m in _BOUNDARY_RE.finditer(view):
        if m.end() <= pos:
            start = m.end()
        elif m.start() >= pos:
            end = m.start()
            break
    return start, end


def find(view: str) -> list[Dash]:
    """Locate every em dash in ``view`` (any spelling)."""
    return [Dash(m.start(), m.end()) for m in GLYPH_RE.finditer(view)]


def _cap_index(view: str, pos: int) -> int | None:
    """View index of the first letter a reader sees after ``pos``, or None if a variable leads."""
    i = pos
    n = len(view)
    while i < n:
        ch = view[i]
        if ch.isspace() or ch in "\"'(*_`":
            i += 1
            continue
        if view.startswith("\\n", i):
            i += 2
            continue
        if view.startswith("{{", i) or view.startswith("${", i) or view.startswith("%(", i):
            return None
        if ch == "{" and view.startswith("{%", i):
            j = view.find("%}", i)
            if j < 0:
                return None
            i = j + 2
            continue
        if ch == "<":
            j = view.find(">", i)
            if j < 0:
                return None
            i = j + 1
            continue
        if ch.isalpha():
            return i
        return None
    return None


def _left_char(view: str, pos: int) -> str:
    i = pos - 1
    while i >= 0 and view[i] in " \t\r\n":
        i -= 1
    return view[i] if i >= 0 else ""


def _right_char(view: str, pos: int) -> str:
    i = pos
    while i < len(view) and view[i] in " \t\r\n":
        i += 1
    return view[i] if i < len(view) else ""


def _decide_single(view: str, d: Dash) -> None:
    s0, s1 = d.sentence
    left = _words(view[s0:d.start])
    right = _words(view[d.end:s1])
    if not right:
        d.kind, d.rule = AMBIGUOUS, "nothing-after"
        return
    if not left:
        d.kind, d.rule = AMBIGUOUS, "nothing-before"
        return
    w = right[0].lower().replace("’", "'")
    if len(left) == 1 and left[0].lower() in _ANSWER_WORDS:
        d.kind, d.rule = COMMA, "answer-word"
        return
    if w in _CONNECTORS or (w.endswith("ly") and len(w) > 4):
        d.kind, d.rule = COMMA, "connector"
        return
    if w in _PRONOUN_SUBJECTS or w in _IMPERATIVES:
        if len(left) <= 3:
            d.kind, d.rule = COLON, "short-label+clause"
            return
        cap = _cap_index(view, d.end)
        if cap is None:
            d.kind, d.rule = SEMICOLON, "new-clause-variable"
        else:
            d.kind, d.rule, d.cap = PERIOD, "new-clause", cap
        return
    label_like = (
        1 <= len(left) <= 5
        and left[0][:1].isupper()
        and not any(x.lower() in _FINITE_VERBS for x in left)
    )
    if label_like and not any(x.lower() in _FINITE_VERBS for x in right[:6]):
        d.kind, d.rule = COLON, "label"
        return
    if w in _DETERMINERS and len(right) <= 6 and not any(x.lower() in _FINITE_VERBS for x in right):
        d.kind, d.rule = COLON, "short-elaboration"
        return
    d.kind, d.rule = AMBIGUOUS, "unclassified"


def classify(view: str, dashes: list[Dash] | None = None) -> list[Dash]:
    """Decide a replacement for every dash in ``view``. Unplaceable ones stay AMBIGUOUS."""
    dashes = find(view) if dashes is None else dashes
    for d in dashes:
        d.sentence = _sentence_bounds(view, d.start)

    pending: list[Dash] = []
    for d in dashes:
        lc, rc = _left_char(view, d.start), _right_char(view, d.end)
        s0, s1 = d.sentence
        no_words_left = not _words(view[s0:d.start])
        no_words_right = not _words(view[d.end:s1])
        if (lc in ">\"'(|:[" or lc == "") and (rc in "<\"')|]" or rc == ""):
            d.kind, d.rule = HYPHEN, "placeholder"
        elif no_words_left and no_words_right:
            d.kind, d.rule = HYPHEN, "placeholder"
        elif _BRAND_RE.match(visible(view[d.end:s1])) and len(_words(view[d.end:s1])) <= 3:
            d.kind, d.rule = PIPE, "brand-separator"
        else:
            pending.append(d)

    # Pair the remaining dashes sentence by sentence: two dashes around a short stretch
    # are one aside, not two separate breaks.
    by_sentence: dict[tuple[int, int], list[Dash]] = {}
    for d in pending:
        by_sentence.setdefault(d.sentence, []).append(d)
    for group in by_sentence.values():
        i = 0
        while i < len(group):
            a = group[i]
            b = group[i + 1] if i + 1 < len(group) else None
            if b is not None:
                middle = view[a.end:b.start]
                mid_words = _words(middle)
                after = _words(view[b.end:b.sentence[1]])
                before = _words(view[a.sentence[0]:a.start])
                if before and after and 1 <= len(mid_words) <= 14:
                    confident = len(mid_words) <= 8
                    if "," in visible(middle) or ";" in visible(middle):
                        a.kind, b.kind = PAREN_OPEN, PAREN_CLOSE
                        nxt = after[0].lower()
                        if nxt in _CONNECTORS - {"and", "or", "but"} or nxt in _DETERMINERS or nxt.endswith("ed"):
                            b.rule = "aside-pair+comma"
                    else:
                        a.kind, b.kind = COMMA, COMMA
                    a.rule = "aside-pair" if confident else "aside-pair-long"
                    if b.rule != "aside-pair+comma" or not confident:
                        b.rule = a.rule
                    if not confident:
                        a.kind = b.kind = AMBIGUOUS
                    i += 2
                    continue
            _decide_single(view, a)
            i += 1
    return dashes


def resolve_default(view: str, d: Dash) -> None:
    """Give an AMBIGUOUS dash a safe unattended replacement (used at import time)."""
    if d.kind != AMBIGUOUS:
        return
    right = _words(view[d.end:d.sentence[1]])
    left = _words(view[d.sentence[0]:d.start])
    if not right or not left:
        d.kind, d.rule = HYPHEN, "default-edge"
    elif right[0].lower() in _DETERMINERS or right[0][:1].isupper():
        d.kind, d.rule = COLON, "default-colon"
    else:
        d.kind, d.rule = COMMA, "default-comma"


def cap_for(view: str, d: Dash) -> int | None:
    return _cap_index(view, d.end)


@dataclass
class View:
    """A cleaned text for analysis plus, per character, the raw span it came from."""

    text: str
    spans: list[tuple[int, int]]


def build_view(
    raw: str,
    drop: re.Pattern[str] | list[tuple[int, int]] | None = None,
    lo: int = 0,
    hi: int | None = None,
) -> View:
    """Build the analysis view of ``raw[lo:hi]``, removing every ``drop`` match or span.

    Each glyph spelling (entity, escape) collapses to one ``—`` character whose span
    covers the whole spelling, so edits land on the raw text exactly.
    """
    hi = len(raw) if hi is None else hi
    chars: list[str] = []
    spans: list[tuple[int, int]] = []
    dropped: list[tuple[int, int]] = []
    if isinstance(drop, list):
        dropped = sorted(drop)
    elif drop is not None:
        dropped = [(m.start(), m.end()) for m in drop.finditer(raw, lo, hi)]
    di = 0
    i = lo
    while i < hi:
        while di < len(dropped) and dropped[di][1] <= i:
            di += 1
        if di < len(dropped) and dropped[di][0] <= i < dropped[di][1]:
            i = dropped[di][1]
            continue
        m = GLYPH_RE.match(raw, i, hi)
        if m:
            chars.append("—")
            spans.append((i, m.end()))
            i = m.end()
            continue
        chars.append(raw[i])
        spans.append((i, i + 1))
        i += 1
    return View("".join(chars), spans)


_PUNCT = {COMMA: ",", COLON: ":", SEMICOLON: ";", PERIOD: "."}


def edits_for(view: View, dashes: list[Dash]) -> list[tuple[int, int, str]]:
    """Raw-text edits (start, end, replacement) that apply ``dashes`` to the source."""
    text = view.text
    edits: list[tuple[int, int, str]] = []

    def raw_at(i: int) -> tuple[int, int]:
        return view.spans[i]

    for d in dashes:
        if d.kind == AMBIGUOUS:
            continue
        gs, ge = raw_at(d.start)[0], raw_at(d.end - 1)[1]
        ls = d.start
        while ls > 0 and text[ls - 1] in " \t ":
            ls -= 1
        re_ = d.end
        while re_ < len(text) and text[re_] in " \t ":
            re_ += 1
        has_right_ws = re_ > d.end or (re_ < len(text) and text[re_] in "\r\n") or re_ >= len(text)
        has_left_ws = ls < d.start

        if d.kind == HYPHEN:
            edits.append((gs, ge, "-"))
            continue
        if d.kind == PIPE:
            edits.append((gs, ge, ("" if has_left_ws else " ") + "|" + ("" if has_right_ws else " ")))
            continue
        if d.kind == PAREN_OPEN:
            edits.append((gs, ge, ("" if has_left_ws else " ") + "("))
            for k in range(d.end, re_):
                edits.append((*raw_at(k), ""))
            continue
        if d.kind == PAREN_CLOSE:
            for k in range(ls, d.start):
                edits.append((*raw_at(k), ""))
            close = ")," if d.rule == "aside-pair+comma" else ")"
            edits.append((gs, ge, close + ("" if has_right_ws else " ")))
            continue

        # Punctuation kinds attach to the word on the left and keep the space on the right.
        for k in range(ls, d.start):
            edits.append((*raw_at(k), ""))
        prev = text[ls - 1] if ls > 0 else ""
        mark = _PUNCT[d.kind]
        if prev and prev in ".,:;!?":
            mark = ""
        edits.append((gs, ge, mark + ("" if has_right_ws else " ")))
        if d.kind == PERIOD and d.cap is not None and not mark == "":
            cs, ce = raw_at(d.cap)
            edits.append((cs, ce, text[d.cap].upper()))
    return edits


def render(raw: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply raw-text edits (non-overlapping) and return the new text."""
    out = raw
    for s, e, rep in sorted(set(edits), key=lambda x: (x[0], x[1]), reverse=True):
        out = out[:s] + rep + out[e:]
    return out


def replace_em_dashes(text: str) -> str:
    """Replace every em dash in plain prose, resolving unplaceable ones with a safe default."""
    if not text or not GLYPH_RE.search(text):
        return text
    view = build_view(text)
    dashes = classify(view.text)
    for d in dashes:
        resolve_default(view.text, d)
        if d.kind == PERIOD and d.cap is None:
            d.cap = cap_for(view.text, d)
    return render(text, edits_for(view, dashes))
