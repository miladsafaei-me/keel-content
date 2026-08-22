# keel-content — subject-driven card and hero art

`keel_content.heroart` builds a listing cover and an article hero for every post or
glossary term, from **the content's own words**. It is deterministic, it balances the
whole corpus at once, and it checks the picture it produced before letting it ship.

It is Django-free on purpose. It is a renderer, and a renderer that imports a web
framework cannot be run from a script, a notebook or a test.

> This supersedes `keel_content.core.hero` for projects that want art derived from what
> an article compares. The older module (five brand styles over six abstract motifs,
> chosen from a topic) is still what SignalBots ships and is not going anywhere; pick
> one per project rather than mixing them.

## 1. The premise

Our content already names its own subject. A post's comparison table has, in the
column that carries names, the exact set of things the post weighs up. A glossary term
ships a `comparison` block with the same shape, plus `at_a_glance` rows and `steps`.

So a picture never has to guess a topic — it is handed the article's own words. That is
the whole idea, and it is what keeps the art honest: **an image can only say what the
article already said.**

## 2. Adopting it in a project

Write a wrapper. That is the entire integration:

```python
#!/usr/bin/env python3
import pathlib, sys
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO.parent / "keel-content/src"))     # or install the package
from keel_content.heroart import Paths, main

PATHS = Paths(
    posts=REPO / "backend/data/blog-posts.json",
    glossary=REPO / "backend/data/glossary-enriched.json",
    extra_posts=(REPO / "docs/blog/pipeline/legacy-posts-subjects.json",),
    order=REPO / "docs/blog/pipeline/feed-order.json",
    hero_dir=REPO / "backend/media/blog-heroes",
    card_dir=REPO / "backend/media/blog-cards",
    og_dir=REPO / "backend/media/blog-og",
)
if __name__ == "__main__":
    raise SystemExit(main(paths=PATHS))
```

```bash
# everything, with OG rasters, failing the run on any layout fault
python3 make_hero_art.py blog --og --strict --report /tmp/r.json --faults /tmp/f.txt

# a preview that touches nothing under media/
python3 make_hero_art.py blog --out-dir /tmp/preview

# sign the canvas with your own brand (two directions render a wordmark)
python3 make_hero_art.py blog --og --strict --wordmark "Your Brand"
```

**Pass `--wordmark` or no wordmark is drawn, and that is deliberate.** Two of the
directions sign their canvas in the lower-left corner. The engine has no idea which site
it is rendering for, so the name has to come from the caller; an unset value renders
nothing, because a hero signed with the wrong brand is worse than one signed with none.
Set it in the same command your deploy runs, not by hand afterwards.

Then three host-side pieces, none of which the engine can do for you:

**Serve every image with a token derived from its own bytes.** Nothing in here writes a
version number. A re-render must be the whole job — a hand-maintained `?v=` is how a
corpus ends up half stale, and it cannot bust the posts an importer never sees.

```python
def file_version(path, length=10):
    """Short stable token for a file's contents. Deliberately not the mtime: a
    container rebuild rewrites every mtime and would bust caches for images whose
    bytes never changed."""
    st = os.stat(path)                       # cache on (st.st_mtime_ns, st.st_size)
    return hashlib.blake2b(open(path, "rb").read(), digest_size=8).hexdigest()[:length]
```

**Record the published feed order.** `Paths.order` points at a JSON file — either
`{"order": [slug, ...]}` or a bare list, newest first. It is what lets the engine keep a
page varied. Refresh it when posts publish:

```bash
ssh HOST "podman exec APP-web python manage.py shell -c \
  \"import json; from blog.models import Post; \
    print('JSON'+json.dumps(list(Post.objects.filter(status=Post.Status.PUBLISHED) \
      .order_by('-published_at','-id').values_list('slug',flat=True))))\"" \
  | grep '^JSON' | sed 's/^JSON//'
```

Posts missing from it still render; they fall to the end of the ordering and lose the
page-level spread. `--no-order` ignores it entirely.

