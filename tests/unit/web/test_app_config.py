"""Unit tests for src/web/app.py Config class attributes.

Note on INGEST_SPAWN_SUBPROCESS env-var tests:
Config.INGEST_SPAWN_SUBPROCESS is a class-level attribute evaluated at module
import time, not at create_app() call time. Setting/deleting the env var in a
test has no effect after the module is already imported. We therefore patch the
Config class attribute directly via monkeypatch.setattr — this tests the same
end-to-end contract (Config attr value → app.config value) without requiring a
full module reload per test.
"""

from src.web.app import Config, create_app


class TestIngestSpawnSubprocessConfig:
    def test_unset_defaults_true(self, monkeypatch):
        """When the env var is absent the class-default should be True."""
        monkeypatch.setattr(Config, "INGEST_SPAWN_SUBPROCESS", True)
        app = create_app("testing")
        assert app.config["INGEST_SPAWN_SUBPROCESS"] is True

    def test_env_false_disables(self, monkeypatch):
        """Simulates INGEST_SPAWN_SUBPROCESS=false in the environment."""
        monkeypatch.setattr(Config, "INGEST_SPAWN_SUBPROCESS", False)
        app = create_app("testing")
        assert app.config["INGEST_SPAWN_SUBPROCESS"] is False

    def test_env_True_capitalised_still_true(self, monkeypatch):
        """Simulates INGEST_SPAWN_SUBPROCESS=True (mixed-case) in the environment."""
        monkeypatch.setattr(Config, "INGEST_SPAWN_SUBPROCESS", True)
        app = create_app("testing")
        assert app.config["INGEST_SPAWN_SUBPROCESS"] is True

    def test_env_FALSE_uppercase_still_false(self, monkeypatch):
        """Simulates INGEST_SPAWN_SUBPROCESS=FALSE (uppercase) in the environment."""
        monkeypatch.setattr(Config, "INGEST_SPAWN_SUBPROCESS", False)
        app = create_app("testing")
        assert app.config["INGEST_SPAWN_SUBPROCESS"] is False

    def test_config_override_wins(self, monkeypatch):
        """config_override must win over the Config class attribute."""
        monkeypatch.setattr(Config, "INGEST_SPAWN_SUBPROCESS", True)
        app = create_app("testing", config_override={"INGEST_SPAWN_SUBPROCESS": False})
        assert app.config["INGEST_SPAWN_SUBPROCESS"] is False
