# 08 - WS-08 OCR Image Path Robustness

## Why This Workstream Exists
Nested image paths can fail during download persistence if parent directories are not created first.

## Primary Touchpoints
1. `src/extraction_v2/stages/ocr_extraction.py`
2. `tests/unit/extraction_v2/test_image_pipeline_integration.py`
3. `tests/unit/extraction_v2/test_ocr_extraction.py`

## Scope
1. Ensure robust parent-directory creation for nested filenames.
2. Add path normalization and traversal-safety validation.
3. Preserve behavior for flat filenames.

## Out of Scope
1. Full image cache redesign.
2. SEC transport stack redesign.

## Technical Design
1. Ensure parent directory exists before file writes.
2. Validate normalized paths remain inside configured cache root.
3. Keep logging behavior but improve error actionability where needed.

## Implementation Plan
1. Patch write path in OCR image download flow.
2. Add positive nested-path tests.
3. Add negative traversal attempts tests.
4. Run broader image-stage regression tests.

## Acceptance Criteria
1. Nested image filenames are written successfully.
2. Traversal patterns are rejected safely.
3. Existing flat-path behavior remains intact.

## Rollout and Rollback
1. Low-risk patch; merge early.
2. Include in next release candidate and extraction smoke suite.

## Deliverables
1. OCR download path fix.
2. Targeted unit tests for nested and unsafe paths.
