"""Find and replace em dashes across a code tree: Python strings, templates, JavaScript.

The replacement itself is decided by :mod:`keel_content.core.em_dash`. This module only
knows where a reader-facing em dash can live in source and how to read around it:

* **Python** — every string literal except docstrings, with implicitly concatenated
  pieces read as one sentence (``"fast "`` ``"— so you never miss"`` is one clause).
  Comments are never touched.
* **Templates** (``.html``, ``.txt`` e-mail bodies) — the whole file, with Django/Jinja
  comments, HTML comments and ``<style>`` blocks masked out.
* **JavaScript** — the whole file with ``//`` and ``/* */`` comments masked out.

Usage, from a host shell (no Django needed)::

    python -m keel_content.core.em_dash_files scan <root> --out plan.json [--exclude DIR ...]
    python -m keel_content.core.em_dash_files apply plan.json [--decisions answers.json]

``scan`` writes every occurrence with its rule decision and a short context, so the
AMBIGUOUS ones (and only those) can be settled by a reviewer; ``apply`` re-reads each
file, re-derives the same occurrences and writes the replacements. An occurrence the
reviewer left undecided is left exactly as it was and listed in the summary.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

from . import em_dash as ed

DEFAULT_EXCLUDES = frozenset(
    {
        "node_modules", "staticfiles", "media", "__pycache__", "migrations", ".git",
        ".venv", "venv", ".lighthouse", ".worktrees", "vendor", "dist", "build",
    }
)
EXTENSIONS = (".py", ".html", ".txt", ".js")

_TEMPLATE_MASK_RE = re.compile(
    r"\{%-?\s*comment\b.*?%\}.*?\{%-?\s*endcomment\s*-?%\}|\{#.*?#\}|<!--.*?-->|<style\b.*?</style>",
    re.DOTALL | re.IGNORECASE,
)
# Where one implicitly concatenated Python string piece ends and the next begins.
_PY_JOINT_RE = re.compile(
    r"""(?<!\\)(?:\"\"\"|'''|"|')\s*(?:\#[^\n]*\n\s*)*[rRbBuUfF]{0,2}(?:\"\"\"|'''|"|')"""
)
_PY_OPEN_RE = re.compile(r"""[rRbBuUfF]{0,2}(?:\"\"\"|'''|"|')""")
_PY_CLOSE_RE = re.compile(r"""(?:\"\"\"|'''|"|')$""")


@dataclass
class Occurrence:
    id: str
    path: str
    line: int
    kind: str
    rule: str
    context: str
    literal_only: bool = False  # the whole string holds no words: may be code, not copy


@dataclass
class FileScan:
    path: str
    raw: str
    units: list[tuple[ed.View, list[ed.Dash], bool]] = field(default_factory=list)


def _line_offsets(src: str) -> list[int]:
    offs = [0]
    for i, ch in enumerate(src):
        if ch == "\n":
            offs.append(i + 1)
    return offs


def _abs(src_lines: list[str], offs: list[int], lineno: int, col_bytes: int) -> int:
    line = src_lines[lineno - 1]
    col = len(line.encode("utf-8")[:col_bytes].decode("utf-8", errors="ignore"))
    return offs[lineno - 1] + col


