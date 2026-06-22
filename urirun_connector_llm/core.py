# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

"""LLM completion + model-list routes for urirun.

Routes match the connect.ifuri.com contract:

* ``llm://host/chat/command/complete``  -- run a chat completion
* ``llm://host/model/query/list``       -- list available models

Each route is declared once with a typed ``@conn.handler``: the function
signature becomes the input schema and the body holds the real logic — no argv
template, no ``_exec.py``, no ``run_route`` dispatcher. ``isolated=True`` runs the
route out-of-process through the shared ``python -m urirun.exec`` runner, so the
binding stays **registry-portable**: it executes from a compiled/served registry
(``urirun compile`` / ``urirun run``) with only the package importable — no
console-script install and no per-connector shim. The backend is an
Ollama-compatible endpoint by default (``http://localhost:11434``); point
``base_url`` at a litellm/OpenAI-compatible proxy to use hosted models such as
Claude.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import urirun

CONNECTOR_ID = "llm"
conn = urirun.connector(CONNECTOR_ID, scheme="llm")

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3"


# --- shared backend helper -------------------------------------------------

def _http_json(method: str, url: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _wants_litellm(model: str, provider: str) -> bool:
    """Route through litellm when the caller picks a hosted provider.

    A provider-prefixed model id (``openrouter/anthropic/claude-3.5-sonnet``,
    ``openai/gpt-4o-mini``, ``anthropic/claude-3-5-sonnet``, ``gemini/...``,
    ``groq/...``) contains a ``/`` — litellm reads the provider from that prefix
    and the matching ``*_API_KEY`` env var. A bare model (``llama3``,
    ``mistral:7b``) keeps the zero-dependency Ollama path. ``provider`` forces it
    either way (``provider="litellm"`` / ``provider="ollama"``).
    """
    if provider == "ollama":
        return False
    if provider in ("litellm", "openai", "openrouter", "anthropic", "azure", "gemini", "groq", "bedrock"):
        return True
    return "/" in model


def _complete_litellm(prompt: str, model: str, base_url: str) -> dict[str, Any]:
    try:
        import litellm
    except ImportError:
        return urirun.fail("litellm not installed — `pip install litellm` to use hosted providers", model=model)
    # Only forward base_url when it's a real override (not the Ollama default).
    api_base = base_url if base_url and base_url != DEFAULT_BASE_URL else None
    try:
        resp = litellm.completion(model=model, messages=[{"role": "user", "content": prompt}],
                                  api_base=api_base)
    except Exception as exc:  # noqa: BLE001 - surface any provider/auth error as JSON
        return urirun.fail(str(exc), model=model)
    try:
        text = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        text = getattr(getattr(resp.choices[0], "message", None), "content", "") if getattr(resp, "choices", None) else ""
    return urirun.ok(model=model, provider="litellm", response=text or "")


# --- route handlers: schema + implementation derived from the signature ----

@conn.handler("chat/command/complete", isolated=True, meta={"label": "Run a chat completion"})
def complete(prompt: str = "", model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL,
             provider: str = "") -> dict[str, Any]:
    """Run a chat completion.

    Backend is chosen by the model/provider: a provider-prefixed model
    (``openrouter/...``, ``openai/...``) goes through **litellm** (hosted models,
    keyed by ``*_API_KEY``); a bare model goes to an **Ollama-compatible** backend
    at ``base_url``. Set ``provider`` to force one path.
    """
    if not prompt:
        return urirun.fail("prompt is required")
    if _wants_litellm(model, provider):
        return _complete_litellm(prompt, model, base_url)
    try:
        payload = _http_json("POST", f"{base_url.rstrip('/')}/api/generate",
                             {"model": model, "prompt": prompt, "stream": False})
    except (urllib.error.URLError, OSError) as exc:
        return urirun.fail(str(exc), model=model)
    return urirun.ok(model=model, provider="ollama", response=payload.get("response", ""))


@conn.handler("model/query/list", isolated=True, meta={"label": "List available models"})
def list_models(base_url: str = DEFAULT_BASE_URL) -> dict[str, Any]:
    """List the models available on the backend."""
    try:
        payload = _http_json("GET", f"{base_url.rstrip('/')}/api/tags")
    except (urllib.error.URLError, OSError) as exc:
        return urirun.fail(str(exc))
    return urirun.ok(models=[e["name"] for e in payload.get("models", []) if isinstance(e, dict) and e.get("name")])


# --- authoring surface: bindings / manifest / CLI --------------------------

def urirun_bindings() -> dict[str, Any]:
    """Serializable v2 bindings for this connector (entry point: urirun.bindings)."""
    return conn.bindings()


def connector_manifest() -> dict[str, Any]:
    """Full manifest: prose (connector.manifest.json) + routes/uriSchemes/
    adapterKinds/examples derived from the handlers."""
    return conn.manifest(urirun.load_manifest(__package__))


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point: subcommands + dispatch derived from the handlers."""
    return conn.cli(argv, manifest_prose=urirun.load_manifest(__package__))


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
