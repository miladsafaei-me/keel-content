"""HTML to structured Markdown, plus the per-page signals the crawl-map route needs.

The crawl-map intake route reads a competitor's crawled pages and derives a site
architecture from them. That needs *structure*, not just prose: which headings a page
carries, whether it answers questions, whether it tabulates comparisons, who wrote it
and when, and which of its own pages it links to. A visible-text extraction throws all
of that away, so this module re-derives it from the stored HTML.

Business-blind by design: nothing here knows what a broker, a strategy or a market is.
It reports structure; classification into page types and clusters is a later stage that
takes a host-supplied vocabulary.

lxml is imported lazily so importing this module never requires the parser to be
installed until it is actually used.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

CHROME_TAGS = ("script", "style", "noscript", "svg", "form", "iframe", "template")
NAV_TAGS = ("nav", "header", "footer", "aside")
BLOCK_SKIP = {"script", "style", "noscript", "svg", "form", "iframe", "template"}

_WS_RE = re.compile(r"\s+")
# An id/class chrome hint only removes a block holding less than this share of the
# page's text; above it the block is the content itself, whatever it is named.
_CHROME_MAX_SHARE = 0.30
_NAV_HINT_RE = re.compile(
    r"(^|[-_ ])(nav|menu|sidebar|breadcrumb|cookie|consent|banner|popup|modal|"
    r"share|social|newsletter|subscribe|related|widget|advert|ad-|ads-|promo)",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


@dataclass
class PageSignals:
    """Everything the crawl-map stages read about one page, minus its prose."""

    url: str = ""
    final_url: str = ""
    path: str = ""
    title: str = ""
    meta_description: str = ""
    words: int = 0
    headings: list[dict] = field(default_factory=list)
    faq_questions: list[str] = field(default_factory=list)
    tables: int = 0
    table_headers: list[list[str]] = field(default_factory=list)
    lists: int = 0
    images: int = 0
    author: str = ""
    published: str = ""
    modified: str = ""
    schema_types: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)
    external_domains: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "path": self.path,
            "title": self.title,
            "meta_description": self.meta_description,
            "words": self.words,
            "headings": self.headings,
            "faq_questions": self.faq_questions,
            "tables": self.tables,
            "table_headers": self.table_headers,
            "lists": self.lists,
            "images": self.images,
            "author": self.author,
            "published": self.published,
            "modified": self.modified,
            "schema_types": self.schema_types,
            "internal_links": self.internal_links,
            "external_domains": self.external_domains,
        }


def parse_html(html: str):
    """Parse to an lxml tree, or None when the document is unusable."""
    if not html or not html.strip():
        return None
    try:
        from lxml import html as lxml_html

        return lxml_html.fromstring(html)
    except Exception:
        return None


def _drop(tree, tags) -> None:
    for tag in tags:
        for el in list(tree.xpath(f"//{tag}")):
            try:
                el.drop_tree()
            except Exception:
                pass


def _looks_like_chrome(el) -> bool:
    """True when an element's own id/class marks it as page furniture."""
    for attr in ("class", "id"):
        val = el.get(attr) or ""
        if val and _NAV_HINT_RE.search(val):
            return True
    return False


def _pick_main(tree):
    """Return the element most likely to hold the page's own content."""
    for xp in ("//main", "//*[@role='main']", "//article"):
        found = tree.xpath(xp)
        if found:
            best = max(found, key=lambda e: len(_clean(" ".join(e.xpath(".//text()")))))
            if len(_clean(" ".join(best.xpath(".//text()")))) >= 400:
                return best
    body = tree.xpath("//body")
    return body[0] if body else tree


def _cell_text(cell) -> str:
    return _clean(" ".join(cell.xpath(".//text()")))


def _table_to_markdown(table) -> tuple[str, list[str]]:
    """Render one table as GitHub-flavoured Markdown; also return its header row."""
    rows = table.xpath(".//tr")
    if not rows:
        return "", []
    grid: list[list[str]] = []
    for tr in rows:
        cells = tr.xpath("./th|./td")
        if not cells:
            continue
        grid.append([_cell_text(c) for c in cells])
    if not grid:
        return "", []
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    header = grid[0]
    body = grid[1:] or []
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for r in body:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out), header


