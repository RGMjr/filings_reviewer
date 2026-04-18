# Handoff: Rewrite `docs/architecture/data-model.md` for V2 schema

**Created:** 2026-04-18
**Status:** Pending — pick up in a dedicated session
**Estimated effort:** 30–60 minutes focused work
**Prerequisites:** None. All DB migrations referenced here are already applied.

---

## Why this needs doing

`docs/architecture/data-model.md` was authored against the V1 schema and has not been touched since 2025-12-09. The V1→V2 cutover completed on 2026-04-18 (see `docs/architecture/v1-table-deprecation-plan.md`). The current doc contains **50 references to dropped or retired tables**, making it actively misleading for anyone onboarding or writing new queries.

The doc is not referenced at extraction runtime, so this is an onboarding/trust issue, not a correctness issue. But it is the first stop for new developers (per `docs/README.md` "Data users → Data Model") and it currently points them at tables that no longer exist.

---

## Current state (as of 2026-04-18)

### Tables actually in the live database

Run to confirm on day-of:
```bash
source .env && psql "$DATABASE_URL" -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
```

Expected output (from this session):
- **V2 (primary extraction output):** `v2_documents`, `v2_segments`, `v2_metric_facts`, `v2_metric_definitions`, `v2_image_assets`, `v2_image_review_decisions`, `v2_review_decisions`, `v2_tables`, `v2_table_cells`
- **Shared core:** `companies`, `filings`, `metrics`, `business_classifications`
- **V1 residual (scheduled for migration, not yet retired):** `review_candidates`, `review_decisions`, `source_segments`, `suppressed_candidates`, `learned_patterns`
- **Infra:** `schema_migrations`, `review_audit_log`, `llm_cache`, `image_cache`, `init_check`

### Tables referenced in data-model.md that NO LONGER EXIST

- `metric_values` — dropped by `sql/27_drop_v1_metric_tables.sql` (applied 2026-04-18)
- `metric_definitions` (V1) — dropped by `sql/27` (the V2 equivalent is `v2_metric_definitions`)
- `filing_metric_incidence` — dropped by `sql/26_drop_filing_metric_incidence.sql` (applied 2026-04-18); the quality scorer that wrote to it was deleted in commit `880f548`
- `image_review_candidates`, V1 `image_review_decisions` — dropped by `sql/30_drop_v1_image_review.sql` (applied 2026-04-17); V2 equivalents: `v2_image_assets` + `v2_image_review_decisions`

### Analysis views that reference dropped tables

`docs/architecture/data-model.md` lines 592, 614, 635 describe:
- `v_filing_metric_incidence` (references dropped table)
- `v_metric_values_cohort` (references dropped table)
- `v_metric_definitions` (references dropped table)

**Action required:** before rewriting the doc, verify whether these views still exist in the DB and, if so, whether they're broken:
```bash
source .env && psql "$DATABASE_URL" -c "\dv" | grep -E "v_filing_metric|v_metric_"
```
If the views exist, they're broken (reference dropped tables) and should either be dropped via a new migration or rewritten against V2 tables. Coordinate with whoever owns analytics consumption before changing them.

---

## Scope of the rewrite

The doc has 808 lines across these sections (line numbers as of 2026-04-18):

| Section | Lines | V1 contamination? |
|---|---|---|
| Overview | 9-20 | Clean |
| Design Principles | 22-45 | Clean |
| Entity Overview | 48-75 | **Heavy** — lists all 7 V1 tables including 3 dropped ones |
| Table Specifications §1 `companies` | 80-127 | Clean |
| Table Specifications §2 `filings` | 128-200 | Check; likely clean |
| Table Specifications §3 `source_segments` | 201-282 | Still exists (V1 residual); note deprecation target |
| Table Specifications §4 `metrics` | 283-333 | Clean (taxonomy table, shared) |
| Table Specifications §5 `metric_values` | 334-421 | **Entire section is a dropped table** |
| Table Specifications §6 `filing_metric_incidence` | 422-510 | **Entire section is a dropped table** |
| Table Specifications §7 `metric_definitions` (V1) | 511-560 | **Entire section is a dropped table** |
| Data Conventions | 561-587 | Probably still valid |
| Analysis-Ready Views | 588-653 | **Broken** — all 3 views reference dropped tables |
| Extensibility Notes | 654-680 | Check |
| Schema 09 Image Review + V2 | 681-740 | **V1 image section is dropped**; V2 section partly correct |
| Schema 10 V2 Fact Identity | 741-748 | Probably correct |
| Schema 15/16/17/18/23/25 migrations | 749-796 | Spot-check for staleness |
| Related Documentation | 797-808 | Cross-link audit |

### Recommended rewrite structure

Organize sections around the current pipeline rather than the legacy V1 grain:

1. **Overview + Design Principles** — keep largely as-is; add one line stating V2 is the production extraction schema.
2. **Entity map** — reorganize into three tiers:
   - Shared core (`companies`, `filings`, `metrics`, `business_classifications`)
   - V2 extraction (all `v2_*` tables — this is where new work lands)
   - V1 residual with retirement status (`review_candidates` + friends — point at `v1-table-deprecation-plan.md` for the roadmap)
