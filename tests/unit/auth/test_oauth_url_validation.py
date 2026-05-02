"""
Unit tests for ``src/web/routes/auth.py::_validate_next``.

Covers the spec §UI Identity redirect-target rules: the validator must
accept legitimate review-tool paths and reject every variant of an
open-redirect bypass attempt.
"""

from __future__ import annotations

import pytest

from src.web.routes.auth import DEFAULT_NEXT, _validate_next


class TestValidateNextPositive:
    """Paths that should pass through (or canonicalise to themselves)."""

    @pytest.mark.parametrize(
        "raw",
        [
            "/v2/review/",
            "/v2/review/?filing=123",
            "/v2/review/abcd-1234",
            "/ingest/",
            "/ingest/batch/42",
        ],
    )
    def test_known_prefix_passes(self, raw):
        assert _validate_next(raw) == raw

    @pytest.mark.parametrize(
        "raw,canonical",
        [
            # Bare prefix without trailing slash canonicalises to the slash form
            # so the rest of the routing layer doesn't have to special-case it.
            ("/v2/review", "/v2/review/"),
            ("/ingest", "/ingest/"),
        ],
    )
    def test_bare_prefix_canonicalises_to_slash(self, raw, canonical):
        assert _validate_next(raw) == canonical


class TestValidateNextNegative:
    """Bypass attempts that must fall back to ``DEFAULT_NEXT``."""

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "//evil.com",
            "//evil.com/",
            r"\\evil.com",
            r"/v2/review/\evil.com",
            "%2F%2Fevil.com",
            "https://evil.com/",
            "http://evil.com/",
            "javascript:alert(1)",
            "javascript:/v2/review/",
            "/v2/review/../../etc/passwd",
            "/etc/passwd",
            "/admin",
            "no-leading-slash",
        ],
    )
    def test_bypass_falls_back_to_default(self, raw):
        assert _validate_next(raw) == DEFAULT_NEXT

    def test_decoded_double_slash_rejected(self):
        # %2F decodes to /, so the input becomes //evil.com after decode.
        assert _validate_next("%2F%2Fevil.com") == DEFAULT_NEXT

    def test_path_outside_known_prefix_rejected(self):
        assert _validate_next("/health") == DEFAULT_NEXT
