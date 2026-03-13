# syntax=docker/dockerfile:1

# SEC Filings Analysis Pipeline
# Multi-target Dockerfile:
#   base   - dependencies + code (shared)
#   web    - Flask web server via Waitress
#   worker - Extraction job runner
#   test   - pytest (includes gold standard data)

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS base

# Prevents Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

# Set the Python path to include src directory
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies for psycopg and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create a non-privileged user that the app will run under.
# See https://docs.docker.com/go/dockerfile-user-best-practices/
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/home/appuser" \
    --shell "/bin/bash" \
    --uid "${UID}" \
    appuser

# Copy dependency files first for Docker layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies using uv (frozen from lockfile)
RUN uv sync --frozen --no-dev --no-install-project

# Copy the source code into the container.
COPY --chown=appuser:appuser . .

# Install the project itself
RUN uv sync --frozen --no-dev

# Create directories for logs, data, and coverage with proper permissions
RUN mkdir -p /app/logs /app/data /app/filings_cache /app/htmlcov && \
    touch /app/.coverage && \
    chown -R appuser:appuser /app/logs /app/data /app/filings_cache /app/htmlcov /app/.coverage

# Switch to the non-privileged user to run the application.
USER appuser

# ---------------------------------------------------------------------------
# web: Flask app served by Waitress
# ---------------------------------------------------------------------------
FROM base AS web

EXPOSE 8000

CMD ["uv", "run", "waitress-serve", "--listen=0.0.0.0:8000", "--call", "src.web.app:create_app"]

# ---------------------------------------------------------------------------
# worker: Extraction job runner
# ---------------------------------------------------------------------------
FROM base AS worker

CMD ["uv", "run", "python3", "-m", "src.worker.job_runner"]

# ---------------------------------------------------------------------------
# test: pytest with gold standard data
# ---------------------------------------------------------------------------
FROM base AS test

# Install dev dependencies (pytest, coverage, etc.)
USER root
RUN uv sync --frozen
USER appuser

# Gold standard data is already present via the COPY . . above (data/gold_standard/)
# No additional COPY needed unless .dockerignore excludes it.

# Default command runs tests without coverage (use --cov to enable)
# Examples:
#   docker build --target test -t filings-test .
#   docker run filings-test                                    # Run all tests
#   docker run filings-test uv run pytest tests/unit/          # Run specific tests
CMD ["uv", "run", "pytest", "-v", "--tb=short", "--no-cov", "-p", "no:cacheprovider"]
