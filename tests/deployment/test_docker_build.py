"""Docker build and container validation tests.

These tests verify:
- The Docker image builds and exists
- The container runs as the expected non-root user
- The health endpoint responds correctly
- Required env vars (DATABASE_URL, SECRET_KEY) are validated at startup
"""

import subprocess

import pytest
import requests

pytestmark = pytest.mark.deployment

DOCKER_IMAGE = "filings-reviewer-test"
CONTAINER_NAME = "filings-reviewer-smoke"


def test_image_exists() -> None:
    """Docker image should exist (built by conftest or CI step)."""
    result = subprocess.run(
        ["docker", "image", "inspect", DOCKER_IMAGE],
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"Docker image '{DOCKER_IMAGE}' not found. Build it first with:\n"
        f"  docker build -t {DOCKER_IMAGE} ."
    )


def test_container_runs_as_nonroot(base_url: str) -> None:
    """Container should run as 'appuser', not root."""
    result = subprocess.run(
        ["docker", "exec", CONTAINER_NAME, "whoami"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"docker exec failed: {result.stderr}"
    assert result.stdout.strip() == "appuser", (
        f"Expected user 'appuser', got '{result.stdout.strip()}'"
    )


def test_container_uid(base_url: str) -> None:
    """Container user should have UID 10001."""
    result = subprocess.run(
        ["docker", "exec", CONTAINER_NAME, "id", "-u"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "10001", (
        f"Expected UID 10001, got '{result.stdout.strip()}'"
    )


def test_health_endpoint_responds(base_url: str) -> None:
    """Health endpoint should return 200 with expected JSON structure."""
    r = requests.get(f"{base_url}/health", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "database" in data


def test_missing_database_url_fails() -> None:
    """Container should exit non-zero when DATABASE_URL is not set."""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            f"SECRET_KEY={'a' * 64}",
            "-e",
            "FILINGS_API_KEY=test",
            "-e",
            "APP_ENV=production",
            "-e",
            "PORT=9998",
            DOCKER_IMAGE,
            "python3",
            "scripts/run_review_server.py",
            "--port",
            "9998",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, (
        "Expected non-zero exit when DATABASE_URL is missing, but got 0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_missing_secret_key_fails() -> None:
    """Container should exit non-zero in production mode without SECRET_KEY."""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "DATABASE_URL=postgresql://x:x@localhost/x",
            "-e",
            "FILINGS_API_KEY=test",
            "-e",
            "APP_ENV=production",
            "-e",
            "PORT=9997",
            DOCKER_IMAGE,
            "python3",
            "scripts/run_review_server.py",
            "--port",
            "9997",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, (
        "Expected non-zero exit when SECRET_KEY is missing in production, but got 0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
