# syntax=docker/dockerfile:1

# SEC Filings Analysis Pipeline
# This container runs batch extraction scripts and tests for analyzing S-1/F-1 filings.

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

# Default command runs tests without coverage (use --cov to enable)
# Coverage generation creates permission issues in Docker; enable only when needed
# Examples:
#   docker run filings-reviewer                                    # Run all tests
#   docker run filings-reviewer python -m pytest tests/unit/llm/   # Run specific tests
#   docker run filings-reviewer python scripts/run_phase1b_extraction.py  # Run script
#   docker run -it filings-reviewer bash                           # Interactive shell
CMD ["uv", "run", "pytest", "-v", "--tb=short", "--no-cov", "-p", "no:cacheprovider"]
