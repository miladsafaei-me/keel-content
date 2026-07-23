"""Load project config + per-content input + prompt template rendering.

The renderer supports ``{{a.b.c}}`` dotted paths and a few synthesized helpers
(e.g. ``content_rules_bulleted``). Kept intentionally tiny — no Jinja dependency.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths

_INTERPOLATION_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge: overrides[key] replaces base[key], descending into dicts."""
    out = dict(base)
    for k, v in overrides.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class ProjectConfig:
    """Parsed config.json — only the legacy single-article API path reads this.

    The on-disk ``config.json`` is committed to git and now governs solely the
    legacy ``core/glossary_gap.py`` path (model + max-tokens + enabled).
    ``core.AiSetting.content_pipeline_overrides()`` (admin-edited DB row) still
    layers on top. The agent Workflow does not read this; callers access
    ``cfg.raw.get(...)`` with defaults, so the file may be slim or absent.
    """

    raw: dict[str, Any]

    @classmethod
    def load(cls) -> "ProjectConfig":
        with paths.config_path().open("r", encoding="utf-8") as fh:
            base = json.load(fh)
        overrides = _load_db_overrides()
        return cls(raw=_deep_merge(base, overrides) if overrides else base)


def _load_db_overrides() -> dict[str, Any]:
    """Return overrides from ``core.AiSetting``; degrade silently if Django isn't ready."""
    try:
        from core.models import AiSetting
        return AiSetting.load().content_pipeline_overrides()
    except Exception:
        return {}


def read_prompt(name: str) -> str:
    """Read a prompt template by stem (without .md)."""
    p = paths.prompts_dir() / f"{name}.md"
    return p.read_text(encoding="utf-8")


def load_blog_guidelines() -> str:
    """Return the repo-root BLOG.md body, or '' (with a warning) when it's absent.

    This is the single source of truth for blog editorial rules — the same doc a
    human author follows. Injected into prompt context as ``editorial_guidelines``
    so every generation/QA step writes against the same rules and never drifts.
    """
    path = paths.blog_guidelines_path()
    if path is None:
        print("WARNING: BLOG.md not found — prompts render without editorial guidelines.")
        return ""
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, ctx: dict[str, Any]) -> str:
    """Replace ``{{a.b.c}}`` paths in template using values from ctx.

    Missing paths render as empty string and a console warning so partial templates
    stay debuggable instead of crashing the pipeline.
    """

    def _resolve(path: str) -> str:
        cur: Any = ctx
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return ""
        if isinstance(cur, (dict, list)):
            return json.dumps(cur, ensure_ascii=False, indent=2)
        return str(cur)

    return _INTERPOLATION_RE.sub(lambda m: _resolve(m.group(1)), template)


def write_artifact(content_id: str, filename: str, payload: Any) -> Path:
    """Write a JSON or text artifact next to input.json. Returns the path."""
    out = paths.article_dir(content_id) / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        out.write_text(str(payload), encoding="utf-8")
    return out


def read_artifact_json(content_id: str, filename: str) -> Any:
    p = paths.article_dir(content_id) / filename
    return json.loads(p.read_text(encoding="utf-8"))


def read_artifact_text(content_id: str, filename: str) -> str:
    p = paths.article_dir(content_id) / filename
    return p.read_text(encoding="utf-8")
