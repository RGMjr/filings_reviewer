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
    # Gold standard regression testing options
    parser.addoption(
        "--gold-standard-mode",
        action="store",
        default="fresh",
        choices=["db", "fresh"],
        help="Extraction mode: 'fresh' re-extracts from local HTML (default), 'db' uses existing database",
    )
    parser.addoption(
        "--gold-standard-tolerance",
        action="store",
        type=float,
        default=0.01,
        help="Regression tolerance as decimal (e.g., 0.01 = 1%%, default: 0.01)",
    )
    parser.addoption(
        "--gold-standard-update-baseline",
        action="store_true",
        default=False,
        help="Update baseline instead of comparing against it",
    )
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
