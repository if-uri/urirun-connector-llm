.PHONY: help manifest bindings smoke test
help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n",$$1,$$2}'
manifest: ## Print the connector manifest
	urirun-connector-llm manifest
bindings: ## Print urirun bindings
	urirun-connector-llm bindings
smoke: ## bindings -> urirun connectors smoke (dry-run, no backend needed)
	urirun-connector-llm bindings | urirun connectors smoke - \
	  --run 'llm://host/chat/command/complete' --payload '{"prompt":"hi","model":"llama3"}' \
	  --allow 'llm://*' --name llm
test: ## Install editable + smoke
	pip install -e . && python3 -m pytest -q && $(MAKE) smoke
