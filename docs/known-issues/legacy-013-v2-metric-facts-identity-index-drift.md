---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 13
severity: n/a
slug: v2-metric-facts-identity-index-drift
source: legacy
status: archived
title: V2 Metric Facts Identity Index Drift
touches: []
updated: '2026-04-22'
---

`sql/33_fix_identity_index.sql` idempotently drops and recreates `idx_v2_metric_facts_identity_unique` with all 9 columns including `source_type`. Prod confirmed 9-col via direct `pg_indexes` read on 2026-04-19; local test DB and prod now agree. See `sql/33_fix_identity_index.sql` and `scripts/apply_migrations.py:68-74`.
