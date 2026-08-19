"""Heroart as an *in-text illustration*: one inline SVG that follows the page theme.

`build.py` writes files — a hero and a card per post, rasterised, content-addressed,
served by the host. That is the right shape for a cover. It is the wrong shape for a
picture that sits between two paragraphs of an article, because a file baked at one
surface cannot follow a reader who toggles dark and light, and the usual escapes (a
second file, a `<picture>` swap) are exactly what a design system should not ship.

So this module renders the same composition a different way. It draws the motif on a
light surface, then strips every palette colour out of the markup and replaces it with
a **role class** — `hai-f-accent` for a fill, `hai-s-ink` for a stroke, `hai-p-lift`
for a gradient stop. What each role *is* comes from CSS custom properties the host
defines once per theme, so a single SVG is correct on both, with no inline style, no
second asset and no JavaScript.

    from keel_content.heroart import illustration
    svg, report = illustration(subject)      # subject from `from_glossary_term`

The host stylesheet owes this module two things, and `token_css` writes both:

* the generic role rules — `.hai-f-accent { fill: var(--hai-accent) }` and so on;
* the role values per variant and per theme — `--hai-accent` under a variant class.

`variant_for` picks a term's variant from its own key, so the choice is deterministic
and spread over the corpus without any state.
"""
import re

from .audit import check
from .choose import score
from .directions import BY_KEY, DIRECTIONS
from .draw import seedof
from .worlds import HUE_WHEEL, palette

#: The palette roles that may appear in drawn output. `hue`, `surface`, `light` and
#: `ground` are metadata rather than colours, so they never reach the markup.
ROLES = ("page", "deep", "mid", "lift", "ink", "onink", "dim", "faint", "accent",
         "hot", "good", "shade")

#: `shade` is the one role `worlds.palette` does not produce: drop shadows are drawn
#: in flat black, which is correct on a light sheet and invisible on a dark one. It is
#: listed as a role so that colour is themed like every other and `untokenised` can
#: stay a hard gate rather than a list with one permanent entry in it.

#: Which SVG attribute carries a colour, and the class prefix that replaces it. The
#: prefixes are short because every drawn element carries at least one.
COLOUR_ATTRS = {"fill": "f", "stroke": "s", "stop-color": "p", "flood-color": "d"}

#: How many colour variants the corpus is spread over. Six is enough that two terms
#: opened back to back rarely match, and few enough that the host's token block stays
#: something a person can read.
VARIANTS = 6

#: The surfaces the two themes are drawn from. Light is `mist` rather than `paper`
#: because an article already sits on white: a picture that is also white loses its
#: edge and stops reading as a figure.
LIGHT_SURFACE, DARK_SURFACE = "mist", "dusk"

_TAG = re.compile(r"<([a-zA-Z][\w:-]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)(\s*/?)>")
_ATTR = re.compile(r'([\w:-]+)="([^"]*)"')
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def variant_for(key):
    """Which of the `VARIANTS` palettes this key gets. Deterministic, never random."""
    return seedof(str(key)) % VARIANTS


