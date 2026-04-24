---
autonomy: safe
discovered: '2026-04-24'
estimated: S
id: 101
severity: high
slug: extraction-cron-silent-success-on-pipeline-error
source: legacy
status: open
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

### Next Steps

- In `batch_v2_extraction.py`, distinguish a pipeline exception (which should count as
  a failure and exit non-zero) from a legitimate empty result (filing has no relevant
  segments).
- Consider adding a minimum-facts guard: if a filing has content and the pipeline
  returns 0 facts, treat it as a soft failure and log at `ERROR` level.
- Add a test that injects a stage exception and asserts the batch exits non-zero.
