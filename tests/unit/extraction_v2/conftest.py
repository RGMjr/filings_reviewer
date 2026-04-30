"""Shared fixtures for extraction_v2 unit tests."""

import pytest


@pytest.fixture(autouse=True)
def _clear_vision_routing_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure VISION_ROUTING_MODE is unset at the start of each test.

    test_batch_runner.py imports batch_v2_extraction via exec_module, which
    calls load_dotenv() and can set VISION_ROUTING_MODE from a local .env file.
    This fixture prevents that from contaminating tests that expect legacy mode.
    """
    monkeypatch.delenv("VISION_ROUTING_MODE", raising=False)
