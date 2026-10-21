SHELL := /bin/bash
PY := .venv/bin/python
AGENT := .venv/bin/agent

.PHONY: install lint test demo mcp-demo check docker

install:
	bash scripts/install.sh

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

test:
	$(PY) -m pytest -q

demo:
	bash scripts/demo.sh

mcp-demo:
	$(AGENT) mcp-demo --workspace demo_workspace

check: lint test

docker:
	docker build -t workspace-agent:local .
	docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges workspace-agent:local
