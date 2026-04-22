---
autonomy: review
discovered: '2026-04-20'
estimated: S
id: 62
note: Docs + optional admin flag; needs design call
severity: low
slug: local-dev-stuck-batch-recovery-is-manual
source: legacy
status: partially-resolved
title: Local-Dev Stuck-Batch Recovery Is Manual
touches:
- docs/operations/*
- src/universe/onboarding_runner.py
updated: '2026-04-20'
---

### Problem

On Render (Phase 7), a worker service with `--watch` mode will re-claim a batch whose `run_lock_until` has expired. On local dev there is no watcher — if the `onboarding_runner` subprocess dies mid-batch (kernel OOM, user kills the Flask server, etc.), the batch stays in `status='running'` forever. Currently recovery requires a hand-crafted `UPDATE v2_ingest_batches SET status='failed' WHERE batch_id=...` plus a cleanup of partially-processed `v2_ingest_batch_filings` rows.

### Partial Resolution (2026-04-21)

Manual recovery SQL documented in `docs/operations/TICKER_ONBOARDING.md` under the new "Recovering a stuck batch (local dev)" section. Operators can now self-serve stuck-batch recovery without improvising SQL. Next Steps 2 (`--cleanup-stuck` admin flag) and 3 (SIGTERM log line) remain open.

### Next Steps

1. Document the manual recovery SQL in `docs/operations/TICKER_ONBOARDING.md` (or a new batch-ingest runbook) when that file lands in Phase 7.
2. Consider a `python3 -m src.universe.onboarding_runner --cleanup-stuck` admin flag that scans for batches with `run_lock_until < NOW() - INTERVAL '1 hour'` still in `running` state and either marks them failed or re-claims them.
3. Add a CLI log line to the runner on SIGTERM that tells the operator "batch <id> interrupted — run `... --cleanup-stuck` to recover".
