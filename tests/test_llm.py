# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

from __future__ import annotations

import json

import urirun
from urirun import v2
from urirun_connector_llm import complete, connector_manifest, list_models, main, urirun_bindings
import urirun_connector_llm.core as core

ROUTE_COMPLETE = "llm://host/chat/command/complete"
ROUTE_MODELS = "llm://host/model/query/list"


def test_complete_requires_prompt() -> None:
    result = complete("")
    assert result["ok"] is False
    assert "prompt is required" in result["error"]


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
    assert set(b) == {ROUTE_COMPLETE, ROUTE_MODELS}
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
    assert {ROUTE_COMPLETE, ROUTE_MODELS} <= uris


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
    assert set(m["routes"]) == {ROUTE_COMPLETE, ROUTE_MODELS}
    assert m["uriSchemes"] == ["llm"]
    assert m["summary"] and m["keywords"]  # prose preserved
    json.dumps(m)


def test_cli_bindings_and_manifest(capsys) -> None:
    assert main(["bindings"]) == 0
    assert ROUTE_COMPLETE in json.loads(capsys.readouterr().out)["bindings"]
    assert main(["manifest"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "llm"
