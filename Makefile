.PHONY: install lint format test typecheck all

install:
	pip install -e ".[dev]"

format:
	ruff format kairos_core tests

lint:
	ruff check kairos_core tests

typecheck:
	mypy kairos_core

test:
	pytest -q

all: lint typecheck test
