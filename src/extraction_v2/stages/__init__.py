"""
V2 Extraction Pipeline Stages

This package contains the individual processing stages for the V2 extraction pipeline.
Each stage implements a specific transformation in the document processing workflow.

Stages:
--------
1. IngestionStage: Parse HTML to Segments with XPath locators
2. SectionClassificationStage: Classify segments into SEC sections
3. TableReconstructionStage: Resolve colspan/rowspan with header_path/stub_path
4. ImageTriageStage: Classify and prioritize images
5. OCRChartExtractionStage: Extract values from images
6. CandidateGenerationStage: Find metric mentions
7. ValueBindingStage: Link keywords to numeric values
8. PeriodInferenceStage: Determine time periods
9. FactConstructionStage: Build MetricFact with provenance
10. DeduplicationStage: Merge duplicate facts
11. ValidationStage: Route facts by confidence

Usage:
------
Stages are invoked sequentially by the pipeline orchestrator in src/extraction_v2/pipeline.py.
"""

from src.extraction_v2.stages.candidate_generation import CandidateGenerationStage
from src.extraction_v2.stages.ingestion import IngestionStage
from src.extraction_v2.stages.period_inference import PeriodInferenceStage
from src.extraction_v2.stages.section_classification import SectionClassificationStage
from src.extraction_v2.stages.table_reconstruction import TableReconstructionStage
from src.extraction_v2.stages.value_binding import ValueBindingStage

__all__ = [
    "CandidateGenerationStage",
    "IngestionStage",
    "PeriodInferenceStage",
    "SectionClassificationStage",
    "TableReconstructionStage",
    "ValueBindingStage",
]
