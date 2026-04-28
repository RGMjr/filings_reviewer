---
autonomy: review
discovered: '2026-04-20'
estimated: S
id: 62
note: Resolved — `--cleanup-stuck` admin flag, SIGTERM log update, docs section shipped.
severity: low
slug: local-dev-stuck-batch-recovery-is-manual
source: legacy
status: resolved
title: Local-Dev Stuck-Batch Recovery Is Manual
touches:
- docs/operations/*
- src/universe/onboarding_runner.py
updated: '2026-04-28'
---

### Problem

On Render (Phase 7), a worker service with `--watch` mode will re-claim a batch whose `run_lock_until` has expired. On local dev there is no watcher — if the `onboarding_runner` subprocess dies mid-batch (kernel OOM, user kills the Flask server, etc.), the batch stays in `status='running'` forever. Currently recovery requires a hand-crafted `UPDATE v2_ingest_batches SET status='failed' WHERE batch_id=...` plus a cleanup of partially-processed `v2_ingest_batch_filings` rows.

### Partial Resolution (2026-04-21, refreshed 2026-04-28)

- **NS1 (docs)** — manual recovery SQL documented in `docs/operations/TICKER_ONBOARDING.md` under "Recovering a stuck batch (local dev)". **Done.**
- **NS3 (SIGTERM log line)** — `src/universe/onboarding_runner.py` registers a SIGTERM handler via `signal.signal(signal.SIGTERM, _signal_handler)` and logs "Shutdown signal received … will stop after current filing." The signal-trap part is shipped; the message just doesn't yet reference `--cleanup-stuck` because the flag (NS2) doesn't exist. Trivial follow-up to the NS2 work.

### Resolution (2026-04-28)

Shipped:

- **NS2 — `--cleanup-stuck` admin flag.** `python3 -m src.universe.onboarding_runner --cleanup-stuck` scans `v2_ingest_batches` for rows in `status='running'` with `run_lock_until < NOW() - <threshold>`. Dry-run by default (lists candidate `batch_id`s, no writes). `--apply` writes `status='failed'`, `finished_at=NOW()`, `run_lock_until=NULL`. Threshold tunable via `--stuck-threshold` (default `'1 hour'`, any Postgres interval string). Production guard: `--apply` against a `*.neon.tech` `DATABASE_URL` is refused with exit code 2 unless `--allow-prod` is also passed; dry-run mode is unaffected.
- **NS3 trailer — SIGTERM log message updated** to point operators at the flag: "Shutdown signal received (%s); will stop after current filing. To recover stuck batches afterwards, run: python3 -m src.universe.onboarding_runner --cleanup-stuck".
- **Docs append.** `docs/operations/TICKER_ONBOARDING.md` gained a `### Cleaning up stuck batches with --cleanup-stuck` subsection under the existing "Recovering a stuck batch (local dev)" heading. Shows dry-run-first, `--apply`, threshold tuning, and the prod guard.

**Design call:** chose mark-failed as the only mode. Rationale: `--watch` mode already re-claims expired rows automatically (see `claim_next_queued_batch` semantics — it picks up rows whose `run_lock_until` is null or past). The point of `--cleanup-stuck` is the abandon path — give the operator a clean way to mark dead batches failed when retry is not what they want. A `--reclaim` mode is out of scope; if a future use case appears, file a separate fragment.

**Test coverage.** Five new integration tests under `tests/integration/universe/test_onboarding_runner_integration.py::TestCleanupStuckBatches`:

1. Dry-run identifies stuck rows without writing.
2. Apply mode marks `status='failed'`, sets `finished_at`, nulls `run_lock_until`.
3. Threshold honored — fresh-enough rows are not flagged.
4. Live-watcher rows (`run_lock_until` in the future) are filtered by construction.
5. Prod-host guard refuses `--apply` against `*.neon.tech`; dry-run permitted; `--allow-prod` lets the write through.
