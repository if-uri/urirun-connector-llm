# Changelog

## [0.2.0] - 2026-06-22

### Added
- Multi-provider completions via litellm: a provider-prefixed `model`
  (`openrouter/...`, `openai/...`, `anthropic/...`) routes through
  `litellm.completion`, keyed by the matching `*_API_KEY`; bare models keep the
  Ollama path. New `provider` parameter forces the backend. Response now reports
  the serving `provider`. litellm is an optional dependency (clean error if
  missing).

## [0.1.0] - 2026-06-20

### Added
- Initial LLM connector: chat-completion and model-list `llm://` routes on the
  urirun connector SDK, dry-run by default, backed by an Ollama-compatible HTTP
  endpoint when `dry_run=false`. CLI, manifest, pytest suite, smoke, CI, entry point.