def hue_for(variant):
    """The wheel hue behind one variant, spaced evenly around the curated arc."""
    return HUE_WHEEL[(variant * len(HUE_WHEEL)) // VARIANTS]


def direction_for(subject, keys=None):
    """The best-fitting direction for one subject, on its own rather than in a corpus.

    `choose.assign` balances a whole feed at once, which is the right call for cards a
    reader scrolls past together. A term page shows one picture, so there is nothing
    to balance — the strongest fit simply wins, and ties break on the direction key so
    the answer never depends on list order.
    """
    pool = [BY_KEY[k] for k in keys] if keys else list(DIRECTIONS)
    return max(pool, key=lambda d: (score(subject, d.key), d.key))


def _tokenise(svg, colours):
    """Replace every palette colour attribute with its role class.

    Returns `(markup, leftover)` where `leftover` is every hex literal still in the
    markup afterwards — a colour no role explains, which would not follow the theme
    and is therefore a fault the caller must see rather than a detail it may ignore.
    """
    by_hex = {"#000": "shade", "#000000": "shade"}
    for role in ROLES:
        value = colours.get(role)
        if value:
            by_hex.setdefault(value.lower(), role)

    def _rewrite(match):
        name, attrs, close = match.group(1), match.group(2), match.group(3)
        classes, out = [], attrs
        for attr, prefix in COLOUR_ATTRS.items():
            for found in _ATTR.finditer(attrs):
                if found.group(1) != attr:
                    continue
                role = by_hex.get(found.group(2).strip().lower())
                if not role:
                    continue
                classes.append(f"hai-{prefix}-{role}")
                out = out.replace(found.group(0), "", 1)
        if not classes:
            return f"<{name}{out}{close}>"
        for found in _ATTR.finditer(out):
            if found.group(1) == "class":
                merged = f'class="{found.group(2)} {" ".join(classes)}"'
                return f"<{name}{out.replace(found.group(0), merged, 1)}{close}>"
        return f'<{name} class="{" ".join(classes)}"{out}{close}>'

    markup = _TAG.sub(_rewrite, svg)
    return markup, sorted(set(_HEX.findall(markup)))


def illustration(subject, *, variant=None, direction=None, pool=None, classes="hai"):
    """Draw `subject` as one theme-following inline SVG.

    `pool` restricts the motifs this call may choose from. A host that knows something
    about its own content that the scorer cannot — that its comparisons carry no
    weights, say, so any motif implying one side is larger would be inventing data —
    passes the motifs it will accept rather than editing the scorer for everyone.

    Returns `(markup, report)`. The report carries the direction and variant chosen,
    whatever the layout audit found, and any colour that survived tokenising — all
    three are things a caller should be able to gate on, and none of them are
    inferable from the markup once it is built.
    """
    picked = BY_KEY[direction] if direction else direction_for(subject, pool)
    variant = variant_for(subject.key) if variant is None else int(variant) % VARIANTS
    colours = palette(hue_for(variant), LIGHT_SURFACE)
    uid = f"hai{seedof(picked.key + subject.key) % 999983}_"
    raw = picked.cover(subject, colours, uid)
    faults = check(raw, kind="cover", bleeds=picked.bleeds, page=colours["ground"])
    markup, leftover = _tokenise(raw, colours)
    markup = markup.replace(
        "<svg ", f'<svg class="{classes} {classes}--v{variant}" ', 1)
    return markup, {"direction": picked.key, "name": picked.name,
                    "variant": variant, "faults": faults, "untokenised": leftover}


def token_css(selector=".hai", light_attr='html[data-keel-theme="light"]'):
    """The stylesheet this module needs, generated rather than hand-kept in sync.

    Two blocks. The role rules bind a class to a property once. The variant blocks
    give each role its value, dark first because a drawn figure is dark-surface work
    by default, then light under whatever attribute the host sets on toggle.
    """
    lines = ["/* Generated by keel_content.heroart.inline.token_css — do not hand-edit. */"]
    for attr, prefix in COLOUR_ATTRS.items():
        for role in ROLES:
            lines.append(f"{selector} .hai-{prefix}-{role} {{ {attr}: var(--hai-{role}); }}")
    for variant in range(VARIANTS):
        hue = hue_for(variant)
        for label, surface in (("", DARK_SURFACE), (light_attr, LIGHT_SURFACE)):
            colours = dict(palette(hue, surface))
            colours["shade"] = "#000000" if surface == LIGHT_SURFACE else "#03070f"
            body = " ".join(f"--hai-{r}: {colours[r]};" for r in ROLES)
            scope = f"{label} {selector}--v{variant}" if label else f"{selector}--v{variant}"
            lines.append(f"{scope} {{ {body} }}")
    return "\n".join(lines) + "\n"
