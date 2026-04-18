"""
Root pytest configuration.

Provides CLI options and fixtures available to all test directories.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "v2_parity: V2 vs V1 parity tests — runs full extraction on all gold standard companies. "
        "Only run with: pytest -m v2_parity",
    )


def pytest_addoption(parser):
    """Add global CLI options for tests."""
    # Transcript gold standard options
    parser.addoption(
        "--transcript-split",
        action="store",
        default="tuning",
        choices=["tuning", "test", "all"],
        help="Transcript split to evaluate: tuning (default), test, or all",
    )
    parser.addoption(
        "--transcript-update-baseline",
        action="store_true",
        default=False,
        help="Save current transcript extraction results as the new baseline",
    )