def _render(el, base_url: str, parts: list[str], state: dict) -> None:
    """Walk the tree once, emitting Markdown blocks and tallying structure."""
    tag = str(getattr(el, "tag", "") or "").lower()
    if tag in BLOCK_SKIP:
        return
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        text = _clean(" ".join(el.xpath(".//text()")))
        if text:
            level = int(tag[1])
            parts.append("#" * level + " " + text)
            state["headings"].append({"level": level, "text": text})
            if text.rstrip().endswith("?"):
                state["faq"].append(text)
        return
    if tag == "table":
        md, header = _table_to_markdown(el)
        if md:
            parts.append(md)
            state["tables"] += 1
            if header:
                state["table_headers"].append(header)
        return
    if tag in ("ul", "ol"):
        items = el.xpath("./li")
        rendered = []
        for i, li in enumerate(items, 1):
            text = _clean(" ".join(li.xpath(".//text()")))
            if text:
                rendered.append((f"{i}. " if tag == "ol" else "- ") + text)
        if rendered:
            parts.append("\n".join(rendered))
            state["lists"] += 1
        return
    if tag in ("pre", "blockquote"):
        text = _clean(" ".join(el.xpath(".//text()")))
        if text:
            prefix = "> " if tag == "blockquote" else "    "
            parts.append(prefix + text)
        return
    if tag == "p":
        text = _clean(" ".join(el.xpath(".//text()")))
        if text:
            parts.append(text)
        return

    children = [c for c in el if isinstance(getattr(c, "tag", None), str)]
    if not children:
        text = _clean(" ".join(el.xpath(".//text()")))
        if text and len(text) > 1:
            parts.append(text)
        return
    for child in children:
        if _is_chrome_block(child, state):
            continue
        _render(child, base_url, parts, state)


def _is_chrome_block(el, state: dict) -> bool:
    """Whether to skip an element as page furniture.

    The id/class hint alone is not enough to act on. Themes routinely name the wrapper
    that *holds* the article after the layout it participates in — a container classed
    ``site with-custom-sidebar`` matches a "sidebar" hint while carrying the entire
    page body. Dropping it silently empties the page, so an element that accounts for a
    large share of the content is kept regardless of what its class is called; the hint
    only removes genuinely peripheral blocks.
    """
    if not _looks_like_chrome(el):
        return False
    total = state.get("total_chars") or 0
    if total <= 0:
        return True
    own = len(_clean(" ".join(el.xpath(".//text()"))))
    return own < total * _CHROME_MAX_SHARE


