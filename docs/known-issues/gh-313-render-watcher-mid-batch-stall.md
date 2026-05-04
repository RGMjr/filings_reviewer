---
autonomy: review
discovered: '2026-04-28'
estimated: S
gh_issue: 313
id: 313
severity: low
slug: render-watcher-mid-batch-stall
source: gh
status: partially-resolved
title: Render watcher silently dies mid-batch with no heartbeat-staleness recovery
touches:
  - src/universe/onboarding_runner.py
  - src/web/routes/ingest.py
  - src/web/templates/ingest_batch.html
updated: '2026-05-04'
pr_refs:
  - 382
note: Operator UI mitigation shipped via PR #382 — Resume Batch button surfaces when status='running' AND lock_stale=true (run_lock_until < NOW()), replacing the manual SQL UPDATE + local-runner workaround. Auto-recovery via the watcher's poll predicate is technically wired (_CLAIM_NEXT_SQL admits stale-locked running rows; watcher loop calls it every poll cycle) but never verified end-to-end on Render after the original incident. Severity downgraded medium→low because the operational pain is gone; remaining concern is verification, not new code.
---

### Problem

`/ingest/populate` for `(year=2016, form_type=10k)` was claimed by the Render watcher within ~4s and progressed to 465/8805 filings (~3 min in). The runner then died silently:

- `status` stayed `running`
- `error = NULL`, `finished_at = NULL`
- `run_lock_until` froze at the last heartbeat (15 min TTL)
- Filings count flat for 5+ consecutive 30s polls

No exception, no log surfaced. The lock would not expire for another ~12 minutes; until then, no other worker could re-claim. The current contract documented in `.claude/rules/web.md` line 13 states the watcher picks up `status='queued'` batches — it does not specify behavior on stale-`running` batches, and the observed behavior was no recovery.

### Recovery (manual, what worked)

1. `UPDATE v2_ingest_batches SET run_lock_until = NULL WHERE batch_id = '<uuid>'`
2. Run the runner locally against the prod DB: `python3 -m src.universe.onboarding_runner --batch-id <uuid>`
3. UniverseBuilder upserts by `accession_number`, so the 463 already-inserted rows became no-ops; remaining 8,302 finished cleanly over ~3.5 hours.

The data was safe (idempotent upserts), but the operational pain is real: someone has to notice the stall, run a write-query against prod, and either re-trigger on Render or babysit a multi-hour local run.

### Why this matters

For populates >~1K filings, the watcher-stall failure mode is reproducible enough that we should not rely on operator vigilance. There is no automatic alert; the only signal today is the batch progress page going flat.

### Possible fixes

1. **Heartbeat-staleness auto-claim.** Have the watcher periodically scan for `status='running' AND run_lock_until < NOW()` and re-claim them. `_CLAIM_NEXT_SQL` (`src/universe/onboarding_runner.py:76-90`) already admits both `queued` and stale-locked `running` rows; the gap is whether the watcher loop wakes up to look. Verify and adjust the watcher's poll predicate.
2. **Shorter lock TTL + per-filing heartbeat.** Today's 900s TTL means recovery is bounded by 15 min. A 60–120s TTL with a heartbeat at every progress callback would let another worker pick up a dead batch within ~1–2 min.
3. **Render dyno watchdog.** If the watcher dyno itself is what's dying, an external healthcheck could restart it faster than the lock TTL.
4. **UI warning for stalled batches.** On `/ingest/batch/<id>`, if `status='running'` AND `run_lock_until < NOW()`, render a "stalled" badge so operators notice without staring at the progress count.

Minimal-effort path: #1 (watcher poll-predicate verification and extension) plus #4 (UI signal).

### Resolution status (2026-05-04)

**Shipped (Possible fix #4 — UI signal + recovery affordance):** PR #382 added a Resume Batch button to `src/web/templates/ingest_batch.html:33-40` gated on `batch.status == 'running' AND batch.lock_stale`, where `lock_stale` is computed in `src/web/routes/ingest.py:710,769,910` as `(status='running' AND run_lock_until < NOW())`. The route at `ingest.py:887` (`/batch/<batch_id>/resume`) re-queues cancelled+failed filings and re-spawns the runner. This replaces the manual `UPDATE v2_ingest_batches SET run_lock_until = NULL` + local-runner workaround with a single click.

**Wired but unverified (Possible fix #1 — auto-recovery):** `_CLAIM_NEXT_SQL` (`src/universe/onboarding_runner.py:98-107`) admits both `queued` and `running` rows with `run_lock_until IS NULL OR run_lock_until < NOW()`. The watcher loop at `onboarding_runner.py:657` calls `claim_next_queued_batch()` on every poll cycle, so in theory the watcher should auto-recover stale-locked running batches without operator action. Whether this actually fires on Render after the original failure mode has not been verified end-to-end since 2026-04-28.

**Not pursued:**
- #2 (shorter lock TTL): TTL still 900s default; per-filing heartbeat already exists at `onboarding_runner.py:263`.
- #3 (Render dyno watchdog): infrastructure concern, out of scope.

**Remaining work to fully close:** reproduce a mid-batch stall on Render and confirm the watcher auto-claims it within the lock TTL. If reproduced and auto-recovery does NOT fire, file a fresh fragment for the watcher poll-predicate gap. If auto-recovery DOES fire, flip this to `resolved`.

### Operator workaround (current)

**Preferred:** click Resume Batch on `/ingest/batch/<id>` when the UI shows the stalled state.

**Fallback (still works if the UI is unavailable):** clear the lock and run the runner locally. UniverseBuilder is idempotent on `accession_number`, so re-running from scratch is safe.

### Cross-references

- Originating session: 2026-04-28 PayPal 10-K populate (batch `dce5e11f-aa52-4030-8e46-21c18310b9e5`)
- `.claude/rules/web.md` — documents the queued-batch claim contract; silent on stale-running recovery
- `src/universe/onboarding_runner.py:64-96` — `_CLAIM_SQL`, `_CLAIM_NEXT_SQL`, `_HEARTBEAT_SQL`
