# Gclaw test + lint runner. One entry point for humans, agents, and CI.
#
#   make test        # the whole suite: ruff + pytest + vitest. Run this before a PR.
#   make py          # python only (ruff check + pytest)
#   make node        # node only (vitest)
#   make fmt         # auto-format python (ruff format)
#   make mutants     # mutation-test the math units (prove the tests catch bugs)
#   make install     # one-time: materialize dev deps (uv sync + npm ci)
#
# Python runs through `uv` (no project venv needed — `uv run` is ephemeral and fast).
# A box hook blocks bare `python3`; always go through uv. Node uses the local vitest.

.PHONY: test py node lint fmt install ci mutants

install:
	uv sync --group dev
	npm ci || npm install

lint:
	uv run --no-project ruff check scripts tests

fmt:
	uv run --no-project ruff format scripts tests
	uv run --no-project ruff check --fix scripts tests

py: lint
	uv run --group dev pytest

node:
	npm test

test: py node

# Mutation testing — inject bugs into the math units and prove the property suite kills
# them. PYTHONPATH=scripts so mutmut's pytest run resolves the bare `import sizing`
# (conftest path-injects scripts/, but mutmut keys mutants by the scripts/ source path).
mutants:
	PYTHONPATH=scripts uv run --group dev mutmut run
	uv run --group dev mutmut results

# What CI runs — fail on any lint/format drift, then the suites.
ci:
	uv run --no-project ruff format --check scripts tests
	uv run --no-project ruff check scripts tests
	uv run --group dev pytest
	npm test