def _json_ld(tree) -> list[dict]:
    out: list[dict] = []
    for node in tree.xpath("//script[@type='application/ld+json']"):
        raw = (node.text or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        out.extend(data if isinstance(data, list) else [data])
    return out


def _walk_json_ld(blocks: list[dict]):
    """Yield every dict in the JSON-LD forest, including @graph children."""
    stack = list(blocks)
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        yield node
        for key in ("@graph", "mainEntity", "itemListElement", "hasPart"):
            val = node.get(key)
            if isinstance(val, (list, dict)):
                stack.append(val)


def _meta(tree, *names: str) -> str:
    for name in names:
        for xp in (f"//meta[@property='{name}']/@content", f"//meta[@name='{name}']/@content"):
            found = tree.xpath(xp)
            if found and str(found[0]).strip():
                return _clean(str(found[0]))
    return ""


def _author(tree, ld_nodes) -> str:
    for node in ld_nodes:
        author = node.get("author")
        if isinstance(author, dict) and author.get("name"):
            return _clean(str(author["name"]))
        if isinstance(author, list) and author and isinstance(author[0], dict):
            if author[0].get("name"):
                return _clean(str(author[0]["name"]))
        if isinstance(author, str) and author.strip():
            return _clean(author)
    meta_author = _meta(tree, "article:author", "author")
    if meta_author and not meta_author.startswith("http"):
        return meta_author
    for xp in ("//*[@rel='author']", "//*[contains(@class,'author-name')]", "//*[contains(@class,'author')]"):
        found = tree.xpath(xp)
        if found:
            text = _clean(" ".join(found[0].xpath(".//text()")))
            if 2 < len(text) <= 80:
                return text
    return ""


def _faq_from_json_ld(ld_nodes) -> list[str]:
    out: list[str] = []
    for node in ld_nodes:
        if str(node.get("@type", "")).lower() in ("question",):
            name = node.get("name")
            if isinstance(name, str) and name.strip():
                out.append(_clean(name))
    return out


def extract(html: str, url: str, *, final_url: str = "") -> tuple[str, PageSignals]:
    """Return ``(markdown, signals)`` for one crawled page.

    The Markdown keeps real heading levels, tables, and lists so a later stage can judge
    how a competitor structures a page type. The signals carry everything the crawl-map
    atlas indexes, so downstream stages read the small record instead of the page.
    """
    sig = PageSignals(url=url, final_url=final_url or url)
    tree = parse_html(html)
    if tree is None:
        return "", sig

    effective = final_url or url
    split = urlsplit(effective)
    sig.path = split.path or "/"
    host = split.netloc.lower().removeprefix("www.")

    ld_nodes = list(_walk_json_ld(_json_ld(tree)))
    sig.schema_types = sorted(
        {
            str(n.get("@type"))
            for n in ld_nodes
            if isinstance(n.get("@type"), str) and n.get("@type")
        }
    )
    sig.meta_description = _meta(tree, "og:description", "description")
    sig.published = _meta(tree, "article:published_time", "datePublished")
    sig.modified = _meta(tree, "article:modified_time", "dateModified")
    for node in ld_nodes:
        if not sig.published and isinstance(node.get("datePublished"), str):
            sig.published = _clean(node["datePublished"])
        if not sig.modified and isinstance(node.get("dateModified"), str):
            sig.modified = _clean(node["dateModified"])
    sig.author = _author(tree, ld_nodes)

    titles = tree.xpath("//title/text()")
    doc_title = _clean(str(titles[0])) if titles else ""

    for href in tree.xpath("//a/@href"):
        try:
            absolute = urljoin(effective, str(href))
        except Exception:
            continue
        parts_url = urlsplit(absolute)
        if parts_url.scheme not in ("http", "https"):
            continue
        link_host = parts_url.netloc.lower().removeprefix("www.")
        if link_host == host:
            sig.internal_links.append(parts_url.path or "/")
        elif link_host:
            sig.external_domains.append(link_host)
    sig.internal_links = sorted(set(sig.internal_links))
    sig.external_domains = sorted(set(sig.external_domains))
    sig.images = len(tree.xpath("//img"))

    faq_ld = _faq_from_json_ld(ld_nodes)

    _drop(tree, CHROME_TAGS)
    main = _pick_main(tree)
    for tag in NAV_TAGS:
        for el in list(main.xpath(f".//{tag}")):
            try:
                el.drop_tree()
            except Exception:
                pass

    state = {
        "headings": [],
        "faq": [],
        "tables": 0,
        "table_headers": [],
        "lists": 0,
        "total_chars": len(_clean(" ".join(main.xpath(".//text()")))),
    }
    parts: list[str] = []
    _render(main, effective, parts, state)

    seen: set[str] = set()
    blocks: list[str] = []
    for block in parts:
        key = block[:160]
        if key in seen:
            continue
        seen.add(key)
        blocks.append(block)

    markdown = "\n\n".join(blocks).strip() + "\n"
    sig.headings = state["headings"]
    sig.tables = state["tables"]
    sig.table_headers = state["table_headers"]
    sig.lists = state["lists"]
    sig.words = len(markdown.split())

    questions = faq_ld + [q for q in state["faq"] if q not in faq_ld]
    sig.faq_questions = questions

    h1 = next((h["text"] for h in sig.headings if h["level"] == 1), "")
    sig.title = h1 or doc_title
    return markdown, sig
