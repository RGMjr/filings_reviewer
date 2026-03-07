# Image Extraction Code Review (V2)

Date: 2026-03-05  
Scope: `src/extraction_v2` image ingestion, triage, OCR/chart extraction, candidate generation, and value binding.

## Executive assessment

The image extraction stack is **functionally complete and reasonably well tested**, but it remains **heuristic-heavy and weakly calibrated** for production-grade precision/recall. The system is strongest at defensive behavior (manual capture over guessing) and weakest at deterministic evidence quality, config consistency, and throughput/cost tuning.

## What performs well

1. **Clear fail-closed design for chart extraction.**
   - Chart prompt and code enforce labeled-values-only extraction and avoid interpolation.
2. **Resilience to partial failures.**
   - OCR/chart errors set low confidence and `requires_manual_capture`, while pipeline processing continues.
3. **Reasonable test depth for image workflow regressions.**
   - Integration tests cover triage, download, OCR->table feedthrough, chart candidate scan, and chart binding/annotations.
4. **Good stage decomposition and metadata capture.**
   - Stages return counts/warnings and retain per-image processing flags.

## Key technical gaps

### 1) Config drift: hardcoded thresholds bypass pipeline config

- Stage thresholds are hardcoded in image triage/OCR stage classes (e.g., relevance threshold `0.3`) while `PipelineConfig` has `min_image_relevance` and `max_images_per_document` that are not wired into these stages.
- Result: operators cannot reliably tune behavior from config, and docs/config imply controls that do not actually apply.

### 2) Missing enforcement of per-document image caps

- `PipelineConfig.max_images_per_document` exists but is not enforced in stage orchestration.
- OCR stage has separate API call caps (`MAX_OCR_CALLS_PER_DOCUMENT`, `MAX_CHART_CALLS_PER_DOCUMENT`), but there is no global cap tied to config.
- Result: potential unpredictable runtime/cost with image-heavy filings.

### 3) Classification logic is rule-based and brittle

- Classification relies mostly on filename/context keywords and coarse size/aspect heuristics.
- Ingestion pre-filters decorative images before triage and may discard content images if dimensions are absent/misleading in SEC HTML.
- Result: risk of false negatives (valuable charts filtered early) and false positives (generic “figure/exhibit” images over-queued).

### 4) OCR table reconstruction is simplistic

- OCR table reconstruction assumes `rowspan=colspan=1`, forces at least one header row, and defaults `stub_cols=1`.
- No spatial geometry or merged-cell recovery is used.
- Result: header/stub path quality can degrade quickly on complex tables, reducing downstream binding quality.

### 5) Chart binding lacks provenance granularity

- Bound chart values use image-level source locator only; point/annotation bounding boxes are not preserved from extraction.
- Candidate scan uses chart metadata/nearby text, then all points/annotations are bound for matching metrics, creating potential over-binding noise.

### 6) Limited confidence calibration and observability

- Confidence depends heavily on model-returned confidence with lightweight adjustments.
- There is no calibration loop against labeled image truth sets (precision/recall by class, chart-value extraction accuracy, OCR cell accuracy).
- Result: review-routing confidence may not map to real-world error rates.

## Priority improvements

## P0 (highest impact, low-medium effort)

1. **Wire stage thresholds to `PipelineConfig`.**
   - Pass `min_image_relevance`, OCR/chart call limits, and max-images budget into `ImageTriageStage` and `OCRExtractionStage` constructors.
2. **Enforce global image budget.**
   - Apply `max_images_per_document` after triage ranking and before stage 5 processing.
3. **Add explicit metrics emission.**
   - Track: triage class distribution, queue rate, OCR success rate, chart parse success, manual-capture rate, avg cost/image, and end-to-end chart fact yield.

## P1 (quality uplift)

4. **Improve ingestion/triage recall safeguards.**
   - Avoid hard-dropping images based only on missing/small dimensions; use soft scoring unless definitely decorative.
   - Add whitelist signals (e.g., nearby numeric-heavy text, figure captions).
5. **Strengthen OCR table reconstruction.**
   - Include optional geometry-aware extraction format (bbox per cell) and inferred merged-cell handling.
6. **Tighten chart value binding.**
   - Bind values only when candidate metric is semantically linked to series/annotation text (not image-wide blanket binding).

## P2 (longer-term)

7. **Introduce calibration harness and golden image set.**
   - Build benchmark set with known classification + extraction truth.
   - Report precision/recall and value-level F1 by chart type.
8. **Model/prompt strategy optimization.**
   - Add cheap first-pass model for easy cases, escalate to high-detail for ambiguous/high-value charts.
9. **Evidence improvements.**
   - Persist per-point/per-annotation bbox and image snippets to improve reviewer trust and correction speed.

## Current readiness verdict

- **Reliability:** Moderate (safe fallbacks, good error containment).
- **Extraction quality:** Moderate-low for complex visuals (heuristic triage + simplistic OCR reconstruction).
- **Operational controllability:** Moderate-low (config controls are partly disconnected from runtime behavior).
- **Scalability/cost predictability:** Moderate (type-specific call caps exist; global budgeting/cost telemetry needs work).

Overall: the implementation is a strong foundation, but to perform robustly at scale it needs calibration, config wiring, and stricter binding/provenance semantics.
