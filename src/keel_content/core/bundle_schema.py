"""The generation-bundle contract — one place that documents and validates the
shape of the JSON a generation agent emits and ``content_import`` reads.

Before this module the contract was implicit: required/optional keys were scattered
across ``content_import``, ``publish_from_bundle`` and ``_persist_bundle``, several
keys had silent aliases, and the lint checked *content* (lengths, takeaway count)
but never *structure* — so a missing or misspelled key was silently dropped with
only a log line. ``validate_bundle_structure`` makes a malformed bundle fail loudly
at import instead.

Pure stdlib + no Django, so it is unit-testable and importable anywhere.

Canonical keys (aliases are still accepted by the publisher for back-compat, but
new bundles should use the canonical name):

  Required:
    - ``slug``           : str, non-empty (stable identity; upsert key)
    - ``title``          : str, non-empty (SEO title tag)
    - ``body_markdown``  : str, non-empty (alias accepted: ``final_markdown``)

  Optional (validated only for shape when present):
    - ``h1`` / ``meta_title`` / ``meta_description`` / ``excerpt``
      / ``key_takeaways_markdown`` : str
    - ``target``                   : "blog" | "news"
    - ``initial_status``           : "draft" | "published" | "archived"
    - ``featured_image_url``       : str
    - ``author_slug`` / ``reviewer_slug`` : str | null
    - ``facets``                   : dict — see ``_FACET_LIST_KEYS`` / ``_FACET_STR_KEYS``
    - ``external_sources``         : list of {url, anchor (alias: title), role?, vetted?}
                                     (``vetted`` is the relevance gate's promotion marker
                                     for an off-fast-lane host; see ``core.external_links``)
    - ``internal_links``           : list of {anchor, target_slug (aliases: target_url, url)}
    - ``hero``                     : dict {svg_element: str, head?: list}
    - ``figure_requests``          : list (advisory; the author's figure contracts,
                                     consumed by the figures stage — not validated here)
    - ``figures``                  : list of {id, file (.webp relative to the bundle
                                     dir), width, height, alt, caption} — deep checks
                                     (marker match, file existence, alt/caption) run in
                                     ``core.figures.figure_violations`` at import
    - ``image_requests``           : list (advisory; the author's ``image-nb2``
                                     photoreal-image contracts — a per-paragraph scene
                                     brief + in-image overlay text — consumed by the
                                     images stage; not validated here)
    - ``images``                   : list of {id, file (.webp relative to the bundle
                                     dir), width, height, alt, caption} — deep checks
                                     (marker match, file existence, alt/caption, the
                                     whole-post NB2 word-budget) run in
                                     ``core.images.image_violations`` at import
    - ``figure_gate`` / ``image_gate`` : dict (the vision judge's verdict; advisory)
    - ``generation_report``        : dict (advisory; not validated)
"""

from __future__ import annotations

from typing import Any

_FACET_LIST_KEYS = (
    "categories",
    "markets",
    "audience_roles",
    "audience_levels",
    "glossary_terms",
)
_FACET_STR_KEYS = ("topic_cluster", "role")


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def validate_bundle_structure(bundle: dict) -> list[str]:
    """Return structural violations for one bundle (empty = structurally valid).

    Checks required keys are present + non-empty and that optional containers have
    the right shape. Does NOT check content rules (lengths, takeaway count) — that
    is ``bundle_lint.lint_bundle``.
    """
    errs: list[str] = []

    if not isinstance(bundle, dict):
        return ["bundle is not a JSON object"]

    if not _nonempty_str(bundle.get("slug")):
        errs.append("missing/empty required key: slug")
    if not _nonempty_str(bundle.get("title")):
        errs.append("missing/empty required key: title")
    if not _nonempty_str(bundle.get("body_markdown") or bundle.get("final_markdown")):
        errs.append("missing/empty required key: body_markdown (or final_markdown)")

    facets = bundle.get("facets")
    if facets is not None:
        if not isinstance(facets, dict):
            errs.append("facets must be an object")
        else:
            for k in _FACET_LIST_KEYS:
                if k in facets and not isinstance(facets[k], list):
                    errs.append(f"facets.{k} must be a list")
            for k in _FACET_STR_KEYS:
                if k in facets and facets[k] is not None and not isinstance(facets[k], str):
                    errs.append(f"facets.{k} must be a string")

    sources = bundle.get("external_sources")
    if sources is not None:
        if not isinstance(sources, list):
            errs.append("external_sources must be a list")
        else:
            for i, s in enumerate(sources):
                if not isinstance(s, dict):
                    errs.append(f"external_sources[{i}] must be an object")
                    continue
                if not _nonempty_str(s.get("url")):
                    errs.append(f"external_sources[{i}] missing url")
                if not (_nonempty_str(s.get("anchor")) or _nonempty_str(s.get("title"))):
                    errs.append(f"external_sources[{i}] missing anchor")

    links = bundle.get("internal_links")
    if links is not None:
        if not isinstance(links, list):
            errs.append("internal_links must be a list")
        else:
            for i, ln in enumerate(links):
                if not isinstance(ln, dict):
                    errs.append(f"internal_links[{i}] must be an object")
                    continue
                if not _nonempty_str(ln.get("anchor")):
                    errs.append(f"internal_links[{i}] missing anchor")
                if not any(_nonempty_str(ln.get(k)) for k in ("target_slug", "target_url", "url")):
                    errs.append(f"internal_links[{i}] missing target (target_slug/target_url/url)")

    hero = bundle.get("hero")
    if hero is not None:
        if not isinstance(hero, dict):
            errs.append("hero must be an object")
        elif "svg_element" in hero and not isinstance(hero["svg_element"], str):
            errs.append("hero.svg_element must be a string")

    figures = bundle.get("figures")
    if figures is not None:
        if not isinstance(figures, list):
            errs.append("figures must be a list")
        else:
            for i, fg in enumerate(figures):
                if not isinstance(fg, dict):
                    errs.append(f"figures[{i}] must be an object")
                    continue
                if not _nonempty_str(fg.get("id")):
                    errs.append(f"figures[{i}] missing id")
                if not _nonempty_str(fg.get("file")):
                    errs.append(f"figures[{i}] missing file")

    images = bundle.get("images")
    if images is not None:
        if not isinstance(images, list):
            errs.append("images must be a list")
        else:
            for i, im in enumerate(images):
                if not isinstance(im, dict):
                    errs.append(f"images[{i}] must be an object")
                    continue
                if not _nonempty_str(im.get("id")):
                    errs.append(f"images[{i}] missing id")
                if not _nonempty_str(im.get("file")):
                    errs.append(f"images[{i}] missing file")

    return errs
