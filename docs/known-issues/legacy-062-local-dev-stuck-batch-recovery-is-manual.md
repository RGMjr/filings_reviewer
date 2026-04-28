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
updated: '2026-04-28'
---

### Problem

On Render (Phase 7), a worker service with `--watch` mode will re-claim a batch whose `run_lock_until` has expired. On local dev there is no watcher — if the `onboarding_runner` subprocess dies mid-batch (kernel OOM, user kills the Flask server, etc.), the batch stays in `status='running'` forever. Currently recovery requires a hand-crafted `UPDATE v2_ingest_batches SET status='failed' WHERE batch_id=...` plus a cleanup of partially-processed `v2_ingest_batch_filings` rows.

### Partial Resolution (2026-04-21, refreshed 2026-04-28)

- **NS1 (docs)** — manual recovery SQL documented in `docs/operations/TICKER_ONBOARDING.md` under "Recovering a stuck batch (local dev)". **Done.**
- **NS3 (SIGTERM log line)** — `src/universe/onboarding_runner.py` registers a SIGTERM handler via `signal.signal(signal.SIGTERM, _signal_handler)` and logs "Shutdown signal received … will stop after current filing." The signal-trap part is shipped; the message just doesn't yet reference `--cleanup-stuck` because the flag (NS2) doesn't exist. Trivial follow-up to the NS2 work.

### Remaining

- **NS2 (`--cleanup-stuck` admin flag)** — `python3 -m src.universe.onboarding_runner --cleanup-stuck` admin mode that scans for batches with `run_lock_until < NOW() - INTERVAL '1 hour'` still in `running` state and either marks them failed or re-claims them. Once shipped, update the SIGTERM log message to point operators at the flag.
