"""
Unit tests for Flask app pool initialization and cleanup.

Tests the init_pool() and close_pool() functions in app.py.
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestInitPool:
    """Tests for init_pool() function."""

    def test_init_pool_creates_pool(self):
        """Should create pool and store in app config."""
        from flask import Flask

        from src.web.app import init_pool

        app = Flask(__name__)
        app.config["DATABASE_URL"] = "postgresql://localhost/test"
        app.config["DB_POOL_ENABLED"] = True
        app.config["DB_POOL_MIN_SIZE"] = 2
        app.config["DB_POOL_MAX_SIZE"] = 5

        with patch("src.infra.pool.create_pool") as mock_create_pool:
            mock_pool = MagicMock()
            mock_create_pool.return_value = mock_pool

            init_pool(app)

            mock_create_pool.assert_called_once_with(
                "postgresql://localhost/test",
                min_size=2,
                max_size=5,
            )
            assert app.config["_db_pool"] == mock_pool

    def test_init_pool_disabled(self):
        """Should skip pool creation when DB_POOL_ENABLED is false."""
        from flask import Flask

        from src.web.app import init_pool

        app = Flask(__name__)
        app.config["DATABASE_URL"] = "postgresql://localhost/test"
        app.config["DB_POOL_ENABLED"] = False

        with patch("src.infra.pool.create_pool") as mock_create_pool:
            init_pool(app)

            mock_create_pool.assert_not_called()
            assert "_db_pool" not in app.config

    def test_init_pool_no_database_url(self):
        """Should skip pool creation when DATABASE_URL not configured."""
        from flask import Flask

        from src.web.app import init_pool

        app = Flask(__name__)
        app.config["DATABASE_URL"] = ""
        app.config["DB_POOL_ENABLED"] = True

        with patch("src.infra.pool.create_pool") as mock_create_pool:
            init_pool(app)

            mock_create_pool.assert_not_called()
            assert "_db_pool" not in app.config

    def test_init_pool_handles_creation_error(self):
        """Should catch pool creation errors and set pool to None."""
        from flask import Flask

        from src.web.app import init_pool

        app = Flask(__name__)
        app.config["DATABASE_URL"] = "postgresql://localhost/test"
        app.config["DB_POOL_ENABLED"] = True

        with patch("src.infra.pool.create_pool") as mock_create_pool:
            mock_create_pool.side_effect = Exception("Connection refused")

            # Should not raise
            init_pool(app)

            # Pool should be None (graceful degradation)
            assert app.config["_db_pool"] is None


class TestClosePool:
    """Tests for close_pool() function."""

    def test_close_pool_closes_pool(self):
        """Should close pool and clear from config."""
        from flask import Flask

        from src.web.app import close_pool

        app = Flask(__name__)
        mock_pool = MagicMock()
        app.config["_db_pool"] = mock_pool

        close_pool(app)

        mock_pool.close.assert_called_once()
        assert app.config["_db_pool"] is None

    def test_close_pool_when_none(self):
        """Should handle case when no pool exists."""
        from flask import Flask

        from src.web.app import close_pool

        app = Flask(__name__)
        app.config["_db_pool"] = None

        # Should not raise
        close_pool(app)

    def test_close_pool_when_not_set(self):
        """Should handle case when pool was never initialized."""
        from flask import Flask

        from src.web.app import close_pool

        app = Flask(__name__)
        # _db_pool key doesn't exist

        # Should not raise
        close_pool(app)

    def test_close_pool_handles_error(self):
        """Should catch errors during pool close and still clear config."""
        from flask import Flask

        from src.web.app import close_pool

        app = Flask(__name__)
        mock_pool = MagicMock()
        mock_pool.close.side_effect = Exception("Close failed")
        app.config["_db_pool"] = mock_pool

        # Should not raise
        close_pool(app)

        # Pool should still be cleared
        assert app.config["_db_pool"] is None


class TestCreateAppPoolIntegration:
    """Tests for pool initialization in create_app()."""

    def test_create_app_initializes_pool(self):
        """Should initialize pool during app creation."""
        with patch("src.infra.pool.create_pool") as mock_create_pool:
            mock_pool = MagicMock()
            mock_create_pool.return_value = mock_pool

            with patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://localhost/test"},
            ):
                from src.web.app import create_app

                app = create_app("testing")

                assert app.config["_db_pool"] == mock_pool

    def test_create_app_registers_atexit(self):
        """Should register close_pool with atexit."""
        with patch("src.infra.pool.create_pool") as mock_create_pool:
            mock_pool = MagicMock()
            mock_create_pool.return_value = mock_pool

            with patch("src.web.app.atexit.register") as mock_atexit:
                with patch.dict(
                    os.environ,
                    {"DATABASE_URL": "postgresql://localhost/test"},
                ):
                    from src.web.app import close_pool, create_app

                    app = create_app("testing")

                    # Verify atexit.register was called with close_pool and app
                    mock_atexit.assert_called()
                    # Find the call with close_pool
                    close_pool_calls = [
                        call
                        for call in mock_atexit.call_args_list
                        if call[0][0].__name__ == "close_pool"
                    ]
                    assert len(close_pool_calls) >= 1
