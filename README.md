# urirun-connector-llm

LLM connector for [ifURI](https://ifuri.com) / urirun. Run completions and list
models through `llm://` routes.

Catalog: <https://connect.ifuri.com/connectors/llm>

| URI | Operation |
| --- | --- |
| `llm://host/chat/command/complete` | run a chat completion |
| `llm://host/model/query/list` | list available models |

Both routes call an external backend, so through the runtime they stay a
**dry-run plan by default** and only hit the backend with `--execute` (CLI) or
`mode="execute"` (library/runtime).

### Model & provider selection

`complete` picks the backend from the **model id** (and optional `provider`):

| `model` example | Backend | Needs |
| --- | --- | --- |
| `llama3`, `mistral:7b` | Ollama at `base_url` (default `http://localhost:11434`) | local Ollama |
| `openrouter/anthropic/claude-3.5-sonnet` | **litellm** (hosted) | `pip install litellm` + `OPENROUTER_API_KEY` |
| `openai/gpt-4o-mini` | **litellm** | `OPENAI_API_KEY` |

A provider-prefixed model (contains `/`) routes through litellm, which reads the
provider from the prefix and the matching `*_API_KEY` env var. A bare model uses
the zero-dependency Ollama path. Force either with `provider="litellm"` or
`provider="ollama"`. The response reports which `provider` served it.

```bash
# local Ollama
urirun-connector-llm complete --prompt "Say hi"
# hosted via litellm (key from env)
OPENROUTER_API_KEY=sk-... urirun-connector-llm complete \
  --prompt "Say hi" --model openrouter/anthropic/claude-3.5-sonnet
urirun-connector-llm list                         # list models
urirun-connector-llm bindings | urirun validate /dev/stdin
```

## Authoring shape (v2)

Each route is declared once with a single typed `@handler(isolated=True)` and runs
**out-of-process from a compiled registry**:

- a typed function holds the real logic and returns a structured result
  (`urirun.ok(...)` / `urirun.fail(...)`);
- `@conn.handler("seg/.../op", isolated=True)` registers the route — its signature
  is the input schema and the body is the implementation. There is no argv
  template, no `_exec.py` and no `run_route` dispatcher;
- the manifest (`connector.manifest.json`) is **prose-only** — `routes`,
  `uriSchemes` and `adapterKinds` are derived from the declared handlers.

Why `isolated=True` rather than a plain in-process handler: a compiled registry is
portable JSON, so a live function reference can't survive it. `isolated=True`
serializes the route as a `local-function-subprocess` binding (module + export),
and urirun runs it out-of-process through the shared `python -m urirun.exec`
runner — so the route executes from `urirun run <uri> <registry.json>` (or a served
registry) with only the package importable, no console-script install and no
per-connector shim.

```bash
urirun-connector-llm bindings | urirun validate /dev/stdin
urirun-connector-llm manifest
urirun run 'llm://host/chat/command/complete' registry.json --execute --allow 'llm://*'
```

Consumers stay on the public API: `urirun.policy(...)` for the allow policy,
`urirun.result_data(env)` to unwrap the route result, `urirun.action_space(reg)`
for the route/schema list, `urirun.testing` for the validate→compile→run→MCP/A2A
smoke, and `Connector.mcp_tools()` / `Connector.a2a_card()` to project to MCP/A2A
straight from the connector object.

## License

Released under the terms in [LICENSE](LICENSE).
