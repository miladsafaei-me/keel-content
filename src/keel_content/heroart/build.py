"""Render hero and cover art for every post or glossary term, in one pass.

The host supplies a `Paths` and calls `main`; a wrapper of a dozen lines is the whole
integration. See HEROART.md for the wrapper and the arguments.

Writes, per item:
    <hero_dir>/<slug>.svg   hero, title baked in, also the OG source
    <card_dir>/<slug>.svg   listing-card cover, no title
    <og_dir>/<slug>.jpg     1200px raster of the hero (with --og)

Rasterising uses headless Chromium, not rsvg-convert: these images rely on SVG
filters (drop shadows, blur, turbulence) that only the browser engine renders
faithfully. Verify output in a browser for the same reason.
"""
import argparse
import dataclasses
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

from . import audit
from . import subject as subject_mod
from .directions import BY_KEY, DIRECTIONS
from .draw import seedof
from .select import assign, load_manifest
from .worlds import WORLDS, palette

@dataclasses.dataclass
class Paths:
    """Where one host keeps its content and where it wants its art.

    Every field is the host's to decide; the engine knows none of them. A project
    wires this once, in a wrapper of a dozen lines, and nothing else about the host
    reaches the renderer.
    """
    posts: pathlib.Path = None          # blog-posts.json-shaped source
    glossary: pathlib.Path = None       # glossary-enriched.json-shaped source
    extra_posts: tuple = ()             # merged into the SAME assignment
    order: pathlib.Path = None          # published feed order, newest first
    hero_dir: pathlib.Path = None
    card_dir: pathlib.Path = None
    og_dir: pathlib.Path = None

CHROME_CANDIDATES = [
    pathlib.Path.home() / ".cache/ms-playwright/chromium_headless_shell-1234/"
    "chrome-headless-shell-linux64/chrome-headless-shell",
    pathlib.Path("/usr/bin/chromium-browser"),
    pathlib.Path("/usr/bin/chromium"),
    pathlib.Path("/usr/bin/google-chrome"),
]


def find_chrome():
    for path in CHROME_CANDIDATES:
        if path.exists():
            return path
    found = shutil.which("chromium") or shutil.which("chromium-browser")
    return pathlib.Path(found) if found else None


def read_posts(path):
    """Items from a blog-posts.json-shaped file, which may be a dict or a bare list."""
    data = json.loads(path.read_text())
    return data["posts"] if isinstance(data, dict) else data


def load_items(kind, paths):
    """Return (items, adapter, category_getter) for a content kind."""
    if kind == "blog":
        return (read_posts(paths.posts), subject_mod.from_blog_post,
                lambda item: item.get("cluster") or item.get("primary_category"))
    if kind == "glossary":
        return (json.loads(paths.glossary.read_text()), subject_mod.from_glossary_term,
                lambda item: item.get("child_category"))
    raise SystemExit(f"unknown content kind: {kind}")


def rasterise(chrome, svg_path, jpg_path):
    """Screenshot one SVG at 1200x675 through the browser engine, then encode JPEG.

    Chromium writes a ~790 KB PNG per frame, which is far too heavy to track in git
    or to serve as an OG image; the same frame is ~55 KB as a quality-85 JPEG, and
    social crawlers accept JPEG.
    """
    html = (f'<html><body style="margin:0">'
            f'<img src="{svg_path.as_uri()}" width="1200" height="675">'
            f'</body></html>')
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
        fh.write(html)
        tmp = pathlib.Path(fh.name)
    try:
        raw = jpg_path.with_suffix(".raw.png")
        subprocess.run(
            [str(chrome), "--headless", "--disable-gpu", "--hide-scrollbars",
             "--window-size=1200,675", f"--screenshot={raw}",
             "--virtual-time-budget=2500", tmp.as_uri()],
            check=False, capture_output=True, timeout=90)
        if raw.exists():
            from PIL import Image

            Image.open(raw).convert("RGB").save(
                jpg_path, "JPEG", quality=85, optimize=True, progressive=True)
            raw.unlink()
    finally:
        tmp.unlink(missing_ok=True)


def feed_spread(report, order):
    """How the assignment reads on the page, which is the only view that matters.

    Corpus-wide counts can look balanced while one page carries five of the same
    motif or two cards in the same colour, so the numbers reported here are measured
    over the ten-card windows the feed actually paginates into.
    """
    from .worlds import hue_distance

    pick = {r["slug"]: (r["direction"], r["hue"]) for r in report}
    seq = [pick[s] for s in order if s in pick]
    pages = [seq[i:i + 10] for i in range(0, len(seq), 10)]
    dup = sum(1 for p in pages
              if any(hue_distance(a[1], b[1]) < 20
                     for i, a in enumerate(p) for b in p[i + 1:]))
    crowded = sum(1 for p in pages
                  if max((sum(1 for c in p if c[0] == d)
                          for d in {c[0] for c in p}), default=0) > 3)
    twins = sum(1 for i in range(1, len(seq)) if seq[i][0] == seq[i - 1][0])
    return (f"{len(pages)} pages, {dup} with colours under 20 degrees apart, "
            f"{crowded} with one motif over 3 of 10, "
            f"{twins}/{max(len(seq) - 1, 1)} neighbouring cards on the same motif")


