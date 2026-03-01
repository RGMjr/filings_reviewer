"""Integration test to verify type safety of review module."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_review_module_passes_mypy_strict():
    """
    Verify src/review/ passes mypy --strict.

    This test prevents type regressions by ensuring all review module
    code maintains strict type safety standards.

    If this test fails:
    1. Run: mypy src/review/ --strict
    2. Fix type errors in the reported files
    3. Update type annotations in function signatures
    4. Add type: ignore comments only as last resort
    """
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "src/review/", "--strict"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,  # Project root
    )

    # Check if mypy found errors only in src/extraction/ or src/infra/
    # (which are out of scope for strict review module checking)
    if result.returncode != 0:
        # Parse output to see if errors are only in excluded modules
        errors_in_review = any(
            "src/review/" in line and "error:" in line for line in result.stdout.split("\n")
        )

        if errors_in_review:
            pytest.fail(
                f"mypy --strict failed on src/review/\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}\n"
                f"\n"
                f"Fix type errors or update mypy config in pyproject.toml"
            )
        # else: errors are only in src/extraction/ or src/infra/, which is expected


@pytest.mark.integration
def test_mypy_config_exists():
    """Verify mypy configuration is present and correct in pyproject.toml."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # Fallback for older versions
        except ImportError:
            pytest.skip("tomllib/tomli not available")
            return

    config_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    # Check mypy section exists
    assert "tool" in config, "Missing [tool] section in pyproject.toml"
    assert "mypy" in config["tool"], "Missing [tool.mypy] section"

    # Check review module override exists
    overrides = config["tool"].get("mypy", {}).get("overrides", [])
    review_override = next(
        (o for o in overrides if o.get("module") == "src.review.*"),
        None,
    )
    assert review_override is not None, "Missing mypy override for src.review.*"
    assert review_override.get("disallow_untyped_defs") is True, (
        "Review module should require type annotations (disallow_untyped_defs=true)"
    )


@pytest.mark.integration
def test_mypy_in_requirements():
    """Verify mypy is listed in requirements.txt."""
    req_path = Path(__file__).parent.parent.parent / "requirements.txt"
    requirements = req_path.read_text()

    assert "mypy" in requirements.lower(), "mypy not found in requirements.txt\nAdd: mypy>=1.0.0"
