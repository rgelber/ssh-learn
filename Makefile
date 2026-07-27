.PHONY: install dev test lint fmt check clean

install:
	pip install -e .

dev:
	pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check src tests

fmt:
	ruff check --fix src tests

check: lint test

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
