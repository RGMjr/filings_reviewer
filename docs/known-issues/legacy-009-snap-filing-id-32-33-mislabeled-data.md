---
autonomy: n/a
discovered: '2026-04-22'
estimated: M
id: 9
note: Needs re-ingestion of real Snap filing; not a code fix
severity: n/a
slug: snap-filing-id-32-33-mislabeled-data
source: legacy
status: archived
title: Snap Filing (ID 32/33) — Mislabeled Data
touches: []
updated: '2026-04-22'
---

Filing 32 was labelled "Snap" but the CIK on record (`0001644378`) belongs to RMR Group Inc.; no Snap content had ever been ingested. Resolution:

1. Relabeled the local `companies` row for CIK `0001644378` to `'RMR Group Inc.'` (preserves the already-extracted RMR content under the correct issuer name; no CASCADE through `v2_segments`/`v2_metric_facts`/`v2_review_decisions`).
2. Seeded `Snap Inc.` (CIK `0001564408`) + its real S-1/A (accession `0001193125-17-056992`, filed 2017-02-27, primary doc `d270216ds1a.htm`) via `sql/seed_snap_s1a.sql` (unnumbered, one-off — follows `sql/register_gold_standard_filings.sql` precedent; not registered in `scripts/apply_migrations.py`).
3. Fetched HTML via `FilingFetcher.fetch_filing` (2.3 MB into `data/filings/0001564408/000119312517056992/primary.htm`).
4. Ran V2 extraction — 8 facts across `cm_daily_active_users`, `cm_revenue_per_customer`, `cm_active_customers_total` (1724 segments, 547 tables, 40 images persisted).
5. Updated `scripts/gi3_richness_analysis.py` FILING_MAP (id 32 → `"RMR Group Inc."`; comment shortened).

Scope limited to local (`$TEST_DATABASE_URL`). Neon prod mirror is a separate workstream. Adding Snap's new filing_id to gold-standard coverage is also out of scope — owned by the gold-standard workflow. Previously attempted as PR #72 on 2026-04-21; that branch was closed during the #65 history scrub and this is the replay.
