# Makefile for SEC Filings Reviewer
#
# Common commands for development, testing, and documentation maintenance.

.PHONY: help install test coverage lint format docs-check docs-update hooks-install clean db-up db-down db-reset db-shell session-check

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
	@echo "  make coverage       Run tests with coverage report"
	@echo "  make lint           Run linter (ruff)"
	@echo "  make format         Format code (black)"
	@echo "  make session-check  Check development environment status"
	@echo ""
	@echo "Database:"
	@echo "  make db-up          Start PostgreSQL container"
	@echo "  make db-down        Stop PostgreSQL container"
	@echo "  make db-reset       Reset database (destroy + recreate)"
	@echo "  make db-shell       Open psql shell to dev database"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs-check     Check if docs are in sync with code"
	@echo "  make docs-update    Update coverage numbers in README"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean          Remove build artifacts and caches"

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

install:
	pip install -r requirements.txt
	@echo "✅ Dependencies installed"

hooks-install:
	git config core.hooksPath .githooks
	@echo "✅ Git hooks installed from .githooks/"
	@echo "   Pre-commit will now check documentation freshness"

# -----------------------------------------------------------------------------
# Development
# -----------------------------------------------------------------------------

test:
	pytest tests/ -v

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

clean:
	rm -rf __pycache__ .pytest_cache htmlcov .coverage
	rm -rf src/__pycache__ tests/__pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Cleaned build artifacts"

# -----------------------------------------------------------------------------
# Database (Docker)
# -----------------------------------------------------------------------------

db-up:
	docker compose up -d
	@echo "✅ PostgreSQL starting on localhost:5433"
	@echo "   Connection: postgresql://dev:dev@localhost:5433/filings_analysis"

db-down:
	docker compose down
	@echo "✅ PostgreSQL stopped"

db-reset:
	docker compose down -v
	docker compose up -d
	@echo "✅ Database reset complete. Fresh schema applied."

db-shell:
	docker compose exec db psql -U dev -d filings_analysis

# -----------------------------------------------------------------------------
# Session Check
# -----------------------------------------------------------------------------

session-check:
	@python scripts/session_check.py
