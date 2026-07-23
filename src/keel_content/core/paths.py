"""Resolve filesystem paths for the content-pipeline directory and per-content artifacts."""

from __future__ import annotations

import os
from pathlib import Path


def pipeline_root() -> Path:
    """Return the absolute path to the project's content-pipeline/ directory.

    Resolution order:
      1. CONTENT_PIPELINE_ROOT env var (override).
      2. Walk up from this file until a sibling content-pipeline/ is found.
    """
    override = os.environ.get("CONTENT_PIPELINE_ROOT")
    if override:
        p = Path(override).resolve()
        if not p.is_dir():
            raise FileNotFoundError(f"CONTENT_PIPELINE_ROOT does not exist: {p}")
        return p

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "content-pipeline"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "Could not locate content-pipeline/ directory. "
        "Set CONTENT_PIPELINE_ROOT env var or create it next to backend/."
    )


def config_path() -> Path:
    return pipeline_root() / "config.json"


def prompts_dir() -> Path:
    return pipeline_root() / "prompts"


def blog_guidelines_path() -> Path | None:
    """Resolve the repo-root BLOG.md (the authoritative blog editorial guidelines).

    Resolution order:
      1. CONTENT_BLOG_GUIDELINES env var (override).
      2. BLOG.md sibling of content-pipeline/ (repo root in dev, /app in the image).
      3. Walk up from pipeline_root() looking for a BLOG.md.
    Returns None when no file is found, so callers can degrade gracefully.
    """
    override = os.environ.get("CONTENT_BLOG_GUIDELINES")
    if override:
        p = Path(override).resolve()
        return p if p.is_file() else None

    sibling = pipeline_root().parent / "BLOG.md"
    if sibling.is_file():
        return sibling

    for parent in pipeline_root().parents:
        candidate = parent / "BLOG.md"
        if candidate.is_file():
            return candidate
    return None


def content_dir() -> Path:
    return pipeline_root() / "content"


def article_dir(content_id: str) -> Path:
    return content_dir() / content_id


def article_images_dir(content_id: str) -> Path:
    d = article_dir(content_id) / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d