3. **Table specifications** — one subsection per table. For the retired V1 tables, do NOT keep the old subsections; drop them entirely. The git history preserves the old text if anyone needs to see it.
4. **V2 fact model** — net-new section: describe how `v2_metric_facts` rows map to (`doc_id`, `canonical_metric_id`, `period_end`, `unit`, `scope`) identity, how `evidence_pack` stores provenance, how `v2_metric_definitions` joins, how chart-bridge facts are tagged via `source_type`.
5. **Analysis views** — replace the three V1 views. Either document new V2 views if they exist, or explicitly state "analytics views against V2 facts are a pending deliverable." Don't leave the dead view SQL in place.
6. **Migration log** — cross-link to `sql/` ordering rather than inline-describing migrations; the current migration-by-migration narrative drifts badly.

### What NOT to change

- `source_segments` is still live (V1 residual; used by `src/gold_standard/fresh_extractor.py` and V1 candidate-gen). Document it honestly as V1 residual with a pointer to the deprecation plan.
- `metrics` table is shared (not V1), describes the canonical taxonomy. Keep.
- `companies`, `filings` are shared core. Keep.

---

## Verification steps before starting

Run these first so the rewrite is based on current reality, not the state captured in this handoff:

```bash
# 1. Tables actually present
source .env && psql "$DATABASE_URL" -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"

# 2. Views actually present (check for broken v_filing_metric_incidence etc.)
source .env && psql "$DATABASE_URL" -c "\dv"

# 3. Latest migrations applied
source .env && psql "$DATABASE_URL" -c "SELECT id FROM schema_migrations ORDER BY id DESC LIMIT 10"

# 4. Confirm none of these 3 V1 tables still exist
source .env && psql "$DATABASE_URL" -c "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('metric_values','metric_definitions','filing_metric_incidence')"
# Expected: 0 rows

# 5. Current V2 schema (structure of the primary fact table)
source .env && psql "$DATABASE_URL" -c "\d v2_metric_facts"
source .env && psql "$DATABASE_URL" -c "\d v2_metric_definitions"
source .env && psql "$DATABASE_URL" -c "\d v2_documents"
source .env && psql "$DATABASE_URL" -c "\d v2_image_assets"
source .env && psql "$DATABASE_URL" -c "\d v2_image_review_decisions"
source .env && psql "$DATABASE_URL" -c "\d v2_segments"
source .env && psql "$DATABASE_URL" -c "\d v2_tables"
source .env && psql "$DATABASE_URL" -c "\d v2_table_cells"
source .env && psql "$DATABASE_URL" -c "\d v2_review_decisions"
```

## Primary sources of truth for the rewrite

- `sql/09_v2_schema.sql` — original V2 DDL
- `sql/10_v2_fact_identity_dedup.sql`, `sql/11_v2_definitions.sql`, `sql/12_v2_documents_transcript_columns.sql`, `sql/17_add_cohort_type_to_v2.sql`, `sql/23_chart_source_dedup.sql`, `sql/25_cross_source_confirmation.sql`, `sql/28_extend_v2_image_assets_review.sql`, `sql/29_create_v2_image_review_decisions.sql` — V2 column additions and constraint tweaks
- `src/extraction_v2/models.py` — dataclasses that correspond 1:1 to V2 tables; authoritative for field meanings
- `src/extraction_v2/persistence.py` — actual INSERT/UPSERT SQL; if the doc contradicts this file, the file wins
- `docs/architecture/v1-table-deprecation-plan.md` — retirement roadmap for the remaining V1 tables; the data-model doc should link to it rather than duplicate it

## Things to not do

- Don't try to preserve the old V1 table sections. Delete them. Git history has them.
- Don't rewrite `src/extraction_v2/models.py` or the SQL to match what the doc says — the doc is behind, not the code.
- Don't attempt this rewrite in the same session as extraction/keyword changes. Doc edits don't need gold-standard validation; mixing them with extraction work burns the GS-validation pre-commit cycle unnecessarily.
- Don't touch the analysis views without first checking who consumes them. `grep -r "v_filing_metric_incidence\|v_metric_values_cohort\|v_metric_definitions" .` — confirm nothing outside the doc itself references them before dropping or rewriting.

## Commit plan

This rewrite is big enough to warrant one dedicated commit:

```
docs(data-model): rewrite for V2 schema post-V1 cutover

Authored against 2026-04-18 DB state. Retired V1 table sections removed
(metric_values, metric_definitions, filing_metric_incidence — tables
dropped by migrations 26/27 on 2026-04-18). Reorganized entity map
around shared/V2/V1-residual tiers. Added V2 fact-model section.
Updated analysis views section to reflect whatever the current state
actually is.

Cross-reference: docs/architecture/v1-table-deprecation-plan.md
```

No tests to run (docs-only); no gold-standard validation; no `pytest` gate per CLAUDE.md.

---

## Starting prompt for the new session

Copy-paste this into a fresh session:

> Rewrite `docs/architecture/data-model.md` to reflect the current V2 schema. The doc at HEAD is authored against the pre-cutover V1 schema and references 50+ instances of dropped tables (`metric_values`, `metric_definitions`, `filing_metric_incidence`). Full scope, verification commands, primary sources, and pitfalls are documented in `docs/analysis/DATA_MODEL_DOC_REWRITE_HANDOFF.md` — read that first, then execute. Verify the DB state with the queries in the handoff before writing, since this handoff may be stale.
