"""The Gemini wrapper: request shape, errors, response cache and what it never caches."""
import io
import json
import urllib.error

import pytest

from keel_content.core import gemini_client as gc


class Store:
    def __init__(self):
        self.rows = {}

    def get(self, key):
        return self.rows.get(key)

    def set(self, key, record):
        self.rows[key] = record


def answer(text='{"a": 1}', reason="STOP", usage=None):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": reason}],
            "usageMetadata": usage or {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 5},
            "modelVersion": "gemini-x"}


def test_no_key_is_its_own_kind():
    with pytest.raises(gc.GeminiError) as err:
        gc.GeminiClient(api_key="").generate("s", "u")
    assert err.value.kind == "no_key"


def test_request_order_and_json_and_cache(monkeypatch):
    sent = []
    client = gc.GeminiClient(api_key="k")
    monkeypatch.setattr(client, "_post", lambda body: sent.append(body) or answer())
    store = Store()
    first = client.generate("SYSTEM", "USER", json_output=True, store=store, prompt_version="v1")
    assert first.data == {"a": 1} and not first.cache_hit
    body = sent[0]
    assert list(body) == ["systemInstruction", "contents", "generationConfig"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    again = client.generate("SYSTEM", "USER", json_output=True, store=store, prompt_version="v1")
    assert again.cache_hit and len(sent) == 1
    client.generate("SYSTEM", "USER", json_output=True, store=store, prompt_version="v2")
    assert len(sent) == 2
    client.generate("SYSTEM", "USER", json_output=True, store=store, prompt_version="v1", refresh=True)
    assert len(sent) == 3


@pytest.mark.parametrize("payload,kind", [
    (answer(reason="MAX_TOKENS"), "truncated"),
    (answer(reason="SAFETY"), "blocked"),
    ({"candidates": []}, "blocked"),
    (answer(text="not json"), "bad_response"),
])
def test_bad_answers_raise_and_are_never_cached(monkeypatch, payload, kind):
    client = gc.GeminiClient(api_key="k")
    monkeypatch.setattr(client, "_post", lambda body: payload)
    store = Store()
    with pytest.raises(gc.GeminiError) as err:
        client.generate("s", "u", json_output=True, store=store)
    assert err.value.kind == kind
    assert store.rows == {}


@pytest.mark.parametrize("code,kind", [(429, "quota"), (403, "auth"), (400, "bad_response")])
def test_http_errors_are_classified(monkeypatch, code, kind):
    def boom(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, code, "x", {}, io.BytesIO(b"detail"))

    monkeypatch.setattr(gc.urllib.request, "urlopen", boom)
    with pytest.raises(gc.GeminiError) as err:
        gc.GeminiClient(api_key="k").generate("s", "u")
    assert err.value.kind == kind


def test_cost_uses_the_price_table(monkeypatch):
    client = gc.GeminiClient(api_key="k", price_per_mtok=(1.0, 10.0))
    monkeypatch.setattr(client, "_post", lambda body: answer(usage={
        "promptTokenCount": 1_000_000, "cachedContentTokenCount": 0, "candidatesTokenCount": 0, "thoughtsTokenCount": 0}))
    assert client.generate("s", "u").cost_usd == pytest.approx(1.0)
    assert json.loads(json.dumps(client.generate("s", "u").usage))["input"] == 1_000_000


def grounded_answer():
    payload = answer(text="Use AppX or AppY.")
    payload["candidates"][0]["groundingMetadata"] = {"groundingChunks": [
        {"web": {"uri": "https://a.example/x", "title": "A"}},
        {"web": {"uri": "https://b.example/y", "title": "B"}},
        {"web": {"title": "no uri"}}]}
    return payload


def test_grounding_off_by_default_sends_no_tools(monkeypatch):
    sent = []
    client = gc.GeminiClient(api_key="k")
    monkeypatch.setattr(client, "_post", lambda body: sent.append(body) or answer())
    result = client.generate("s", "u")
    assert "tools" not in sent[0]
    assert result.sources == []


def test_grounding_adds_tool_and_exposes_sources(monkeypatch):
    sent = []
    client = gc.GeminiClient(api_key="k")
    monkeypatch.setattr(client, "_post", lambda body: sent.append(body) or grounded_answer())
    result = client.generate("s", "u", grounding=True)
    assert sent[0]["tools"] == [{"google_search": {}}]
    assert result.sources == [{"title": "A", "uri": "https://a.example/x"}, {"title": "B", "uri": "https://b.example/y"}]


def test_grounding_flag_is_in_the_cache_key_and_sources_are_cached(monkeypatch):
    sent = []
    client = gc.GeminiClient(api_key="k")
    monkeypatch.setattr(client, "_post", lambda body: sent.append(body) or grounded_answer())
    store = Store()
    client.generate("s", "u", store=store)
    assert len(sent) == 1
    first = client.generate("s", "u", store=store, grounding=True)
    assert len(sent) == 2 and not first.cache_hit
    again = client.generate("s", "u", store=store, grounding=True)
    assert again.cache_hit and len(sent) == 2
    assert again.sources == first.sources