**Track the output in git** (`git add -f` if `media/` is ignored) so a deploy that
resets the checkout carries the art with it.

## 3. Hard rules

1. **Words come from the Subject, never from the direction.** A direction supplies
   composition; the content supplies every string. No direction invents a label.
2. **Numbers are drawn only when they are real.** Proportional widths and gauge needles
   move only when `Subject.weights` was populated from a numeric column. Nothing is
   invented to make a picture look better. **A stated count is `Subject.total`, never
   `Subject.n`** — `n` is what survived truncation, so a direction that prints it prints
   the size of its own frame. Read off `n`, the chapter plate said "4" on almost every
   card in a corpus whose articles compare two to six things.
3. **Cover safe area.** Covers keep every element inside `draw.COVER_PAD` (84 px on the
   1200x675 canvas). The single exception is a direction whose idea *is* leaving the
   frame; it sets `bleeds = True` and says so in its docstring. Everything else that
   touches an edge is a bug.
4. **Type is sized to the words; the words are not cut to the type.** Labels are the
   article's own — "Tier" and "Regulated activities (permissions)" arrive at the same
   slot. Every direction sizes its text to the room it has (`draw.txt_fit`, or
   `draw.fit`/`draw.fit_all` where it may wrap), and only text that will not fit at
   `draw.MIN_LABEL` is trimmed — on a **word boundary**, never mid-word, never
   silently. A `maxlen` on a direction is a ceiling that stops runaway prose reaching
   the renderer, not a target.
5. **One type size per role per card.** Fitting each label on its own gives a card as
   many sizes as it has labels, which reads as carelessness rather than as emphasis.
   `draw.fit_all` picks one size for a set, decided by its longest member.
6. **A motif must be honest about what it can hold.** `split` gives each item a whole
   panel and takes sentences; `ladder` centres a label over its own step with a
   neighbour either side and takes short names only; `plate` runs items together on one
   line and shows fewer rather than cutting them. `select.PROSE_HOME` routes a subject
   whose items are statements to a motif that never promised to label anything.
7. **Determinism.** Same slug, same image, forever. Randomness comes only from
   `draw.seedof(slug)`; never `random`, and never `hash()`, which is salted per process.
8. **`direction:ltr` on the SVG root.** An inline SVG inherits `direction` from its host
   page; under RTL every `text-anchor` flips and text renders from the wrong edge.
   Silent, and it has bitten this codebase twice.
9. **Namespaced ids.** Every gradient and filter id carries a per-image `uid`. Several
   of these end up inline on one page, and a duplicated id makes every later SVG quietly
   use the first one's definition.
10. **Verify in a browser.** These rely on SVG filters that `rsvg-convert` does not
    render faithfully. Render the page in headless Chromium and look at it — checking a
    separately-rasterised PNG is how a broken page got signed off before.
11. **The layout audit is clean before anything ships.** `--strict` exits non-zero on
    any fault. A fault is fixed in the direction, never by loosening the check.

## 4. The layout audit

Every layout fault this system has shipped was invisible to the code that caused it,
because each was a *relationship* between two elements that neither call site knew
about: a label sized correctly for its own text but wider than the plate behind it, a
decorative tile dropped on a word, a step label pushed off the frame and then shifted
back onto the panel it names, type shrunk past reading. A direction cannot catch these
by reading itself, and a person catches them only by looking at every image.

So [`heroart/audit.py`](src/keel_content/heroart/audit.py) reads the finished SVG — the
artifact, not the intent. It walks the tree, resolves transforms, gives every text run a
polygon using the same metrics that placed it, and asks:

