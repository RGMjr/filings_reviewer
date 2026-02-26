"""Unit tests for V2 exception hierarchy."""

import pytest

from src.extraction_v2.exceptions import (
    V2FatalError,
    V2PipelineError,
    V2StageError,
    V2TransientError,
)


class TestExceptionHierarchy:
    def test_v2_stage_error_is_pipeline_error(self) -> None:
        err = V2StageError("boom", stage_name="stage_1")
        assert isinstance(err, V2PipelineError)
        assert isinstance(err, Exception)

    def test_v2_transient_error_is_stage_error(self) -> None:
        err = V2TransientError("timeout", stage_name="ocr")
        assert isinstance(err, V2StageError)
        assert isinstance(err, V2PipelineError)

    def test_v2_fatal_error_is_stage_error(self) -> None:
        err = V2FatalError("parse failed", stage_name="ingestion")
        assert isinstance(err, V2StageError)
        assert isinstance(err, V2PipelineError)

    def test_transient_not_fatal(self) -> None:
        err = V2TransientError("timeout", stage_name="ocr")
        assert not isinstance(err, V2FatalError)

    def test_fatal_not_transient(self) -> None:
        err = V2FatalError("parse failed", stage_name="ingestion")
        assert not isinstance(err, V2TransientError)


class TestStageNameAttribute:
    def test_stage_error_preserves_stage_name(self) -> None:
        err = V2StageError("message", stage_name="table_reconstruction")
        assert err.stage_name == "table_reconstruction"

    def test_transient_error_preserves_stage_name(self) -> None:
        err = V2TransientError("timeout", stage_name="vision_api")
        assert err.stage_name == "vision_api"

    def test_fatal_error_preserves_stage_name(self) -> None:
        err = V2FatalError("schema violation", stage_name="validation")
        assert err.stage_name == "validation"

    def test_stage_name_propagated_via_raise(self) -> None:
        with pytest.raises(V2TransientError) as exc_info:
            raise V2TransientError("network error", stage_name="ocr_stage")
        assert exc_info.value.stage_name == "ocr_stage"


class TestStrAndRepr:
    def test_str_includes_stage_name(self) -> None:
        err = V2StageError("something went wrong", stage_name="stage_3")
        assert "stage_3" in str(err)
        assert "something went wrong" in str(err)

    def test_str_format(self) -> None:
        err = V2StageError("bad input", stage_name="ingestion")
        assert str(err) == "[ingestion] bad input"

    def test_repr_includes_class_name(self) -> None:
        err = V2FatalError("parse error", stage_name="parsing")
        r = repr(err)
        assert "V2FatalError" in r
        assert "parse error" in r
        assert "parsing" in r

    def test_transient_repr(self) -> None:
        err = V2TransientError("timeout", stage_name="ocr")
        r = repr(err)
        assert "V2TransientError" in r
        assert "timeout" in r
        assert "ocr" in r

    def test_catch_as_pipeline_error(self) -> None:
        with pytest.raises(V2PipelineError):
            raise V2FatalError("unrecoverable", stage_name="dedup")

    def test_catch_as_stage_error(self) -> None:
        with pytest.raises(V2StageError):
            raise V2TransientError("retry me", stage_name="api_call")
