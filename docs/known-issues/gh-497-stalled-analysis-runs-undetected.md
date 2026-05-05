---
id: 497
source: gh
slug: stalled-analysis-runs-undetected
title: No proactive alert on stalled text_decision_analysis_runs / model_training_runs / v2_ingest_batches rows
status: open
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-05
updated: 2026-05-05
gh_issue: 497
note: stale-row sweeps are reactive; nightly-sweep digest could surface stranded jobs
---

### Problem

Until 2026-05-05, every text-pattern-analysis run since the surface launched was stranded at `status='running'` because the prod web service no-op'd the spawn (`INGEST_SPAWN_SUBPROCESS=false` early-return with no worker-side queue consumer; fixed in commit `495ae43`). The "anchor: (lifetime, no prior succeeded run)" line on the manual-unblock log proved no run had ever succeeded since the surface was deployed. Nothing alerted — the 1-hour stale-row sweep at `src/web/routes/api_unified.py:1489-1498` is reactive (next click only), and the surface is button-driven, so the only signal was a reviewer noticing the spinner never resolved. The same observability gap applies to `model_training_runs` and `v2_ingest_batches`: their queue+worker pairs work today, but a worker that stops draining (OOM, env misconfig) would strand rows identically.

### Next Steps

- Add a scheduled check in `filings-nightly-sweep` (or a Metabase card) that flags `text_decision_analysis_runs.status='running' AND started_at < NOW() - INTERVAL '30 minutes'`, plus the lock-aware equivalents for `model_training_runs` and `v2_ingest_batches`.
- Add a "no succeeded run in N days where reviewer activity exists" alert keyed off `count_text_decisions_since(last_succeeded_run.completed_at)` clearing the threshold.
- Stretch: surface "last analysis: N days ago" in the `/v2/review/stats` header so reviewers see a passive signal.
