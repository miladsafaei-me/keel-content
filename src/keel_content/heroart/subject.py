"""What a piece of content is *about*, in the one shape every direction consumes.

The insight the whole system rests on: our content already names its own subject.
A blog post's comparison table has, in its first column, the exact set of things the
post weighs up. A glossary term ships a `comparison` block with the same shape, plus
`at_a_glance` rows and `steps`. So a direction never has to guess a topic — it is
handed the article's own words.

Adding a new content type means writing one adapter that returns a Subject. Nothing
in draw.py or directions.py changes.
"""
import re
from dataclasses import dataclass, field

from .draw import clip, squeeze

NUM = re.compile(r"-?\d[\d,]*\.?\d*")


@dataclass
class Subject:
    key: str                       # stable seed, normally the slug
    title: str                     # headline baked into the hero
    kicker: str                    # small uppercase label above the title
    head: str = "Compared"         # what the item list is a list *of*
    items: list = field(default_factory=list)
    notes: list = field(default_factory=list)   # one short note per item
    weights: list = None           # real numbers, only when the source had them
    vocabulary: list = field(default_factory=list)  # domain words for texture
    takeaway: str = ""

    #: Set once from the source items, and carried through `truncated` so a motif
    #: cannot mistake a clipped statement for a short name.
    named: bool = None
    #: How many things the article actually compares, before any motif trimmed the
    #: list to what it can draw. A direction that states a count must state this one:
    #: reading `n` after truncation printed "4" on almost every chapter plate in the
    #: corpus, because four is what the frame holds, not what the article weighed up.
    total: int = None

    def __post_init__(self):
        if self.named is None:
            self.named = label_shaped(self.items)
        if self.total is None:
            self.total = len(self.items)

    @property
    def n(self):
        return len(self.items)

    def truncated(self, limit, maxlen):
        """A copy with at most `limit` items, each at most `maxlen` characters."""
        return Subject(
            key=self.key, title=self.title, kicker=self.kicker, head=self.head,
            items=[clip(i, maxlen) for i in self.items[:limit]],
            notes=[clip(x, 40) for x in self.notes[:limit]],
            weights=self.weights[:limit] if self.weights else None,
            vocabulary=self.vocabulary, takeaway=self.takeaway, named=self.named,
            total=self.total)


def md_tables(body_markdown):
    out, cur = [], []
    for line in (body_markdown or "").split("\n"):
        if line.strip().startswith("|"):
            cur.append(line)
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    parsed = []
    for block in out:
        rows = [[c.strip() for c in r.strip().strip("|").split("|")]
                for r in block if set(r.strip()) - set("|-: ")]
        if len(rows) >= 3:
            parsed.append(rows)
    return parsed


def _weights(rows, items):
    """Real numbers for the item list, or None. Never invent a proportion."""
    for ci in range(1, len(rows[0])):
        vals = [r[ci] for r in rows[1:1 + len(items)] if len(r) > ci]
        hits = [NUM.search(v) for v in vals]
        if len(vals) == len(items) and all(hits):
            nums = [float(h.group().replace(",", "")) for h in hits]
            if len(set(nums)) > 1 and min(nums) > 0:
                return nums
    return None


BARE_NUMBER = re.compile(r"^\d{1,3}$")


#: A cell longer than this is a statement about the thing, not the name of it.
#: Cards are seen rather than read, so a column of statements makes a poor label
#: column even when it is the first one.
LABEL_CHARS = 34


