"""Anthropic API wrapper with prompt caching and per-step usage tracking.

Reads ANTHROPIC_API_KEY from the environment (Django loads the project-root .env
on startup, so the key is already in os.environ when this module is imported).

For the SERP step, exposes server-side ``web_search`` and ``web_fetch`` tools
so the model can browse competitor results without client-side scraping.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import anthropic

from .types import StepUsage

logger = logging.getLogger(__name__)

# Anthropic-hosted server-side tools (versioned identifiers).
# Update here when Anthropic ships newer tool versions.
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}
WEB_FETCH_TOOL = {
    "type": "web_fetch_20250910",
    "name": "web_fetch",
    "max_uses": 8,
}

# Per-million-token pricing in USD. Update as Anthropic prices change.
# Cache write = 1.25x base input. Cache read = 0.1x base input.
_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-7":   (15.0, 75.0),
    "claude-sonnet-4-6": (3.0,  15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


def _resolve_pricing(model: str) -> tuple[float, float]:
    base = model.split("[")[0]  # strip any [1m] suffix
    return _PRICING_PER_MTOK.get(base, (3.0, 15.0))


def _calc_cost(
    model: str, input_tokens: int, output_tokens: int,
    cache_creation_tokens: int, cache_read_tokens: int,
) -> float:
    in_per_mtok, out_per_mtok = _resolve_pricing(model)
    plain_in_cost = (input_tokens / 1_000_000) * in_per_mtok
    cache_write_cost = (cache_creation_tokens / 1_000_000) * in_per_mtok * 1.25
    cache_read_cost = (cache_read_tokens / 1_000_000) * in_per_mtok * 0.1
    output_cost = (output_tokens / 1_000_000) * out_per_mtok
    return round(plain_in_cost + cache_write_cost + cache_read_cost + output_cost, 6)


def _resolve_anthropic_api_key() -> str:
    """DB value (AiSetting) wins over the env var, since the admin form
    is the official place to manage it; falls back to ANTHROPIC_API_KEY."""
    try:
        from core.models import AiSetting
        return AiSetting.load().resolved_anthropic_api_key()
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY", "").strip()


@dataclass
class ClaudeReply:
    text: str
    json: Any | None
    usage: StepUsage
    raw_response: Any


class ClaudeClient:
    def __init__(self) -> None:
        key = _resolve_anthropic_api_key()
        if not key:
            raise RuntimeError(
                "Anthropic API key is not set. Add it via /admin-os/ai-settings/ "
                "(Content Pipeline → Anthropic API key) or set ANTHROPIC_API_KEY "
                "in the project-root .env."
            )
        self._client = anthropic.Anthropic(api_key=key)

    def call(
        self,
        *,
        step: str,
        model: str,
        max_tokens: int,
        system_text: str,
        user_text: str,
        cache_system: bool = True,
        with_web_tools: bool = False,
        expect_json: bool = False,
    ) -> ClaudeReply:
        """One Claude API call with a single system + single user message.

        Caches the system block by default (5-minute TTL) — keep system text
        large and stable so the cache pays for itself across the 5 pipeline steps.

        ``expect_json=True`` extracts the first ```json fenced block from the reply
        and parses it; raises ValueError if not found / not parseable.
        """
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system_text}]
        if cache_system:
            system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_blocks,
            "messages": [{"role": "user", "content": user_text}],
        }
        if with_web_tools:
            params["tools"] = [WEB_SEARCH_TOOL, WEB_FETCH_TOOL]

        logger.info("claude_pipeline.call step=%s model=%s tools=%s", step, model, with_web_tools)
        resp = self._client.messages.create(**params)

        text = _collect_text(resp)
        usage = _build_usage(step, model, resp)
        parsed = _extract_json(text) if expect_json else None
        return ClaudeReply(text=text, json=parsed, usage=usage, raw_response=resp)

    def call_vision(
        self,
        *,
        step: str,
        model: str,
        max_tokens: int,
        system_text: str,
        user_text: str,
        images: list[tuple[str, bytes]],
        cache_system: bool = True,
        expect_json: bool = False,
    ) -> ClaudeReply:
        """One Claude call whose user turn carries one or more images plus text.

        ``images`` is a list of ``(media_type, raw_bytes)`` tuples (e.g.
        ``("image/png", png_bytes)``); each is base64-encoded into an image block,
        placed before ``user_text`` so the model sees the picture then the question.
        Used by the glossary visualization comprehension gate to judge a rendered
        screenshot against the term it is meant to teach.
        """
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system_text}]
        if cache_system:
            system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            }
            for media_type, data in images
        ]
        content.append({"type": "text", "text": user_text})

        logger.info("claude_pipeline.call_vision step=%s model=%s images=%d", step, model, len(images))
        resp = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": content}],
        )

        text = _collect_text(resp)
        usage = _build_usage(step, model, resp)
        parsed = _extract_json(text) if expect_json else None
        return ClaudeReply(text=text, json=parsed, usage=usage, raw_response=resp)


def _build_usage(step: str, model: str, resp: Any) -> StepUsage:
    usage_obj = getattr(resp, "usage", None)
    in_tok = int(getattr(usage_obj, "input_tokens", 0) or 0)
    out_tok = int(getattr(usage_obj, "output_tokens", 0) or 0)
    cache_create = int(getattr(usage_obj, "cache_creation_input_tokens", 0) or 0)
    cache_read = int(getattr(usage_obj, "cache_read_input_tokens", 0) or 0)
    cost = _calc_cost(model, in_tok, out_tok, cache_create, cache_read)
    return StepUsage(
        step=step,
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cache_creation_tokens=cache_create,
        cache_read_tokens=cache_read,
        cost_usd=cost,
    )


def _collect_text(resp: Any) -> str:
    parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


_FENCED_JSON_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """Pull the first ```json fenced block; fall back to whole text if no fence."""
    m = _FENCED_JSON_RE.search(text)
    payload = m.group(1) if m else text.strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        snippet = payload[:200].replace("\n", " ")
        raise ValueError(
            f"Expected valid JSON in Claude reply but failed to parse: {exc}. "
            f"First 200 chars: {snippet!r}"
        ) from exc
