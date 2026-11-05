# Everyday commands in one place: `make help`. Every target uses the project's venv.
BIN ?= venv/bin/
PY := $(BIN)python
.DEFAULT_GOAL := help
.PHONY: help install install-dev lint lint-all type js-check test test-fast cov eval check run on off restart status report rss metrics new-tool new-memory new-agent files-guide

help:  ## list the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

install:  ## create the venv and install the pinned dependencies
	python3 -m venv venv && $(PY) -m pip install -r requirements.txt

install-dev:  ## + the developer tools (mypy, coverage)
	$(PY) -m pip install -r requirements-dev.txt

lint:  ## the commit gate: syntax errors, undefined names (must be clean)
	$(BIN)ruff check jarvis tests scripts

# the modules whose types are checked (widen one module at a time, keep `make type` clean)
TYPED := jarvis/core/results.py jarvis/core/registry.py jarvis/core/safety.py jarvis/core/workmem.py \
	jarvis/core/budget.py jarvis/core/metrics.py jarvis/core/intents/base.py jarvis/core/intents/files.py \
	jarvis/core/intents/control.py jarvis/api/routes/metrics.py \
	jarvis/core/plugins.py jarvis/core/memories.py jarvis/memories

type:  ## the type gate (mypy) on the core contracts
	$(BIN)mypy $(TYPED)

js-check:  ## every frontend file parses (no build step: the browser loads them as they are)
	@for f in frontend/*.js; do node --check "$$f" || exit 1; done && echo "frontend: all files parse"

lint-all:  ## every style rule (a to-do list, not a gate)
	$(BIN)ruff check jarvis tests scripts --select E,F,W,B,UP,SIM,RUF --statistics

test:  ## the whole test suite (~5 min; no network, no real AI calls)
	$(PY) -m pytest

test-fast:  ## stop at the first failure
	$(PY) -m pytest -x --ff

cov:  ## the test suite with coverage; fails under the floor in pyproject.toml
	$(PY) -m pytest --cov=jarvis --cov-report=term:skip-covered --cov-report=html:data/coverage

eval:  ## the routing / shortcut scorecard (isolated from your learned data)
	$(PY) -m tests.eval.harness

check: lint type js-check test eval  ## everything CI runs

run:  ## the server in the foreground (Ctrl+C stops it)
	$(PY) -m jarvis.server --port 8000

on:  ## start KURAMA (server + desktop window)
	scripts/kurama-power.sh on
off:  ## stop KURAMA
	scripts/kurama-power.sh off
restart: off on  ## restart after a code change
status:  ## is it running?
	scripts/kurama-power.sh status

report:  ## what went wrong lately (traces)
	$(PY) scripts/trace_report.py

rss:  ## memory of the running server (budget: idle < 600 MB)
	@ps -o rss=,args= -C python | awk '/jarvis/ {printf "%.0f MB  %s\n", $$1/1024, $$0}' | cut -c1-110

metrics:  ## the live metrics (Prometheus text: tokens, tool calls, routing, jobs, RAM)
	@curl -s http://127.0.0.1:8000/api/v1/metrics | grep -v '^#'

new-tool:  ## skeleton of a new tool + its test: make new-tool NAME=word_count [GROUP=general] [SAFETY=safe]
	$(PY) scripts/new_plugin.py tool $(NAME) --group $(or $(GROUP),general) --safety $(or $(SAFETY),safe)

new-memory:  ## skeleton of a new memory source + its test: make new-memory NAME=bookmarks
	$(PY) scripts/new_plugin.py memory $(NAME)

new-agent:  ## skeleton of a new agent (folder, tools, test): make new-agent NAME=study
	$(PY) scripts/new_plugin.py agent $(NAME)

files-guide:  ## refresh LEARN.md's "every file" list from each file's own description
	$(PY) scripts/file_guide.py
