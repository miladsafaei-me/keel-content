"""Expand component placeholders in a bundle body into rendered HTML.

The blog generator emits in-body visuals **as data, not HTML** — one fenced block
per visual, exactly like the glossary path:

    ```cp-component
    {"component_id": "calculator", "spec": {...}, "caption": "...", "eyebrow": "..."}
    ```

This pass (run inside ``publish_from_bundle``, alongside the external-sources and
internal-links passes) finds each block, validates ``spec`` against the component's
JSON Schema, renders the server-authored template via ``keel_ui``,
and substitutes the rendered HTML wrapped in a ``<figure>``. The component library
is the single source of every visual's markup — authors never hand-write HTML/CSS.

Best-effort: a missing component or invalid spec drops that one block (and is
recorded in the report) rather than failing the whole publish.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from django.utils.html import escape

from keel_ui import render as render_component
from keel_ui.registry import ComponentNotFound
from keel_ui.renderer import RenderError, SpecValidationError

log = logging.getLogger(__name__)

# A fenced block whose info-string is exactly ``cp-component`` (optionally followed
# by whitespace). Captures the JSON body between the fences.
_FENCE_RE = re.compile(r"```cp-component[^\n]*\n(.*?)\n```", re.DOTALL)


def apply_components(body_markdown: str) -> tuple[str, dict[str, Any]]:
    """Replace each ```cp-component fenced block with its rendered component HTML.

    Returns ``(new_body, report)`` where report = ``{"rendered": int,
    "failed": [str, ...], "ids": [str, ...]}``.
    """
    report: dict[str, Any] = {
        "rendered": 0,
        "failed": [],
        "ids": [],
        "pruned": [],
        "clamped": [],
    }

    def _sub(match: re.Match) -> str:
        raw = (match.group(1) or "").strip()
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            report["failed"].append(f"invalid JSON: {exc}")
            log.warning("cp-component block dropped (bad JSON): %s", exc)
            return ""
        if not isinstance(item, dict):
            report["failed"].append("block is not a JSON object")
            return ""
        component_id = item.get("component_id")
        spec = item.get("spec") or {}
        if not component_id or not isinstance(spec, dict):
            report["failed"].append(f"missing component_id/spec: {component_id!r}")
            return ""
        dropped_keys: list[str] = []
        clamped_labels: list[str] = []
        try:
            html = render_component(
                component_id,
                spec,
                prune_additional=True,
                dropped_keys=dropped_keys,
                clamped_labels=clamped_labels,
            )
        except (ComponentNotFound, SpecValidationError, RenderError) as exc:
            report["failed"].append(f"{component_id}: {exc}")
            log.warning("cp-component block dropped (%s): %s", component_id, exc)
            return ""
        if dropped_keys:
            report["pruned"].append(f"{component_id}: dropped unknown keys {dropped_keys}")
        if clamped_labels:
            # An over-length field that had to be truncated is a quality signal:
            # the author wrote label copy longer than the component allows. Surface
            # it (not just a silent log) so a reviewer can shorten it at the source.
            report["clamped"].append(f"{component_id}: truncated over-length {clamped_labels}")

        eyebrow = item.get("eyebrow")
        caption = item.get("caption")
        eye_html = (
            f'<div class="cp-figure__eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
        )
        cap_html = (
            f'<figcaption class="cp-figure__caption">{escape(caption)}</figcaption>'
            if caption
            else ""
        )
        report["rendered"] += 1
        report["ids"].append(component_id)
        # Blank lines around the figure keep the Markdown renderer from wrapping the
        # raw HTML in <p>; pipeline posts bypass sanitize so the markup survives.
        return f'\n\n<figure class="cp-figure cp-figure--embed">{eye_html}{html}{cap_html}</figure>\n\n'

    new_body = _FENCE_RE.sub(_sub, body_markdown or "")
    return new_body, report
