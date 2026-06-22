# llm connector — examples

LLM chat completion (gated by an API key).

## Install
```bash
urirun install urirun-connector-llm
```
`urirun install` resolves catalog ids via connect.ifuri.com; `--catalog <url>` points at a
local/on-prem registry; a full package name / git URL / path falls back to `pip install`.

## Run
```bash
# LLM chat completion (gated by an API key) (read)
urirun run 'llm://host/chat/command/complete' --payload '{"prompt": "hello"}' --allow 'llm://*'

# preview without running (dry-run): drop --execute
urirun run 'llm://host/chat/command/complete' --payload '{"prompt": "hello"}' --allow 'llm://*'
```
> Config-gated: without runtime config this prints the plan (dry-run).

## Inspect the runtime (no path — like error:// / log://)
```bash
urirun list | grep 'llm://'                                   # this connector's routes
urirun run 'registry://local/routes/query/list' --payload '{"scheme":"llm"}' --allow 'registry://*'
urirun run 'registry://local/bindings/query/show' --payload '{"uri":"llm://host/chat/command/complete"}' --allow 'registry://*'   # full typed contract
urirun errors                                                      # recent runtime errors (error://)
```

## Generate a client / API surface from the binding
```bash
urirun discover | urirun gen openapi - --out openapi.json   # OpenAPI 3 (one path per route)
urirun discover | urirun gen proto   - --out service.proto  # protobuf + gRPC (typed rpc per route)
urirun discover | urirun gen client  - --out client.py      # typed Python client
```