def main(argv=None, paths=None):
    """Render one host's corpus. `paths` is the only thing the engine needs to know."""
    paths = paths or Paths()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("kind", choices=["blog", "glossary"])
    ap.add_argument("--manifest", help="JSON of per-slug direction/world choices")
    ap.add_argument("--posts", help="alternative source file in blog-posts.json shape")
    ap.add_argument("--extra-posts", action="append", default=None,
                    help="additional source files, merged into the SAME assignment; "
                         "defaults to the legacy set for `blog` so all published "
                         "posts are balanced against each other")
    ap.add_argument("--order", help="JSON of published feed order (default: "
                                    "docs/blog/pipeline/feed-order.json)")
    ap.add_argument("--no-order", action="store_true",
                    help="ignore the feed order and balance over the corpus only")
    ap.add_argument("--slugs", nargs="*", help="restrict to these slugs")
    ap.add_argument("--limit", type=int, help="stop after N items")
    ap.add_argument("--out-dir", help="write everything here instead of media/")
    ap.add_argument("--og", action="store_true", help="also write the 1200px OG raster")
    ap.add_argument("--report", help="write a JSON report of every choice made")
    ap.add_argument("--faults", help="write every layout fault to this file")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero when the layout audit finds anything")
    args = ap.parse_args(argv)

    items, adapt, category_of = load_items(args.kind, paths)
    if args.posts:
        items = read_posts(pathlib.Path(args.posts))

    # Every published post has to be assigned in one pass. Splitting the corpus into
    # two runs meant each run enforced the caps and the colour spread against only
    # its own half, while the reader saw both halves interleaved on one page.
    extra = args.extra_posts
    if extra is None and args.kind == "blog" and not args.posts:
        extra = [p for p in paths.extra_posts if pathlib.Path(p).exists()]
    for path in extra or []:
        items = items + read_posts(pathlib.Path(path))

    order = []
    if not args.no_order:
        order_path = pathlib.Path(args.order) if args.order else paths.order
        if order_path and pathlib.Path(order_path).exists():
            order_path = pathlib.Path(order_path)
            data = json.loads(order_path.read_text())
            order = data["order"] if isinstance(data, dict) else data

    manifest = load_manifest(args.manifest)
    valid = set(BY_KEY)

    if args.out_dir:
        base = pathlib.Path(args.out_dir)
        hero_dir, card_dir, og_dir = base / "heroes", base / "cards", base / "og"
    else:
        hero_dir, card_dir, og_dir = paths.hero_dir, paths.card_dir, paths.og_dir
    for d in {hero_dir, card_dir} | ({og_dir} if args.og else set()):
        d.mkdir(parents=True, exist_ok=True)

    chrome = find_chrome() if args.og else None
    if args.og and chrome is None:
        sys.exit("--og needs headless Chromium; none found")

    # Two passes: read every subject, assign directions across the whole corpus so
    # the caps can be enforced, then render. A single pass could not balance.
    pending, skipped = [], []
    for item in items:
        slug = item.get("slug")
        if not slug or (args.slugs and slug not in args.slugs):
            continue
        subject = adapt(item)
        if subject is None:
            skipped.append(slug)
            continue
        pending.append((subject, category_of(item), item.get("role", "")))
        if args.limit and len(pending) >= args.limit:
            break

    assigned = assign(pending, sorted(valid), order=order)
    report, faults = [], []
    for subject, _cluster, _role in pending:
        slug = subject.key
        key, hue = assigned[slug]
        source = "auto"
        entry = manifest.get(slug) or {}
        if entry.get("direction") in valid:
            key, source = entry["direction"], "manifest"
        if entry.get("world") in WORLDS:
            hue = WORLDS[entry["world"]]["hue"]
        if isinstance(entry.get("hue"), int):
            hue = entry["hue"]
        direction = BY_KEY[key]
        colours = palette(hue)
        hero_svg = direction.hero(subject, colours, f"h{seedof(slug) % 999983}_")
        cover_svg = direction.cover(subject, colours, f"c{seedof(slug) % 999983}_")
        # Check the image that was produced, not the intent behind it: every layout
        # fault this project shipped was a relationship between two elements that
        # neither call site could see.
        for kind, markup in (("cover", cover_svg), ("hero", hero_svg)):
            for fault in audit.check(markup, kind=kind, bleeds=direction.bleeds):
                faults.append(f"{slug} [{key} {kind}] {fault}")
        (hero_dir / f"{slug}.svg").write_text(hero_svg, encoding="utf-8")
        (card_dir / f"{slug}.svg").write_text(cover_svg, encoding="utf-8")
        if args.og:
            rasterise(chrome, hero_dir / f"{slug}.svg", og_dir / f"{slug}.jpg")
        report.append(dict(slug=slug, direction=key, hue=hue, source=source,
                           items=subject.n, weights=bool(subject.weights)))
    count = len(report)

    if args.report:
        pathlib.Path(args.report).write_text(json.dumps(report, indent=1))
    from collections import Counter

    print(f"rendered {count} {args.kind} items"
          + (f", skipped {len(skipped)} with no usable subject" if skipped else ""))
    print("directions:", dict(Counter(r["direction"] for r in report)))
    print("distinct hues:", len({r["hue"] for r in report}), "of", count)
    if order:
        print("feed spread:", feed_spread(report, order))
    print("hand-pinned by manifest:", sum(1 for r in report if r["source"] == "manifest"))
    if skipped:
        print("skipped:", ", ".join(skipped[:12]) + ("…" if len(skipped) > 12 else ""))

    if faults:
        kinds = Counter(f.split("] ", 1)[1].split(":")[0].split(" (")[0]
                        for f in faults)
        print(f"\nLAYOUT FAULTS: {len(faults)} across "
              f"{len({f.split(' ')[0] for f in faults})} items")
        for name, count in kinds.most_common():
            print(f"  {count:>4}  {name}")
        if args.faults:
            pathlib.Path(args.faults).write_text("\n".join(faults) + "\n")
            print(f"  written to {args.faults}")
        else:
            for line in faults[:20]:
                print("   ", line)
            if len(faults) > 20:
                print(f"    … and {len(faults) - 20} more (use --faults FILE)")
        if args.strict:
            return 1
    else:
        print("\nlayout audit: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
