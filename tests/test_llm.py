# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

from __future__ import annotations

import json

import urirun
from urirun import v2
from urirun_connector_llm import complete, connector_manifest, list_models, main, ocr, urirun_bindings
import urirun_connector_llm.core as core

ROUTE_COMPLETE = "llm://host/chat/command/complete"
ROUTE_MODELS = "llm://host/model/query/list"
ROUTE_OCR = "llm://host/vision/command/ocr"
ALL_ROUTES = {ROUTE_COMPLETE, ROUTE_MODELS, ROUTE_OCR}

# 1x1 transparent PNG as a data-URI, for image tests (no real OCR needed).
PNG_1PX = ("data:image/png;base64,"
           "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def test_complete_requires_prompt() -> None:
    result = complete("")
    assert result["ok"] is False
    assert "prompt or image is required" in result["error"]


def test_complete_executes_real_path(monkeypatch) -> None:
    monkeypatch.setattr(core, "_http_json", lambda *a, **k: {"response": "hello!"})
    assert complete("hi") == {"ok": True, "model": "llama3", "provider": "ollama", "response": "hello!"}


def test_provider_routing() -> None:
    # bare model -> Ollama; provider-prefixed model -> litellm
    assert core._wants_litellm("llama3", "") is False
    assert core._wants_litellm("mistral:7b", "") is False
    assert core._wants_litellm("openrouter/anthropic/claude-3.5-sonnet", "") is True
    assert core._wants_litellm("gpt-4o-mini", "openai") is True
    assert core._wants_litellm("openrouter/x", "ollama") is False  # explicit override wins


def test_complete_routes_through_litellm_for_prefixed_model(monkeypatch) -> None:
    calls = {}

    def fake_completion(model, messages, api_base=None):
        calls["model"] = model
        calls["api_base"] = api_base
        return {"choices": [{"message": {"content": "hi from claude"}}]}

    import sys, types
    fake = types.ModuleType("litellm")
    fake.completion = fake_completion
    monkeypatch.setitem(sys.modules, "litellm", fake)
    r = complete("hello", model="openrouter/anthropic/claude-3.5-sonnet")
    assert r == {"ok": True, "model": "openrouter/anthropic/claude-3.5-sonnet",
                 "provider": "litellm", "response": "hi from claude"}
    assert calls["model"] == "openrouter/anthropic/claude-3.5-sonnet"
    assert calls["api_base"] is None  # default ollama base_url is not forwarded to litellm


def test_litellm_missing_is_a_clean_error(monkeypatch) -> None:
    import sys
    monkeypatch.setitem(sys.modules, "litellm", None)  # force ImportError on `import litellm`
    r = complete("hello", model="openai/gpt-4o-mini")
    assert r["ok"] is False and "litellm" in r["error"]


def test_complete_backend_error(monkeypatch) -> None:
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(core, "_http_json", boom)
    r = complete("hi")
    assert r["ok"] is False and "offline" in r["error"]


def test_models_executes_real_path(monkeypatch) -> None:
    monkeypatch.setattr(core, "_http_json", lambda *a, **k: {"models": [{"name": "llama3"}, {"name": "mistral"}]})
    assert list_models()["models"] == ["llama3", "mistral"]


def test_bindings_are_isolated_handlers() -> None:
    b = urirun_bindings()["bindings"]
    assert set(b) == ALL_ROUTES
    for route, export in ((ROUTE_COMPLETE, "complete"), (ROUTE_MODELS, "list_models")):
        # registry-portable in-process handler: runs out-of-process via urirun.exec
        assert b[route]["adapter"] == "local-function-subprocess"
        assert b[route]["python"]["module"] == "urirun_connector_llm.core"
        assert b[route]["python"]["export"] == export
        assert "argv" not in b[route]
    json.dumps(urirun_bindings())  # serializable: no live ref leaks


def test_compiles_and_routes_present() -> None:
    registry = urirun.compile_registry(json.loads(json.dumps(urirun_bindings())))
    uris = {r["uri"] for r in urirun.list_routes(registry)}
    assert ALL_ROUTES <= uris


def test_runtime_executes_from_compiled_registry() -> None:
    # the whole point: a serialized->compiled registry still runs the route
    # out-of-process. Point at an unreachable backend so no real network is hit:
    # the route still executes and returns a structured connection-refused result.
    registry = urirun.compile_registry(json.loads(json.dumps(urirun_bindings())))
    env = v2.run(ROUTE_MODELS, registry, payload={"base_url": "http://127.0.0.1:1"},
                 mode="execute", policy=urirun.policy(allow=["llm://*"]))
    assert env["ok"] is True
    data = urirun.result_data(env)
    assert data["ok"] is False  # connection refused: route ran, backend unreachable
    assert "error" in data


def test_manifest_prose_plus_derived_routes() -> None:
    m = connector_manifest()
    assert m["id"] == "llm"
    assert set(m["routes"]) == ALL_ROUTES
    assert m["uriSchemes"] == ["llm"]
    assert m["summary"] and m["keywords"]  # prose preserved
    json.dumps(m)


def test_cli_bindings_and_manifest(capsys) -> None:
    assert main(["bindings"]) == 0
    assert ROUTE_COMPLETE in json.loads(capsys.readouterr().out)["bindings"]
    assert main(["manifest"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "llm"


# --- image / OCR -----------------------------------------------------------

def test_image_helpers_resolve_data_uri() -> None:
    raw, mime = core._image_bytes(PNG_1PX)
    assert mime == "image/png" and raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert core._image_data_url(PNG_1PX).startswith("data:image/png;base64,")
    # http(s) URLs pass through to litellm untouched (no fetch)
    assert core._image_data_url("https://x/y.png") == "https://x/y.png"


def test_image_helpers_resolve_file(tmp_path) -> None:
    import base64
    p = tmp_path / "pic.png"
    p.write_bytes(base64.b64decode(PNG_1PX.split(",", 1)[1]))
    raw, mime = core._image_bytes(str(p))
    assert mime == "image/png" and raw[:4] == b"\x89PNG"


def test_complete_with_image_builds_multimodal_litellm(monkeypatch) -> None:
    captured = {}

    def fake_completion(model, messages, api_base=None):
        captured["messages"] = messages
        return {"choices": [{"message": {"content": "INVOICE 2026"}}]}

    import sys, types
    fake = types.ModuleType("litellm"); fake.completion = fake_completion
    monkeypatch.setitem(sys.modules, "litellm", fake)
    r = complete("read it", model="openrouter/google/gemini-3.1-flash-image-preview", image=PNG_1PX)
    assert r == {"ok": True, "model": "openrouter/google/gemini-3.1-flash-image-preview",
                 "provider": "litellm", "response": "INVOICE 2026"}
    content = captured["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "read it"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_complete_with_image_ollama_native(monkeypatch) -> None:
    sent = {}

    def fake_http(method, url, body=None, timeout=30.0):
        sent["url"] = url; sent["body"] = body
        return {"response": "READ"}

    monkeypatch.setattr(core, "_http_json", fake_http)
    r = complete("read", model="llava", image=PNG_1PX)   # bare model -> Ollama path
    assert r["ok"] is True and r["provider"] == "ollama"
    assert sent["url"].endswith("/api/generate")
    assert isinstance(sent["body"]["images"], list) and sent["body"]["images"]
    # native Ollama wants raw base64 (no data: prefix)
    assert not sent["body"]["images"][0].startswith("data:")


def test_ocr_route(monkeypatch) -> None:
    def fake_completion(model, messages, api_base=None):
        return {"choices": [{"message": {"content": "FAKTURA 199,00 PLN"}}]}

    import sys, types
    fake = types.ModuleType("litellm"); fake.completion = fake_completion
    monkeypatch.setitem(sys.modules, "litellm", fake)
    r = ocr(PNG_1PX, model="openrouter/google/gemini-3.1-flash-image-preview")
    assert r["ok"] is True
    assert r["response"] == "FAKTURA 199,00 PLN"


def test_ocr_requires_image() -> None:
    assert ocr("")["ok"] is False
