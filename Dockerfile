# syntax=docker/dockerfile:1
#
# Multi-stage build:
#   - builder: installs gcc + libpq-dev so psycopg etc. can compile wheels,
#     then puts everything into /opt/venv.
#   - runtime: installs only libpq5 (the runtime shared library) and copies
#     the venv from the builder. ~250 MB of build toolchain stays out of
#     the final image, which speeds Render's image pull on every deploy.

ARG PYTHON_VERSION=3.11

# ---------- builder ----------
FROM python:${PYTHON_VERSION}-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.lock,target=requirements.lock \
    pip install -r requirements.lock

# ---------- runtime ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:${PATH}"

# Runtime system deps:
#   libpq5         — psycopg's runtime shared library.
#   ca-certificates, curl — needed to fetch the pinned gh CLI .deb at build time
#                    and (for curl) by the gh CLI at run time.
#   git            — used by scripts/open_pattern_recommendation_pr.py (worker
#                    branches, commits, and pushes the patched
#                    config/metric_keywords.yaml). libpq-dev (with headers) is
#                    only needed at build time and stays in the builder stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# GitHub CLI (gh) — pinned to a specific release via the official .deb from
# GitHub Releases. Bypasses the apt repo entirely so the version is explicit.
# Architecture is detected at build time so amd64 (Render prod) and arm64
# (local Mac Docker) both work without changes. Mirrors Dockerfile.nightly-sweep.
# To bump: update GH_VERSION to the new tag (without the leading "v").
ARG GH_VERSION=2.91.0
RUN ARCH=$(dpkg --print-architecture) \
    && curl -fsSL -o /tmp/gh.deb \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${ARCH}.deb" \
    && dpkg -i /tmp/gh.deb \
    && rm /tmp/gh.deb

ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/home/appuser" \
    --shell "/bin/bash" \
    --uid "${UID}" \
    appuser

COPY --from=builder /opt/venv /opt/venv

# Copy only the dirs read at runtime. Keeping this list explicit prevents
# unrelated tree changes (docs, tests, .claude/) from busting the layer cache.
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser sql/ ./sql/
COPY --chown=appuser:appuser config/ ./config/
# gh-437: required by scripts/retrain_image_triage.py's sklearn version check
# (gh-406). Bind-mount in builder is not enough — the runtime image must
# contain the file so the worker can compare installed sklearn against the
# pinned version at script startup.
COPY --chown=appuser:appuser requirements.lock ./requirements.lock
# Image-relevance model artifact, loaded by src/shared/image_features.py to
# power the "Model score" sort on the image-review queue. Stopgap until
# gh-391 (R2 artifact persistence) — until then the joblib must ride in the
# image so it survives Render's ephemeral disk wipe on every deploy.
COPY --chown=appuser:appuser data/image_model/relevance_model.joblib ./data/image_model/relevance_model.joblib
COPY --chown=appuser:appuser data/image_model/model_report.txt ./data/image_model/model_report.txt

RUN mkdir -p /app/logs /app/data /app/filings_cache /app/htmlcov && \
    touch /app/.coverage && \
    chown -R appuser:appuser /app/logs /app/data /app/filings_cache /app/htmlcov /app/.coverage

USER appuser

# PORT env var is set by Render; falls back to 8080 locally.
CMD python3 scripts/run_review_server.py --host 0.0.0.0 --port ${PORT:-8080}
