"""Unit tests for src/shared/segment_validators.py."""

import pytest

from src.shared.extraction_exceptions import ValidationError
from src.shared.models import SourceSegment
from src.shared.segment_validators import (
    ClassificationValidator,
    SegmentValidator,
)

# ---------------------------------------------------------------------------
# SegmentValidator.validate_filing_id
# ---------------------------------------------------------------------------


def test_validate_filing_id_accepts_positive_int():
    SegmentValidator.validate_filing_id(1)
    SegmentValidator.validate_filing_id(9999)


@pytest.mark.parametrize("bad", [0, -1, -999])
def test_validate_filing_id_rejects_non_positive(bad):
    with pytest.raises(ValidationError) as excinfo:
        SegmentValidator.validate_filing_id(bad)
    assert excinfo.value.field_name == "filing_id"


@pytest.mark.parametrize("bad", ["1", 1.5, None, [1]])
def test_validate_filing_id_rejects_non_int_types(bad):
    with pytest.raises(ValidationError):
        SegmentValidator.validate_filing_id(bad)


# ---------------------------------------------------------------------------
# SegmentValidator.validate_html_path
# ---------------------------------------------------------------------------


def test_validate_html_path_accepts_existing_file(tmp_path):
    p = tmp_path / "f.htm"
    p.write_text("<html></html>")
    resolved = SegmentValidator.validate_html_path(str(p))
    assert resolved == p.resolve()


def test_validate_html_path_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        SegmentValidator.validate_html_path(str(tmp_path / "nope.htm"))


def test_validate_html_path_rejects_directory(tmp_path):
    with pytest.raises(ValidationError):
        SegmentValidator.validate_html_path(str(tmp_path))


def test_validate_html_path_rejects_empty_string():
    with pytest.raises(ValidationError):
        SegmentValidator.validate_html_path("")
    with pytest.raises(ValidationError):
        SegmentValidator.validate_html_path("   ")


def test_validate_html_path_rejects_non_string():
    with pytest.raises(ValidationError):
        SegmentValidator.validate_html_path(123)


# ---------------------------------------------------------------------------
# SegmentValidator.validate_segment
# ---------------------------------------------------------------------------


def test_validate_segment_accepts_valid_segment():
    seg = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="hi", sequence_index=0)
    SegmentValidator.validate_segment(seg)


def test_validate_segment_rejects_non_segment():
    with pytest.raises(ValidationError):
        SegmentValidator.validate_segment({"filing_id": 1})


def test_validate_segment_rejects_non_positive_filing_id():
    seg = SourceSegment(filing_id=0, segment_type="paragraph")
    with pytest.raises(ValidationError) as excinfo:
        SegmentValidator.validate_segment(seg)
    assert excinfo.value.field_name == "filing_id"


def test_validate_segment_rejects_missing_segment_type():
    seg = SourceSegment(filing_id=1, segment_type="")
    with pytest.raises(ValidationError) as excinfo:
        SegmentValidator.validate_segment(seg)
    assert excinfo.value.field_name == "segment_type"


def test_validate_segment_rejects_negative_sequence_index_for_non_empty_text():
    seg = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="x", sequence_index=-1)
    with pytest.raises(ValidationError) as excinfo:
        SegmentValidator.validate_segment(seg)
    assert excinfo.value.field_name == "sequence_index"


# ---------------------------------------------------------------------------
# SegmentValidator.validate_min_max_length
# ---------------------------------------------------------------------------


def test_validate_min_max_length_accepts_valid_range():
    SegmentValidator.validate_min_max_length(1, 100)
    SegmentValidator.validate_min_max_length(0, 1)


def test_validate_min_max_length_rejects_non_int():
    with pytest.raises(ValidationError):
        SegmentValidator.validate_min_max_length(1.5, 10)


def test_validate_min_max_length_rejects_negative_min():
    with pytest.raises(ValidationError) as excinfo:
        SegmentValidator.validate_min_max_length(-1, 10)
    assert excinfo.value.field_name == "min_length"


def test_validate_min_max_length_rejects_non_positive_max():
    with pytest.raises(ValidationError) as excinfo:
        SegmentValidator.validate_min_max_length(1, 0)
    assert excinfo.value.field_name == "max_length"


def test_validate_min_max_length_rejects_inverted_range():
    with pytest.raises(ValidationError):
        SegmentValidator.validate_min_max_length(50, 10)


# ---------------------------------------------------------------------------
# ClassificationValidator.validate_confidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("score", [0.0, 0.5, 1.0, 0, 1])
def test_validate_confidence_accepts_valid_range(score):
    ClassificationValidator.validate_confidence(score)


@pytest.mark.parametrize("score", [-0.01, 1.01, -1, 2])
def test_validate_confidence_rejects_out_of_range(score):
    with pytest.raises(ValidationError):
        ClassificationValidator.validate_confidence(score)


def test_validate_confidence_rejects_non_numeric():
    with pytest.raises(ValidationError):
        ClassificationValidator.validate_confidence("0.5")


def test_validate_confidence_uses_custom_field_name():
    with pytest.raises(ValidationError) as excinfo:
        ClassificationValidator.validate_confidence(2.0, field_name="cohort_conf")
    assert excinfo.value.field_name == "cohort_conf"


# ---------------------------------------------------------------------------
# ClassificationValidator.validate_metric_ids
# ---------------------------------------------------------------------------


def test_validate_metric_ids_accepts_valid_list():
    ClassificationValidator.validate_metric_ids(["cm_revenue", "cm_customers_period_end"])
    ClassificationValidator.validate_metric_ids([])


def test_validate_metric_ids_rejects_non_list():
    with pytest.raises(ValidationError):
        ClassificationValidator.validate_metric_ids("cm_revenue")


def test_validate_metric_ids_rejects_non_string_element():
    with pytest.raises(ValidationError) as excinfo:
        ClassificationValidator.validate_metric_ids(["ok", 42])
    assert "metric_ids[1]" in excinfo.value.field_name


def test_validate_metric_ids_rejects_empty_string_element():
    with pytest.raises(ValidationError):
        ClassificationValidator.validate_metric_ids(["ok", ""])
    with pytest.raises(ValidationError):
        ClassificationValidator.validate_metric_ids(["  "])


# ---------------------------------------------------------------------------
# ClassificationValidator.validate_segment_for_classification
# ---------------------------------------------------------------------------


def test_validate_segment_for_classification_accepts_valid():
    seg = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="content")
    ClassificationValidator.validate_segment_for_classification(seg)


def test_validate_segment_for_classification_rejects_none_raw_text():
    seg = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="content")
    seg.raw_text = None  # force None past dataclass default
    with pytest.raises(ValidationError) as excinfo:
        ClassificationValidator.validate_segment_for_classification(seg)
    assert excinfo.value.field_name == "raw_text"


def test_validate_segment_for_classification_delegates_to_segment_validator():
    # Invalid filing_id should bubble up from SegmentValidator.
    seg = SourceSegment(filing_id=0, segment_type="paragraph", raw_text="x")
    with pytest.raises(ValidationError):
        ClassificationValidator.validate_segment_for_classification(seg)
