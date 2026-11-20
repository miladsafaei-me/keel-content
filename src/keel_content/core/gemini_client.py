"""Gemini API wrapper: the one place every Gemini text call of a Keel consumer goes through.

Standard library only (urllib), so a site that needs nothing else from keel-content
can call it without the Anthropic SDK being used. It owns what the model-call rules
(``~/.claude/topics/model-api-caching.md``) put on a wrapper:

- **The model id**, fixed per client (``KEEL_GEMINI_MODEL`` or ``DEFAULT_MODEL``).
- **The prompt cache.** Gemini caches a repeated prefix implicitly; the wrapper sends
  the system instruction first and unchanged, and reports
  ``usageMetadata.cachedContentTokenCount`` so a run can prove it.
- **The response cache**, when the caller passes a ``store`` (any object with
  ``get(key) -> dict | None`` and ``set(key, record)``). The key is the SHA-256 of
  canonical JSON of provider, model, system, user, output kind, generation settings
  and the caller's ``prompt_version``. Only a complete, valid answer is stored:
  never an error, a refusal, a cut-off answer or JSON that does not parse.
  ``refresh=True`` bypasses it.
- **Google Search grounding**, off by default: ``generate(..., grounding=True)`` adds the
  ``google_search`` tool and ``result.sources`` lists the cited ``{"title", "uri"}`` pairs
  from ``groundingMetadata.groundingChunks``. The flag is part of the response-cache key
  (only when on, so keys of existing callers do not change). Grounded answers rely on live
  web results: pass a short-lived store, or none.
- **Cost logging**, one log line per call: model, input, cached, output and thinking
  tokens, the dollar cost (``price_per_mtok``; a free-tier key costs 0) and whether
  the response cache answered.

Every failure is one ``GeminiError`` with a ``kind`` the caller can fall back on:
``no_key``, ``auth``, ``quota``, ``unavailable``, ``blocked``, ``truncated``,
``bad_response``, ``network``.

    client = GeminiClient(api_key=key)
    result = client.generate(SYSTEM, user_text, json_output=True, store=db_store,
                             prompt_version="review-v1")
    result.data        # the parsed JSON
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiError(Exception):
    def __init__(self, kind: str, message: str = ""):
        super().__init__("%s: %s" % (kind, message) if message else kind)
        self.kind = kind


@dataclass
class GeminiResult:
    text: str
    data: object = None
    model: str = ""
    model_version: str = ""
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    cache_hit: bool = False
    sources: list = field(default_factory=list)


def cache_key(**parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, *, timeout: float = 120.0,
                 thinking_level: str = "low", price_per_mtok: tuple = (0.0, 0.0), retries: int = 1):
        self.api_key = (api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")).strip()
        self.model = model or os.environ.get("KEEL_GEMINI_MODEL", "") or DEFAULT_MODEL
        self.timeout = timeout
        self.thinking_level = thinking_level
        self.price_per_mtok = price_per_mtok
        self.retries = retries

    def _body(self, system: str, user: str, json_output: bool, temperature: float, max_output_tokens: int,
              grounding: bool = False) -> dict:
        config = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
        if json_output:
            config["responseMimeType"] = "application/json"
        if self.thinking_level:
            config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        # Stable first (system), volatile last (user): the order the prompt cache needs.
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": config}
        if grounding:
            body["tools"] = [{"google_search": {}}]
        return body

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            ENDPOINT.format(model=self.model), data=json.dumps(body).encode(),
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:300].decode("utf-8", "replace")
                if exc.code == 429:
                    raise GeminiError("quota", detail) from exc
                if exc.code in (401, 403):
                    raise GeminiError("auth", detail) from exc
                if exc.code >= 500 and attempt < self.retries:
                    attempt += 1
                    time.sleep(3 * attempt)
                    continue
                raise GeminiError("unavailable" if exc.code >= 500 else "bad_response", "%s %s" % (exc.code, detail)) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    attempt += 1
                    time.sleep(3 * attempt)
                    continue
                raise GeminiError("network", str(exc)) from exc
            except ValueError as exc:
                raise GeminiError("bad_response", "not JSON") from exc

    def generate(self, system: str, user: str, *, json_output: bool = False, temperature: float = 0.4,
                 max_output_tokens: int = 2048, store=None, prompt_version: str = "", refresh: bool = False,
                 label: str = "", grounding: bool = False) -> GeminiResult:
        if not self.api_key:
            raise GeminiError("no_key")
        key = cache_key(provider="gemini", model=self.model, system=system, user=user, json=json_output,
                        temperature=temperature, max_output_tokens=max_output_tokens,
                        thinking=self.thinking_level, prompt_version=prompt_version,
                        **({"grounding": True} if grounding else {}))
        if store is not None and not refresh:
            hit = store.get(key)
            if hit:
                logger.info("gemini %s model=%s cache_hit=1", label, self.model)
                return GeminiResult(text=hit["text"], data=hit.get("data"), model=self.model,
                                    model_version=hit.get("model_version", ""), usage={}, cache_hit=True,
                                    sources=hit.get("sources") or [])

        payload = self._post(self._body(system, user, json_output, temperature, max_output_tokens, grounding))
        candidates = payload.get("candidates") or []
        if not candidates:
            raise GeminiError("blocked", str(payload.get("promptFeedback", ""))[:200])
        cand = candidates[0]
        reason = cand.get("finishReason", "")
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
        if reason == "MAX_TOKENS":
            raise GeminiError("truncated")
        if reason not in ("STOP", "") or not text.strip():
            raise GeminiError("blocked", reason)
        data = None
        if json_output:
            try:
                data = json.loads(text)
            except ValueError as exc:
                raise GeminiError("bad_response", "answer is not valid JSON") from exc

        sources = []
        for chunk in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []:
            web = chunk.get("web") or {}
            if web.get("uri"):
                sources.append({"title": web.get("title", ""), "uri": web["uri"]})

        meta = payload.get("usageMetadata") or {}
        usage = {"input": meta.get("promptTokenCount", 0), "cached": meta.get("cachedContentTokenCount", 0),
                 "output": meta.get("candidatesTokenCount", 0), "thinking": meta.get("thoughtsTokenCount", 0)}
        price_in, price_out = self.price_per_mtok
        cost = ((usage["input"] - usage["cached"]) * price_in + usage["cached"] * price_in * 0.25
                + (usage["output"] + usage["thinking"]) * price_out) / 1_000_000
        logger.info("gemini %s model=%s version=%s input=%s cached=%s output=%s thinking=%s cost_usd=%.5f cache_hit=0",
                    label, self.model, payload.get("modelVersion", ""), usage["input"], usage["cached"],
                    usage["output"], usage["thinking"], cost)
        result = GeminiResult(text=text, data=data, model=self.model, model_version=payload.get("modelVersion", ""),
                              usage=usage, cost_usd=cost, sources=sources)
        if store is not None:
            store.set(key, {"text": text, "data": data, "model_version": result.model_version,
                            "prompt_version": prompt_version, "usage": usage, "cost_usd": cost,
                            "sources": sources})
        return result
