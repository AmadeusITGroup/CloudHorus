.PHONY: help install install-dev install-all test lint format clean run run-gui pre-commit-install pre-commit-run

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install core dependencies
	pip install -r requirements.txt

install-dev: ## Install with dev dependencies (tests, linting)
	pip install -e ".[dev]"

install-all: ## Install everything (Azure SDK + export + dev)
	pip install -e ".[all]"

test: ## Run tests
	python3 -m pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage report
	python3 -m pytest tests/ --cov=src --cov-report=term-missing --tb=short

lint: ## Run linters (flake8 + black check + isort check + mypy)
	flake8 src/ tests/
	black --check --diff src/ tests/
	isort --check --diff src/ tests/
	mypy src/

format: ## Auto-format code
	black src/ tests/
	isort src/ tests/

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true

run: ## Run CLI (pass ARGS="--help" for usage)
	python3 src/main.py $(ARGS)

run-gui: ## Launch the desktop GUI
	python3 cloudhorus_webui.py

pre-commit-install: ## Install pre-commit git hooks
	pre-commit install

pre-commit-run: ## Run pre-commit on all files
	pre-commit run --all-files
