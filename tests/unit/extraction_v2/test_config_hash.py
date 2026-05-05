"""Unit tests for src/extraction_v2/config_hash.py.

Verifies:
- Return type is a 64-char hex SHA-256 string.
- Determinism: same file contents → same hash.
- Sensitivity: different file bytes → different hash.
- Call-time reads: Path.read_bytes is invoked on every call (not cached at import).
- FileNotFoundError propagation when a file is missing.

Patching strategy: monkeypatch ``pathlib.Path.read_bytes`` at the class level,
routing by ``self.name`` to return per-file fake bytes. This is necessary because
``PosixPath`` instance attributes are read-only (C-level slots).
"""

from __future__ import annotations

import hashlib

import pytest

_FAKE_KEYWORDS_BYTES = b"cm_net_revenue_retention:\n  - retained\n"
_FAKE_FP_FILTER_BYTES = b"def _rule_wrong_value(segment):\n    pass\n"


def _make_router(keywords: bytes, fp_filter: bytes):
    """Return a Path.read_bytes replacement that dispatches by filename."""

    def _read_bytes(self):  # noqa: ANN001
        if self.name == "metric_keywords.yaml":
            return keywords
        if self.name == "false_positive_filter.py":
            return fp_filter
        raise FileNotFoundError(f"Unexpected path in test: {self}")

    return _read_bytes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReturnType:
    def test_returns_64_char_hex_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pathlib

        from src.extraction_v2 import config_hash as ch

        monkeypatch.setattr(
            pathlib.Path,
            "read_bytes",
            _make_router(_FAKE_KEYWORDS_BYTES, _FAKE_FP_FILTER_BYTES),
        )
        result = ch.compute_config_hash()
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_matches_manual_sha256(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pathlib

        from src.extraction_v2 import config_hash as ch

        monkeypatch.setattr(
            pathlib.Path,
            "read_bytes",
            _make_router(_FAKE_KEYWORDS_BYTES, _FAKE_FP_FILTER_BYTES),
        )
        expected = hashlib.sha256(
            _FAKE_KEYWORDS_BYTES + b"\x00" + _FAKE_FP_FILTER_BYTES
        ).hexdigest()
        assert ch.compute_config_hash() == expected


class TestDeterminism:
    def test_same_bytes_same_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pathlib

        from src.extraction_v2 import config_hash as ch

        monkeypatch.setattr(
            pathlib.Path,
            "read_bytes",
            _make_router(_FAKE_KEYWORDS_BYTES, _FAKE_FP_FILTER_BYTES),
        )
        h1 = ch.compute_config_hash()
        h2 = ch.compute_config_hash()
        assert h1 == h2


class TestSensitivity:
    def test_different_keywords_bytes_yields_different_hash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pathlib

        from src.extraction_v2 import config_hash as ch

        monkeypatch.setattr(
            pathlib.Path,
            "read_bytes",
            _make_router(_FAKE_KEYWORDS_BYTES, _FAKE_FP_FILTER_BYTES),
        )
        h1 = ch.compute_config_hash()

        # Swap in different keywords bytes for the second call.
        monkeypatch.setattr(
            pathlib.Path,
            "read_bytes",
            _make_router(b"different_keyword_content: true", _FAKE_FP_FILTER_BYTES),
        )
        h2 = ch.compute_config_hash()
        assert h1 != h2

    def test_different_fp_filter_bytes_yields_different_hash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pathlib

        from src.extraction_v2 import config_hash as ch

        monkeypatch.setattr(
            pathlib.Path,
            "read_bytes",
            _make_router(_FAKE_KEYWORDS_BYTES, _FAKE_FP_FILTER_BYTES),
        )
        h1 = ch.compute_config_hash()

        monkeypatch.setattr(
            pathlib.Path,
            "read_bytes",
            _make_router(_FAKE_KEYWORDS_BYTES, b"def rule_changed(): return True"),
        )
        h2 = ch.compute_config_hash()
        assert h1 != h2


class TestCallTimeReads:
    def test_read_bytes_called_on_every_invocation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """read_bytes must be invoked fresh on each compute_config_hash() call.

        Two calls → 4 total read_bytes invocations (2 files × 2 calls).
        We count by filename to isolate keywords vs fp_filter reads.
        """
        import pathlib

        from src.extraction_v2 import config_hash as ch

        keywords_calls = 0
        fp_filter_calls = 0

        def counting_router(self):  # noqa: ANN001
            nonlocal keywords_calls, fp_filter_calls
            if self.name == "metric_keywords.yaml":
                keywords_calls += 1
                return _FAKE_KEYWORDS_BYTES
            if self.name == "false_positive_filter.py":
                fp_filter_calls += 1
                return _FAKE_FP_FILTER_BYTES
            raise FileNotFoundError(f"Unexpected path in test: {self}")

        monkeypatch.setattr(pathlib.Path, "read_bytes", counting_router)

        ch.compute_config_hash()
        ch.compute_config_hash()

        assert keywords_calls == 2, (
            f"Expected 2 reads of keywords file (one per call), got {keywords_calls}"
        )
        assert fp_filter_calls == 2, (
            f"Expected 2 reads of fp_filter file (one per call), got {fp_filter_calls}"
        )


class TestFileNotFound:
    def test_raises_when_keywords_file_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pathlib

        from src.extraction_v2 import config_hash as ch

        def raise_for_keywords(self):  # noqa: ANN001
            if self.name == "metric_keywords.yaml":
                raise FileNotFoundError("metric_keywords.yaml not found")
            return _FAKE_FP_FILTER_BYTES

        monkeypatch.setattr(pathlib.Path, "read_bytes", raise_for_keywords)

        with pytest.raises(FileNotFoundError):
            ch.compute_config_hash()

    def test_raises_when_fp_filter_file_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pathlib

        from src.extraction_v2 import config_hash as ch

        def raise_for_fp(self):  # noqa: ANN001
            if self.name == "false_positive_filter.py":
                raise FileNotFoundError("false_positive_filter.py not found")
            return _FAKE_KEYWORDS_BYTES

        monkeypatch.setattr(pathlib.Path, "read_bytes", raise_for_fp)

        with pytest.raises(FileNotFoundError):
            ch.compute_config_hash()
