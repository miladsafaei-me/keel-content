"""What a consuming site decides about its own art, in one object.

The engine's discipline — determinism, corpus-wide assignment, page-window balancing,
the layout audit — is independent of how the pictures look. Everything else was not:
until this module existed the palette, the surfaces, the motif pack and the scorer
were module-level constants, so a second consumer with a different visual identity had
exactly two options, both bad. It could pass ``--surfaces`` to pick from four grounds
built for somebody else's brand, or it could fork the package.

A ``Skin`` is the seam. It carries the four decisions that belong to a site and none
that belong to the engine:

* **directions** — the motif pack. What kinds of picture this site draws at all.
* **surfaces** — the grounds spread across a feed page.
* **palette** — ``(tone, surface) -> {role: colour}``. The roles are the engine's
  contract and never change; what the roles resolve to is the site's decision.
* **allocate** and **score** — which motif each item gets and which tone, both still
  pure functions of the content plus a hash of the slug.
* **allocate_axes** — anything else that varies per post and has to be spread across
  a page: a composition, a crop, a type scale. The engine passes whatever comes back
  through to the direction inside its palette dict and otherwise ignores it.

The tone axis is deliberately untyped. `PASTEL` uses integer hues off a curated wheel;
a site whose colours *mean* something uses named tones instead, and supplies a
``distance`` so the feed-spread report keeps working for it. The engine never does
arithmetic on a tone — it hands it to ``palette`` and prints it in the report.

`PASTEL` below is the original behaviour, assembled out of the same modules it always
lived in. It is the default, so a host that passes no skin renders exactly what it
rendered before.
"""
import dataclasses

from . import choose as _choose
from . import directions as _directions
from . import worlds as _worlds


def _pastel_allocate(entries):
    """Hues off the curated wheel, combed across each feed page.

    The pastel skin's colour carries no meaning, so it reads nothing from the
    subject: the slug and the reader's position in the feed decide everything.
    """
    return _worlds.allocate([slug for slug, _subject, _direction in entries])


def _pastel_surfaces(entries, choices, blocked):
    return _worlds.allocate_surfaces(
        [(slug, direction) for slug, _subject, direction in entries],
        choices, blocked=blocked)


@dataclasses.dataclass(frozen=True)
class Skin:
    """One site's visual identity, handed to the engine at render time.

    Every field is a decision the engine refuses to make for a consumer. The
    defaults reproduce the pastel skin, so a partial skin is still a valid one —
    a site that wants the original motifs in its own colours overrides `palette`
    and `surfaces` and leaves the rest alone.
    """

    name: str
    #: Direction instances. Their `.key` values are the only motif names that exist
    #: for this skin, so two skins may reuse a key for unrelated motifs.
    directions: tuple
    #: Ground names spread across each feed page. `palette` must accept every one.
    surfaces: tuple
    #: (tone, surface) -> the nine roles plus `ground`, `light` and `surface`.
    palette: callable
    #: (entries) -> {slug: tone}, where entries is [(slug, subject, direction_key)]
    #: in published feed order. Feed order is passed because the set a reader
    #: compares is one page, never the corpus.
    allocate: callable = _pastel_allocate
    #: (entries, choices, blocked) -> {slug: surface}. Same entry shape.
    allocate_surfaces: callable = _pastel_surfaces
    #: (entries) -> {slug: {name: value}}, merged into the palette dict each
    #: direction is handed, after the manifest has had its say. This is where a skin
    #: puts axes the engine has no opinion about — which composition a cover uses,
    #: how close the crop is, how large the readout is set. The engine spreads
    #: motifs, tones and grounds; a skin that varies anything else has to spread that
    #: too, and it has to do it over the same feed order, which is why this is handed
    #: the feed rather than one item. None means the skin adds no axes, which is what
    #: `PASTEL` does, so its output is unchanged by the existence of this seam.
    allocate_axes: callable = None
    #: (subject, direction_key, role) -> float. Higher wins.
    score: callable = _choose.score
    #: Separation between two tones, for the feed-spread report only. Whatever it
    #: returns is compared against 20, so a skin with named tones reports a large
    #: number for "different" and 0 for "the same".
    distance: callable = _worlds.hue_distance
    #: Named tones a --manifest may pin by name, as {name: tone}.
    worlds: dict = dataclasses.field(default_factory=dict)
    #: {surface: (direction keys,)} for pairings that contradict themselves.
    blocked: dict = dataclasses.field(default_factory=dict)
    #: Signed into the corner by the directions that sign their canvas. --wordmark
    #: still overrides it, so a host can render an unsigned proof sheet.
    wordmark: str = ""

    @property
    def by_key(self):
        return {d.key: d for d in self.directions}


#: The original skin: 22 editorial motifs, four pastel grounds, a 40-step hue wheel.
#: Built for an academy that reads as a magazine. Kept as the default so every host
#: that predates this seam renders byte-identical output.
PASTEL = Skin(
    name="pastel",
    directions=tuple(_directions.DIRECTIONS),
    surfaces=tuple(_worlds.SURFACES),
    palette=_worlds.palette,
    worlds={name: pal["hue"] for name, pal in _worlds.WORLDS.items()},
    blocked={"panel": _choose.NO_CONTAINER},
)
