# syntax=docker/dockerfile:1

# SEC Filings Analysis Pipeline
# This container runs batch extraction scripts and tests for analyzing S-1/F-1 filings.

ARG PYTHON_VERSION=3.11
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

# Download dependencies as a separate step to take advantage of Docker's caching.
# Leverage a cache mount to /root/.cache/pip to speed up subsequent builds.
# Leverage a bind mount to requirements.txt to avoid having to copy them into
# into this layer.
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.txt,target=requirements.txt \
    python -m pip install -r requirements.txt

# Copy the source code into the container.
COPY --chown=appuser:appuser . .

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
CMD ["python", "-m", "pytest", "-v", "--tb=short", "--no-cov", "-p", "no:cacheprovider"]
