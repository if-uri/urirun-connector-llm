#!/usr/bin/env bash
# llm: install once, then run — auto-discovered, no registry path.
set -euo pipefail
urirun install urirun-connector-llm            # local dev: pip install -e .
urirun run 'llm://host/chat/command/complete' --payload '{"prompt": "hello"}' --allow 'llm://*'
