"""Shared dataclasses passed between pipeline steps.

The core/ package stays project-agnostic: nothing here imports Django models.
Adapters convert these into project-specific objects (Post, NewsPost, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class ContentInput:
    """User-supplied per-article input (loaded from input.json)."""

    id: str
    keyword: str
    search_intent: Literal["informational", "commercial", "navigational", "transactional"]
    audience: str
    notes: str = ""
    target: Literal["blog", "news"] = "blog"
    slug_override: str | None = None
    author_slug: str | None = None
    reviewer_slug: str | None = None
    search_intent_description: str = ""


@dataclass
class StepUsage:
    """Token usage + cost for a single Claude API call."""

    step: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float


@dataclass
class PublishPayload:
    """Project-agnostic payload handed to the publisher adapter."""

    slug: str
    title: str
    h1: str
    meta_title: str
    meta_description: str
    excerpt: str
    key_takeaways_markdown: str
    final_markdown: str
    target: Literal["blog", "news"]
    author_slug: str | None
    reviewer_slug: str | None
    initial_status: Literal["draft", "published", "archived"]
    featured_image_url: str = ""
