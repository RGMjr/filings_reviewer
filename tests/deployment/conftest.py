"""Fixtures for deployment smoke tests.

When SMOKE_TEST_BASE_URL is set, tests run against that URL (live deployment).
Otherwise, a Docker container is built and started locally using the project
Dockerfile and TEST_DATABASE_URL for the database connection.
"""

import os
import secrets
import subprocess
import time

import pytest
import requests

DOCKER_IMAGE = "filings-reviewer-test"
CONTAINER_NAME = "filings-reviewer-smoke"
DEFAULT_PORT = 8080


def _wait_for_healthy(url: str, timeout: int = 30) -> None:
    """Poll GET /health until 200 or timeout (raises RuntimeError)."""
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/health", timeout=5)
            if r.status_code == 200:
                return
        except requests.RequestException as e:
            last_error = e
        time.sleep(1)
    raise RuntimeError(
        f"Container did not become healthy at {url} within {timeout}s. "
        f"Last error: {last_error}"
    )


@pytest.fixture(scope="session")
def base_url():
    """Return the base URL for smoke tests.

    If SMOKE_TEST_BASE_URL is set, use it directly (live deployment).
    Otherwise, build the Docker image and start a local container.
    """
    env_url = os.environ.get("SMOKE_TEST_BASE_URL")
    if env_url:
        yield env_url.rstrip("/")
        return

    # Build the Docker image
    result = subprocess.run(
        ["docker", "build", "-t", DOCKER_IMAGE, "."],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Docker build failed (exit {result.returncode}):\n{result.stderr}"
        )

    port = int(os.environ.get("SMOKE_TEST_PORT", str(DEFAULT_PORT)))
    db_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://postgres:postgres@host.docker.internal:5432/filings_analysis_test",
    )
    secret_key = secrets.token_hex(32)

    run_result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "--network=host",
            "--add-host=host.docker.internal:host-gateway",
            "-e",
            f"DATABASE_URL={db_url}",
            "-e",
            f"SECRET_KEY={secret_key}",
            "-e",
            "FILINGS_API_KEY=test-smoke-api-key",
            "-e",
            "APP_ENV=production",
            "-e",
            f"PORT={port}",
            DOCKER_IMAGE,
        ],
        capture_output=True,
        text=True,
    )
    if run_result.returncode != 0:
        raise RuntimeError(
            f"Failed to start container (exit {run_result.returncode}):\n{run_result.stderr}"
        )

    url = f"http://localhost:{port}"
    try:
        _wait_for_healthy(url, timeout=60)
    except RuntimeError:
        logs = subprocess.run(
            ["docker", "logs", CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
        raise RuntimeError(
            f"Container did not become healthy.\nContainer logs:\n{logs.stdout}\n{logs.stderr}"
        ) from None

    yield url

    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)


@pytest.fixture(scope="session")
def api_key() -> str:
    """Return the API key for authenticated requests."""
    return os.environ.get("SMOKE_TEST_API_KEY", "test-smoke-api-key")


@pytest.fixture(scope="session")
def is_live() -> bool:
    """True when testing against a live deployment (SMOKE_TEST_BASE_URL is set)."""
    return bool(os.environ.get("SMOKE_TEST_BASE_URL"))
