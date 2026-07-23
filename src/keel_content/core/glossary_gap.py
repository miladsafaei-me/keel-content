"""Glossary-gap analysis — flag important terms the finished article relies on
that are missing from the trading glossary, so the editor can decide whether to
author dedicated glossary pages for them.

Runs once after the format step, reading ``final.md``. It is **advisory only**:
any failure (no API key, missing artifact, parse error, Django not ready) degrades
to an empty suggestion list and never aborts the pipeline. The result lands in the
run summary, the end-of-task report, and ``glossary-suggestions.json``.

The existing-terms lookup is delegated to the project adapter (the only place
allowed to touch Django models) via a guarded import, mirroring the lazy-import
pattern in ``config._load_db_overrides``, so this module stays importable without
Django.
"""

from __future__ import annotations

import logging
from typing import Any

from . import logging_jsonl, paths, term_match
from .claude_client import ClaudeClient
from .config import ProjectConfig, read_prompt, render_prompt, write_artifact
from .types import ContentInput, StepUsage

logger = logging.getLogger(__name__)

STEP = "glossary_gap"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_MAX_TOKENS = 2000


def _existing_glossary_terms() -> list[dict[str, Any]]:
    """Pull existing glossary terms from the project adapter; ``[]`` on any failure."""
    try:
        from keel_content.adapters import get_adapter
        return get_adapter().existing_glossary_terms()
    except Exception as exc:  # Django not ready, table missing, import error…
        logger.warning("glossary_gap: could not load existing glossary terms (%s)", exc)
        return []


def _existing_names_block(terms: list[dict[str, Any]]) -> tuple[str, int]:
    """Flatten names + abbreviations + aka aliases into a deduped bullet block."""
    names: set[str] = set()
    for t in terms:
        if t.get("name"):
            names.add(t["name"].strip())
        if t.get("abbreviation"):
            names.add(t["abbreviation"].strip())
        for alias in t.get("aka") or []:
            if isinstance(alias, str) and alias.strip():
                names.add(alias.strip())
    ordered = sorted(names, key=str.lower)
    block = "\n".join(f"- {n}" for n in ordered) if ordered else "(glossary is empty)"
    return block, len(ordered)


def analyze(
    content_id: str, cfg: ProjectConfig, ci: ContentInput, *,
    client: ClaudeClient | None = None,
) -> tuple[list[dict[str, Any]], StepUsage | None]:
    """Analyze ``final.md`` for glossary-worthy terms missing from the glossary.

    Returns ``(suggestions, usage)`` where ``suggestions`` is a list of
    ``{"term", "reason", "example_sentence"}`` dicts (possibly empty) and ``usage``
    is the API ``StepUsage`` (or ``None`` if the analysis was skipped).
    """
    if not cfg.raw.get("glossary_gap", {}).get("enabled", True):
        return [], None

    final_md_path = paths.article_dir(content_id) / "final.md"
    if not final_md_path.exists():
        logger.warning("glossary_gap: final.md missing for %s; skipping analysis", content_id)
        return [], None

    article_md = final_md_path.read_text(encoding="utf-8").strip()
    if not article_md:
        return [], None

    existing = _existing_glossary_terms()
    existing_block, existing_count = _existing_names_block(existing)
    existing_sets = term_match.existing_token_sets(existing)

    template = read_prompt("06-glossary-gap")
    ctx = {
        "article_markdown": article_md,
        "existing_glossary_terms_block": existing_block,
        "keyword": ci.keyword,
        "audience": ci.audience,
    }
    system_text = render_prompt(template, ctx)

    model = cfg.raw.get("claude_models", {}).get(STEP, _DEFAULT_MODEL)
    max_tokens = int(cfg.raw.get("claude_max_tokens", {}).get(STEP, _DEFAULT_MAX_TOKENS))

    try:
        client = client or ClaudeClient()
        reply = client.call(
            step=STEP,
            model=model,
            max_tokens=max_tokens,
            system_text=system_text,
            user_text="Return the glossary-gap JSON now.",
            expect_json=True,
        )
    except Exception as exc:
        logger.warning("glossary_gap: analysis call failed (%s); skipping", exc)
        return [], None

    suggestions: list[dict[str, Any]] = []
    filtered_dupes = 0
    if isinstance(reply.json, dict):
        for s in reply.json.get("suggested_terms", []) or []:
            if not (isinstance(s, dict) and (s.get("term") or "").strip()):
                continue
            term = s["term"].strip()
            if term_match.already_covered(term, existing_sets):
                filtered_dupes += 1
                continue
            suggestions.append({
                "term": term,
                "reason": (s.get("reason") or "").strip(),
                "example_sentence": (s.get("example_sentence") or "").strip(),
            })
    if filtered_dupes:
        logger.info("glossary_gap: dropped %d model suggestion(s) already in the glossary", filtered_dupes)

    write_artifact(content_id, "glossary-suggestions.json", {
        "content_id": content_id,
        "existing_term_count": existing_count,
        "suggested_count": len(suggestions),
        "suggested_terms": suggestions,
    })
    logging_jsonl.log_event(
        content_id, "glossary_gap_completed", step=STEP, model=model,
        existing_term_count=existing_count, suggested_count=len(suggestions),
        cost_usd=reply.usage.cost_usd,
    )
    return suggestions, reply.usage
