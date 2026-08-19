"""Render candidate directions against unlike subjects, audit them, and lay them out.

Step 7 of the method in HEROART.md says to look at a new direction against four
unlike articles at card size, in a browser, before believing it works. Most of the
bugs in this system's history were invisible on the one article being designed
against, and several were invisible to the audit as well.

That step is easy to skip while it is a paragraph of prose, so it is a function.
"""
import html
import pathlib

from .audit import check
from .worlds import HUE_WHEEL, palette
from .draw import seedof

PAGE_CSS = """
:root { color-scheme: dark; }
body { margin:0; background:#0c0c10; color:#c8cfda;
       font:14px/1.5 Inter,system-ui,sans-serif; }
h1 { font-size:17px; margin:26px 20px 4px; color:#e8edf5; }
h2 { font-size:13px; margin:30px 20px 10px; color:#8b95a6; font-weight:600;
     letter-spacing:.04em; text-transform:uppercase; }
p.note { margin:0 20px 14px; color:#7b8697; font-size:13px; max-width:70ch; }
.row { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; padding:0 20px; }
.c { background:#000; border-radius:12px; overflow:hidden; }
.c svg { display:block; width:100%; height:auto; }
.m { padding:5px 9px; font:11px ui-monospace,monospace; color:#6b7688; background:#15161b; }
.bad { color:#fca5a5; background:#2a1417; padding:5px 9px; font:11px ui-monospace,monospace; }
"""


def contact_sheet(directions, subjects, out_path, title="Direction preview",
                  kind="cover", hues=None):
    """One row per direction, one column per subject, faults printed under each.

    `directions` is a list of Direction instances, `subjects` a list of Subject. The
    hue changes per column so a row is never judged in one colour — a motif that only
    works in violet is a motif that does not work.
    """
    hues = hues or [HUE_WHEEL[(i * 9) % len(HUE_WHEEL)] for i in range(len(subjects))]
    out = [f"<style>{PAGE_CSS}</style><h1>{html.escape(title)}</h1>",
           f'<p class="note">{len(directions)} directions &times; {len(subjects)} '
           f'unlike subjects, at {kind} size. Anything the layout audit flags is '
           f'printed under the image it came from.</p>']
    total_faults = 0
    for d in directions:
        out.append(f"<h2>{html.escape(d.key)} &mdash; {html.escape(d.name)} "
                   f"<span style='text-transform:none;font-weight:400'>"
                   f"&middot; {html.escape(d.fits)}</span></h2>")
        out.append('<div class="row">')
        for subject, hue in zip(subjects, hues):
            colours = palette(hue)
            uid = f"p{seedof(d.key + subject.key) % 999983}_"
            svg = (d.cover(subject, colours, uid) if kind == "cover"
                   else d.hero(subject, colours, uid))
            faults = check(svg, kind=kind, bleeds=d.bleeds)
            total_faults += len(faults)
            out.append(f'<div><div class="c">{svg}</div>'
                       f'<div class="m">hue {hue} &middot; {html.escape(subject.key)}</div>'
                       + "".join(f'<div class="bad">{html.escape(f)}</div>'
                                 for f in faults) + "</div>")
        out.append("</div>")
    path = pathlib.Path(out_path)
    path.write_text("\n".join(out), encoding="utf-8")
    return total_faults