| check | what it means |
|---|---|
| leaves the frame | any part of a word outside the canvas |
| outside the cover safe area | a cover word inside `COVER_PAD` of the edge |
| text over text | two words printed across each other |
| painted over | something drawn after a word covers it |
| lands on a surface that is not its own | the nearest surface under a word is not the plate that backs it — a lit panel, a tile from the field behind |
| crowds the label plate | a loose decoration parked inside a plate's air (`BREATH`) |
| type too small | a content label under `MIN_LABEL`; mono eyebrows have their own floor |
| too little contrast | a word within `MIN_CONTRAST` of what it is printed on — present in the file, absent from the picture |
| content leaves the frame half empty | the drawn content spans less than `MIN_SPREAD_X` × `MIN_SPREAD_Y` of the safe area — a small picture marooned in a large frame |
| content presses the margin | anything drawn reaches past the safe area — crowded even where it is technically inside |
| label too long / too much text on the card | a cover being read rather than seen |

Run it on its own against any SVG:

```python
from keel_content.heroart import check
faults = check(svg_text, kind="cover", bleeds=False)
```

The contrast check resolves gradient fills to their mean stop colour, because almost
every fill in these images is a gradient and a check that gives up on `url(#…)` gives
up on the pairings it exists to catch. It ignores a gradient that is mostly
transparent — a wash over what is behind it is not a surface — and it holds an
approximate `path` or `polygon` box to a higher overlap before treating it as the
ground under a word, since a curve's box overstates it.

### Four things it took a wrong answer to learn

* **Measure polygons, not boxes.** A 765x66 label plate turned seven degrees has an
  axis-aligned box 158 tall. Measured that way a fanned stack looks like every label
  overlaps every other — a fault in the ruler, not in the image.
* **Model every transform the directions emit.** `skewY` was missing at first, so every
  step of a staircase was measured in the wrong place and the checks built on those
  boxes silently stopped meaning anything. And `transform="A B C"` composes as
  `A(B(C(p)))` — applying them left to right is harmless while each transform holds one
  operation, and wrong the moment one holds three.
* **A collision fixed by breaking the meaning is not fixed.** The frosted-sheet motif
  first tilted each name plate about its own sheet's centre, which slid the plates into
  one another. Lifting the names out into one shared column ended the collisions and the
  audit went quiet — but four bars spanning four sheets belong to no sheet at all, and
  the motif's whole idea is that a sheet you can see and a name you can read are the
  same object. **When a check goes quiet, look at the picture before believing it.**
* **A rule that fires on good work is worse than no rule.** The first crowding check
  flagged 445 things, nearly all of them a motif's own panels doing their job. A check
  nobody can trust is a check everybody learns to skip.

## 5. How a direction is chosen

Two stages, both pure functions of the content plus a hash of the slug.

**Per item.** `select.score` reads the table's own column header first (a head of `Rail`
or `Method` is a list of ways to get paid; `Tier` is an ordered ladder), then the shape
of the data (how many items, how long their names, whether a numeric column exists),
then framing vocabulary. A small stable jitter breaks ties per slug.

**Across the corpus.** `select.assign` places the confident picks first and applies four
pressures at once: a per-direction cap and floor so no motif takes over or dies out, a
per-cluster penalty because sibling posts share a table header and therefore score
identically, and a **feed-window limit** so no motif fills a page and no two neighbouring
cards share one. Colour is allocated last, in feed order, from a comb of hues that
rotates page to page.

A `--manifest` of `{slug: {direction, world|hue}}` overrides any pick by hand.

> **Measured, not assumed:** an earlier version asked a model to pick a direction per
> post. Against this scorer the agents added no quality — they read the same signals and
> then converged, one run putting 40 of 153 posts on the same direction, so a mechanical
> balancing pass had to overrule 93 of their choices anyway. Rules that encode the same
> reasoning cost nothing, run in milliseconds over the whole corpus, are reviewable, and
> stay stable across runs.

## 5b. Surfaces: the second axis

A palette has two independent decisions — which hue, and **what the hue is allowed to
touch**. The second is the surface, and it is where variety comes from without a single
new motif: twenty-five directions on four surfaces are a hundred distinct cards.