def _label_column(rows):
    """Which column names the things being compared.

    Normally the first, with two exceptions learned from the corpus. Some tables
    lead with a bare rank or score — a column of "5 4 3 2" is true and completely
    uninformative as a label. And some lead with a sentence, which no card can show
    whole: those get cut to a fragment, so a later column of short names is a better
    label column even though it is not the first.
    """
    for ci in range(min(3, len(rows[0]))):
        values = [squeeze(r[ci]) for r in rows[1:] if len(r) > ci and squeeze(r[ci])]
        if not values:
            continue
        bare = sum(1 for v in values if BARE_NUMBER.match(v))
        if bare >= max(2, len(values) * 0.6):
            continue
        typical = sorted(len(v) for v in values)[len(values) // 2]
        if typical > LABEL_CHARS:
            continue
        # A later column only earns the job if it actually names things. A ratings
        # column reads short and label-shaped and says nothing: "High, Medium, High,
        # High" is four labels and one fact, which is how a scoring article ended up
        # illustrated with the word High three times.
        if ci and len(set(values)) < max(2, len(values) - len(values) // 4):
            continue
        return ci
    # No column names anything. Keep the first: `Subject.named` will come out False
    # and the selector sends the post to a motif that does not label its items.
    return 0


def label_shaped(items):
    """Whether an item list reads as names. A list of statements does not."""
    if not items:
        return False
    lengths = sorted(len(i) for i in items)
    return lengths[len(lengths) // 2] <= LABEL_CHARS


def _from_rows(rows, key, title, kicker, vocabulary, takeaway, limit=6):
    ci = _label_column(rows)
    head = squeeze(rows[0][ci]) or "Compared"
    items = [squeeze(r[ci]) for r in rows[1:] if len(r) > ci and squeeze(r[ci])][:limit]
    if len(items) < 2:
        return None
    note_col = ci + 1 if ci + 1 < len(rows[0]) else max(0, ci - 1)
    notes = [squeeze(r[note_col]) if len(r) > note_col else ""
             for r in rows[1:1 + limit]]
    return Subject(key=key, title=title, kicker=kicker, head=head, items=items,
                   notes=notes, weights=_weights(rows, items),
                   vocabulary=vocabulary, takeaway=takeaway)


def from_blog_post(post, limit=6):
    """Adapter for backend/data/blog-posts.json entries."""
    kicker = (post.get("primary_category") or "ib academy").replace("-", " ").upper()
    takeaway = (post.get("key_takeaways") or [post.get("excerpt", "")])[0]
    vocab = [squeeze(t).replace("-", " ").upper()
             for t in (post.get("glossary_terms") or [])]
    tables = md_tables(post.get("body_markdown", ""))
    tables.sort(key=lambda r: -(len(r) * len(r[0])))
    for rows in tables:
        subject = _from_rows(rows, post["slug"], post.get("h1") or post["title"],
                             kicker, vocab, takeaway, limit)
        if subject:
            return subject
    # No table: fall back to the post's own key takeaways as the item list.
    points = [squeeze(k) for k in (post.get("key_takeaways") or [])][:limit]
    if len(points) >= 2:
        return Subject(key=post["slug"], title=post.get("h1") or post["title"],
                       kicker=kicker, head="Key points", items=points,
                       notes=[""] * len(points), vocabulary=vocab, takeaway=takeaway)
    return None


def from_glossary_term(term, limit=6):
    """Adapter for backend/data/glossary-enriched.json entries.

    Prefers the term's own comparison block, then its at-a-glance rows, then its
    steps — three different shapes that all reduce to the same item list.
    """
    kicker = (term.get("child_category") or term.get("parent_category")
              or "glossary").upper()
    vocab = [squeeze(v).upper() for v in _aka(term)]
    takeaway = (term.get("key_takeaways") or [term.get("why_it_matters_for_partnership", "")])
    takeaway = takeaway[0] if isinstance(takeaway, list) and takeaway else str(takeaway)
    title = term.get("term") or term.get("slug", "")

    comparison = term.get("comparison") or {}
    rows = comparison.get("rows") or []
    cols = comparison.get("columns") or []
    if rows and cols:
        subject = _from_rows([cols] + rows, term["slug"], title, kicker, vocab,
                             takeaway, limit)
        if subject:
            return subject

    glance = term.get("at_a_glance") or []
    if len(glance) >= 2:
        return Subject(key=term["slug"], title=title, kicker=kicker,
                       head="At a glance",
                       items=[squeeze(g.get("label", "")) for g in glance[:limit]],
                       notes=[squeeze(g.get("value", "")) for g in glance[:limit]],
                       vocabulary=vocab, takeaway=takeaway)

    steps = term.get("steps") or []
    if len(steps) >= 2:
        return Subject(key=term["slug"], title=title, kicker=kicker, head="How it works",
                       items=[squeeze(s.get("title", "")) for s in steps[:limit]],
                       notes=[squeeze(s.get("detail", "")) for s in steps[:limit]],
                       vocabulary=vocab, takeaway=takeaway)
    return None


def _aka(term):
    raw = term.get("aka")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            import ast

            parsed = ast.literal_eval(raw)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, SyntaxError):
            return []
    return []
