---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 54
severity: n/a
slug: chart-bridge-emits-low-confidence-misbinds-on-non-tier-1-cha
source: legacy
status: archived
title: Chart-Bridge Emits Low-Confidence Misbinds on Non-Tier-1 Charts
touches: []
updated: '2026-04-22'
---

New `PipelineConfig.chart_metric_min_confidence` knob (Guard 6 on `ChartFactBridgeStage`). Default 0.60 matches the existing classification gate — no default behavior change — because Tier 1 `cm_balance_by_cohort` classifies at ~0.6024 and a 0.70 default would regress Tier 1 recall. Operators can tighten the knob during backfills to suppress weak top-match binds. 5 unit tests added as `TestGuard6MetricConfidenceFloor`. See commit `7848605` and companion Issue #64 for the boundary sensitivity follow-up.
