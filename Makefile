UV ?= uv

.PHONY: install lint format format-check test typecheck security build all

install:
	$(UV) sync --locked

format:
	$(UV) run --locked ruff format kairos_core tests

format-check:
	$(UV) run --locked ruff format --check kairos_core tests

lint:
	$(UV) run --locked ruff check kairos_core tests

typecheck:
	$(UV) run --locked mypy kairos_core

test:
	$(UV) run --locked pytest -q --tb=short

security:
	$(UV) run --locked bandit -q -r kairos_core -x tests

build:
	$(UV) build --no-sources

all: lint format-check typecheck security test build
