"""Prove the host hooks a write loop needs are importable BEFORE its first row.

Every hook in ``KEEL_CONTENT`` resolves lazily, at call time. For a read that is
harmless; for a command that rewrites many posts it is a trap, because the first
call sits INSIDE the loop — so a misconfigured host saves row #1, dies on row #1's
hook, and leaves the corpus half-rewritten. That is exactly what happened to a live
339-post corpus on 2026-08-22.

One line at the top of such a command closes it::

    require_write_hooks("prepare_storage_hook", "refresh_rendered_hook")

Name every hook the loop will touch, not just the one that bit last time.
"""

from __future__ import annotations

from django.core.management.base import CommandError

from keel_content import host


def require_write_hooks(*names: str) -> None:
    """Raise ``CommandError`` unless every named write-path hook imports cleanly."""
    try:
        host.preflight_hooks(*names)
    except host.HookResolutionError as exc:
        raise CommandError(str(exc)) from exc
