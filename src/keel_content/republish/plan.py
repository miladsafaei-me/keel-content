"""The plan: the one artifact a model writes, and the contract it must meet."""
from __future__ import annotations

from typing import Any

PLAN_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Republish plan",
    "description": (
        "Says which harvested sources feed which outputs. The counts are "
        "independent: merge several sources into one article, split one source "
        "into several, or emit a single visual grafted into a post that already "
        "exists."),
    "type": "object",
    "required": ["outputs"],
    "properties": {
        "notes": {"type": "string",
                  "description": "Why the sources were split or merged this way."},
        "outputs": {
            "type": "array", "minItems": 1,
            "items": {"oneOf": [
                {
                    "type": "object",
                    "title": "post — a new draft article",
                    "required": ["kind", "slug", "from", "bundle"],
                    "properties": {
                        "kind": {"const": "post"},
                        "slug": {"type": "string",
                                 "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"},
                        "from": {"type": "array", "minItems": 1,
                                 "items": {"type": "string"},
                                 "description": "Source ids from harvest.json."},
                        "bundle": {
                            "type": "object",
                            "required": ["title", "meta_title", "meta_description",
                                         "excerpt", "key_takeaways_markdown",
                                         "body_markdown", "facets"],
                        },
                        "figures": {
                            "type": "array",
                            "description": (
                                "Figures drawn for this output. Each names a "
                                "page_extract builder, so the SVG is generated "
                                "from parameters rather than written by hand."),
                            "items": {
                                "type": "object",
                                "required": ["id", "builder", "alt", "caption"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "builder": {"type": "string"},
                                    "params": {"type": "object"},
                                    "alt": {"type": "string"},
                                    "caption": {"type": "string"},
                                    "section": {"type": "string"},
                                    "comprehension_job": {"type": "string"},
                                    "width": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
                {
                    "type": "object",
                    "title": "graft — one visual into an article that already exists",
                    "required": ["kind", "target_slug", "anchor"],
                    "properties": {
                        "kind": {"const": "graft"},
                        "target_slug": {"type": "string"},
                        "graft_id": {
                            "type": "string",
                            "description": (
                                "Stable id. Re-running with the same id replaces "
                                "the block instead of adding a second one.")},
                        "from": {"type": "string"},
                        "visual": {
                            "type": "object",
                            "required": ["component_id", "spec"],
                            "properties": {
                                "component_id": {"type": "string"},
                                "spec": {"type": "object"},
                                "eyebrow": {"type": "string"},
                                "caption": {"type": "string"},
                            },
                        },
                        "figure": {
                            "type": "object",
                            "description": (
                                "A drawn figure instead of a component, for a "
                                "visual whose layout carries its meaning."),
                            "required": ["builder", "alt", "caption"],
                            "properties": {
                                "builder": {"type": "string"},
                                "params": {"type": "object"},
                                "alt": {"type": "string"},
                                "caption": {"type": "string"},
                                "width": {"type": "integer"},
                            },
                        },
                        "anchor": {
                            "type": "object",
                            "required": ["mode", "text"],
                            "properties": {
                                "mode": {"enum": ["before_heading", "after_heading",
                                                  "end"]},
                                "text": {"type": "string"},
                            },
                        },
                    },
                },
            ]},
        },
    },
}


def validate_plan(plan: dict) -> list[str]:
    """Return every problem with a plan, or an empty list. Never raises."""
    try:
        import jsonschema
    except ImportError:
        return _validate_without_jsonschema(plan)
    errors = []
    validator = jsonschema.Draft202012Validator(PLAN_SCHEMA)
    for err in sorted(validator.iter_errors(plan), key=str):
        loc = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{loc}: {err.message}")
    errors.extend(_semantic_checks(plan))
    return errors


def _validate_without_jsonschema(plan: dict) -> list[str]:
    errors = []
    outputs = plan.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        return ["outputs: must be a non-empty list"]
    for i, out in enumerate(outputs):
        kind = out.get("kind")
        if kind == "post":
            for key in ("slug", "from", "bundle"):
                if not out.get(key):
                    errors.append(f"outputs.{i}: post is missing {key}")
        elif kind == "graft":
            for key in ("target_slug", "anchor"):
                if not out.get(key):
                    errors.append(f"outputs.{i}: graft is missing {key}")
            if not out.get("visual") and not out.get("figure"):
                errors.append(f"outputs.{i}: graft needs a visual or a figure")
        else:
            errors.append(f"outputs.{i}: kind must be 'post' or 'graft', got {kind!r}")
    return errors + _semantic_checks(plan)


def _semantic_checks(plan: dict) -> list[str]:
    """Rules the JSON Schema cannot express."""
    errors = []
    for i, out in enumerate(plan.get("outputs") or []):
        if out.get("kind") != "graft":
            continue
        if out.get("visual") and out.get("figure"):
            errors.append(f"outputs.{i}: a graft carries a visual OR a figure, not both")
        if not out.get("visual") and not out.get("figure"):
            errors.append(f"outputs.{i}: a graft needs either a visual or a figure")
    slugs = [o.get("slug") for o in plan.get("outputs") or [] if o.get("kind") == "post"]
    for slug in {s for s in slugs if slugs.count(s) > 1}:
        errors.append(f"two post outputs share the slug {slug!r}")
    return errors
