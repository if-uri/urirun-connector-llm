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


# --- image input (for multimodal models / OCR) -----------------------------

def _collect_images(image: str, images: list[str] | None) -> list[str]:
    out = [image] if image else []
    if images:
        out.extend(images)
    return [i for i in out if i]


def _image_bytes(img: str) -> tuple[bytes, str]:
    """Resolve a file path / http(s) URL / data-URI / raw base64 to (bytes, mime)."""
    import base64
    import mimetypes
    import os
    if os.path.isfile(img):
        with open(img, "rb") as fh:
            return fh.read(), (mimetypes.guess_type(img)[0] or "image/png")
    if img.startswith("data:"):
        header, _, b64 = img.partition(",")
        mime = header[5:].split(";", 1)[0] or "image/png"
        return base64.b64decode(b64), mime
    if img.startswith(("http://", "https://")):
        with urllib.request.urlopen(img, timeout=30) as response:
            return response.read(), (response.headers.get_content_type() or "image/png")
    return base64.b64decode(img), "image/png"  # assume raw base64


def _image_data_url(img: str) -> str:
    """A URL usable in a litellm ``image_url`` part (remote URLs pass through)."""
    if img.startswith(("http://", "https://")):
        return img
    import base64
    data, mime = _image_bytes(img)
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _image_b64(img: str) -> str:
    """Raw base64 (no ``data:`` prefix) for the Ollama ``/api/generate`` images field."""
    import base64
    if img.startswith(("http://", "https://")) or img.startswith("data:") or _looks_like_path(img):
        data, _ = _image_bytes(img)
        return base64.b64encode(data).decode()
    return img  # already raw base64


def _looks_like_path(img: str) -> bool:
    import os
    return os.path.isfile(img)


def _complete_litellm(prompt: str, model: str, base_url: str, images: list[str] | None = None) -> dict[str, Any]:
    try:
        import litellm
    except ImportError:
        return urirun.fail("litellm not installed — `pip install litellm` to use hosted providers", model=model)
    # Only forward base_url when it's a real override (not the Ollama default).
    api_base = base_url if base_url and base_url != DEFAULT_BASE_URL else None
    try:
        if images:
            content: list[dict] = [{"type": "text", "text": prompt}] if prompt else []
            content += [{"type": "image_url", "image_url": {"url": _image_data_url(i)}} for i in images]
            messages = [{"role": "user", "content": content}]
        else:
            messages = [{"role": "user", "content": prompt}]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return urirun.fail(f"image error: {exc}", model=model)
    try:
        resp = litellm.completion(model=model, messages=messages, api_base=api_base)
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
             provider: str = "", image: str = "", images: list[str] | None = None) -> dict[str, Any]:
    """Run a chat completion, optionally **multimodal**.

    Backend is chosen by the model/provider: a provider-prefixed model
    (``openrouter/...``, ``openai/...``) goes through **litellm** (hosted models,
    keyed by ``*_API_KEY``); a bare model goes to an **Ollama-compatible** backend
    at ``base_url``. Set ``provider`` to force one path.

    ``image`` / ``images`` attach pictures (file path, http(s) URL, data-URI or
    raw base64) for a vision model — litellm gets ``image_url`` message parts,
    Ollama gets the native ``images`` base64 list. Use a vision-capable model.
    """
    if not prompt and not (image or images):
        return urirun.fail("prompt or image is required")
    imgs = _collect_images(image, images)
    if _wants_litellm(model, provider):
        return _complete_litellm(prompt, model, base_url, imgs)
    body: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
    try:
        if imgs:
            body["images"] = [_image_b64(i) for i in imgs]
        payload = _http_json("POST", f"{base_url.rstrip('/')}/api/generate", body)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return urirun.fail(str(exc), model=model)
    return urirun.ok(model=model, provider="ollama", response=payload.get("response", ""))


@conn.handler("vision/command/ocr", isolated=True, meta={"label": "Extract text from an image (OCR)"})
def ocr(image: str = "", model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL,
        provider: str = "", prompt: str = "") -> dict[str, Any]:
    """OCR / read an image with a vision model.

    ``image`` is a file path, http(s) URL, data-URI or raw base64. Returns the
    recognised text in ``response``. Pass a vision-capable ``model`` (e.g. a local
    Ollama ``llava``/``llama3.2-vision``, or a hosted ``openrouter/...`` vision
    model). ``prompt`` overrides the default OCR instruction.
    """
    if not image:
        return urirun.fail("image is required")
    instruction = prompt or "Extract ALL text from this image verbatim. Return only the text, no commentary."
    return complete(instruction, model=model, base_url=base_url, provider=provider, image=image)


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
