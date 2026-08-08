#!/usr/bin/env python3
"""Turn a /seo-top-pages workbook into a content-pipeline worklist.

A top-pages workbook (e.g. docs/seo/gap/forex-blog-layer-1.xlsx) holds one sheet
per Topic Cluster; inside a sheet each *content* is one Title row (with H1,
Intent, Intent Frame, Entity, Role, Categories, Markets, Audience, Glossary,
Priority, Clarity, Traffic) followed by zero or more continuation rows that carry
only a Competitor URL. This script reconstructs each content as one independent
spec and emits a worklist JSON the generation step fans out over — one fresh
agent per spec, no shared context.

Pure standard library (no pandas / openpyxl): the OOXML read mirrors the sibling
/seo-clustering and /seo-top-pages tools so the xlsx handling stays uniform.

Facet values are passed through as the human-readable NAMES exactly as they
appear in the workbook (already scaffold-vocab validated by the writer). The
ingest step resolves those names to TopicCluster / Category / Market /
AudienceRole / AudienceLevel / Tag rows against the live DB.

Usage:
  parse_top_pages.py <workbook.xlsx> [--top N] [--sheet NAME] [--title "Exact Title" ...]
                     [--date YYYY-MM-DD] [--out path.json]

  --top N      keep the N highest-Priority contents across all sheets
  --sheet NAME keep only contents from this sheet (repeatable)
  --title T    keep only this exact title (repeatable; overrides --top)
  --date D     date prefix for content_id (default: today)
  --out P      write worklist JSON here (default: stdout only)
"""

import argparse
import datetime
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

# Header label -> column index is resolved from the sheet header row, so a column
# reorder in the writer never silently misaligns the parse.
EXPECTED_HEADERS = [
    "Title", "H1", "Intent", "Intent Frame", "Entity", "Content Type", "Role",
    "Categories", "Markets", "Audience", "Glossary Terms", "Priority", "Clarity",
    "# Competitors", "Total Traffic", "Competitor URLs",
]

# Intent Frame (what the title does) -> the pipeline's search_intent enum.
FRAME_TO_INTENT = {
    "what-is": "informational",
    "how-to": "informational",
    "guide": "informational",
    "best": "commercial",
    "compare": "commercial",
    "review": "commercial",
    "vs": "commercial",
}


def _col_index(cell_ref):
    letters = re.match(r"([A-Z]+)", cell_ref).group(1)
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _shared_strings(zf):
    out = []
    if "xl/sharedStrings.xml" not in zf.namelist():
        return out
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    for si in root.findall("m:si", NS):
        out.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    return out


def _sheet_targets(zf):
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    for sh in wb.find("m:sheets", NS):
        target = rid[sh.get(R_NS)]
        if not target.startswith("xl/"):
            target = "xl/" + target
        out.append((sh.get("name"), target))
    return out


def _row_cells(row, shared):
    cells = {}
    for c in row.findall("m:c", NS):
        v = c.find("m:v", NS)
        val = ""
        if v is not None:
            val = shared[int(v.text)] if c.get("t") == "s" else (v.text or "")
        else:
            inline = c.find("m:is", NS)
            if inline is not None:
                val = "".join(x.text or "" for x in inline.iter("{%s}t" % NS["m"]))
        cells[_col_index(c.get("r"))] = (val or "").strip()
    return cells


def _split_multi(raw):
    """Split a comma-separated facet cell into a clean list of names."""
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


# Audience facet vocabulary (CONTENT-ARCHITECTURE.md §5.3), used to classify each
# audience token as a role or a level by MEANING, not position.
_AUDIENCE_ROLES = {"trader", "ib"}
_AUDIENCE_LEVELS = {"beginner", "mid-level", "advanced"}


def _parse_audience(raw):
    """'Trader · Mid-Level' (optionally comma-joined) -> (roles, levels).

    Classifies each token against the known role/level vocabulary rather than by
    position, so a cell that carries only levels (e.g. 'Beginner · Mid-Level') never
    mislabels a level as a role — the bug that made 'Mid-Level' show up as an
    unresolved audience_role. Unknown tokens are ignored. Any separator works
    (comma via _split_multi, or ·/| within a chunk).
    """
    roles, levels = [], []
    for chunk in _split_multi(raw):
        for part in re.split(r"[·|/]", chunk):
            p = part.strip()
            pl = p.lower()
            if pl in _AUDIENCE_ROLES:
                roles.append(p)
            elif pl in _AUDIENCE_LEVELS:
                levels.append(p)
    # de-dup, preserve order
    return list(dict.fromkeys(roles)), list(dict.fromkeys(levels))