def _python_units(raw: str) -> list[tuple[int, int]]:
    """Raw spans of every non-docstring string literal (outermost only)."""
    tree = ast.parse(raw)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Constant, ast.JoinedStr)):
                    docstrings.add(id(stmt.value))
    lines = raw.split("\n")
    offs = _line_offsets(raw)
    spans: list[tuple[int, int]] = []

    def visit(node: ast.AST, inside: bool) -> None:
        is_str = isinstance(node, ast.JoinedStr) or (
            isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        if is_str and not inside and id(node) not in docstrings:
            spans.append(
                (_abs(lines, offs, node.lineno, node.col_offset), _abs(lines, offs, node.end_lineno, node.end_col_offset))
            )
        for child in ast.iter_child_nodes(node):
            visit(child, inside or is_str)

    visit(tree, False)
    return spans


def _js_comment_spans(raw: str) -> list[tuple[int, int]]:
    """Comment spans in JavaScript, found with a small lexer that respects strings."""
    spans: list[tuple[int, int]] = []
    i, n = 0, len(raw)
    quote: str | None = None
    while i < n:
        ch = raw[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            continue
        if raw.startswith("//", i):
            j = raw.find("\n", i)
            j = n if j < 0 else j
            spans.append((i, j))
            i = j
            continue
        if raw.startswith("/*", i):
            j = raw.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append((i, j))
            i = j
            continue
        i += 1
    return spans


def scan_file(path: str) -> FileScan | None:
    try:
        raw = open(path, encoding="utf-8").read()
    except (UnicodeDecodeError, OSError):
        return None
    if not ed.GLYPH_RE.search(raw):
        return None
    fs = FileScan(path, raw)
    if path.endswith(".py"):
        try:
            spans = _python_units(raw)
        except SyntaxError:
            return None
        for lo, hi in spans:
            seg = raw[lo:hi]
            if not ed.GLYPH_RE.search(seg):
                continue
            drops = [(lo + m.start(), lo + m.end()) for m in _PY_JOINT_RE.finditer(seg)]
            om = _PY_OPEN_RE.match(seg)
            if om:
                drops.append((lo, lo + om.end()))
            cm = _PY_CLOSE_RE.search(seg)
            if cm:
                drops.append((lo + cm.start(), hi))
            view = ed.build_view(raw, _merge(drops), lo, hi)
            literal_only = not re.search(r"[A-Za-z]", ed.visible(view.text))
            fs.units.append((view, ed.classify(view.text), literal_only))
    else:
        if path.endswith(".js"):
            drops = _js_comment_spans(raw)
        else:
            drops = [(m.start(), m.end()) for m in _TEMPLATE_MASK_RE.finditer(raw)]
        view = ed.build_view(raw, drops)
        if ed.GLYPH_RE.search(view.text):
            fs.units.append((view, ed.classify(view.text), False))
    return fs if fs.units else None


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def iter_files(root: str, excludes: frozenset[str] = DEFAULT_EXCLUDES):
    if os.path.isfile(root):
        yield root
        return
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d not in excludes and not d.startswith("."))
        for f in sorted(fn):
            if f.endswith(EXTENSIONS):
                yield os.path.join(dp, f)


def occurrences(fs: FileScan) -> list[tuple[Occurrence, ed.View, ed.Dash]]:
    out = []
    n = 0
    for view, dashes, literal_only in fs.units:
        for d in dashes:
            raw_pos = view.spans[d.start][0]
            ctx = view.text[max(0, d.start - 160):d.start] + "⟦—⟧" + view.text[d.end:d.end + 160]
            occ = Occurrence(
                id=f"{fs.path}#{n}",
                path=fs.path,
                line=fs.raw.count("\n", 0, raw_pos) + 1,
                kind=d.kind,
                rule=d.rule,
                context=re.sub(r"\s+", " ", ctx),
                literal_only=literal_only,
            )
            out.append((occ, view, d))
            n += 1
    return out


def scan_tree(roots: list[str], excludes: frozenset[str] = DEFAULT_EXCLUDES) -> list[Occurrence]:
    """Every em dash a reader could see under ``roots``, with the rule's decision."""
    found: list[Occurrence] = []
    for root in roots:
        for path in iter_files(root, excludes):
            fs = scan_file(path)
            if fs:
                found.extend(o for o, _, _ in occurrences(fs))
    return found


def apply_file(path: str, decisions: dict[str, str], skip_literal_only: bool = True) -> tuple[int, list[str]]:
    """Rewrite one file. ``decisions`` overrides the rule by occurrence id."""
    fs = scan_file(path)
    if not fs:
        return 0, []
    edits: list[tuple[int, int, str]] = []
    left: list[str] = []
    applied = 0
    for occ, view, d in occurrences(fs):
        kind = decisions.get(occ.id, d.kind)
        if kind == "KEEP" or (occ.literal_only and skip_literal_only and occ.id not in decisions):
            left.append(occ.id)
            continue
        if kind not in ed.KINDS:
            left.append(occ.id)
            continue
        d.kind = kind
        if kind == ed.PERIOD and d.cap is None:
            d.cap = ed.cap_for(view.text, d)
            if d.cap is None:
                d.kind = ed.SEMICOLON
        edits.extend(ed.edits_for(view, [d]))
        applied += 1
    if edits:
        new = ed.render(fs.raw, edits)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
    return applied, left


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="em_dash_files")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("roots", nargs="+")
    s.add_argument("--out", required=True)
    s.add_argument("--exclude", action="append", default=[])
    a = sub.add_parser("apply")
    a.add_argument("plan")
    a.add_argument("--decisions")
    a.add_argument("--include-literal-only", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "scan":
        excludes = DEFAULT_EXCLUDES | frozenset(args.exclude)
        occ = scan_tree(args.roots, excludes)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"roots": args.roots, "excludes": sorted(excludes), "occurrences": [o.__dict__ for o in occ]}, fh, ensure_ascii=False, indent=1)
        c = Counter(o.kind for o in occ)
        print(f"{len(occ)} em dashes in {len({o.path for o in occ})} files")
        for k, v in c.most_common():
            print(f"  {k:12} {v}")
        print(f"  literal-only strings (left for review): {sum(o.literal_only for o in occ)}")
        return 0

    plan = json.load(open(args.plan, encoding="utf-8"))
    decisions: dict[str, str] = {}
    if args.decisions:
        decisions = json.load(open(args.decisions, encoding="utf-8"))
    files = sorted({o["path"] for o in plan["occurrences"]})
    total, remaining = 0, []
    for path in files:
        n, left = apply_file(path, decisions, skip_literal_only=not args.include_literal_only)
        total += n
        remaining.extend(left)
    print(f"replaced {total} em dashes in {len(files)} files; left untouched: {len(remaining)}")
    for r in remaining:
        print("  " + r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
