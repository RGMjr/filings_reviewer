# Makefile for SEC Filings Reviewer
#
# Common commands for development, testing, and documentation maintenance.

.PHONY: help install test test-unit coverage lint format docs-check docs-update hooks-install clean test-docker test-smoke-live

# Default target
help:
	@echo "SEC Filings Reviewer - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install        Install dependencies"
	@echo "  make hooks-install  Install git pre-commit hooks"
	@echo ""
	@echo "Development:"
	@echo "  make test           Run all tests"
	@echo "  make test-unit      Run unit tests in parallel (pytest-xdist)"
	@echo "  make coverage       Run tests with coverage report"
	@echo "  make lint           Run linter (ruff)"
	@echo "  make format         Format code (black)"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs-check     Check if docs are in sync with code"
	@echo "  make docs-update    Update coverage numbers in README"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean          Remove build artifacts and caches"
	@echo ""
	@echo "Deployment:"
	@echo "  make test-docker    Build Docker image and run deployment tests locally"
	@echo "  make test-smoke-live Run smoke tests against live Render deployment"

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

install:
	pip install -r requirements.txt
	@echo "✅ Dependencies installed"

hooks-install:
	# Install the default pre-commit hook (ruff + yaml checks on commit).
	uv run pre-commit install
	# Install the pre-push hook (unit tests before push).
	uv run pre-commit install --hook-type pre-push
	# Pre-fetch hook environments so the first commit isn't a minute-long wait.
	uv run pre-commit install-hooks
	@echo "pre-commit hooks installed (pre-commit + pre-push)"
	@echo "If you previously ran the old hooks-install, clear the stale config:"
	@echo "  git config --unset core.hooksPath"

# -----------------------------------------------------------------------------
# Development
# -----------------------------------------------------------------------------

test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -n auto -v

coverage:
	pytest --cov=src --cov-report=html --cov-report=term
	@echo ""
	@echo "HTML report: htmlcov/index.html"

lint:
	ruff check src/ tests/

format:
	black src/ tests/
	@echo "✅ Code formatted"

# -----------------------------------------------------------------------------
# Documentation
# -----------------------------------------------------------------------------

docs-check:
	@python scripts/check_docs_sync.py

docs-update:
	@echo "Updating coverage in README.md..."
	@COVERAGE=$$(pytest --cov=src --cov-report=term -q --tb=no 2>/dev/null | grep TOTAL | awk '{print $$4}' | tr -d '%'); \
	if [ -n "$$COVERAGE" ]; then \
		sed -i "s/Test Coverage:\*\* [0-9]*%/Test Coverage:** $${COVERAGE}%/" README.md; \
		echo "✅ README.md updated with coverage: $${COVERAGE}%"; \
	else \
		echo "❌ Could not determine coverage"; \
	fi

# Alias for quick doc validation
docs: docs-check

# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Deployment
# -----------------------------------------------------------------------------

test-docker:
	docker build -t filings-reviewer-test .
	uv run pytest tests/deployment/ -m deployment -v --tb=short --no-cov

test-smoke-live:
	SMOKE_TEST_BASE_URL=https://filings-reviewer.onrender.com \
	uv run pytest tests/deployment/test_smoke.py -m deployment -v --tb=short --no-cov

# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------

clean:
	rm -rf __pycache__ .pytest_cache htmlcov .coverage
	rm -rf src/__pycache__ tests/__pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Cleaned build artifacts"