| surface | ground | where the hue goes |
|---|---|---|
| `paper` | a near-white sheet, neutral | the elements |
| `mist` | a pale tint of the post's own hue | the elements |
| `dusk` | a mid-dark ground in the post's hue | the ground and the elements |
| `deep` | a deep ground in the post's hue | the ground and the elements |

Two light and two dark, spread across the feed page the same way hues are, so a page
carries all four.

**A dark ground carries the post's hue; it is never one fixed colour.** A neutral
charcoal held every dark card at the same value and threw away the one thing a dark
ground is good at — being the post's own colour at full depth. `dusk` and `deep` are
what give a feed its navy, green, violet and red cards. The light surfaces stay quiet
by design: on a near-white sheet the colour belongs to what is drawn.

**The register is pastel by construction.** No role is fully saturated and none is
black: saturation tops out near half, the lit roles sit high on the luminance scale,
and depth is a soft tonal step rather than a cast shadow — `draw.SHADOW_LIFT`,
`SHADOW_BLUR` and `SHADOW_OPACITY` scale every direction's request down to a hint that
one thing is above another.

**There is no container surface, and no motif paints a second ground.** A filled panel
inside a filled ground is two backgrounds, and the second one is always the weaker
picture.

**The one rule to get right when writing a direction:** `ink` is the type that reads on
`page`, `mid` and `lift`; `onink` is the type that reads on `deep` and `accent`. Roles
keep their names across all four surfaces while their values flip, so a plate that was
dark under light type becomes light under light type — which is why the audit checks
contrast rather than trusting the author. Two corollaries learned the same way:

* **A structure colour is not a type colour.** `faint` and `dim` exist to sit behind
  content; on a light ground they are a pale word on a pale sheet.
* **An object's gradient must stay in one tonal band.** A fill running from the
  lightest role to the darkest has no single text colour that can be read across it, so
  it fails on whichever end the author was not looking at.

Two `p` keys a direction may read beyond the roles: `p["light"]`, true only on `paper`,
for the rare element that must invert; and `p["ground"]`, what content is effectively
drawn over, which is the container rather than the page on `panel`.

## 6. Keeping a feed from looking like one article repeated

Sameness has four independent layers, and each needs its own lever. The first three are
corpus-wide; the fourth is the one that matters to a reader and the one everybody
forgets.

1. **Colour — one palette per post, not per category.** A hue comes off a 40-step
   curated wheel; the nine palette roles are solved for a fixed **target luminance** per
   role, so rotating the hue never changes the tonal register. Matching HSL lightness
   instead washes out half the wheel — a magenta at L=63% reads far lighter than a blue
   at the same number.
2. **Motif — a per-cluster repeat penalty.** Siblings share a table header, so they
   score identically without it.
3. **Composition — variant axes inside one motif.** `draw.variant(key, axis, options)`
   picks stably per post; axes are named so two never correlate.
4. **The page.** A corpus-wide number says nothing about what lands on one screen. Read
   the published order and work in the blocks the listing paginates into: no motif over
   `WINDOW_REPEAT` of a page, no two neighbouring cards on one motif, and a comb of hues
   24 degrees apart that rotates onto the next page.

Two traps, both of which shipped:

* **A balancing rule that can be exhausted must say so, not degrade quietly.** A per-hue
  quota of three across a 22-hue wheel is 66 slots; on a 153-post corpus everything past
  post 66 fell back to the raw hash, and every page carried duplicate colours while the
  corpus metric looked healthy.
* **Rendering a corpus in two commands is the same bug as colour-by-category.** Two
  sources rendered separately each enforce their caps against only their own half, while
  the reader sees both halves interleaved. Use `extra_posts`, not a second run.

Do **not** reach for randomness that breaks determinism, and do not vary the tonal
register itself — the register is what holds a feed together while everything else moves.

## 7. How to invent a direction

The motifs that ship are not special. They are answers to the same question, and the
method that produced them is the reusable part.

