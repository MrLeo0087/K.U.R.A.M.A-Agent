# Everyday commands in one place: `make help`. Every target uses the project's venv.
PY := venv/bin/python
.DEFAULT_GOAL := help
.PHONY: help install lint lint-all test test-fast eval check run on off restart status report rss

help:  ## list the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

install:  ## create the venv and install the pinned dependencies
	python3 -m venv venv && $(PY) -m pip install -r requirements.txt

lint:  ## the commit gate: syntax errors, undefined names (must be clean)
	venv/bin/ruff check jarvis tests scripts

lint-all:  ## every style rule (a to-do list, not a gate)
	venv/bin/ruff check jarvis tests scripts --select E,F,W,B,UP,SIM,RUF --statistics

test:  ## the whole test suite (~5 min; no network, no real AI calls)
	$(PY) -m pytest

test-fast:  ## stop at the first failure
	$(PY) -m pytest -x --ff

eval:  ## the routing / shortcut scorecard (isolated from your learned data)
	$(PY) -m tests.eval.harness

check: lint test eval  ## everything CI runs

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
