---
autonomy: safe
discovered: '2026-04-24'
estimated: S
id: 101
severity: high
slug: extraction-cron-silent-success-on-pipeline-error
source: legacy
status: resolved
title: Extraction Cron Reports Success With 0 Facts on Fatal Pipeline Error
touches:
  - scripts/batch_v2_extraction.py
updated: '2026-04-24'
---

### Problem

When the V2 pipeline crashes inside a stage (e.g., `ModuleNotFoundError: No module
named 'boto3'` during ingestion), `batch_v2_extraction.py` catches the exception,
persists 0 facts, and still increments the success counter. The final log line reads
`"1/1 succeeded, 0 failed"` and the script exits 0 — so Render marks the cron job as
successful with no alert. The issue was observed on 2026-04-24 when the boto3 lockfile
omission caused every run to silently extract nothing.

### Resolution

`scripts/batch_v2_extraction.py` now checks `result.success` after `pipeline.process()`
returns. When a critical stage emits `V2FatalError` and the pipeline returns
`PipelineResult(success=False, error_message=...)`, the worker marks the filing
`extraction_failed`, propagates `success=False` to the batch stats, and skips the
empty persist. The batch's existing exit-code logic
(`sys.exit(1) if stats.failed > stats.succeeded`) then surfaces the failure to Render.
Regression guard: `tests/unit/test_batch_v2_extraction.py::TestPipelineFailurePropagates`.
