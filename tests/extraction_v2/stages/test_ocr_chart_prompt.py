from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage


def test_chart_prompt_phase1_strings_present() -> None:
    stage = OCRExtractionStage()
    prompt = stage._get_chart_extraction_prompt("")
    assert "Series name from legend" in prompt
    assert "Category or date label" in prompt


def test_chart_prompt_block_a_hint_present() -> None:
    stage = OCRExtractionStage()
    prompt = stage._get_chart_extraction_prompt("")
    assert "COHORT VINTAGE" in prompt


def test_chart_prompt_block_b_example_present() -> None:
    stage = OCRExtractionStage()
    prompt = stage._get_chart_extraction_prompt("")
    assert "Q1 FY2022" in prompt
