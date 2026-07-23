"""Publisher protocol — the only seam between core/ and project-specific code.

Adapters in content_pipeline/adapters/ implement this protocol and are wired
into the publish step. Keeping the core unaware of Django models is what makes
extracting this module to resonans-cms a copy-and-go operation.
"""

from __future__ import annotations

from typing import Protocol

from .types import PublishPayload


class ContentPublisher(Protocol):
    """Push a fully-rendered article into the host project's CMS."""

    def publish(self, payload: PublishPayload) -> str:
        """Persist the article and return its public URL (or admin URL if draft)."""
        ...

    def resolve_author_id(self, slug: str) -> object:
        """Return the author primary key the host project expects (UUID, int, str)."""
        ...

    def resolve_reviewer_id(self, slug: str) -> object | None:
        ...