def _slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def _norm_key(s):
    """Alphanumeric-lowercase form, for matching a truncated sheet name to a full one."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _overview_cluster_names(zf, shared):
    """Full topic-cluster names from the Overview sheet, as {normalized: full}.

    Worksheet (tab) names are capped at Excel's 31 chars, so a cluster-sheet name can
    be a *truncated* cluster name; the Overview's first column carries the untruncated
    names (with a trailing ' (new)' marker on new clusters). Used to recover the full
    name so the ingested TopicCluster row is not named e.g. 'Platforms & Brokers for
    Automat'.
    """
    out = {}
    for sheet_name, target in _sheet_targets(zf):
        if sheet_name != "Overview":
            continue
        root = ET.fromstring(zf.read(target if target.startswith("xl/") else "xl/" + target))
        seen_header = False
        for row in root.iter("{%s}row" % NS["m"]):
            a = _row_cells(row, shared).get(0, "")
            if not a:
                continue
            if a == "Topic Cluster":
                seen_header = True
                continue
            if not seen_header:
                continue
            if a.startswith("TOTAL") or "total search volume" in a.lower():
                break
            full = re.sub(r"\s*\(new\)\s*$", "", a).strip()
            if full:
                out[_norm_key(full)] = full
        break
    return out


def _resolve_cluster_name(name_map, sheet_name):
    """Map a (possibly 31-char-truncated) sheet name back to its full Overview name."""
    key = _norm_key(sheet_name)
    if not key:
        return sheet_name
    if key in name_map:
        return name_map[key]
    for nk, full in name_map.items():
        if nk.startswith(key):  # the sheet name is a truncation -> a prefix of the full name
            return full
    return sheet_name


def _read_contents(path):
    """Yield one spec dict per content across every cluster sheet."""
    zf = zipfile.ZipFile(path)
    shared = _shared_strings(zf)
    name_map = _overview_cluster_names(zf, shared)
    contents = []
    for sheet_name, target in _sheet_targets(zf):
        if sheet_name == "Overview":
            continue
        cluster_name = _resolve_cluster_name(name_map, sheet_name)
        root = ET.fromstring(zf.read(target))
        header = None
        current = None
        for row in root.iter("{%s}row" % NS["m"]):
            cells = _row_cells(row, shared)
            if not cells:
                continue
            title = cells.get(0, "")
            if header is None:
                # first non-empty row is the header
                header = {cells.get(i, ""): i for i in cells}
                continue
            url_col = header.get("Competitor URLs", 15)
            if title:
                # new content row
                if current:
                    contents.append(current)
                roles, levels = _parse_audience(cells.get(header.get("Audience", 9), ""))
                frame = cells.get(header.get("Intent Frame", 3), "")
                current = {
                    "topic_cluster": cluster_name,
                    "title": title,
                    "h1": cells.get(header.get("H1", 1), ""),
                    "intent": cells.get(header.get("Intent", 2), ""),
                    "intent_frame": frame,
                    "search_intent": FRAME_TO_INTENT.get(frame, "informational"),
                    "entity": cells.get(header.get("Entity", 4), ""),
                    "content_type": cells.get(header.get("Content Type", 5), "Blog").lower(),
                    "role": cells.get(header.get("Role", 6), "").lower(),
                    "categories": _split_multi(cells.get(header.get("Categories", 7), "")),
                    "markets": _split_multi(cells.get(header.get("Markets", 8), "")),
                    "audience_roles": roles,
                    "audience_levels": levels,
                    "glossary_terms": _split_multi(cells.get(header.get("Glossary Terms", 10), "")),
                    "priority": int(cells.get(header.get("Priority", 11), "") or 0),
                    "clarity": int(cells.get(header.get("Clarity", 12), "") or 0),
                    "competitors": int(cells.get(header.get("# Competitors", 13), "") or 0),
                    "traffic": int(cells.get(header.get("Total Traffic", 14), "") or 0),
                    "competitor_urls": [],
                    # Cannibalization-prevention fields (CANNIBALIZATION-PREVENTION-PLAN.md
                    # §6). Empty at parse time; the Layer 1 reconcile step
                    # (intent_registry.py + reconcile.workflow.js) fills observed_intent /
                    # canonical_key / scope fences, and Layer 3 fills canonical_owner.
                    "observed_intent": "",
                    "canonical_key": "",
                    "scope_includes": [],
                    "scope_excludes": [],
                    "canonical_owner": "",
                }
                first_url = cells.get(url_col, "")
                if first_url:
                    current["competitor_urls"].append(first_url)
            elif current is not None:
                # continuation row: only the Competitor URL is populated
                url = cells.get(url_col, "")
                if url:
                    current["competitor_urls"].append(url)
        if current:
            contents.append(current)
    return contents


def _layer_scope_relevance(workbook_path):
    """Map the workbook's scope LAYER (carried in the FILE NAME by top_pages.py's
    ``_LAYER_SUFFIX``: layer 1 -> ``in-scope``, layer 2 -> ``relevant``; Out is dropped
    upstream and never written) to the 1-5 scope scale, so top-pages rows carry
    ``ContentPlan.scope_relevance`` like the keyword route: In Scope (L1) -> 1 (core),
    Relevant (L2) -> 3 (needs an angle). None when the layer can't be read from the name
    (e.g. a legacy combined file) — leaving the row ungraded for a later re-judge."""
    name = str(workbook_path or "").lower()
    if "in-scope" in name or "layer-1" in name or "layer1" in name:
        return 1
    if "relevant" in name or "layer-2" in name or "layer2" in name:
        return 3
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workbook")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--sheet", action="append", default=[])
    ap.add_argument("--title", action="append", default=[])
    ap.add_argument("--date", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    contents = _read_contents(args.workbook)

    if args.sheet:
        wanted = set(args.sheet)
        contents = [c for c in contents if c["topic_cluster"] in wanted]
    if args.title:
        wanted = set(args.title)
        contents = [c for c in contents if c["title"] in wanted]
    elif args.top:
        contents = sorted(contents, key=lambda c: -c["priority"])[: args.top]

    date_prefix = args.date or datetime.date.today().isoformat()
    layer_scope = _layer_scope_relevance(args.workbook)
    for c in contents:
        c["slug"] = _slugify(c["title"])
        c["content_id"] = f"{date_prefix}-{c['slug']}"[:80]
        # scope_relevance from the workbook's scope layer -> ContentPlan.scope_relevance
        # (queue exclude + priority weight), None left absent so the host adapter guard
        # skips it. The re-judge command can refine any specific row later.
        if layer_scope is not None:
            c["scope_relevance"] = layer_scope

    worklist = {
        "source": args.workbook,
        "generated_date": date_prefix,
        "count": len(contents),
        "contents": contents,
    }
    text = json.dumps(worklist, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"Wrote {len(contents)} content specs -> {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
