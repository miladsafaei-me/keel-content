"""Subject-driven card and hero art: images built from what the content compares.

The premise is that our content already names its own subject. A post's comparison
table has, in the column that carries names, the exact set of things the post weighs
up; a glossary term ships the same shape. So a picture never has to guess a topic —
it is handed the article's own words, and it never says anything the text did not.

    from keel_content.heroart import Paths, main

    main(paths=Paths(
        posts=REPO / "backend/data/blog-posts.json",
        order=REPO / "docs/blog/pipeline/feed-order.json",
        hero_dir=REPO / "backend/media/blog-heroes",
        card_dir=REPO / "backend/media/blog-cards",
        og_dir=REPO / "backend/media/blog-og",
    ))

Four things make it repeatable rather than a one-off, and each exists because its
absence cost a re-render:

* **Deterministic.** Same slug, same image, forever. Randomness comes only from
  `draw.seedof(slug)` — never `random`, never `hash()`, which is salted per process.
* **Assigned over the whole corpus at once**, including the feed order the reader
  actually scrolls, so no motif or colour takes over a page.
* **Audited.** `audit.check` reads the SVG that was produced and fails the run on
  geometry no direction can see about itself.
* **Content-addressed.** Nothing in here writes a version number; the host serves each
  file with a token derived from its bytes.

This module is Django-free on purpose: it is a renderer, and a renderer that imports a
web framework cannot be run from a script, a notebook or a test.
"""
from .audit import check
from .build import Paths, main
from .directions import BY_KEY, DIRECTIONS, Direction
from .draw import MAX_LABEL, MIN_LABEL, seedof
from .select import assign, load_manifest, score
from .subject import Subject, from_blog_post, from_glossary_term
from .worlds import HUE_WHEEL, allocate, palette

__all__ = [
    "BY_KEY", "DIRECTIONS", "Direction", "HUE_WHEEL", "MAX_LABEL", "MIN_LABEL",
    "Paths", "Subject", "allocate", "assign", "check", "from_blog_post",
    "from_glossary_term", "load_manifest", "main", "palette", "score", "seedof",
]
