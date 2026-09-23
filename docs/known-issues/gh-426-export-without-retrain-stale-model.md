---
id: 426
source: gh
slug: export-without-retrain-stale-model
title: Export-without-retrain leaves data/image_model/relevance_model.joblib stale
status: archived
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-04
gh_issue: 426
pr_refs:
  - 446
note: resolved by PR #446 (Option C — stderr banner at end of export, suppressed when retrain_image_triage.py sets RETRAIN_CHAINED=1)
---

### Problem

`scripts/export_image_training_data.py` and `scripts/train_image_relevance_model.py` are independently runnable. `retrain_image_triage.py` chains them, but operators can (and have) re-run the export alone — leaving `data/image_model/training_data.csv` regenerated while `relevance_model.joblib` reflects the prior CSV. Discovered during the gh-405 audit (2026-05-01): CSV had 1,499 rows, joblib was the 808-row model.

Currently benign because `USE_LEARNED_TRIAGE=false` in prod (per gh-391 — runtime never loads the joblib). Becomes a silent staleness bug the moment that flag flips on.

### Next Steps

- Refuse to leave CSV/model out of sync (sidecar checksum, fail-fast on load), OR
- Chain export into retrain by default with an explicit `--export-only` escape, OR
- Print a loud warning at the end of the export step pointing at the next required command.