**Step 1 — start from a visual device, not from a topic.** The failure mode is picking a
subject ("regulation") and drawing an icon for it. Pick a way of *seeing*: physical
objects, flow, perspective, depth of field, typographic scale, orbit, division of the
frame, translucency, instrumentation, paper. Ask which device is not yet in the set.

**Step 2 — bind the device to the Subject, not to the topic.** Every direction consumes
the same `Subject`: a head, an item list, optional notes, optional weights. If your
device cannot be driven by that shape, it is decoration. The test: swap in a different
article's subject and the image must change meaningfully.

**Step 3 — decide what it does when the numbers are missing.** Most posts have no
numeric column. A direction must degrade honestly — show index numbers rather than fake
percentages, an opening fan rather than fake proportions. Never fabricate a quantity to
complete a composition.

**Step 4 — design the card size first.** A cover is read at about 320 px wide. If the
idea only works large it is a hero-only direction and should say so.

**Step 5 — build it as a `Direction` subclass.** Implement `motif(p, uid, s, box, big)`;
the shared frames handle title, ground, wordmark and the two sizes. Take colours only
from the world roles (`deep`, `mid`, `lift`, `ink`, `dim`, `faint`, `accent`, `hot`,
`good`) — never a literal hex. Set `bleeds`, `cover_items` and `cover_maxlen` honestly:
they are the direction's own statement of what it can hold.

**Step 6 — add a variant axis, and make it structural.** An axis that only changes a
radius is not worth the code. Mirror the layout, reverse the fan, move the light, change
which element is lit.

**Step 7 — run the audit, then look at four unlike articles at card size in a browser.**
Not one flagship article: four, from different clusters. Most of the bugs in this
system's history were invisible on the one article being designed against, and several
of them were invisible to the audit too.

**Step 8 — write its `fits` string**, one line naming the kind of article it suits, and
add it to `DIRECTIONS`. `fits` is what the scorer's routing is documented against, so a
vague one never gets chosen well.

## 8. Adopting a candidate

`DIRECTIONS` holds twenty-two motifs — ten from the original set and twelve built by
the method in §7. Three more were built and dropped: a pile of tokens, a field of pins
and a stack of strata, each of which said the same thing as a motif already in the set
and said it less clearly.

| device | motifs |
|---|---|
| objects and depth | `stack` `glass` `ladder` |
| flow and sequence | `flow` `track` `funnel` `tree` `pulse` |
| a field or a frame | `grid` `split` `matrix` `compass` `orbit` |
| instruments and measures | `gauge` `dial` `bars` `scale` `rings` |
| records and marks | `tape` `passport` `seal` `plate` |

New candidates live in `directions_proposed.py` until they have been looked at, because
adding a direction re-assigns every post in a corpus, not only the posts that take the
new motif. Adopting one means moving its class into `directions.py`, adding it to
`DIRECTIONS`, and giving it head-word routing in `choose.HEAD_MAP` if it should be
reachable without a manifest.

Preview any set against unlike subjects and surfaces with the harness §7 step 7 asks
for:

```python
from keel_content.heroart.preview import contact_sheet
contact_sheet(DIRECTIONS, subjects, "/tmp/sheet.html",
              surfaces=["tinted", "slate", "paper", "panel"])   # returns the fault count
```

The hue changes per column on purpose: a motif that only works in violet is a motif
that does not work.

## 9. Scaling to another content type

Write one adapter that returns a `Subject`. Nothing in `draw.py` or `directions.py`
changes. `subject.from_blog_post` and `subject.from_glossary_term` are the two that
ship; both are shapes keel-cms already produces.

The one judgement in an adapter is **which column names the things being compared**.
Prefer the first column that carries names: skip a column of bare ranks, skip one whose
values are statements rather than names, and do not accept a later column whose values
repeat (a ratings column reads short and label-shaped and says nothing — "High, Medium,
High, High" is four labels and one fact). When no column names anything, leave
`Subject.named` false and let the selector route the post to a typographic motif.
