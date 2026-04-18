# V1 Retirement Code Scan (2026-04-18)

This scan catalogs two buckets:

1. **Dead references** to the retired V1 extraction pipeline (or V1 tables already dropped).
2. **Active V1 code** that still runs and should be migrated to V2 during retirement completion.

## Scope and method

- Searched active source, scripts, tests, and non-archive docs for V1 terms and retired table names.
- Commands used:
  - `rg -n "\bv1\b|v1_|_v1|pipeline v1|old pipeline|legacy pipeline|extraction_pipeline|review_pipeline"`
  - `rg -n "src\.extraction\.|extraction_pipeline\.py|generate_review_candidates\.py|review_candidates|source_segments|review_decisions|suppressed_candidates|image_review_candidates|metric_values\b|metric_definitions\b" src scripts tests docs --glob '!docs/archive/**' --glob '!docs/analysis/**'`
  - `test -d src/extraction && echo src_extraction_exists || echo src_extraction_missing`

`src/extraction` is absent (`src_extraction_missing`), consistent with V1 pipeline retirement.

---

## A) Dead references to retired V1 pipeline / dropped V1 tables

These are references that are misleading for current production use because they point to deleted pipeline code or dropped tables.

### A1) Stale docs that still describe dropped V1 schema as current

- `docs/architecture/data-model.md`
  - Still documents `source_segments`, `metric_values`, and `metric_definitions` as core tables and includes V1 DDL.
  - Should be rewritten to V2-first schema and explicitly mark V1 sections as historical or remove them.

- `docs/operations/extraction-runbook.md`
  - Primary operational flow still centers on `source_segments` → `review_candidates` → `metric_values`.
  - Contains a small V2 note, but the runbook body remains V1-centric and is risky as an operational guide.

- `docs/operations/v2-deployment-guide.md`
  - Contains statements implying V1 extraction outputs (`metric_values`, related tables) remain available as a normal state.
  - `metric_values`/V1 `metric_definitions` are already dropped; language should be updated to post-cutover reality.

- `docs/operations/image-model-training-runbook.md`
  - References `image_review_decisions` table as training source; V1 image review tables were dropped in migration 30.

- `docs/README.md`
  - Mentions migration for `image_review_candidates` as if table is still part of live schema progression; this now reads as historical and should be clearly tagged as such.

### A2) Historical references to deleted module path

- `docs/analysis/SAMSARA_VISION_EXTRACTION_ANALYSIS.md`
- `docs/analysis/COMPREHENSIVE_EVALUATION_AND_IMPROVEMENT_PLAN.md`
- `docs/architecture/extraction-pipeline.md` (appendix/historical sections)

These mention `src/extraction/extraction_pipeline.py`. In `docs/architecture/extraction-pipeline.md` it is explicitly marked deleted; that is acceptable in historical context. The two analysis docs should be tagged “historical” to prevent accidental operational use.

### A3) One migration-era script now effectively retirement-only

- `scripts/migrate_image_decisions_to_v2.py`
  - Purpose was pre-drop backfill from V1 image tables.
  - It now short-circuits if `image_review_candidates` is absent; useful for older DBs, but effectively dead for already migrated environments.
  - Recommendation: move to `scripts/archive/` (or mark clearly as pre-migration-only) after confirming no remaining environments need it.

---

## B) Active V1 code to migrate to V2 (retirement backlog)

This is the separate list of code that is still active and should be ported or replaced.

### B1) Core persistence + review workflow (highest priority)

- `src/infra/db.py`
  - Heavy use of `review_candidates`, `review_decisions`, `source_segments`, `suppressed_candidates`.
  - Includes both read/write paths, filtering, sorting, bulk insert/upsert, and decision lifecycle.

- `src/review/helpers.py`
- `src/review/candidate_generator.py`
- `src/review/pattern_analyzer.py`
- `src/review/models.py`
- `src/review/rule_applicator.py`
- `src/review/__init__.py`

These modules still implement V1 candidate-based review flow and map directly to remaining V1 tables.

### B2) V1-backed web/API surfaces

- `src/web/routes/api.py` (V1 review decision operations)
- `src/web/templates/filing_list.html` (still instructs running V1 candidate generation script)

(Meanwhile, `src/web/routes/review_unified.py` and `src/web/routes/api_unified.py` are already V2-oriented for unified/image workflows.)

### B3) V1 operational scripts still in active use

- `scripts/generate_review_candidates.py`
- `scripts/regenerate_candidates_with_segments.py`
- `scripts/export_review_decisions.py` (contains both V1 + V2 modes; V1 branch should be retired once cutover is complete)

### B4) Tests anchored to V1 workflow (migration/testing backlog)

- `tests/unit/scripts/test_generate_review_candidates.py`
- `tests/integration/test_generate_review_candidates_integration.py`
- `tests/integration/test_db_review_methods.py`
- `tests/integration/test_db_upsert.py`
- `tests/unit/review/test_helpers.py`
- `tests/unit/review/test_pattern_analyzer.py`
- `tests/e2e/*` references to V1 candidate generation / V1 review tables

These should be progressively replaced with V2-native equivalents to avoid locking V1 APIs in place.

---

## Recommended tracking split for future work

1. **Docs cleanup ticket (dead references):**
   - Rewrite `docs/architecture/data-model.md` to V2.
   - Update extraction/deployment/image runbooks to remove dropped-table assumptions.
   - Tag legacy analysis docs as historical-only.

2. **V1 runtime retirement epic (migration):**
   - Design V2-native replacement for `review_candidates` workflow.
   - Port `db.py` V1 review methods to V2 fact-based review model.
   - Migrate scripts + APIs + tests in lockstep.

3. **Post-cutover cleanup:**
   - Archive/remove migration-only scripts (`migrate_image_decisions_to_v2.py`) after environment verification.

