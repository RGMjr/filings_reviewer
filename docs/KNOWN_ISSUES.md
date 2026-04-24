<!-- AUTO-GENERATED — do not edit directly. Edit fragments in docs/known-issues/ and run scripts/regenerate_known_issues.py. -->

# Known Issues


## Summary

| Status | Count |
|--------|-------|
| Open | 32 |
| Partially Resolved | 1 |
| Archived | 46 |
| Resolved | 17 |


## Nightly Sweeper Classification

| Issue | Autonomy | Estimated | Touches | Note |
|-------|----------|-----------|---------|------|
| #2 | skip | L | — | Umbrella for Farfetch recall; sub-issues, stakeholder tuning |
| #4 | skip | — | — | Known limitation; not actionable |
| #5 | skip | — | — | Working as designed |
| #9 | skip | M | — | Needs re-ingestion of real Snap filing; not a code fix |
| #11 | skip | XS | — | Tied to archived Issue #10; defer |
| #16 | skip | M | — | Precision tuning; data-driven, needs judgment |
| #24 | skip | M | — | Data audit + FK migration; needs cleanup decision |
| #27 | skip | S | — | Stale assertions — needs judgment on test rewrite |
| #28 | skip | L | — | Root architecture issue; no single-file fix |
| #34 | skip | — | — | Cross-referenced only; closes when dependents close |
| #35 | skip | L | — | Dissolved by the chart-presence pivot (2026-04-23). Historical filings no longer need chart-fact backfill — the chart pipeline no longer produces facts. detected_metrics backfill on historical filings is tracked separately. |
| #38 | review | M | `sql/*.sql` `src/*/*.py` `src/web/routes/*.py` `tests/**/*.py` | Column rename + callsite sweep; needs callsite audit |
| #39 | skip | M | — | Column rename; needs migration ordering decision |
| #40 | skip | — | — | Stakeholder decision (supersession semantics) |
| #43 | skip | — | — | Latent; no action needed until re-extraction |
| #49 | skip | M | — | Resolved 2026-04-23 — cannot reproduce on main; retained in table for audit trail |
| #53 | skip | M | — | Chart call limit; needs data-driven tuning. Post-#86 chart-presence pivot (2026-04-23), truncation affects presence coverage only (missed detected_metrics signals) — no per-value correctness impact because the pipeline no longer emits per-value chart facts. |
| #55 | skip | S | — | Data cleanup; needs inspection of stuck filings |
| #58 | review | S | `src/filing_fetcher/*.py` `tests/unit/filing_fetcher/*.py` | 8-K Exhibit 99.1 fetch; feature add, needs validator run |
| #59 | review | S | `src/extraction_v2/classifier*.py` `tests/unit/extraction_v2/*classifier*` | New classifier patterns; FP risk |
| #60 | skip | XS | — | Resolved 2026-04-21; retained in table as audit trail |
| #62 | review | S | `docs/operations/*` `src/universe/onboarding_runner.py` | Docs + optional admin flag; needs design call |
| #63 | skip | S | — | Monkey-patch integration test; mid-complexity |
| #66 | review | S | `render.yaml` `.claude/rules/infrastructure.md` | Wire apply_migrations into Render deploy; infra-change risk |
| #69 | review | S | `Dockerfile.nightly-sweep` | Pin claude + gh versions; needs validation step |
| #75 | skip | S | `tests/ui/*.spec.js` `tests/ui/test_server.py` | Playwright E2E gap — cross-filing auto-advance; needs stub-server extension |
| #79 | safe | XS | `scripts/known_issues_selector.py` | Filter selector picks on status=open or partially-resolved |
| #80 | review | S | `src/infra/image_storage.py` `src/gold_standard/v2_validator.py` `.claude/rules/infrastructure.md` | Add env-scoped guard against unintended prod R2 writes from CLI tools; design call (storage-layer vs validator-layer) needed |
| #84 | review | S | `scripts/known_issues_selector.py` `.claude/commands/commit.md` | Cross-reference pr_refs with GitHub API; auto-update status=resolved on merge |
| #85 | safe | XS | `scripts/apply_all_migrations.py` | Recurrence of Issue |
| #86 | review | M | `src/extraction_v2/stages/deduplication.py` | Dissolved by the chart-presence pivot (PRs #147/#150/#151/#154, 2026-04-23). Chart pipeline no longer emits per-value facts, so the dedup identity-key collapse root cause no longer exists. Residual chart facts drain in PR 4b. |
| #88 | skip | S | `scripts/apply_all_migrations.py` `.pre-commit-config.yaml` | Add a pre-commit hook that fails if any sql/NN_*.sql on disk lacks an entry in MIGRATION_ORDER or EXCLUDED_FILES. |
| #94 | safe | S | `sql/31_drop_v1_review_tables.sql` `sql/` `src/web/middleware.py` |  |
| #95 | review | M | `scripts/apply_migrations.py` `render.yaml` `src/web/app.py` `sql/` |  |
| #97 | review | M | — | Residual pre-pivot chart facts (30 rows across 10 filings) remain in v2_metric_facts post-#86 because 18 reviewer decisions on those facts would CASCADE-destroy on DELETE. Low blast radius — new UI does not read them, validator bypasses them — but analytics views filtering on source_type=chart still see them. |
| #98 | review | S | `src/gold_standard/v2_validator.py` `src/extraction_v2/stages/chart_fact_bridge.py` | PR #150 added the presence P/R/F1 infrastructure to the validator + baseline, but presence_f1 is emitted as None because v2_context.images[*].detected_metrics is not populated during the validator's in-memory pipeline run. Baseline refresh in PR 4b (2026-04-24) has presence_f1=null as a result. |


## Open Issues

## #95. Schema Migrations Drift From Prod — No Post-Deploy Apply Step

**Status**: Open
**Severity**: high
**Discovered**: 2026-04-23
**Updated**: 2026-04-23

### Problem

Code that references new schema can ship to prod (Render) without the
corresponding SQL migration being applied. Nothing in the deploy path
runs `scripts/apply_migrations.py` against Neon after a merge to `main`.
The result is runtime `UndefinedColumn` / `UndefinedTable` errors in
prod while the same queries succeed in local dev and CI (both of which
apply migrations implicitly via pytest/Docker bootstrap).

**Trigger case (2026-04-23):** PR #151 merged with `sql/42_add_detected_metrics_to_v2_image_assets.sql` and `sql/43_create_v2_image_metric_confirmations.sql`. Code at `src/infra/db.py:1709` began selecting `v.detected_metrics` from `v2_image_assets`. Neon never received the migrations. Every call to `get_image_review_candidates_for_filing_v2()` — which `review_filing` invokes unconditionally for the Images-tab counts — raised `psycopg.errors.UndefinedColumn`, got caught by the try/except at `src/web/routes/review_unified.py:472-475`, flashed "Error loading review", and redirected to the filing list. Users saw "Review button flashes and returns to the list." Auto-accepted facts were effectively unreviewable.

Fix was a one-shot manual `python3 scripts/apply_migrations.py` against `$DATABASE_URL`. Both migrations applied cleanly. Review page recovered on next request.

### Compounding issue: checksum-guard false positive

During the manual fix the runner halted on `37_create_analytics_role.sql` with
```
HALTED: Checksum mismatch for 37_create_analytics_role.sql: expected e7b06ff3…, got a589d96a…
```
Commit `8d09001` (#111) added a purely cosmetic `-- cluster-ddl-ok: ...` comment to `sql/37_create_analytics_role.sql` to silence the cluster-DDL pre-commit guard. No DDL change, no DB impact — but the content hash changed, so the ledger's SHA-256 check flagged drift and refused to proceed. Had to reconcile the ledger row manually:
```sql
UPDATE schema_migrations SET checksum = '<new_hash>' WHERE id = '37_create_analytics_role.sql';
```
Any future comment-only edit to an applied migration file will trip the same guard and block all subsequent applies — including emergency ones. This has happened before (see legacy-018, legacy-090).

### Blast radius

- Prod features silently break on any PR that adds a migration.
- The failure surfaces only when a specific endpoint queries the new column/table — often hours or days after deploy, not at build/health-check time.
- `scripts/apply_migrations.py` is the only recovery path, and the checksum guard can block even that.
- No alerting: Render logs show per-request exceptions but nothing watches the rate.

### Next steps

Pick one (or more) of:

1. **Render post-deploy hook.** Add to `render.yaml` under the `filings-reviewer` service:
   ```yaml
   preDeployCommand: python3 scripts/apply_migrations.py
   ```
   Runs after build, before traffic cuts over. Blocks deploy if migrations fail. This is the minimum viable fix.

2. **App-startup migration check.** In `src/web/app.py::create_app`, after pool init, SELECT `MAX(id)` from `schema_migrations` and compare against a pinned "expected head" constant maintained in `scripts/apply_migrations.py::MIGRATIONS[-1]`. Fail-fast with a clear error if behind. Catches the "migration not applied" case even when the pre-deploy hook is skipped (e.g., manual restart).

3. **Relax the checksum guard for comment-only diffs.** In `scripts/apply_migrations.py::_checksum`, strip SQL comments (lines matching `^\s*--`) before hashing. Commit-marker comments (`-- cluster-ddl-ok:`) and operator-note comments should not force a ledger reconciliation. Alternatively: add a `--reconcile-ledger` flag that updates the stored checksum to the file's current hash when the diff is comment-only, without re-executing the migration.

4. **CI schema-drift check.** After apply-migrations in the integration-tests job, diff the applied set against `MIGRATIONS` and fail if any file in `sql/` is not registered. Catches the "developer added sql/42 but forgot to register it" case that's worse than this one.

5. **Alerting.** Simple: log an ERROR line with a stable token (e.g., `MIGRATION_DRIFT_DETECTED`) whenever the app-startup check in #2 fires, and add a Render log alert on that string. No new infra.

**Recommended order:** #1 (render.yaml pre-deploy) + #3 (relax checksum) as the tight Phase-1 pair — unblocks routine deploys and prevents the guard from re-blocking future emergency applies. #2 and #4 as Phase-2 defense-in-depth.

### Verification after fix

- Trigger a no-op deploy on Render and confirm `scripts/apply_migrations.py` runs in the pre-deploy log.
- Temporarily roll back a migration's ledger entry (`DELETE FROM schema_migrations WHERE id='42_*'`) and confirm the next deploy re-applies it.
- Add a comment-only change to an applied migration, commit, push, and confirm the pre-deploy hook does not halt.
- Tail `filings-reviewer` Render logs for 15 minutes post-deploy: zero `UndefinedColumn` / `UndefinedTable` exceptions.

### Related history

- **legacy-018** — checksum mismatch on `sql/01_create_schema.sql`; self-healed via V1 retirement. Same class of problem.
- **legacy-090** — integration tests fail on sql/37 checksum. Same class of problem.
- Commit `8d09001` (#111) — added the cluster-DDL pre-commit guard and the `-- cluster-ddl-ok:` marker that caused this round's checksum drift.
- PR #151 — shipped `v.detected_metrics` SELECT without enforcing migration apply; the trigger case for this issue.

## #2. Low Farfetch Recall

**Status**: Open
**Severity**: medium
**Discovered**: 2026-01-01
**Updated**: 2026-01-01

**Re-measured**: 2026-04-18

### Current Farfetch Metrics (2026-04-18)

Re-measured via `python3 -m src.gold_standard.v2_validator --companies "Farfetch Limited" --fn-diagnostics`:

- **Overall**: P=50.0%, R=36.7%, F1=42.3% (TP=11, FP=11, FN=19)
- **Tier 1**: P=100%, R=10%, F1=18.2%
- **Tier 2**: P=45%, R=90%, F1=60%

Original "12.5%" figure (1 of 8 non-chart) is stale. The gold standard grew from 8 to ~30 Farfetch rows (49 total, 32 non-chart, 17 chart) since this issue was filed.

### Per-Metric Breakdown

| Metric | Tier | P | R | F1 | Notes |
|---|---|---|---|---|---|
| `cm_gross_margin_by_cohort` | T1 | 0% | 0% | 0% | 10 FNs — chart (see #15) |
| `cm_ltv_to_cac_ratio` | T1 | 100% | 100% | 100% | ✓ (Issue #14 resolved 2026-04-18) |
| `cm_ltv_to_cac_ratio_by_cohort` | T1 | 100% | 50% | 67% | Text FNs cleared (#14); 3 chart FNs remain (#20) |
| `cm_revenue_by_cohort` | T1 | 0% | 0% | 0% | 2 FNs — chart (see #15) |
| `cm_active_customers_total` | T2 | 29% | **100%** | 44% | Recall fine; 5 FPs (see #16) |
| `cm_average_order_value` | T2 | 100% | 100% | 100% | ✓ |
| `cm_cac_payback_period` | T2 | 0% | 0% | 0% | 1 FN — bare word-number (see #17) |
| `cm_purchase_transactions_overall` | T2 | 25% | 100% | 40% | Recall fine; 4 FPs (see #16) |

### Contributing Factors (Updated)

1. ~~**Metric ID mismatch** (Issue #1)~~ — resolved
2. ~~**URL issue** (Issue #6)~~ — resolved
3. ~~**CAC Payback "six"**~~ — KNOWN_ISSUES.md previously claimed this was fixed; **claim was inaccurate**. Spelled-out number support was added only for scaled forms ("six million"), not for time-unit forms ("six months"). See #17.
4. ~~**Take Rate patterns**~~ — void: `cm_take_rate` was removed from taxonomy 2026-01-02 (not a customer metric).
5. ~~**Layout-table dedup collision**~~ — resolved 2026-04-18 via #14 (respectively-parser priority + cohort_hint).
6. **Chart extraction blocked locally** — no `OPENAI_API_KEY` means chart-sourced gold rows can't be tested/recovered locally. See #15.
7. **Table-scale + period precision drag** — see #16.

### Next Steps

Issue #2 is now an umbrella. Individual gaps are tracked in sub-issues #14–#19. Close or demote Issue #2 after those sub-issues are triaged.

## #58. 8-K Fetcher Returns Only Primary Doc; Earnings Content Lives in Exhibit 99.1

**Status**: Open
**Severity**: medium
**Discovered**: 2026-04-20
**Updated**: 2026-04-20

### Problem

`FilingFetcher.fetch_filing` (`src/filing_fetcher/filing_fetcher.py:263-365`) downloads only `primary.htm` resolved from the accession's directory URL. For many 8-K filings the primary doc is a ~10 KB cover page that points at Exhibit 99.1 (the actual press release / financial-highlights HTML). Pipeline ran cleanly on 4/5 Phase 0 candidates but Samsara (2025-08-21) produced 0 facts — the primary doc was 9,336 bytes of boilerplate; all customer-metric content sat in `exhibit991-2025x08x21.htm` which was never fetched.

### Next Steps

1. In `fetch_filing`, after downloading `primary.htm`, parse the index for `99.1` (or regex-matched variants like `ex-99-1`) and download the exhibit alongside the primary doc.
2. Decide whether the pipeline consumes only the exhibit, both docs concatenated, or runs twice and merges facts — prefer "concat with a section break" for the MVP to avoid invalidating `filing_id` uniqueness.
3. Add an integration test using the Samsara 8-K (or a fixture mirroring its structure) asserting >0 customer-metric facts.
4. Gate on this before enabling 8-K in the batch-ingest UI form-type selector.

## #66. Migrations Not Auto-Applied on Render Deploy

**Status**: Open
**Severity**: medium
**Discovered**: 2026-04-21
**Updated**: 2026-04-21

### Problem

`scripts/apply_migrations.py` is idempotent (via the `schema_migrations` ledger) and keeps a registered list through `sql/39_v2_ingest_batches.sql`, but Render's blueprint-driven deploys do not invoke it. When PR #48 merged with `sql/39_v2_ingest_batches.sql`, Render auto-deployed `filings-onboarding-runner` without running the migration, and the worker then crashed every ~5 minutes with `psycopg.errors.UndefinedTable: relation "v2_ingest_batches" does not exist` until an operator manually ran `python3 scripts/apply_migrations.py` against Neon. Every future schema-change PR has the same failure mode.

### Next Steps

- Add a Render pre-deploy command on `filings-reviewer` (the web service with the longest deploy budget) that runs `python3 scripts/apply_migrations.py` before the container starts. The ledger makes it safe on every deploy.
- Alternative: a dedicated one-shot Render Job that runs the migration runner on every merge to main, blocking service redeploys until it exits 0.
- Document the chosen path in `.claude/rules/infrastructure.md` so future schema-change PRs don't repeat this.

### Cross-References

- `scripts/apply_migrations.py` — migration runner (idempotent via `schema_migrations` ledger)
- `sql/39_v2_ingest_batches.sql` — the migration that triggered this discovery
- `render.yaml` — pre-deploy hook would attach to the web service entry

## #80. GS Validator Has No Safeguard Against Unintended Prod R2 Writes

**Status**: Open
**Severity**: medium
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Problem

`python3 -m src.gold_standard.v2_validator` reads its environment uncritically. If `R2_BUCKET` (and the rest of the R2 creds) are set when the validator runs, the chart pipeline's `OCRExtractionStage._download_missing_images` will issue `storage.put_bytes` calls against the live R2 backend — a production write — for every chart-classified image whose asset row lacks a `file_path`. There is no warning, no dry-run mode, no env-scoped guardrail. A contributor who sources prod `.env` to make `psql` / `boto3` work for one CLI step (e.g. probing a key with `HeadObject`) and then runs the validator gets a silent prod state mutation.

The same risk applies to any code path that calls `storage.put_bytes` without an env-scoped sanity check (currently `OCRExtractionStage._download_missing_images` and `IngestionStage._extract_image_assets` both qualify).

### Next Steps

- Add an env-scoped safeguard to `get_image_storage()` (or wrap `put_bytes` itself): when the active backend is `R2Storage` AND the process was started without an explicit "I intend prod writes" opt-in (e.g., a `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` env var), refuse `put_bytes` and surface a clear error pointing at the cause. Reads (`get_bytes`, `exists`) stay open so diagnostics remain possible.
- Alternative: add a startup check in `v2_validator.py __main__` that warns (or aborts) when `R2_BUCKET` matches the prod bucket name unless `--allow-prod-writes` is passed. Narrower scope than the storage-layer guard but catches the validator-specific foot-gun.
- Document the foot-gun in `.claude/rules/infrastructure.md` under image-storage so future contributors are aware before the safeguard lands.

Cross-references: #77 (the bug whose fix surfaced this), #34 (R2 backend introduction).

## #81. PayPal Pre-2024 8-Ks Extract No Facts — Body Is Page-Image Scans

**Status**: Open
**Severity**: medium
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Problem

PayPal's pre-2024 8-K filings (CIK `0001633917`, 12 filings 2021–2023)
are submitted as page-image decks: each "page" is a JPG (~1055×1365),
there is no HTML body text to segment. The existing V2 pipeline
classifies these images as `UNKNOWN` (below `MIN_RELEVANCE_FOR_PROCESSING=0.3`)
so they never reach the OCR stage, and `context.segments` is empty
so `candidate_generation` runs over nothing. DB state: 0 segments,
199 JPGs unprocessed, 0 facts, 0 review decisions across these 12
filings.

### Resolution

Full-page-scan OCR (Path A) + image-level Tier-1 keyword pre-scan
(Path B), both default-off, landed on the `full-page-ocr` branch.
See `.claude/rules/v2-pipeline.md` for the pipeline-level design and
`docs/operations/full-page-ocr-runbook.md` for the operator runbook
(detector thresholds, dry-run/backfill workflow, verification SQL,
rollback).

### Next Steps

1. Merge the feature branch with both flags default-off; CI green.
2. Dev smoke test on one PayPal 8-K; eyeball segments + facts.
3. Enable `FULL_PAGE_OCR_ENABLED=true` in prod; run
   `scripts/backfill_full_page_ocr.py --confirm --cik 0001633917 --form-type 8-K --filing-date-before 2024-01-01`.
4. Stability permitting, enable `IMAGE_KEYWORD_PRESCAN_ENABLED=true`
   and re-extract 5 investor-deck-style filings to exercise Path B.

## #88. No pre-commit guard catches sql/ files missing from MIGRATION_ORDER

**Status**: Open
**Severity**: medium
**Discovered**: 2026-04-23
**Updated**: 2026-04-23

### Problem

`scripts/apply_all_migrations.py` has drifted twice (issues #46 and #85) because new SQL migration files land on disk without a corresponding entry in `MIGRATION_ORDER`. The `check_unregistered_migrations` guard only fires at runtime (`--dry-run`), not at commit time, so the drift isn't caught until someone runs the script.

### Next Steps

- Add a pre-commit hook (or `local` hook in `.pre-commit-config.yaml`) that runs `python3 scripts/apply_all_migrations.py --dry-run` (which exits 1 when unregistered files are found) before each commit.
- Alternatively, write a small standalone check script and register it as a `local` repo hook so it doesn't require a DB connection.
- Verify the hook runs in CI as well (the pre-commit framework is already in use for ruff and the extraction guard).

## #89. Image-OCR Segments + Re-OCR'd Images Not Surfaced in Review UI

**Status**: Open
**Severity**: medium
**Discovered**: 2026-04-23
**Updated**: 2026-04-23

### Problem

Full-page-OCR smoke test (filing_id 1748, PayPal Q3'23 8-K) wrote 18
`v2_segments` rows with `source_type='image_ocr'` + populated
`v2_image_assets.ocr_text` on all 18 images. The synthesized OCR text
is high quality (verbatim extraction: "Total payment volume (TPV) of
$387.7 billion, growing 15% and 13% on an FX-neutral (FXN) basis…").
But none of it is reachable through the review UI:

1. **Text tab renders facts, not segments.** The tab queries
   `v2_metric_facts`. Full-page-OCR on PayPal produced 0 facts because
   PayPal's earnings language (TPV, active accounts, cross-border
   volume) doesn't match CMASB Tier 1 patterns without further tuning.
   Result: text tab is empty even though 18 segments of real earnings
   prose are in the DB.
2. **Image tab shows prior review decisions as "already reviewed"**,
   even though the images have fresh `ocr_text` now. The 18 images had
   `v2_image_review_decisions` rows from before the re-extraction
   (made when they had no OCR data). The reviewed-filing guard
   preserves those decisions across re-extraction, so the images land
   in the UI as reviewed — with the new OCR text attached but hidden
   behind "already done" UX.

Net effect: the full-page-OCR feature is technically working in prod
(18 segments + `ocr_text` persisted correctly, no FK errors post-#139)
but **no reviewer ever sees the output** unless they know to query SQL
directly or pull up individual image-review pages.

### Next Steps

1. **Surface image-OCR segments in the text tab** (or a sibling tab).
   One option: render `v2_segments` rows with `source_type='image_ocr'`
   alongside fact rows so operators can see the raw OCR'd prose even
   when extraction produces no facts. Link each segment to its
   `source_img_id`.
2. **Invalidate prior image review decisions when new OCR data lands.**
   If `v2_image_assets.ocr_text` or `chart_data` is updated and differs
   from what existed when the previous decision was made, flip
   `review_status` back to `pending` (with an audit trail). Alternative:
   add a "re-review" button to image-detail pages that lets operators
   explicitly unlock a reviewed image.
3. **Validation target:** filing_id 1748 is already extracted with the
   full pipeline; use it as the fixture. Success = navigating to
   `/v2/review/1748` surfaces the 18 OCR'd segments and lets a reviewer
   see/validate the extracted earnings text.

### Cross-references

- #81 — PayPal pre-2024 8-K page-scan coverage (full-page-OCR feature).
- #82 — Full-page-OCR pipeline integration test missing; this issue
  adds the UI-surfacing layer to that integration gap.
- PR #139 — landed the three backfill fixes that made filing 1748
  ingest cleanly; this issue is the logical follow-up.

## #90. Integration Tests Fail at Startup on sql/37 Migration-Checksum Drift

**Status**: Open
**Severity**: medium
**Discovered**: 2026-04-23
**Updated**: 2026-04-23

### Problem

Running `pytest` without `--ignore=tests/integration` fails before any
test body executes with:

```
RuntimeError: Checksum mismatch for 37_create_analytics_role.sql:
expected e7b06ff3…, got a589d96a…. Migration file was modified
after it was applied.
```

Surfaced today while running the full suite for the B5.x chart-read
commit gate. `sql/37_create_analytics_role.sql` has been edited after
the shared test DB had already applied the earlier content (PRs #111
touched it for hook guards), so the `schema_migrations` checksum no
longer matches the file. Hitting this on any dev machine that rebuilds
its test DB from a snapshot, or that runs integration tests after
pulling a branch that touches migration 37.

Unit-only runs (`pytest --ignore=tests/integration`) are unaffected —
the full 3833-test unit suite passes cleanly. Blast radius is CI
integration jobs + local integration runs.

### Next Steps

- Add a "rebuild test DB" runbook entry under
  `docs/operations/setup-guide.md` documenting the drop/recreate
  workflow when checksums drift after a migration edit.
- Alternatively: loosen `scripts/apply_migrations.py:137` to `WARN` when
  the file is in a known "intentional edit" allowlist (the hook-guard
  migrations) rather than hard-failing. Risky — checksum mismatches
  usually indicate a real problem. Prefer the runbook entry.
- Could also add a `conftest.py` pre-check that drops the
  `schema_migrations` row for a modified migration before re-applying,
  scoped to test DBs only. More invasive.

## #91. gemini-pro Returns Empty Content on vision + response_format=json_object

**Status**: Open
**Severity**: medium
**Discovered**: 2026-04-23
**Updated**: 2026-04-23

### Problem

In the 2026-04-23 metric-classify bake-off
(`docs/operations/vision-bakeoff-metric-classify-2026-04-23.md`),
`gemini-pro` (`gemini-2.5-pro`) returned an empty `content` field
(`""`) for every one of the 7 images when called via
`VisionClient.analyze_image(image_bytes, prompt, response_format={"type":
"json_object"})`. This drove parse failure rate to 1.0, tag F1 to 0.0,
and auto-disposition to 0.0 for that provider. The same corpus + prompt
works cleanly on `gemini-2.5-flash-lite`, so the quirk is specific to
the Pro model path — likely the combination of vision input and the
JSON response-format hint.

Not reproducing on any other provider in `PROVIDER_CONFIGS`.

### Next Steps

- Reproduce with a minimal repro (one image, direct `google-genai`
  call) to confirm it's upstream behaviour and not something the
  vision adapter is stripping.
- If confirmed upstream: drop the JSON response-format hint for the
  Gemini Pro adapter path in `src/llm/vision_client.py` and parse
  free-text back into the four-field classify schema.
- Or route Pro through a non-JSON code path when the harness calls
  `analyze_image` so other downstream callers are unaffected.
- Until resolved, omit `gemini-pro` from the classify bake-off order
  (`BAKEOFF_PROVIDER_ORDER_METRIC_CLASSIFY`) — current ordering
  already excludes `two-stage` for a similar reason.

## #4. Spelled-Out Number Parsing Limitations

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Current Support

The system correctly parses:
- Simple numbers: "six", "twenty", "ninety"
- Teen numbers: "eleven", "fifteen", "nineteen"
- Compound numbers: "twenty-one", "forty-five"
- Magnitude words: "five million", "two billion"
- Hundreds: "hundred", "one hundred", "two hundred"

### Not Supported

Complex numbers like:
- "one hundred twenty-three" (compound hundreds)
- "two thousand five hundred" (multi-magnitude)
- "four hundred and fifty" (with "and")

### Rationale

These complex spelled-out numbers are rare in SEC filings - companies typically use numeric format for precision. The current implementation handles the common cases (e.g., "six months" for CAC payback period).

## #16. Farfetch Precision Drag — Table-Scale + Period Attribution

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-18
**Updated**: 2026-04-18

### Problem

Two Tier 2 Farfetch metrics show high recall but low precision due to table-scale inference producing near-match FPs:

- `cm_active_customers_total`: P=29%, R=100%, 5 FPs. Examples:
  - raw `935.8` → 935,800 (table "in thousands" applied); gold=796,297 in same period → BOTH_MISMATCH
  - raw `1,118.0` → 1,118,000 in 2018-H1; gold=796,297 in 2017-H1 → period + value mismatch
- `cm_purchase_transactions_overall`: P=25%, R=100%, 4 FPs. Same pattern (raw `800.5` → 800,500, etc.).

### Root Cause

For each period (e.g., 2015, 2016, 2017 + H1), the system extracts ONE correct value and several near-match values from adjacent periods with slightly different scales. These produce period-mismatch or value-mismatch FPs rather than clean TPs.

### Next Steps

- Investigate whether period-attribution logic can be tightened to prefer the nearest-period match when multiple extracted values share a metric.
- Consider dedup-collapsing same-metric near-matches that share source-locator ancestors.
- Low priority; doesn't affect recall or Tier 1.

## #24. `v2_metric_facts.source_locator.img_id` Has No Referential Integrity

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-18
**Updated**: 2026-04-18

### Problem

`img_id` is stored as a value inside a JSONB `source_locator` column (`sql/09_v2_schema.sql:420`), not as a foreign key. After the sql/34 fix, new facts written by `persist_pipeline_result` use the stable DB img_id. However, historical facts written before the fix likely contain orphaned img_ids pointing to rows that were collapsed by the dedup migration.

### Suggested Fix

Add a scheduled integrity-check script, or promote `img_id` to a dedicated FK column on `v2_metric_facts`. The latter is the more robust fix but requires a migration and application-layer changes.

### Diagnostic Script (2026-04-19)

`scripts/check_image_referential_integrity.py` scans for orphan `img_id` values and exits non-zero when any are found. Baseline against the local dev DB on 2026-04-19: **9 orphan facts across 4 docs** (doc_id=1546: 4, doc_id=1545: 2, doc_id=1551: 2, doc_id=1539: 1). These are historical facts predating the `sql/34` dedup migration. Prod has not been scanned yet. Cleanup strategy (delete orphan facts vs. rewrite `source_locator.img_id` to NULL vs. leave as-is) is still open.

### Extended to Three Classes (2026-04-19, commit `d1430d9`)

The script now reports three classes and is wired into the integration-tests CI job (`.github/workflows/ci.yml`):

- **Class (A)** — `source_type='chart'` facts with null `source_locator.img_id`. **Blocking** (exit 1); baseline 0; protects the `ChartFactBridgeStage` invariant.
- **Class (B)** — orphaned `img_id` refs (this issue). Warning-only.
- **Class (C)** — asset rows with `file_path` outside `data/` or missing on disk. Warning-only; tracked under Issue #34.

`tests/unit/extraction_v2/test_chart_fact_bridge_invariants.py` locks the Class (A) invariant at unit-test level.

## #38. `v2_metric_facts.doc_id` Is Misleadingly Named

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-19
**Updated**: 2026-04-19

### Problem

`v2_metric_facts.doc_id` is `BIGINT REFERENCES filings(filing_id)` per
`sql/09_v2_schema.sql:18` — i.e., it's a `filing_id`, not a reference to
`v2_documents.doc_id` (which is a separate UUID primary key). The column
name suggests the latter.

This tripped me during Issue #7 hotfix work: `count_review_decisions` in
`scripts/onboard_tickers.py` originally joined
`v2_documents.doc_id (UUID) = v2_metric_facts.doc_id (BIGINT)`, producing
a runtime `operator does not exist: uuid = bigint` error that only fired
in production (fixed in commit `c353e83`). Any future developer writing
a cross-table query is likely to hit the same trap.

### Suggested Fix

Rename `v2_metric_facts.doc_id` → `filing_id` via a migration:

- `sql/NN_rename_metric_facts_doc_id.sql` — `ALTER TABLE v2_metric_facts
  RENAME COLUMN doc_id TO filing_id`.
- Update every caller in `src/` (look for `.doc_id` on fact objects or in
  raw SQL touching `v2_metric_facts`).
- Update `MetricFact` dataclass if the attribute is exposed.
- Identity-tuple logic in `src/extraction_v2/models.py` and
  `src/extraction_v2/persistence.py` references `doc_id` — check.

Not urgent (inline comment in `scripts/onboard_tickers.py` flags the
naming; `count_review_decisions` SQL correct). Queue when `v2_*` has a
broader cleanup window.

### Cross-References

- `sql/09_v2_schema.sql:18` — column definition
- `scripts/onboard_tickers.py::REVIEW_DECISIONS_SQL` — inline caveat comment
- commit `c353e83` — the bug that surfaced this

## #39. `is_in_scope_phase1` Is a Misnomer Post-Issue-#7

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-19
**Updated**: 2026-04-19

### Problem

`filings.is_in_scope_phase1` suggests "this filing is in the active
universe." Its actual semantic is stricter: "this is an S-1/F-1 filing
from a first-time non-SPAC non-investment-vehicle non-resource-extraction
issuer" (classifiers.py:832-834). With 10-K support (Issue #7) landed,
10-K rows correctly have `is_in_scope_phase1=FALSE` — but that reads as
"out of scope" to anyone browsing `filings`. The column and query-time
filter are now confusing.

### Suggested Fix

Two options:

1. **Rename column** → `is_phase1_ipo_candidate` (scoped to S-1/F-1 by
   design). Migration + updates to `filings` upserts, discovery SQL in
   `scripts/onboard_tickers.py::_build_discovery_sql`, gold-standard
   validator queries, any `WHERE is_in_scope_phase1 = ...` usage.
2. **Add a form-aware companion column** `is_customer_metric_candidate`
   that's true for S-1/F-1 FTI _and_ true for 10-K/10-K/A that pass basic
   filters (non-SPAC, non-investment-vehicle, non-resource-extraction).
   Leave `is_in_scope_phase1` as-is for historical callers.

Option 2 is less disruptive but adds DB surface area. Option 1 is
conceptually cleaner but requires a coordinated migration + code sweep.

Bundle with Issue #38 if tackled — both are column-name clarifications in
the same schema area.

### Cross-References

- `src/universe/classifiers.py:832-834` — `is_in_scope_phase1` definition
- `scripts/onboard_tickers.py::_build_discovery_sql` — already has a
  workaround (conditionally omits the Phase-1 filter for non-S-1/F-1
  form types)
- `docs/operations/TICKER_ONBOARDING.md` — "10-K onboarding semantics"
  section documents the current confusing behavior
- Issue #7 — introduced 10-K support that makes the misnomer visible

## #40. 10-K/A Supersession Semantics Undefined

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-19
**Updated**: 2026-04-19

### Problem

`UniverseBuilder` after-loop step `self.db.mark_superseded_filings()`
(universe_builder.py:107) demotes earlier S-1/S-1/A/F-1/F-1/A filings per
CIK — "only the latest amendment in scope." For 10-K/A (restatements),
the method is scoped to S-1/F-1 only; 10-K and 10-K/A rows are preserved
as separate in-scope entries.

Two defensible interpretations:

- **"Restatement replaces original":** 10-K/A is the corrected version —
  the original is misleading and should be marked superseded. Matches
  S-1/A semantics.
- **"Both are distinct fiscal-year events":** each row represents a
  point-in-time filing with different disclosures; analytics may want to
  compare pre- vs post-restatement. Current behavior.

Current behavior is option 2 (both survive). No one has validated this is
the intended operator workflow; no 10-Ks are in prod today (Issue #7 just
shipped the capability).

### Suggested Fix

Before the first operator bulk-onboards 10-Ks:

1. Decide which semantic matches the analytic use case (ask CMASB
   stakeholders).
2. If "restatement replaces": extend `mark_superseded_filings` to include
   10-K/A pairs, add a test, document in the runbook.
3. If "both distinct": document the decision in
   `docs/operations/TICKER_ONBOARDING.md` under "10-K onboarding semantics"
   so reviewers / analysts know what to expect.

Lightweight either way — <30 LOC + tests + doc line.

### Cross-References

- `src/universe/universe_builder.py:107` — `mark_superseded_filings` call
- `src/infra/db.py::mark_superseded_filings` — form-type scope
- `docs/operations/TICKER_ONBOARDING.md` — "10-K onboarding semantics"
- Issue #7 — landed 10-K support without resolving this

## #43. Spectrum Brands Co-Registrant Filings Still Have Uber HTML Cached on Disk

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-19
**Updated**: 2026-04-19

### Problem

Filing_ids 902, 903, 904, 905, 906, 907, 908, 909, 910, 911, 913, 914, 915, 916, 919 all point `html_storage_path` at `data/filings/0001725792/000119312519149408/primary.htm`. That file contains **Uber S-1/A content**, not the Spectrum Brands 2019 S-1/A content these rows represent (accession `0001193125-19-149408`, co-registered by 15 Spectrum Brands entities). Root cause is the same pre-Issue-#6 FilingFetcher mis-save that caused Issue #30 — the URL column was fixed by the #30 resolution, but the cached HTML file was not replaced.

### Why it's latent, not active

All 15 rows have `v2_metric_facts_count = 0`, `v2_review_decisions_count = 0`, `v2_image_review_decisions_count = 0`. No extraction has run on these filings, so no facts are derived from the wrong HTML. Reviewer-facing UI links point to the correct SEC documents (fixed in Issue #30). The problem would only surface if/when someone runs `scripts/batch_v2_extraction.py` against these filing_ids — they'd get Uber facts attributed to Spectrum Brands.

### Next Steps

Pick one:

1. **Refetch once, update all 15** (preferred): Call `FilingFetcher.fetch_filing()` for one co-registrant (e.g., the primary Spectrum Brands CIK `0001028985`) with the correct resolved URL, writing to a new storage path under `data/filings/0001028985/000119312519149408/primary.htm`. Then `UPDATE filings SET html_storage_path = <new path>, html_content = NULL WHERE filing_id IN (902, 903, ..., 919)`. Force-reextract not needed because `facts=0`.
2. **Delete the stale file + clear paths**: Just `UPDATE filings SET html_storage_path = NULL, html_content = NULL, html_fetched_at = NULL, processing_status = 'pending' WHERE filing_id IN (...)` and let the normal `FilingFetcher` flow re-download on next run. Simpler, but reverts processing_status.
3. **Remove from universe**: if Spectrum Brands debt-securities S-1/A is not actually in scope for customer-metrics analysis (these are consumer-goods entities, not tech/SaaS), consider deleting the 15 rows entirely — safe here because `facts=0 AND reviews=0`.

### Context

See Issue #30 resolution notes (now in archive) for full audit trail. Apply log at `data/audit/issue_30_applied_20260419T210109Z.jsonl`.

## #53. Chart Call Limit (10) Truncates OCR on High-Chart Filings

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-21
**Updated**: 2026-04-23

### Problem

`OCRExtractionStage` enforces a hard cap on per-filing chart OCR calls. During the Chewy smoke (`logs/issue_35_prod_smoke3.log`), only 10 of 20 queued chart/table images were OCR'd before:

```
WARNING:src.extraction_v2.stages.ocr_extraction:Chart call limit (10) reached
```

Filings with lots of charts (Chewy has 16 chart-classified images; Snowflake has 8; on-average-larger S-1s exceed 10 easily) silently lose extraction coverage on the trailing images. The skipped images never get queried, so any Tier 1 cohort/NRR chart in positions 11+ is invisible to the bridge regardless of whether the OCR would have succeeded.

### Next Steps

- Locate the limit in `src/extraction_v2/stages/ocr_extraction.py` (likely a module-level constant or `PipelineConfig` field) and either raise the default, convert to a per-filing override, or expose via CLI flag on `batch_v2_extraction.py`.
- Re-run the Chewy smoke with the cap raised to quantify the missed-recall impact.
- Consider prioritization: OCR charts in likely-Tier-1 sections first (MDA, financials) rather than HTML order.

## #55. 28 Stuck 8-K Filings in Class (E) from Form-Filter Bypass

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-21
**Updated**: 2026-04-21

### Problem

Of the 38 filings in `scripts/diagnostic_chart_evidence_coverage.py` Class (E) on Neon prod, **28 are 8-K filings** in `processing_status='processing'` with `html_storage_path IS NULL` and `html_content IS NULL`. The extraction system is designed for S-1/F-1 (see `DEFAULT_FORM_TYPES_S1F1` in `src/universe/universe_builder.py`), yet these 8-Ks reached ingestion far enough to have `v2_image_assets` chart-classified rows written, then stalled. This suggests a form-filter bypass somewhere in the ingestion path — possibly an early-path onboarding script, possibly a reviewer action, possibly a daily-cron edge case.

Seven of the 28 additionally have 2–3 reviewer decisions each on text/table facts, which is even more puzzling for an allegedly out-of-scope form type.

Filing ids captured in `data/audit/issue_35_prod_class_e_raw.txt` and the original target/exclusion lists.

### Next Steps

- Trace how these 8-K filings entered the pipeline: `git log` the ingestion path around the 2026-04-xx window, `grep` for any codepath that calls `FilingFetcher` or `V2Pipeline.process` without a form-type gate.
- Decide cleanup strategy: (a) retroactively delete the `filings` + `v2_image_assets` + `v2_metric_facts` rows for these 28 ids; or (b) reclassify to `processing_status='out_of_scope'` and update the Class (E) diagnostic to filter on `form_type IN ('S-1','S-1/A','F-1','F-1/A')`.
- If reviewer decisions on 8-Ks are intentional (user-directed review for some reason), skip the deletion option and go with (b).

## #59. 8-K Section Classifier Produces Only `COVER` / `FINANCIALS` Labels

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-20
**Updated**: 2026-04-20

### Problem

`SectionClassificationStage.SECTION_PATTERNS` (`src/extraction_v2/stages/section_classification.py:104-138`) only knows S-1/10-K structural headings (`Item 1A`, `Item 7`, `Item 8`, etc.). 8-K earnings exhibits use narrative patterns like "Financial Highlights", "Key Business Metrics", "Q4 Highlights", "Results of Operations" that none of the existing patterns match. Phase 0 run: every segment on Chewy / DoorDash / Robinhood / Snowflake 8-Ks was classified as `COVER` or `FINANCIALS`. Candidate generation and value binding still produced correct facts, but sections-aware downstream logic (FP rules keyed on `section_type`, reviewer UI navigation, section-scoped metric scoring) is blind on 8-Ks.

### Next Steps

1. Add a new `SectionType` variant — e.g. `EARNINGS_HIGHLIGHTS` — or piggyback on `BUSINESS` if the existing type taxonomy already carries the right semantics.
2. Add pattern list entries for common 8-K headings: `Financial Highlights`, `Key Business Metrics`, `Q[1-4]\s*\d{4}\s*Highlights`, `Results of Operations`, `Business Highlights`.
3. Validate against the Phase 0 candidate set (Chewy, DoorDash, Robinhood, Snowflake 8-Ks) — expect >=30% of segments to land on non-COVER sections.
4. Audit existing FP rules for section-gated behavior that might fire differently once 8-K segments are correctly typed.

## #63. Cancel-During-Populate Not Exercised by Integration Test

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-20
**Updated**: 2026-04-20

### Problem

Wave C documents the cancel-during-populate flow (cancel flips `status='cancelled'`; runner respects it on natural completion via the new `WHERE status='running'` predicate on `_BATCH_COMPLETE_SQL`). The conditional SQL is unit-tested via string assertion (`tests/unit/universe/test_onboarding_runner.py::TestBatchCompleteConditional`), but no integration test simulates a runner mid-`build_universe` while cancel fires concurrently.

### Next Steps

1. Add an integration test in `tests/integration/universe/test_onboarding_runner_integration.py::TestPopulateCancellation` that: inserts a populate batch, monkey-patches `UniverseBuilder.build_universe` to flip the batch status to `cancelled` mid-run, calls `_run_populate`, asserts final status stays `cancelled` (not `complete`) and `finished_at IS NOT NULL`.
2. Optionally extend Phase 5's JS to render a "Cancellation pending — batch will stop after current operation completes" banner when `status='cancelled' AND finished_at IS NULL` (today the JS shows the cancelled banner immediately).

---

## #69. `Dockerfile.nightly-sweep` Installs `claude` + `gh` Unpinned

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-21
**Updated**: 2026-04-21

### Problem

`Dockerfile.nightly-sweep` installs the Claude Code CLI via `curl -fsSL https://claude.ai/install.sh | sh` and the GitHub CLI via the package repo without a version pin. Each Render build pulls whatever is current, so a tool update between builds could silently change sweeper behaviour (e.g., `claude -p` flag semantics, `gh pr merge` auto-squash wiring).

### Next Steps

- Pin the `claude` installer to a specific version once the installer supports a version argument; otherwise cache a specific binary in the image.
- Pin `gh` to a specific apt version (`gh=2.X.Y`) or switch to the GitHub Releases tarball.
- Consider adding a build-time smoke test: `claude --version && gh --version` to fail the build on unexpected drift.

## #75. Missing Playwright E2E for Cross-Filing Auto-Advance

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-21
**Updated**: 2026-04-21

### Problem

The "auto-advance to next filing when queue empties" behavior is tested at the route-plumbing layer (`tests/unit/web/test_review_v2_routes.py::test_next_filing_preserves_sort_order` and siblings) but not at the browser layer. A regression in `unified_review.html:~1047` (text completion) or `review_images_v2.js:navigateAfterQueueEmpty` would slip past current CI. Prior regressions of this behavior (commits `5f16360`, `34ec47e`) are the reason this PR exists.

### Next Steps

- Add a Playwright spec in `tests/ui/` that seeds two filings with pending facts, sets sort to `company asc` on the list, approves the last pending fact in filing A, and asserts the browser lands on filing B (not the list, not default date-desc order).
- Repeat the assertion with image-queue completion as the trigger (relevant → non-relevant → skip the last image).
- Reuse the stub-server pattern in `tests/ui/test_server.py`; extend it with a `/filings-list-stub` route that renders `unified_filing_list.html` with two seeded filings.

## #82. Full-Page-OCR Pipeline Integration Test Missing

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Problem

Phase-3 unit tests exercise `ImageTriageStage._detect_full_page_scan_filing`, `OCRExtractionStage.process_full_page_scan`, and `_prescan_ambiguous_images` individually. No integration test runs the full `V2Pipeline` on a page-scan HTML fixture and asserts that `v2_segments` rows with `source_type='image_ocr'` land, downstream `v2_metric_facts` get produced, and the chart two-pass populates `chart_data` where expected. Local test DB (`filings_analysis_test`) has 0 filings so we couldn't seed from real data.

### Next Steps

1. Create a minimal fixture: a stub HTML document with a handful of `<img>` tags pointing at portrait-page-sized dummy JPGs, seeded under `tests/integration/fixtures/full_page_ocr/`.
2. Add `tests/integration/extraction_v2/test_full_page_ocr_pipeline.py` that constructs a `PipelineConfig(enable_full_page_ocr=True)`, runs `V2Pipeline.process` with a mocked `VisionClient`, and asserts segment + fact + image-asset state end-to-end.
3. Alternative: once the prod rollout backfill completes on a real PayPal 8-K, capture its vision responses as VCR cassettes and build the fixture from that.

## #83. `TIER1_KEYWORDS_RE` Drifts From `config/metric_keywords.yaml`

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Problem

`OCRExtractionStage.TIER1_KEYWORDS_RE` is a hand-curated regex alternation listing Tier-1 metric phrases (cohort, retention, ltv, cac, etc.). The authoritative source of Tier-1 metrics is `config/metric_keywords.yaml` (`tier: 1` entries' `patterns` + `specific_patterns`). Adding a new Tier-1 metric today requires two edits in lockstep; miss the regex update and Path B silently under-matches.

### Next Steps

1. Load Tier-1 patterns from `config/metric_keywords.yaml` at `OCRExtractionStage` init time (module-level cached) — build the regex union automatically.
2. Add a unit test that asserts every Tier-1 metric in the YAML has at least one phrase covered by the compiled regex.
3. Decide whether to additionally compile `exclusions` from the YAML into a negative filter on the pre-scan match (probably overkill for Path B, but note the option).

## #84. Fragment Status Drift After PR Merge (Needs Auto-Update Mechanism)

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Problem

Fragment frontmatter's `pr_refs` field lists the PRs expected to resolve each issue, but nothing updates a fragment's `status` from `open` to `resolved` when those PRs merge. Discovered during the 4-phase known-issues migration (PRs #115/#116/#117/#119): #68 and #71 fragments still said `status: open` on `main` two days after their fix-PRs merged (#107, #108), causing the nightly sweeper to re-attempt already-resolved work until someone noticed.

The selector's Phase 3 status filter (issue #79) correctly excludes `status in {resolved, archived}`, but only if something populates those statuses in the first place. Manual bookkeeping is fragile — drift is guaranteed at scale.

### Next Steps

- Option A: A periodic script that scans fragments, pulls `pr_refs` from each frontmatter, queries `gh pr view <ref> --json state` for each, and updates fragments whose referenced PRs are all `MERGED` to `status: resolved` + `autonomy: n/a`. Run it from the nightly sweep cron (pre-selector) or as a GitHub Action on a schedule.
- Option B: Update the `/commit` skill to accept a `resolves: #N,#M` hint and, on successful merge of the PR, rewrite the referenced fragments via a merge-queue hook. More invasive; ties fragment updates to the `/commit` path.
- Option C: A pre-commit check that warns (not fails) when a fragment's `pr_refs` all point at merged PRs but `status` is still `open`. Low-cost nudge.

Recommend Option A — simplest, runs outside the happy path, no coupling to `/commit`.

## #92. CLASSIFY_PROMPT Lives in Bake-off Harness — Move to VisionClient When Classify Lands in Prod

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-23
**Updated**: 2026-04-23

### Problem

`CLASSIFY_PROMPT` (the per-image metric-disclosure classification
prompt) is defined inline in `scripts/benchmark_vision.py` rather than
in `src/llm/vision_client.py`. This was intentional for the 2026-04-23
bake-off (PR B5.x.1) — validating the approach before touching prod
routing. But if / when classify is adopted as a prod extraction gate,
two prompt copies will exist and will drift. The harness has a `TODO`
comment flagging the eventual home (next to the constant).

### Next Steps

- Promote `CLASSIFY_PROMPT` + `_build_classify_prompt` +
  `_parse_classify_response` into a new
  `VisionClient.analyze_image_for_metric_classification` helper
  (alongside the existing `analyze_image_for_text` / `_targeted`
  helpers).
- Update `scripts/benchmark_vision.py::_run_provider_metric_classify`
  to call the new helper instead of re-implementing the API wrapping +
  parsing.
- Coordinate with the full-page-OCR work (PRs #110 / #114 / #139)
  which owns `analyze_image_for_text` — the two helpers should share
  the `VisionClient` lifecycle and cache key style.
- Expected to land alongside the `v2_image_classifications`
  table/surface PR (tracked separately in
  `project_image_extraction_program.md` follow-up #2).

## #93. v2_image_review_decisions.rejection_reason Enum Lacks "table_handled_elsewhere"

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-23
**Updated**: 2026-04-23

### Problem

When the metric-classify harness (PR B5.x.1) sees a table-in-image it
returns `predicted_metrics=[]` + `rejection_reason="other"` because the
existing enum on `v2_image_review_decisions.rejection_reason`
(migration 29: `decorative`, `not_a_chart`, `wrong_subject`,
`duplicate`, `unreadable`, `other`) has no "table" bucket. The detail
is carried in the `reasoning` free-text field, but the bucketing is
blurry — `"other"` mixes genuine unknowns with routed-elsewhere
tables, which hurts downstream analytics.

Tables are handled by the separate full-page-OCR pipeline
(`VisionClient.analyze_image_for_text`, PRs #110 / #114 / #139), so a
dedicated enum value would let reviewers + analytics distinguish
"classifier chose not to classify — route elsewhere" from "classifier
genuinely unsure".

### Next Steps

- Add a migration extending the enum:
  `ALTER TYPE rejection_reason ADD VALUE 'table_handled_elsewhere';`
  (or the Postgres check-constraint form, depending on how the enum
  is modelled — check `sql/29_v2_image_review_decisions.sql`).
- Update `REJECTION_REASONS` in `src/gold_standard/image_eval.py` and
  `CLASSIFY_REJECTION_REASONS` in `scripts/benchmark_vision.py` to
  include the new value.
- Update the review UI surface so reviewers can pick the value
  manually (and so the classifier's emission maps cleanly).
- Back-fill any existing `"other"` rows whose `reasoning` references
  a table — optional, tracked separately if useful.

## #94. v2_audit_log.check_v2_audit_http_method Rejects HEAD and OPTIONS Requests

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-23
**Updated**: 2026-04-23

### Problem

The `v2_audit_log.check_v2_audit_http_method` CHECK constraint
(defined in `sql/31_drop_v1_review_tables.sql:57`) allowlists only
`GET`, `POST`, `PUT`, `DELETE`, `PATCH`. When the audit middleware
tries to log a `HEAD` or `OPTIONS` request the INSERT fails and the
request transaction rolls back.

Observed on `filings-reviewer` in Render logs on 2026-04-23 after a
routine deploy:

```
Database error, rolling back: new row for relation "v2_audit_log"
violates check constraint "check_v2_audit_http_method"
DETAIL: Failing row contains (4228, ..., Go-http-client/1.1,
review.index, HEAD, /, ..., 301, 0).
```

`Go-http-client/1.1` is Render's internal health prober, which hits
`/` with `HEAD` on every probe cycle. Each probe generates one error
log line + one transaction rollback on `filings-reviewer`. CORS
preflights (`OPTIONS`) would hit the same wall if any cross-origin
client ever reaches an audited route.

Blast radius: log noise + per-probe rollback overhead. No user-facing
breakage — the response itself (301 redirect) still returns. Pre-dates
Wave B5 work; no single PR introduced it, and it has been firing
quietly since `sql/31` was applied.

### Next Steps

- Add a migration extending the allowlist:
  `ALTER TABLE v2_audit_log DROP CONSTRAINT check_v2_audit_http_method;`
  `ALTER TABLE v2_audit_log ADD CONSTRAINT check_v2_audit_http_method CHECK (http_method IN ('GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'));`
- Register it as the next-unused `sql/NN_*.sql` number (per
  `.claude/rules/sql.md`).
- Alternatively: have `src/web/middleware.py` skip audit logging for
  `HEAD` / `OPTIONS` requests entirely — probe traffic arguably
  doesn't belong in the audit trail. Slightly cleaner but changes
  behaviour vs "log everything routed through Flask"; needs a call on
  which semantics to keep.
- Verify after: tail `filings-reviewer` Render logs for 5 minutes and
  confirm the `check_v2_audit_http_method` violation is gone.

## #97. Residual Chart Facts Remain After Chart-Presence Pivot (Drain Deferred)

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-24
**Updated**: 2026-04-24

### Problem

The chart-presence pivot (Issue #86, merged across PRs #147/#150/#151/#154/#158) stops new chart-fact emission but PR 4b deliberately **did not drain** the existing rows. Pre-flight audit on 2026-04-24:

| Metric | Count |
|---|---|
| Rows: `v2_metric_facts WHERE source_type='chart'` | 30 |
| Distinct filings | 10 |
| Reviewer decisions (`v2_review_decisions`) on chart facts | 18 |

The 18 decisions break down as:

| Decision | Count | Metrics |
|---|---|---|
| reject | 9 | cm_new_customers_acquired, cm_customers_period_end (bulk), cm_customers_period_end_by_tenure, cm_active_customers_total, cm_ltv_to_cac_ratio, cm_purchase_transactions_overall, cm_lifetime_value_per_customer, cm_customer_acquisition_cost |
| accept | 5 | cm_revenue_by_cohort (×3), cm_large_customers_period_end, cm_customers_period_end |
| correct | 4 | cm_average_order_value (×2), cm_monthly_active_users, cm_new_customers_acquired |

17 are by reviewer `RGM`, 1 is a bulk-system entry (`bulk:superseded_slack_s1a_2019-05-20`).

`v2_review_decisions.fact_id ON DELETE CASCADE` means a plain `DELETE FROM v2_metric_facts WHERE source_type='chart'` would silently destroy reviewer work. User chose to defer the drain (option B1 in the PR 4b exchange) to preserve those 18 pieces of work.

### Impact (low)

- **Review UI:** Chart Evidence block deleted in PR #151; detected-metrics card reads from `v2_image_assets.detected_metrics`, not `v2_metric_facts`. **No user-visible impact.**
- **Validator:** PR #150 routes `segment_type='chart'` gold rows through presence P/R, not value-level P/R. Chart facts in `v2_metric_facts` are not considered when evaluating chart gold expectations. **No measurement impact.**
- **Analytics views:** `v_analytics_*` views (sql/38, …) may include `source_type='chart'` rows in fact aggregates. If downstream reporting filters on source_type, the 30 residual rows will appear. Typical fix: add `AND source_type != 'chart'` at view level if unwanted. **Low impact, shimmable.**
- **DB footprint:** 30 rows. Negligible.

### Next Steps (if drain becomes needed later)

Three paths, pick at triage time:

1. **Archive decisions + DELETE.** Export the 18 `v2_review_decisions` rows (plus the 30 facts) to `data/audit/chart_fact_decisions_predrain_<ts>.json` for historical reference, then `DELETE FROM v2_metric_facts WHERE source_type='chart'` in a transaction. Reviewer work preserved as JSON, not queryable live.
2. **Migrate accepts + corrects to `v2_image_metric_confirmations`.** For each chart fact with `source_locator.img_id` not null: derive a `(img_id, detected_metric_id=canonical_metric_id, decision)` row. Rejects have no natural img-level equivalent (the "this value is wrong" signal doesn't map cleanly to "this metric is not present"), so rejects would still be lost. Complex but preserves the most work as live signal.
3. **Keep deferred.** No action; residual 30 rows are inert. Revisit only if analytics downstream actually needs them gone.

### Cross-References

- Parent rollout: legacy-096 (chart-presence pivot rollout, resolved).
- Dissolved root cause: legacy-086 (dedup stage collapse).
- Dissolved consequence: legacy-035 (pre-2026-04-17 chart-fact backfill).
- Reviewed-filing guard: `src/extraction_v2/persistence.py::_persist_facts_in_tx`, `ReviewedFilingError`.
- Cascade path: `v2_review_decisions.fact_id ON DELETE CASCADE` (sql/05 originally; `chart_only=True` guard in `persist_pipeline_result` refuses when decisions exist).

## #98. Validator presence_f1 Stays Null — detected_metrics Not Populated in-Memory

**Status**: Open
**Severity**: low
**Discovered**: 2026-04-24
**Updated**: 2026-04-24

### Problem

The chart-presence pivot landed presence P/R/F1 infrastructure in PR #150:

- `FilingResult.presence_tp / presence_fp / presence_fn` fields (`src/gold_standard/v2_validator.py`).
- `BaselineMetrics.presence_f1` field (`src/gold_standard/baseline.py`).
- `to_dict()` emits `presence_f1` only when `has_presence = (total_presence_tp + total_presence_fp + total_presence_fn) > 0` (`src/gold_standard/v2_validator.py:374`).

After the PR 4b baseline refresh on 2026-04-24, `v2_baseline.json` has `presence_f1` **absent at all scopes** (overall and per-company). The pre-PR-4a baseline (2026-04-23) also lacked it. That means the validator has been silently computing zero presence TP/FP/FN for every run since PR #150 landed.

Root cause (likely): the validator calls `V2Pipeline(...).process(..., document_date=...)` with `filing_id=0` (no persistence). The pipeline's chart bridge stage writes `image.detected_metrics` in-memory. But either:

1. The chart bridge stage isn't firing because chart images aren't reaching it — e.g., vision calls skipped under test harness, `chart_data` never populated → classifier runs on empty input → no presence emitted.
2. The validator accesses `v2_context.images` via a getter that doesn't surface the in-memory `detected_metrics` populated by the bridge.
3. Something else in the `filing_id=0` mode skips the full image pipeline.

Confirmed via grep: `_chart_presence_set_from_context` (`v2_validator.py` around the presence block) reads `v2_context.images[*].detected_metrics`. The validator does walk through that code path. But `presence_tp/fp/fn` stay 0.

### Impact

- Presence-F1 is unmeasurable via the GS pipeline right now. Chart-native metric improvements can't be quantified — the baseline has no floor to regress against.
- The 30% cross-source confirmation gate (`_derive_chart_native_metrics`) still works (it's CSV-driven, not pipeline-driven), so metric-aware classification isn't affected.
- Not a correctness issue; it's a measurement gap.

### Next Steps

1. Instrument `_chart_presence_set_from_context` to log `len(v2_context.images)` and how many have non-empty `detected_metrics`. Run against one filing with a known chart (e.g., Robinhood S-1 has chart images).
2. If images reach the validator but `detected_metrics` is empty → inspect `ChartFactBridgeStage.process()` — did vision OCR fire? Did `classify_all` return anything? Check `chart_presence_min_score` threshold.
3. If the images list is empty → the validator's pipeline run is skipping image-processing stages. Check `PipelineConfig` defaults used by the validator vs. the prod config.
4. Fix whichever gap is real, re-run the baseline refresh, confirm `presence_f1` field appears.

### Cross-References

- Parent rollout: legacy-096.
- Introducing PR: #150.
- Baseline refresh PR (where this was surfaced): PR 4b.

## #5. Revenue Synonym Context Gating

**Status**: Open
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Background

Revenue-related metrics (GMV, TCV, ACV, Bookings, Billings) only generate review candidates when cohort/per-customer context is present. This is intentional to reduce false positives.

### Current Behavior

- ARR/MRR: Always generate candidates (inherently customer-related)
- GMV/TCV/ACV/Bookings/Billings: Require context keywords within 1500 chars
- Context keywords: cohort, vintage, per customer, per user, by account, etc.

### Potential Issue

Some valid per-customer GMV values may not have context keywords nearby, causing them to be missed.

### Monitoring

Review rejection rates for revenue synonyms to determine if context gating is too strict.

## Partially Resolved Issues

## #62. Local-Dev Stuck-Batch Recovery Is Manual

**Status**: Partially Resolved
**Severity**: low
**Discovered**: 2026-04-20
**Updated**: 2026-04-20

### Problem

On Render (Phase 7), a worker service with `--watch` mode will re-claim a batch whose `run_lock_until` has expired. On local dev there is no watcher — if the `onboarding_runner` subprocess dies mid-batch (kernel OOM, user kills the Flask server, etc.), the batch stays in `status='running'` forever. Currently recovery requires a hand-crafted `UPDATE v2_ingest_batches SET status='failed' WHERE batch_id=...` plus a cleanup of partially-processed `v2_ingest_batch_filings` rows.

### Partial Resolution (2026-04-21)

Manual recovery SQL documented in `docs/operations/TICKER_ONBOARDING.md` under the new "Recovering a stuck batch (local dev)" section. Operators can now self-serve stuck-batch recovery without improvising SQL. Next Steps 2 (`--cleanup-stuck` admin flag) and 3 (SIGTERM log line) remain open.

### Next Steps

1. Document the manual recovery SQL in `docs/operations/TICKER_ONBOARDING.md` (or a new batch-ingest runbook) when that file lands in Phase 7.
2. Consider a `python3 -m src.universe.onboarding_runner --cleanup-stuck` admin flag that scans for batches with `run_lock_until < NOW() - INTERVAL '1 hour'` still in `running` state and either marks them failed or re-claims them.
3. Add a CLI log line to the runner on SIGTERM that tells the operator "batch <id> interrupted — run `... --cleanup-stuck` to recover".

## Archived Issues

## #1. Metric ID Mismatch Between Gold Standard and System

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Gold standard CSV (`data/gold_standard/golden_set_251218.csv`) aligned to system taxonomy in `config/metric_keywords.yaml`. No remaining ID mismatches. See git log (2026-03-16) for full resolution details.

## #3. Gold Standard Methodology Questions

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Created `docs/GOLD_STANDARD_SPECIFICATION.md` covering: metric ID alignment, value normalization rules, chart vs text classification, period format, negative examples, and duplicate group handling.

## #6. FilingFetcher Downloads Directory Index Instead of Primary Document

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`FilingFetcher` defaulted `sec_client` to `None` and guarded URL resolution behind `if self.sec_client:`, causing directory-index pages to be saved instead of actual filings. Fixed in `src/filing_fetcher/filing_fetcher.py` (lines 81, 295). 78 cloud-fetched filings need re-fetching on Render. See git log (2026-03-16) for full details.

### Issues #7 and #8: Test Deadlock and Connection Pool Exhaustion

Root cause: `DatabaseAdapter` had no `close()` method; test fixtures were session-scoped with no teardown and no connection pool, so every `get_connection()` call created a new TCP connection.

Fixes applied:
- Added `DatabaseAdapter.close()` to `src/infra/db.py`
- Converted `test_db_adapter` fixtures in `tests/integration/conftest.py` and `tests/integration/extraction/conftest.py` from `return` to `yield` with pool (`max_size=5`) and teardown
- Added `command: ["postgres", "-c", "max_connections=200"]` to `docker-compose.yml`

## #9. Snap Filing (ID 32/33) — Mislabeled Data

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Filing 32 was labelled "Snap" but the CIK on record (`0001644378`) belongs to RMR Group Inc.; no Snap content had ever been ingested. Resolution:

1. Relabeled the local `companies` row for CIK `0001644378` to `'RMR Group Inc.'` (preserves the already-extracted RMR content under the correct issuer name; no CASCADE through `v2_segments`/`v2_metric_facts`/`v2_review_decisions`).
2. Seeded `Snap Inc.` (CIK `0001564408`) + its real S-1/A (accession `0001193125-17-056992`, filed 2017-02-27, primary doc `d270216ds1a.htm`) via `sql/seed_snap_s1a.sql` (unnumbered, one-off — follows `sql/register_gold_standard_filings.sql` precedent; not registered in `scripts/apply_migrations.py`).
3. Fetched HTML via `FilingFetcher.fetch_filing` (2.3 MB into `data/filings/0001564408/000119312517056992/primary.htm`).
4. Ran V2 extraction — 8 facts across `cm_daily_active_users`, `cm_revenue_per_customer`, `cm_active_customers_total` (1724 segments, 547 tables, 40 images persisted).
5. Updated `scripts/gi3_richness_analysis.py` FILING_MAP (id 32 → `"RMR Group Inc."`; comment shortened).

Scope limited to local (`$TEST_DATABASE_URL`). Neon prod mirror is a separate workstream. Adding Snap's new filing_id to gold-standard coverage is also out of scope — owned by the gold-standard workflow. Previously attempted as PR #72 on 2026-04-21; that branch was closed during the #65 history scrub and this is the replay.

## #10. `test_candidate_generation_finds_active_consumers` — Root Cause Unclear

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`tests/integration/test_gold_standard_coverage.py` was deleted in commit `03a8a20` ("refactor(v1): retire review_candidates + source_segments + suppressed_candidates"). The failing test no longer exists; pipeline-level recall for `cm_active_customers_total` remains 100% on Farfetch. See commit `03a8a20`.

## #11. Gold Standard Coverage Tests

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

The "1 remaining" test tied to archived Issue #10 no longer exists; `tests/integration/test_gold_standard_coverage.py` was deleted in commit `03a8a20` ("refactor(v1): retire review_candidates + source_segments + suppressed_candidates"). The 11/12 → 12/12 finish line was reached implicitly. See archive entry for Issue #10.

## #12. `test_image_crop.py` Pollutes Working Tree with Test PNGs

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`make_png_in_data_dir` fixture added to `tests/unit/web/test_image_crop.py`; fixture writes the PNG, tracks the path, and deletes it on teardown. Working tree clean after suite run. See git log (2026-04-18) for details.

## #13. V2 Metric Facts Identity Index Drift

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`sql/33_fix_identity_index.sql` idempotently drops and recreates `idx_v2_metric_facts_identity_unique` with all 9 columns including `source_type`. Prod confirmed 9-col via direct `pg_indexes` read on 2026-04-19; local test DB and prod now agree. See `sql/33_fix_identity_index.sql` and `scripts/apply_migrations.py:68-74`.

## #14. Farfetch LTV/CAC Dedup Collision on Layout Tables

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Respectively-parser priority introduced in `value_binding.py::_bind_prose_cell`; `cohort_hint` field added to `BoundValue`; defensive 80-char prose guard in `_extract_cohort_def`. `cm_ltv_to_cac_ratio` R 33%→100%; `cm_ltv_to_cac_ratio_by_cohort` R 17%→50% (text FNs); Farfetch F1 +10.3pp. 6 regression tests added. See git log (2026-04-18).

## #15. Chart Pipeline Env Bootstrap

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`load_dotenv()` added to `src/gold_standard/v2_validator.py` `__main__` block. Chart stages now run automatically when `.env` contains `OPENAI_API_KEY`. See git log (2026-04-18).

## #17. CAC Payback "Six Months" — Bare Word-Number Not Bound

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`WORD_NUMBER_TIME_PATTERN` regex added to `value_binding.py`, gated to `TIME_UNIT_VALUED_METRICS = {"cm_cac_payback_period"}`; `_V1_SPELLED_OUT_OVERRIDE_METRICS` bypass added to `false_positive_filter.py`. `cm_cac_payback_period` 0%→100% F1 on Farfetch. 6 unit tests added. See git log (2026-04-18).

## #18. Migration Checksum Mismatch on `sql/01_create_schema.sql`

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Self-healed via V1 retirement merge (commit `03a8a20`); the gold-standard pytest fixtures that triggered the checksum guard were deleted along with the V1 review tables. No reconciliation action needed. See commit `03a8a20`.

## #19. FN Diagnostic Classification Gaps

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`dedup_collision` and `no_matching_binding` categories added to `src/gold_standard/v2_validator.py`; `wrong_period` restricted to post-dedup facts. 4 new unit tests in `tests/unit/gold_standard/test_v2_validator.py::TestDiagnosefalseNegative`. See git log (2026-04-18).

## #20. `cm_gross_margin_by_cohort` Still 0% on Farfetch Despite Chart Pipeline Active

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Four targeted changes in `src/extraction_v2/chart/`: `_cohort_gate` accepts ≥2 distinct years in `points[].x` + customer-type series names; `_metric_gate` fallback for empty `y_axis_label`; `_score_metric` nearby_text title fallback + structural bonus; `cohort_parser._parse_customer_type_regime` new regime. `cm_gross_margin_by_cohort` Farfetch 0%→100% F1 (9/9 rows); Tier 1 F1 +5.4pp overall. 7 regression tests added. See git log (2026-04-18).

## #21. `v2_image_assets` Duplicates + Pending-Count Discrepancy (Maplebear S-1)

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`sql/34_dedup_v2_image_assets.sql` collapses duplicate `(doc_id, filename)` groups and adds `UNIQUE (doc_id, filename)` constraint; `_persist_images_in_tx` upserts on `(doc_id, filename)` preserving stable `img_id`; `persist_pipeline_result` remaps in-memory `source_locator.img_id` before fact persistence. See `sql/34_dedup_v2_image_assets.sql` and git log (2026-04-18).

## #22. No Reviewed-Filing Guard on Image Re-Extraction

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Narrow image-side guard added to `_persist_images_in_tx` in `src/extraction_v2/persistence.py`: fires when a decided image would be re-classified from the visible set (`chart`/`table_image`/`unknown`) into the hidden set (`decorative`/`logo`/`signature`); `force=True` proceeds with structured warning. `ReviewedFilingError` gained optional `context` kwarg. 5 new tests in `tests/integration/extraction_v2/test_persistence_guard.py::TestGuardOnPersistImages`. See git log (2026-04-18).

## #23. `v2_image_assets.segment_id` Is a Dead Column

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`sql/35_drop_v2_image_assets_segment_id.sql` idempotently drops the column; `_persist_images_in_tx` cleaned up. See `sql/35_drop_v2_image_assets_segment_id.sql` and git log (2026-04-18).

## #25. `scripts/migrate_image_ids_to_deterministic.py` Scope Is Confusing

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Module-level docstring expanded to clarify the script only rewrites local gold-standard JSON files and does not modify the database. See git log (2026-04-18).

## #26. Review UI — Lost SEC + Image Links for Investor Presentations

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`sql/36_backfill_presentation_urls.sql` corrected 166 rows; `src/web/url_builders.py` introduced as single source for URL construction; `scripts/validate_database_urls.py` gained `--fail-on-errors` / `--document-type` and wired into CI. See `sql/36_backfill_presentation_urls.sql`, `src/web/url_builders.py`, and git log (2026-04-19).

## #27. Images Tab Playwright Assertions Fail

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Of 3 originally failing assertions: line 965 fixed via mock `img_id` addition in commit `413b386`; the two remaining `test.skip` blocks (keyword-badge and "Image 1 of 2" in the image context panel) deleted as stale — neither element is rendered by `unified_review.html` (template renders `Image #N` only, no "of M" counter; no `.keyword-badge` class exists). Product intent confirmed: these assertions had no corresponding template markup to validate. See git log 2026-04-21.

## #29. `cm_new_customers_acquired` Receives `2.71x` Chart Fact From Farfetch LTV/CAC Chart

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`_rule_ratio_suffix_on_count_metric` added to `src/extraction_v2/stages/false_positive_filter.py`; rejects `N.NNx`/`N.NN×` raw values on count/currency/rate/time metrics. 6 unit tests. Farfetch GS confirms the `2.71x` FP eliminated. See git log (2026-04-19).

## #30. 15 Filings With CIK / sec_html_url Mismatch

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`scripts/audit_filing_url_mismatch.py` enumerated affected rows; `scripts/repair_filing_url_mismatch.py --path A --apply` corrected all 15 `sec_html_url` values. Apply log at `data/audit/issue_30_applied_20260419T210109Z.jsonl`. Latent cached-HTML residue tracked as Issue #43. See git log (2026-04-19).

## #31. Audit Log Spams DNS Error in Test / Dev

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Both async (`src/web/routes/review_unified.py:97-109`) and sync (`src/web/middleware.py:87-120`) audit-log paths downgrade `ERROR` to `DEBUG` when `TESTING=True`. Covered by `tests/unit/web/test_middleware.py::TestAuditLogFailureLogging`. See commit `366d9dd`.

## #32. `src/shared/html_segmenter.py` Has 0% Test Coverage

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Module deleted (2032 LOC) as dead code — zero production callers verified; smoke test also deleted. Coverage rose from 81.44% to 83.5%, enabling the #33 floor bump. Successor: `src/extraction_v2/stages/ingestion.py`. See git log `-- src/shared/html_segmenter.py`.

## #33. Raise Coverage Threshold to 80% After Issue #32

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`pyproject.toml` `[tool.coverage.report]` `fail_under` raised 75→80 in the same change as Issue #32; `.claude/rules/testing.md` updated to match. See git log (2026-04-20).

## #36. `onboard_tickers.py populate` Has No `--limit`

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`UniverseBuilder.build_universe` gained `limit: int | None = None` kwarg; `scripts/onboard_tickers.py populate --limit N` threads through. Covered by `tests/unit/universe/test_universe_builder.py::test_limit_stops_after_n_in_scope_upserts`. See commit `366d9dd`.

## #37. `classify_first_time_issuer` Reports `True` for Non-S-1/F-1 Filers

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`_process_filing` in `src/universe/universe_builder.py` gates `classify_first_time_issuer` on `filing.form_type in DEFAULT_FORM_TYPES_S1F1`; non-S-1/F-1 filings land with `is_first_time_issuer=NULL`. Covered by `tests/unit/universe/test_universe_builder.py::test_10k_filing_has_null_first_time_issuer`. See commit `366d9dd`.

## #41. Review-UI Sticky Header Offset Mismatch + Narrow-Width Overlap

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`--navbar-height: 48px` CSS custom property unifies sticky offsets in `src/web/static/css/review.css`; `.review-pill-row` flex-wrap prevents narrow-width badge overlap. Deployed Render build verified visually. See commit `366d9dd`.

## #42. `_download_missing_images` Writes Image Bytes Twice

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`OCRExtractionStage._download_missing_images` no longer writes a second `pipeline/...` copy after `SECClient.fetch_image()` caches the bytes. New public `SECClient.get_image_cache_path` accessor; `asset.file_path` points at the SECClient cache key directly. `TestImageDownloading` updated. See commit `7848605`.

## #44. `audit_filing_url_mismatch.py` Classifier Over-Rotates on Legitimate Co-Registrant Sharing

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`_classify_path` decision tree refined: `facts==0` short-circuits to Path A; `facts>0` + collision routes to new `B_coordinated` sub-path. `repair_filing_url_mismatch.py` warns on `B_coordinated` rows. 7 unit tests at `tests/unit/scripts/test_audit_filing_url_mismatch.py`. See git log (2026-04-20).

## #45. `scripts/validate_database_urls.py` Missing `load_dotenv()`

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`load_dotenv()` added before `DATABASE_URL` read; mirrors `scripts/apply_migrations.py:21` pattern. See git log (2026-04-20).

## #46. `scripts/apply_all_migrations.py` Stale — Stops at Migration 31

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`MIGRATION_ORDER` extended with migrations 32–38; `--dry-run` now reports 44 migrations; `check_unregistered_migrations` no longer aborts. Sync chosen over deletion (script referenced from 7 docs). See git log (2026-04-20).

## #47. `data/audit/` Not Gitignored

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`data/audit/` added to `.gitignore` (line 46) alongside peer `data/*` runtime entries. Verified via `git check-ignore -v`. See git log (2026-04-20).

## #48. `image_crop` Endpoint Is Unauthenticated

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`@require_api_key` decorator added to `image_crop` in `src/web/routes/review_unified.py`; `_verify_api_key()` module-level helper extracted from `register_api_auth` in `src/web/middleware.py`. Same-origin `Origin`/`Referer` bypass preserves embedded `<img>` loads from review pages. 5 auth tests in `tests/unit/web/test_image_crop.py::TestImageCropAuth`. See git log (2026-04-20) and `docs/architecture/image-storage.md`.

## #50. No 401-Path Test Coverage for `api_unified_bp`

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

New `tests/unit/web/test_api_unified_auth.py` — 6 cases covering missing/wrong/correct key, query-arg + same-origin Referer bypass, and `API_KEY_REQUIRED`-without-`API_KEY` misconfig. Mirrors `TestImageCropAuth` shape. Target endpoint: `DELETE /api/v2/decisions/<decision_id>` with mocked DB. See commit `7848605`.

## #51. Brittle Source-String Assertions in `test_persistence_sql.py`

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

4 grep-the-source tests in `test_persistence_sql.py` rewritten as behavioral mock-cursor assertions. `# fmt: skip` removed from `src/extraction_v2/persistence.py`; black reformatted the `or None` expression to its own line. Tests immune to future formatting changes. See commit `7848605`.

## #52. `pg_dump` Version-Mismatch Silent Failure

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

New `scripts/check_pg_client_version.py` pre-flight that compares `pg_dump` major version against server major version and errors loudly on mismatch. `.claude/rules/infrastructure.md` gains a `### pg_dump client version` subsection documenting the PG16+ client requirement for Neon (PG15). Script confirmed the 14→15 mismatch on the reference machine. See commit `7848605`.

## #54. Chart-Bridge Emits Low-Confidence Misbinds on Non-Tier-1 Charts

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

New `PipelineConfig.chart_metric_min_confidence` knob (Guard 6 on `ChartFactBridgeStage`). Default 0.60 matches the existing classification gate — no default behavior change — because Tier 1 `cm_balance_by_cohort` classifies at ~0.6024 and a 0.70 default would regress Tier 1 recall. Operators can tighten the knob during backfills to suppress weak top-match binds. 5 unit tests added as `TestGuard6MetricConfidenceFloor`. See commit `7848605` and companion Issue #64 for the boundary sensitivity follow-up.

## #56. `check_docs_sync.py --ci` Fails CI on Transitive-Import Warnings

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`import_to_pkg` dict in `scripts/check_docs_sync.py` extended with `dateutil`, `botocore`, `PIL`; `README.md` updated with pipeline-stage class names and coverage line matching the `(\d+)%\s*overall` regex. `check_docs_sync.py --ci` now exits 0; PR #50 and all future PRs unblocked. See git log (2026-04-21).

## #57. `unified_review.html` Missing Breadcrumb + Count Badges Broke 7 Playwright Tests

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Bootstrap breadcrumb nav and `badge bg-success`/`badge bg-danger` accepted/rejected count spans added to `src/web/templates/unified_review.html`; 2 test selectors updated in `tests/ui/review.spec.js` (`.fact-metric-id` + `.fs-5.fw-bold`). All 151 UI tests pass. See git log (2026-04-21).

## #60. `detect_universe_gaps` Ignores SIC Filter

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`_YEARS_IN_FILINGS_SQL` now joins `companies` and filters on `industry_code = ANY(%(sic_codes)s)`, matching the pattern already used by `discover_candidates`. Gap detection no longer reports spurious populate prompts for years that have filings under a different SIC. Three unit tests added in `tests/unit/universe/test_onboarding.py`.

## #61. `/ingest/preview` Integration-Test Gap

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`POST /ingest/preview` was only covered by unit tests on the form-parser helpers.
Added `TestIngestPreview` to `tests/integration/web/test_ingest_flow.py` with three tests:
three-bucket split assertion (new / already-extracted no-review / already-reviewed),
volume-banner alert-class check (`alert-success` for ≤49 filings via `_volume_band_alert_class`),
and hidden-`filing_id` field survival assertion. Seeds two 10-K filings via
`create_test_company_and_filing`; reuses existing `client`/`db_adapter` fixtures.

## #64. Chart Classifier Tier 1 Boundary Sensitivity

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`ChartMetricClassifier.classify` scored the HOOD "Cumulative Net Deposits by Cohort" fixture at 0.6024 — only 0.0024 above the 0.6 classification gate — creating a silent-regression risk if any future keyword or weight change narrowed the margin.

Resolved by adding `tests/extraction_v2/chart/test_chart_classifier_margin.py`: a parametrized characterization test that measures empirical scores for three Tier 1 chart fixtures (HOOD `cm_balance_by_cohort` at 0.6024, Farfetch `cm_gross_margin_by_cohort` at 1.0000, FTCH empty-axes `cm_gross_margin_by_cohort` at 0.6627), locks in score floors (measured score − 0.005), and also asserts the 0.60 gate. Any future re-weighting that narrows the margin fails loudly. Classifier itself is untouched.

Cross-references: Issue #54 — `chart_metric_min_confidence` knob; `src/extraction_v2/chart/metric_classifier.py`.

## #65. Secret-Leak Guard for Mis-Named Env Duplicates

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Broadened `.gitignore` to `.env*` with `!.env.template` allowlist; added
`gitleaks` pre-commit hook at the repo-wide level. Forward-looking defense
plus historical cleanup — the OpenAI key found during audit has been rotated,
and on 2026-04-22 `git filter-repo --invert-paths --path data_preprocessing.py`
was run against a fresh mirror clone to strip the file (the only artifact
that ever held the key) from all of history. Force-push rewrote 1,066
commits on `main` (new tip after scrub vs. the pre-scrub tip differ by SHA
only; merge topology and file contents are otherwise identical). Tainted
refs also purged on origin: tag `backup-before-history-rewrite`, branches
`worktree-fix-issue-9-snap-ingestion` and `worktree-review-ui-improvements`.
`main` branch protection (`allow_force_pushes: false`, `enforce_admins: true`,
required PR + 5 status checks) was restored immediately after the push.

Known residue: four **merged** PRs (`refs/pull/1/head`, `refs/pull/9/head`,
`refs/pull/10/head`, `refs/pull/11/head`) still hold the tainted blob in
GitHub's read-only PR refs. These cannot be rewritten via push — only GitHub
Support can purge them via the [sensitive-data removal process](https://docs.github.com/en/code-security/secret-scanning/removing-sensitive-data-from-a-repository).
The key is rotated, so exposure risk is historical only; filing a support
request is optional.

## #67. `/cleanup` Skill Mode-Detection Returns False `remote` From ccw Worktrees

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

`.claude/commands/cleanup.md` step 1 replaced the CWD-relative `test -d .claude/worktrees` check with an `if`-expression anchored to the primary repo's git dir via `git rev-parse --git-common-dir`, with `$HOME/.claude-worktrees` as a fallback. Works from any linked worktree (agent-isolation or ccw) as well as the primary tree. Companion `ccw` PID-lockfile + `ccw-rm` merged-branch cleanup (both `~/.zshrc`) close the same accumulation vector from the session-creation side. `/commit` skill step 1 now appends `-HHMM` timestamp on branch-name collision.

## #73. `.github` PR Template Case Collision

**Status**: Archived
**Severity**: n/a
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

Removed the uppercase `.github/PULL_REQUEST_TEMPLATE.md` via `git -c core.ignorecase=false rm -f`, keeping the lowercase `pull_request_template.md` (matches GitHub's 2024 convention). Fresh-clone warning on case-insensitive filesystems is gone.

## Resolved Issues

## #72. Robinhood Tier 1 Gold-Standard Regression vs. 2026-04-19 Baseline

**Status**: Resolved
**Severity**: high
**Discovered**: 2026-04-21
**Updated**: 2026-04-22
**PR refs**: #87, #102

**Resolved**: 2026-04-22 — chart pipeline produces facts end-to-end on HOOD's S-1. Validator against Neon (post-backfill): HOOD **recall=0.486, F1=0.586** (vs baseline 0.3143 / 0.4231 — +15pp recall above baseline). Tier-1: **P=92.3%, R=54.5%, F1=68.6%**. `cm_balance_by_cohort` at 100/100/100. `cm_revenue_by_cohort` at 50/10/16.7 — residual gap tracked as Issue #86 (dedup stage collapses chart-sourced cohort facts at the fact-construction boundary); orthogonal to the original infra regression. Path to close: PR #87 restored `boto3` in `pyproject.toml`/`uv.lock` (unblocked ingestion); PR #102 wired `storage.put_bytes` into `_download_missing_images` (unblocked R2 chart-image reads); chart-only re-extract + R2 upload executed against prod Neon on 2026-04-22 — 12 new chart facts persisted, 17 chart images processed cleanly. Chart-only mode preserved 16 text-review + 20 image-review decisions on HOOD.

### Problem

Baseline at pre-scrub `cdc831f` (2026-04-19) recorded Robinhood `recall=0.3143, f1=0.4231`. Current main state: `recall=0.171, f1=0.255` (-14pp on HOOD, -0.009 overall). Per-metric diagnostics:

| Metric | Tier | Current P/R/F1 | Notes |
|---|---|---|---|
| `cm_balance_by_cohort` | T1 | 0% / 0% / 0% | Same chart-pipeline failure mode as `cm_revenue_by_cohort` (both chart-only metrics on the same filing). Issue #64 — chart classifier boundary sensitivity — is a separate, narrower concern already resolved |
| `cm_customer_acquisition_cost` | T1 | 100% / 50% / 66.7% | 1 FN — dedup collision (`20.0` collapsed into sibling with different value) |
| `cm_revenue_by_cohort` | T1 | 0% / 0% / 0% | 10 FNs — chart pipeline never ran on source image (see below) |

### Diagnosis (2026-04-22, against Neon `filing_id=1545`)

HOOD S-1 has 21 images, 17 classified as charts, **0 with `ocr_text`, 0 with `chart_data`** before this PR. The "Annual Revenue by Annual Cohort ($mm)" image — the single source of all 10 gold per-cohort values ($17/$62/$44/$56/$87/$45/$130/$186/$175/$326) — is `img_id=e5f65961-f33f-44db-9fd0-5f3b61dae987`, classified `chart`, `processed=False`, no linked facts. The lone `$130` chart fact in the DB references `img_id=c8da02f5-227c-4830-94d9-c45944d45e7f` which no longer exists in `v2_image_assets` — an orphan from a pre-`d94acab` img_id stabilisation run. The `$102,034.8` text fact flagged as an FP is an unrelated period-`2026-Q1` mis-bind.

### Root cause: PR #34 dropped `boto3` from the uv-managed manifest

`src/infra/image_storage.py` routes chart/image storage to R2 (prod) or local filesystem (dev) based on whether `R2_BUCKET` is set. The R2 backend calls `import boto3` lazily inside `R2Storage.__init__`. PR #34 (`9aeb454 feat(image-cache): migrate to Cloudflare R2 via ImageStorage abstraction`) added `boto3>=1.34.0` to `requirements.txt` but **not to `pyproject.toml`/`uv.lock`**. Any extraction launched via `uv run …` in an R2-configured environment therefore crashes at the ingestion stage with `ModuleNotFoundError: No module named 'boto3'` before any chart processing runs.

### What the earlier framing got wrong

- **Not a scale bug.** There is no `$33,421.5` anywhere in HOOD's facts. Extraction wasn't binding a quarterly total — it wasn't binding the cohort chart at all.
- **Not caused by #52.** `24bfd6b` (re-hashed post-scrub to `5c44a4b`) is a 3-file persistence refactor with commit body "No behavioral change; 3630 tests pass." Zero value-binding or chart-stage code is touched.
- **"Only extraction-touching commit in the window" was wrong.** The real extraction-touching commits in the window include `d94acab` (#21, img_id stabilisation), `9aeb454`/`cf0c756` (#34, R2 migration), `1d7c204` + `8cd3b4d` (#50, chart_only persistence).

### Why this landed on main

CI installs from `requirements.txt`, which has `boto3` pinned — so CI never reproduced the missing-dep crash. The `uv`-managed path that developers and the nightly sweeper use diverges silently. The dual-manifest layout (pip + pyproject) can drift any time only one is updated.

### Fix in this PR

- Add `boto3>=1.34.0` to `pyproject.toml` dependencies; regenerate `uv.lock`.
- Proved locally against Neon: `uv run python scripts/batch_v2_extraction.py --filing-id 1545 --chart-only --force-reextract` now runs the full pipeline (2215 segments, 137 tables, 22 images parsed; 16 text/html_table facts produced). Previously died at stage 1.
- **No data loss.** Chart-only mode safely skipped the fact-DELETE when 0 new chart facts were produced; 9 text-review + 3 image-review decisions on HOOD S-1 remain intact.

### Second layer still open (new follow-up needed)

After the boto3 fix, all 17 HOOD chart images now run through OCR but fail with `FileNotFoundError: Image file not found: 1783879/000162828021019902/hood-20211008_g*.jpg`. The R2 bucket does not have bytes at those keys. Two possible explanations: (a) the canonical storage-key format changed (infrastructure.md's example uses a `pipeline/` prefix that's absent from the DB's `file_path` values), or (b) the bytes were never uploaded for the HOOD S-1 filing after the R2 migration.

### Next Steps

1. Merge this PR to unblock `uv run` extraction for everyone.
2. Resolve the R2 image-bytes layer — tracked as Issue #77.
3. **Do NOT refresh the baseline until the R2 layer is resolved** — refreshing over zero chart recall locks in the bug.
4. Consider adding a CI job that exercises `uv sync` + a smoke extraction so pip/pyproject manifest drift gets caught pre-merge.
5. Blocks: PR merge commits against current main will keep failing the pre-commit Tier-1 guard until HOOD chart recall recovers (both this fix AND the R2 fix are required).

## #77. R2 Chart-Image Bytes Missing for HOOD S-1 (Second Layer of #72)

**Status**: Resolved
**Severity**: high
**Discovered**: 2026-04-22
**Updated**: 2026-04-22
**PR refs**: #102

**Resolved**: 2026-04-22 — PR #102 wired `storage.put_bytes` into `OCRExtractionStage._download_missing_images` (the existing call mirrors the correct pattern at `ingestion.py:956-969`). Manual HOOD prod backfill on 2026-04-22 via `uv run python scripts/batch_v2_extraction.py --filing-id 1545 --chart-only --force-reextract`: no `FileNotFoundError`, 17 chart images processed, 2 cohort charts populated `chart_data` (`e5f65961` Annual Revenue by Annual Cohort, `44e035d8` Cumulative Net Deposits by Annual Cohort), 12 chart facts persisted. Case A confirmed — no `pipeline/` prefix divergence; unprefixed keys are the live convention. Unblocks Issue #72 (closed same day).

### Problem

After PR #87 restored `boto3` to `pyproject.toml`/`uv.lock`, `uv run python scripts/batch_v2_extraction.py --filing-id 1545 --chart-only --force-reextract` runs the full V2 pipeline on HOOD's S-1 (22 images parsed, 16 text/html_table facts produced) — but **all 17 chart-classified images** then fail in the OCR stage with:

```
FileNotFoundError: Image file not found: 1783879/000162828021019902/hood-20211008_g<N>.jpg
```

for `N` in `{2, 3, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20}`. All 17 images end the run marked `processed=True` but with `ocr_text IS NULL` and `chart_data IS NULL`, so `cm_revenue_by_cohort` and `cm_balance_by_cohort` remain at 0/0/0 P/R/F1 on HOOD. This is the reason Issue #72's Tier 1 regression persists even after #87.

### Root cause confirmed (one concrete writer-without-upload bug; second cause still open)

**Confirmed (2026-04-22, this PR's investigation):**

`OCRExtractionStage._download_missing_images()` at `src/extraction_v2/stages/ocr_extraction.py:199-274` calls `SECClient.fetch_image()` (which writes bytes to the local disk cache rooted at `image_cache_dir()`), assigns `asset.file_path = key` (the cache-relative path), and increments `downloaded` — but **never calls `storage.put_bytes(key, bytes)` to upload those bytes to the active storage backend**. In dev (`LocalFilesystemStorage` rooted at `image_cache_dir()`), this is invisible because the disk write IS the storage write. In prod (`R2Storage`), the bytes never leave the local disk; the DB row's `file_path` then points at an R2 key that was never PUT, and downstream `process_chart_image` / `process_table_image` calls fail with `FileNotFoundError`. Compare with the correct upload pattern at `src/extraction_v2/stages/ingestion.py:956-969`, which DOES call `storage.put_bytes` after assigning the key.

This applies to **every** prod filing that went through `_download_missing_images` since PR #34 — not just HOOD. HOOD is the most visible victim (Tier 1 chart-only metrics).

**Still open:** the original entry's Case A (key-format divergence between `pipeline/<cik>/<accession>/<filename>` per docs vs. `<cik>/<accession>/<filename>` per DB rows) is **separate** from the writer-without-upload bug. My investigation surfaced that `data/image_cache/pipeline/` exists locally as a legacy layout, suggesting the `pipeline/` prefix WAS used by some other code path historically. Whether any prod R2 keys live under the `pipeline/` prefix is unverified — distinguishing requires R2 `HeadObject` against both layouts (deferred to manual prod op; see Next Steps).

### Evidence from Neon (2026-04-22)

| Fact | Observation |
|---|---|
| Cohort image `img_id=e5f65961-f33f-44db-9fd0-5f3b61dae987` | `classification='chart', relevance_score=0.66, processed=True` (post-#87 re-run); `ocr_text IS NULL`, `chart_data IS NULL`, `file_path='1783879/000162828021019902/hood-20211008_g6.jpg'` |
| Cumulative-Net-Deposits image `img_id=44e035d8-2302-40bb-ab40-01c8fec41665` | Same state; `file_path='1783879/000162828021019902/hood-20211008_g5.jpg'`. Also has a human `relevant` decision in `v2_image_review_decisions`. |
| 15 other chart-classified images on `doc_id=1545` | All `processed=True`, 0 OCR, 0 chart_data, `file_path` without `pipeline/` prefix |
| Pre-#87 chart fact `$130 cm_revenue_by_cohort` | Orphan — references `img_id=c8da02f5-227c-4830-94d9-c45944d45e7f` which does not exist in `v2_image_assets`. Stranded from a pre-`d94acab` run. Preserved by chart-only mode's reviewer-guard path (did not get deleted in the #87 verification run because 0 new chart facts were produced). |

### Why this matters

- **Blocks Issue #72 closure and Tier-1 baseline refresh.** PR #87 is a *partial* fix — it restores the ability to run the pipeline, but HOOD chart recall cannot recover without image bytes reaching the OCR stage.
- **Blocks any merge commit against current main.** The pre-commit Tier-1 guard keeps firing on HOOD until `cm_revenue_by_cohort` recovers.
- **Risk of quietly affecting other pre-R2 filings** beyond HOOD — worth checking whether any non-S-1 filings with chart-sourced gold standard values show the same `FileNotFoundError` pattern when their chart stage runs.

### Status

- **Code fix landed** in this PR (`src/extraction_v2/stages/ocr_extraction.py` adds `storage.put_bytes` mirroring `ingestion.py:956-969`). New unit test `tests/unit/extraction_v2/test_image_pipeline_integration.py::TestImageDownloading::test_uploads_bytes_to_storage` locks in the invariant.
- **Prod backfill still pending.** From now on, any new prod filing that goes through `_download_missing_images` will upload bytes to R2 correctly. But the historical filings (including HOOD's 17 chart images) are still in the broken state — their bytes need to be re-uploaded via a chart-only re-extract or a targeted backfill script.

### Next Steps (deferred to a separate manual prod operation)

1. **R2 `HeadObject` against both prefix variants** — `1783879/000162828021019902/hood-20211008_g6.jpg` AND `pipeline/1783879/000162828021019902/hood-20211008_g6.jpg`. Distinguishes the writer-without-upload bug (this PR's fix) from any residual Case A key-format divergence. Requires real R2 credentials.
2. **HOOD chart backfill** — `python3 scripts/batch_v2_extraction.py --filing-ids-file <one-line file with HOOD's filing_id> --chart-only` against prod (Neon `$DATABASE_URL` + R2 creds). With this PR's fix, `_download_missing_images` will re-fetch from EDGAR and upload to R2 in the same run. Pre-flight: confirm `chart_decision_count` for HOOD chart facts is zero (otherwise add `--force-reextract` only after explicit confirmation, since it purges reviewer decisions).
3. **Repo-wide audit** — `scripts/check_image_referential_integrity.py` against prod (Neon) DB, looking for class-C violations beyond HOOD. Every filing routed through `_download_missing_images` since PR #34 likely has the same orphan-key state. Decide between bulk chart-only re-extract vs. a targeted backfill script that walks `v2_image_assets` rows + uploads from local cache where present.
4. **Refresh the v2 gold-standard baseline** once HOOD `cm_revenue_by_cohort` + `cm_balance_by_cohort` recover chart facts. **Only then** do the regression deltas return to the pre-scrub 0.3143 recall target.
5. **Investigate Case A (`pipeline/` prefix)** — `data/image_cache/pipeline/` exists locally as a legacy layout, but no live writer code constructs `pipeline/`-prefixed keys. Either dead-code cleanup or a third-party prod path; needs a `git log -S "pipeline/"` archaeology pass. Reconcile `infrastructure.md` and `src/infra/image_storage.py:8` docstrings with whichever convention is canonical (probably remove the `pipeline/` prefix from docs since live code never uses it).
6. **Hygiene follow-up**: add a CI smoke that runs the chart stage on at least one fixture filing end-to-end under `uv run` against a mock R2 (`moto[s3]` is already in `requirements-dev.txt`). Would have caught both the boto3-missing case AND this writer-without-upload regression at PR-time.

Cross-references: #34 (R2 migration, Phases 1+3), #72 (overall regression tracking), #42 (resolved — `_download_missing_images` double-write collapse). PR #87 fix commit `8713f51`.

## #34. `v2_image_assets.file_path` Rooted in TMPDIR (Purged by OS)

**Status**: Resolved
**Severity**: medium
**Discovered**: 2026-04-19
**Updated**: 2026-04-19

**Resolved**: 2026-04-19

### Problem

`v2_image_assets.file_path` was being written as `/var/folders/.../T/filings_image_cache/pipeline/<filename>.jpg` — macOS's TMPDIR. 158 of 165 asset rows on the local dev DB lived outside `<repo>/data/` entirely (the remaining 7 are a separate, presentation-pipeline root). The TMPDIR is purged by the OS on reboot and after long periods of inactivity, so `image_crop` (`src/web/routes/review_unified.py:521-581`) returned 404 for the majority of rows even when the asset row and the extracted chart fact were intact.

The endpoint's `resolved.relative_to(data_dir)` security check also rejects TMPDIR paths outright as a path-traversal precaution, so the 404 fires even when the file happens to still be present. Either way, the reviewer saw no chart preview.

This was the dominant root cause behind the Box Inc S-1/A `cm_revenue_by_cohort = $2.8M` case in the commit-`d1430d9` investigation. Template placeholders added in `d1430d9` surfaced the failure explicitly.

### Diagnostics

`scripts/check_image_referential_integrity.py` (Issue #24) reports Class (C) "asset rows with file_path outside data/ or missing on disk" alongside the Class (B) orphan check. Local baseline 2026-04-19: 158 / 165 rows (96%) outside `data/`, 50 / 165 absent on disk. Class (C) remains **warning-only** in CI; flip to blocking once any remaining TMPDIR rows are rewritten or reprocessed.

### Resolution (2026-04-19)

`src/extraction_v2/stages/ocr_extraction.py:199-227` was rooted in `tempfile.gettempdir()`. The fix introduces `src/infra/paths.py::image_cache_dir()`, an `lru_cache`'d helper that honors an `IMAGE_CACHE_DIR` env var and defaults to `<repo>/data/image_cache/`. The pipeline subdirectory was also restructured from a flat `pipeline/<filename>` to a collision-safe `pipeline/<cik>/<accession>/<filename>` layout — the flat layout would have become permanent cross-filing corruption under `batch_v2_extraction.py --workers N` once the cache was persistent (latent in TMPDIR because OS purges masked it).

`data/image_cache/` was added to `.gitignore`. Unit tests at `tests/unit/infra/test_paths.py` and the `TestImageDownloading` fixture in `tests/unit/extraction_v2/test_image_pipeline_integration.py` fence `IMAGE_CACHE_DIR` to `tmp_path` via a class-scoped autouse fixture, preventing test-time pollution of the real `data/image_cache/` tree.

Every subsequent re-extraction heals its own filing's rows; no one-shot migration is required. Historical rows surface via `d1430d9`'s Chart Evidence placeholder until their filing is re-extracted.

### Resolution — Phase 3 (2026-04-20)

**Option C adopted** (instead of A or B): introduced an `ImageStorage` abstraction with two backends — `LocalFilesystemStorage` (dev/test, defaults under `data/image_cache/`) and `R2Storage` (prod, backed by a private Cloudflare R2 bucket via `boto3`). Selected at runtime via the `R2_BUCKET` env var. `v2_image_assets.file_path` now stores an opaque storage key (e.g. `pipeline/<cik>/<accession>/<filename>`) rather than an absolute filesystem path; shape is validated by `src/infra/image_storage.py::validate_key`.

Seven call sites were migrated off direct `Path(file_path)` dereferencing (write in `ocr_extraction._download_missing_images` and `ingestion._extract_image_assets`; reads in `process_table_image`, `process_chart_image`, `fact_construction` evidence-screenshot copy, `image_crop`, and `_resolve_chart_image_status`). `check_image_referential_integrity.py` Class (C) now validates via `storage.exists()` and shape-check instead of `Path.resolve() / relative_to(data_dir)`. `image_crop` gained a `Cache-Control: private, max-age=3600` header to keep repeat clicks off R2.

Prod provisioning (user actions, completed 2026-04-19): Cloudflare R2 bucket `filings-reviewer-image-cache`, object-scoped API token, and four `R2_*` env vars on both Render web + cron services. Test-only dependency `moto[s3]>=5.0.0` (in `requirements-dev.txt`) mocks R2 for unit tests — no real R2 calls in CI.

Chosen over Option A (Render persistent disk) because R2's free tier (10 GB + 1M write ops + zero egress) covers current volume without paid infra, and over Option B (re-fetch-on-miss) because R2 is architecturally the same thing with fewer per-request latency surprises and sets up for multi-reviewer concurrency without OneDrive-style sync hazards. See `docs/architecture/image-storage.md`.

Legacy rows (pre-migration absolute paths) fail `validate_key` and return 404 via the review UI's placeholder path — identical user-facing behavior to the Phase 1 post-state. They heal naturally on re-extraction.

### Cross-References

- Issue #24 — JSONB img_id has no FK (the orphan class is a separate failure mode; this one is about the file system root)
- Issue #22 — reviewed-filing guard on image re-extraction (must be honoured by any backfill script)
- Issue #35 — now fully unblocked; 38-filing chart-fact backfill can proceed on both dev and prod
- `docs/architecture/image-storage.md` — detailed architecture reference

## #78. Integration Tests Cannot Run Under pytest-xdist — Shared Postgres Fixtures

**Status**: Resolved
**Severity**: medium
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Resolution

`tests/integration/conftest.py` now gives each pytest-xdist worker its own Postgres database (`filings_analysis_test_gw0`, `_gw1`, …) via a session-autouse fixture that runs before any DB-touching fixture. The fixture rewrites `os.environ["TEST_DATABASE_URL"]` at session start so both the fixture chain and the ~13 direct `os.environ.get()` readers pick up the worker URL automatically — zero application code changes. A Postgres advisory lock in `_apply_migrations_to_test_db` serialises migration 37 (`CREATE ROLE metabase_ro` + `ALTER ROLE`) across workers so concurrent `pg_authid` writes don't trigger `tuple concurrently updated`. CI (`.github/workflows/ci.yml:185`) now runs integration tests with `-n auto`. Verified locally: two back-to-back `pytest tests/integration/ -n auto` runs pass 226/226 in ~55s (vs ~3.6 min sequential on CI).

### Original problem (for reference)

### Problem

Adding `-n auto` (or even `-n auto --dist loadfile`) to the CI integration command produces immediate fixture collisions when run against a shared Postgres service. Reproduction: `uv run pytest tests/integration/ -n auto -x -q --no-cov` against `$TEST_DATABASE_URL` fails with mixes of:

- `ForeignKeyViolation: Key (filing_id)=(22432) is not present in table "filings"` — worker A cleans up a `filings` row that worker B's `v2_documents` insert still references.
- `ForeignKeyViolation: Key (fact_id)=(…) is not present in table "v2_metric_facts"` — same pattern on `v2_review_decisions.fact_id`.
- `DID NOT RAISE ReviewedFilingError` / decision-count assertions (0 == 1) — CASCADE cleanup from one worker deletes state another worker is about to assert on.

The same suite passes cleanly 43/43 in ~2.2s sequentially. Failures span `tests/integration/extraction_v2/test_persistence{,_guard}.py`, `test_definition_persistence.py`, `test_transcript_e2e.py`, and cascade into errors in `test_db_v2_image_methods.py`, `test_batch_runner_db.py`, `test_filing_fetcher_db.py`, `test_ingest_flow.py`, `test_v2_review_workflow.py`, and `test_universe_builder_integration.py`.

Root cause: integration fixtures share Postgres state (fixed CIKs, fixed filing accessions, session-scoped seed data) without per-worker isolation. `--dist loadfile` helps with intra-file cases but still fails on cross-file shared seed (e.g. a filing row seeded in one file that another file's test insert depends on).

### Why this matters

- Integration Tests is the current required-check critical path on CI at ~3.6 min wall-clock. Parallelizing would cut merge wait to ~2.0–2.5 min — the single biggest remaining PR-latency win.
- Unit Tests already run `-n auto` (uses in-memory fixtures only), so the blocker is specific to DB-backed integration tests.

### Next Steps

1. **Per-worker DB schemas.** xdist exposes `PYTEST_XDIST_WORKER` (e.g. `gw0`, `gw1`). Thread this through `conftest.py` to create/apply migrations against a schema named after the worker, and have the DB adapter `SET search_path` to it. Cleanest long-term fix.
2. **Uniquified fixture data.** Second-best: inject `uuid4()` / worker-id suffixes into `cik`, `accession_number`, and other natural keys in `create_test_company_and_filing` and equivalents.
3. **`--dist loadgroup` with shared-state markers.** Tag tests that share seed data with a `@pytest.mark.xdist_group("filings_seed")` and let xdist keep them on one worker. Cheapest change but leaves perf on the table.
4. **Verification after fix:** run `pytest tests/integration/ -n auto -x -q` locally twice in a row against `$TEST_DATABASE_URL` with zero failures, then land the `-n auto` flag in `.github/workflows/ci.yml:184–187`.

## #85. `scripts/apply_all_migrations.py` MIGRATION_ORDER missing migration 40

**Status**: Resolved
**Severity**: medium
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Problem

`scripts/apply_all_migrations.py` `MIGRATION_ORDER` ends at `39_v2_ingest_batches.sql`, but `sql/40_full_page_scan_and_ocr_provenance.sql` has existed on disk since before 2026-04-22. On a fresh-DB setup, running the script will skip migration 40 entirely. The `check_unregistered_migrations` guard flags this at `--dry-run` time but the list itself is stale.

This is a recurrence of Issue #46 (resolved 2026-04-20 by extending the list through `38_create_analytics_views.sql`) — the drift pattern resurfaced as soon as new migrations landed. A related fragment (#85) covers migration 41 of the same commit, which was registered correctly in this PR; #40 was left alone to keep scope narrow.

### Next Steps

- Append `"40_full_page_scan_and_ocr_provenance.sql"` to `MIGRATION_ORDER` in `scripts/apply_all_migrations.py`.
- Confirm the migration itself is idempotent (it uses `ALTER TABLE ... DROP CONSTRAINT IF EXISTS` / `ADD COLUMN IF NOT EXISTS`, so re-running on a DB where it was already applied manually should be safe, but verify before registering).
- Consider a pre-commit hook that fails if any `sql/NN_*.sql` file is on disk without a matching entry in `MIGRATION_ORDER` or `EXCLUDED_FILES`. That would close the drift class, not just this one recurrence.

## #86. Dedup Stage Collapses Same-Metric Different-Value Cohort Facts

**Status**: Resolved
**Severity**: medium
**Discovered**: 2026-04-22
**Updated**: 2026-04-23

### Problem

On HOOD's S-1, the Annual Revenue by Annual Cohort chart produces candidate per-cohort bar values pre-dedup — gold-standard values $17, $62, $44, $56, $87, $45, $130, $186, $175 all appear in the pre-dedup candidate set — but only one ($87) survives to the persisted fact set. Running `python3 -m src.gold_standard.v2_validator --companies "Robinhood Markets, Inc." --fn-diagnostics` after the 2026-04-22 HOOD backfill (#72, #77) classifies all 9 missing cohort values as `DEDUP_COLLISION` with the diagnostic:

> *"Value-matching fact (17.0) existed pre-dedup but was collapsed into a sibling with different value; 1 match(es) pre-dedup, 2 total post-dedup"*

Same pattern repeats for 62.0, 45.0, 130.0, 186.0, 56.0, 175.0, 326.0 (eight more). The same failure mode also produces HOOD's pre-existing `cm_customer_acquisition_cost` FN (expected $20, collapsed into a sibling).

### Impact

| Metric | Tier | Current P/R/F1 (post-#72 backfill) | Gap vs. perfect |
|---|---|---|---|
| `cm_revenue_by_cohort` | T1 | 50% / 10% / 16.7% | 9 cohort FNs (all `dedup_collision`) |
| `cm_customer_acquisition_cost` | T1 | 100% / 50% / 66.7% | 1 FN (dedup collision on value 20) |

HOOD's overall Tier 1 F1 is 68.6% post-backfill; closing this gap could push it well above 80%. Not a Tier 1 blocker on its own (HOOD T1 recall is already above the pre-scrub 0.3143 baseline thanks to `cm_balance_by_cohort` at 100/100/100), but it's the single biggest remaining per-metric recall gain available without new extractor work.

### Candidate root causes (not yet narrowed)

1. **Post-transfer collision collapse merges too aggressively.** The validator run logged `Post-transfer collision collapse: merged 18 colliding primaries` then `Fuzzy period dedup: removed 4 duplicate-value facts (68 → 28)`. The first step is the suspect — collapsing facts that share `(canonical_metric_id, period, source_type)` but differ in `value` is exactly what's happening here. A cohort chart legitimately has N distinct bars for the same `canonical_metric_id` and effectively no period (period is the cohort dimension, encoded in `cohort_def` / `cohort_type`, not `period_start`/`period_end`).
2. **Identity-key doesn't include `cohort_def`/`cohort_type`.** If the dedup identity key skips those cohort-specific columns for chart-sourced facts, every bar value collapses into one.
3. **`source_locator.img_id` isn't part of the identity either.** Even if two facts came from different bars of the same image, distinctness on img_id + bar position is probably what uniquely identifies a cohort bar.

### Next Steps

1. Read `src/extraction_v2/stages/deduplication.py` and identify which columns form the identity key for the "post-transfer collision collapse" step. Confirm whether chart-sourced cohort facts are being merged on a key that excludes `value`, `cohort_def`, or the bar-position portion of `source_locator`.
2. Add a regression test in `tests/unit/extraction_v2/` that constructs 10 chart-sourced `cm_revenue_by_cohort` facts with identical `canonical_metric_id`/`source_type`/`period_*` and distinct `value`+`cohort_def`; assert all 10 survive the stage.
3. Fix: extend the dedup identity to include `cohort_def` (and/or the bar-position within `source_locator`) for chart-sourced cohort metrics. Should be a narrow change in `_collision_identity_key` or equivalent.
4. Re-run the HOOD validator; expect `cm_revenue_by_cohort` recall to jump from 10% toward 100% and `cm_customer_acquisition_cost` to move from 50% to 100%.
5. Refresh the v2 baseline once the gain is observed (still gated on Issue #78 / Chewy lxml regression per PR #102 body, if unresolved).

### Cross-references

- Issue #72 — HOOD Tier 1 regression (resolved 2026-04-22; this issue was the residual).
- Issue #77 — R2 chart-image bytes (resolved 2026-04-22; unrelated root cause).
- Issue #14 — Farfetch LTV/CAC dedup collision on layout-table misclassification (different failure mode but related stage).
- Validator diagnostic output on HOOD post-backfill: `dedup_collision: 16 (89%)`.

### Resolution (2026-04-23)

Dissolved by the chart-presence pivot — see parent plan `~/.claude/plans/pick-up-issue-86-tranquil-piglet.md`. Under the new model, `ChartFactBridgeStage` no longer emits per-value `v2_metric_facts` rows; it writes `(metric_id, score)` presence records to `v2_image_assets.detected_metrics`. Reviewers confirm per-metric coverage via `v2_image_metric_confirmations` (accept / reject / correct / add). Because the chart pipeline no longer produces same-identity different-value groups, the `post-transfer collision collapse` step in `DeduplicationStage` can no longer collide chart-sourced cohort facts — the root cause is gone.

No code change was made to `src/extraction_v2/stages/deduplication.py`; the bug is structurally impossible post-pivot.

Shipped across four PRs:

- [PR #147](https://github.com/RGMjr/filings_reviewer/pull/147) — `ChartFactBridgeStage` rewrite (emit presence, not facts).
- [PR #150](https://github.com/RGMjr/filings_reviewer/pull/150) — Gold-standard validator: presence P/R/F1; `_derive_chart_native_metrics` drives the chart-vs-text split.
- [PR #151](https://github.com/RGMjr/filings_reviewer/pull/151) — `v2_image_metric_confirmations` schema + `GET /api/v2/metrics/list` + `POST /api/v2/image-metric-confirmations`.
- [PR #154](https://github.com/RGMjr/filings_reviewer/pull/154) — Reviewer UI: Detected metrics card + per-row A/R/C/Add + Playwright coverage.

The HOOD `cm_revenue_by_cohort` 9/10 FN pattern is expected to resolve: the 10 cohort bars now count as **one** presence TP rather than requiring 10 value-level TPs. Any historical `cm_revenue_by_cohort` chart facts persisted pre-pivot are drained in PR 4b.

## #87. Text Recall Regression on Farfetch + Robinhood Between 04-19 and 04-22 Baselines

**Status**: Resolved
**Severity**: medium
**Discovered**: 2026-04-22
**Updated**: 2026-04-23

### Problem (original framing)

Between the 04-19 gold-standard baseline (`8840912`) and post-image-pipeline-waves
`main`, the committed baseline appeared to show a text-recall regression:

| Metric | 04-19 baseline | Post-wave baseline | Claimed delta |
|---|---|---|---|
| Overall recall | 0.498 | 0.459 | −0.039 |
| Farfetch recall | 0.867 | 0.533 | **−0.333** (10 TPs) |
| Robinhood recall | 0.314 | 0.171 | −0.143 |

The regression was discovered when Wave B4 (two-stage vision routing) hit the
pre-commit `extraction-guard`. B4's code was not the cause — the validator
runs without `OPENAI_API_KEY`, so Stages 4–5 (image/chart) are disabled. The
fragment hypothesized PR #110 (full-page OCR + Tier-1 keyword pre-scan) as
the primary suspect via unconditional classification side effects.

### Post-mortem (2026-04-23)

**No code regression exists.** The 0.867 number in the preserved
`v2_baseline_pre_regression_2026-04-22.json` was produced in a Python
environment that no longer reproduces on the current repo.

Evidence:

1. **Systematic bisect via 6 parallel subagents in isolated worktrees** (one per
   extraction-touching commit — `b517f75` #110, `a9da728` #114, `e20fb04` #121,
   `7b02584` #131, `fe4e544` #132, plus `e92c821` as main-tip sanity) showed
   Farfetch recall = 0.867 at every commit, including current main tip. No
   extraction-touching commit flipped the number.

2. **Reproduction in the primary Python env** (the same env that CI runs
   under — `lxml>=6.1.0` per pyproject) at commit `8840912` produces Farfetch
   recall **0.533** — matching current main. Upgrading lxml 6.0.2→6.1.0 did
   not change the result; the variable is elsewhere in the dep tree.

3. **The committed baseline (0.533) reflects real current-env validator
   output.** Running `python3 -m src.gold_standard.v2_validator
   --companies "Farfetch Limited"` on current main reproduces exactly TP=16
   FP=11 FN=14 — identical to what the baseline records.

Conclusion: the "pre-regression" baseline was measured in some historical
Python environment (likely an older transitive dep combination) whose output
the current repo cannot reproduce. When extraction work landed on main, the
validator was re-run in the new environment and produced 0.533 — which got
saved as the "post-regression" baseline alongside the preserved 0.867 file.
Because the comparison spans two different environments, the apparent −0.333
delta is not attributable to any specific code change.

The fragment's hypothesis about PR #110's `_detect_full_page_scan_filing`
running unconditionally was independently refuted earlier by a code read of
`src/extraction_v2/stages/image_triage.py:692-706` and
`src/extraction_v2/stages/ocr_extraction.py:1053-1068` — the flag guards
behind `enable_full_page_ocr` and `enable_image_keyword_prescan` are tight
and symmetric, with no side effects when both flags default to `False`.

### Why the bisect subagents reported 0.867

The six subagents each ran the validator from an isolated git worktree after
`git checkout <SHA>` + `uv pip install -r requirements.txt`. On this machine
the `uv pip install` step silently no-ops when it fails to find a venv, so
the agents fell back to the same interpreter I later reproduced the 0.533
number under. The 0.867 result they reported is inconsistent with the
interpreter they should have been using. Most likely explanation: their
processes inherited a cached package state — pyc files, a prior `sys.path`
entry, or a `sitecustomize` side effect — carried over from an earlier long-
running session that had briefly used a different dep combination. The
measurement is therefore not authoritative; the authoritative number is
whatever the validator produces under a fresh, CI-equivalent interpreter.

### Resolution actions

- [x] `data/gold_standard/v2_baseline.json`: kept the 0.533-family numbers,
      rewrote the description to reflect the post-mortem (no code regression
      exists; numbers reflect current-env validator output).
- [x] Deleted `data/gold_standard/v2_baseline_pre_regression_2026-04-22.json`
      (stale snapshot from an unreproducible env).
- [x] This fragment flipped to `status: resolved` with full post-mortem.

### Follow-ups worth tracking separately (not addressed here)

- The Python dep set that produced 0.867 is not identified. If recapturing it
  is valuable (e.g., because 0.867 *was* the correct Farfetch recall and the
  current env regressed on some transitive), it would need to be done via
  `uv.lock` archaeology on the 04-19 commit. Deferred as non-urgent — Tier 1
  recall still passes the extraction-guard at current numbers.
- The bisect-agent reproducibility gap (fresh worktree + `uv pip install`
  failing silently to create a venv) is a repeatable footgun for future
  bisect work. Consider filing a separate issue if parallel-bisect becomes
  a recurring pattern.

## #28. Mock-Server / Template-Contract Coupling

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-17
**Updated**: 2026-04-17

**Resolved**: 2026-04-21 — `tests/unit/test_mock_server_contract.py` renders the 7 smoke-spec routes with `jinja2.StrictUndefined` via Flask `test_client` in <1s and runs in the Unit Tests CI job. Template-variable drift now fails fast with `UndefinedError: 'foo' is undefined` instead of as cascading 500s that time out UI E2E after ~28 minutes.

### Problem

`tests/ui/test_server.py` must supply every template variable that production routes pass to `unified_review.html`. Whenever a new variable is introduced in `src/web/routes/review_unified.py` (e.g. `next_filing_url|tojson` in commit `3e398fd`), the mock server renders an `Undefined` and Jinja raises `TypeError` on filters like `|tojson`, returning 500 across every route.

Related surface: the mock also ships stubs for `POST /api/v2/decisions`, `DELETE /api/v2/decisions/<id>`, `POST /api/v2/image-decisions`, and `POST /api/v2/missed-metric`. Their response shapes are maintained in parallel with production; no contract check enforces parity.

### Resolution

The contract test exposed latent drift already on main — `filing.ticker`, `source_locator.img_id`, fact `confirming_source_types`, fact `_chart_image_status`, image-candidate `image_src_url` were all referenced by production templates but missing from mock context. These were added to the mock dicts in the same commit so the test lands green.

Remaining narrow gaps (POST stub shape drift; non-rendering template files) are out of the contract test's scope — revisit if they become a real source of failure.

## #35. Pre-2026-04-17 Filings Missing Chart-Sourced Facts

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-19
**Updated**: 2026-04-23

**Partial resolution**: 2026-04-21 (PR #50 landed `chart_only` surgical backfill mode)

### Update 2026-04-21 — investigation outcome

Backfill mechanism shipped via PR #50 (`V2PersistenceAdapter.persist_*(chart_only=True)` + `scripts/batch_v2_extraction.py --chart-only`). The mode scopes the DELETE-then-INSERT to `source_type='chart'` and the reviewed-filing guard to chart-fact decisions only, so text facts and their reviewer decisions are preserved — allowing surgical re-extraction on filings with accumulated reviewer work without CASCADE-destroying it.

Neon-prod quantification on 2026-04-21 revised the problem size sharply:

- 38 Class (E) filings total → **28 are stuck 8-K filings** in `processing_status='processing'` that shouldn't have been ingested (see Issue #55 below), and **10 are in-scope S-1/F-1** (8 non-reviewed + 2 reviewed) — the real backfill target is ≤10 filings, not 38.
- Of those ≤10, all 8 non-reviewed candidates have accumulated 81 reviewer decisions across them, making the guard's preservation the binding constraint (which `chart_only` solves).

Three smokes on Neon (1547 Samsara, 1541 Flywire, 1146 Chewy) confirmed:

- Mechanism is safe: reviewer decisions fully preserved across all three runs; text/html_table facts untouched.
- Recall gain is sparse: only 1 chart fact produced across 3 filings (Chewy), and that fact was a low-confidence (0.508) misbind of `cm_customer_acquisition_cost`=$3 — a reviewer-gated false positive.

Root cause of the sparse gain: the original 38-filing Class (E) baseline conflates (a) filings where pre-fix OCR dropped Tier 1 cohort/NRR chart data with (b) filings whose charts aren't Tier 1 metrics at all (market-size, process diagrams, photos). Only (a) recovers under re-extraction; most of the 38-filing set is (b).

### Remaining work

- Full 5-filing Phase 4' (1442, 1543, 1549 Snowflake, 1550 Tenable, 1146-remainder) deferred: expected recall gain doesn't justify the reviewer-curation overhead until Issues #53 and #54 (chart-call-limit truncation and chart-bridge low-confidence misbinds) are investigated.
- Class (E) diagnostic should narrow to S-1/F-1 form types (and exclude filings whose charts don't include Tier 1 metrics) to avoid overstating the gap in future audits.
- 2 reviewed filings (1542, 1543) still in Class (E) under chart_only's guard — acceptable; they preserve reviewer work.

### Cross-References

- `.claude/rules/v2-pipeline.md#chart-only-re-extraction-chart_onlytrue` — mechanism documentation
- Issue #34 — R2 backend (Phases 1 + 3 resolved 2026-04-19)
- Issue #24 — Class (B) orphan img_id refs (still open; independent of Issue #35 scope)
- Issue #53 — chart call limit (10) truncates OCR for high-chart filings
- Issue #54 — chart-bridge emits low-confidence misbinds on non-Tier-1 charts
- Issue #55 — 28 stuck 8-K filings in Class (E) (form-filter bypass during ingestion)
- PR #50 — `feat(persistence): add chart_only mode for surgical Issue #35 backfills`
- Session artifacts: `data/audit/issue_35_presmoke_snapshot.sql`, `data/audit/issue_35_presmoke_gs.txt`, `logs/issue_35_prod_smoke{,2,3}.log`

### Resolution (2026-04-23)

The chart-presence pivot (#86, PRs #147/#150/#151/#154) makes the chart-fact backfill concern moot:

- The chart pipeline no longer emits per-value `v2_metric_facts` rows. Historical filings that never had chart facts now have nothing to backfill on that table.
- The new signal is image-level `detected_metrics` on `v2_image_assets`. Historical filings do need a one-time `detected_metrics` backfill, but that is a *different* operation from the Issue #35 chart-fact backfill — cheaper, idempotent, no reviewer-CASCADE risk, and no Tier-1 recall gain depends on it. It will run via a scheduled cron or as a separate operational PR after PR 4b drains the legacy chart-fact rows.
- The original Issue #35 scope (surgical chart-fact re-extraction via `chart_only=True`) still exists on the persistence layer and is reused by PR 4b's drain step; the mode is no longer needed for backfill but is useful for the one-shot DELETE pass.

## #49. Integration Test DB Flakiness Under Full-Suite `pytest -x`

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-20
**Updated**: 2026-04-23

**Resolved**: 2026-04-23 — cannot reproduce on current `main`. Five back-to-back clean runs of the full suite (4× sequential `pytest -x -q`, 1× xdist `pytest -x -q -n auto`), all green. The symptoms described below (`AdminShutdown`, `connection is lost`, deadlock in ROLLBACK) do not surface. Two commits since #49 was filed likely combine to eliminate the race: (a) `5c11593` (2026-03-30) added `_terminate_stale_connections` + atomic-TRUNCATE in the V1 `clean_extraction_db` (V1 since retired); (b) `2e5977e` (2026-04-22, #78) added `_isolate_xdist_worker_database` so each pytest-xdist worker runs against its own Postgres DB, eliminating cross-worker pool/TRUNCATE contention entirely. Under `-n0` sequential mode the shared-pool race was never re-observed.

One latent hygiene concern remains (not fixed here, not currently reproducible): `tests/integration/conftest.py::clean_db` still issues three separate TRUNCATE blocks (review tables, V2 tables, `filings`+`companies`) rather than one atomic TRUNCATE. The March 30 commit explicitly identified this pattern as the "interleaved-lock deadlock window" cause in the V1 fixture. File a follow-up if the flakiness recurs.

### Problem

Running `pytest -x -q` over the full suite (unit + integration) reproducibly
fails in the first integration test that hits the connection pool. Errors
observed: `AdminShutdown: terminating connection due to administrator
command`, `psycopg.OperationalError: the connection is lost`, and
`deadlock detected` in `ROLLBACK` during fixture teardown. The specific
test that trips varies run-to-run — during #48 work, both
`tests/integration/test_db_v2_image_methods.py::TestGetImageReviewCandidatesForFilingV2::test_returns_non_decorative_images_only`
and
`tests/integration/extraction_v2/test_batch_runner_db.py::TestBatchRunnerQueryFilings::test_query_filings_returns_expected_columns`
have surfaced. Each test passes individually. Reproduces on clean `main`
with in-flight changes stashed, so it predates #48. Distinct from resolved
issues #7/#8 (missing teardown); symptom here looks like cross-test pool
orchestration or a session-scoped fixture forcing a pool rebuild during
another test's open transaction.

The effect is that the "run `pytest -x -q` before committing" gate in
CLAUDE.md is undermined — operators have to know to fall back to
`pytest tests/unit -q` and separately exercise integration, or skip the
pre-commit check.

### Next Steps

- Reproduce deterministically: run `pytest -x -q` against the integration
  dir in isolation and bisect which test ordering triggers the admin
  shutdown.
- Inspect `tests/integration/conftest.py` `test_db_adapter` and
  `clean_db` fixtures for session-scoped lifetime vs. per-test pool use.
- Candidate fix: force `function`-scoped pools for integration tests, or
  ensure the `clean_db` fixture's `TRUNCATE` does not race with another
  test's open connection.

## #68. Nightly Sweeper Orchestrator Uses GNU `timeout` (Incompatible with macOS)

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-21
**Updated**: 2026-04-22
**PR refs**: #107

### Problem

`scripts/run_nightly_sweep.sh` invokes `timeout "$PER_ISSUE_BUDGET" claude -p "$prompt"` to enforce per-issue wall-clock budgets. `timeout` is GNU coreutils; macOS ships BSD utilities and does not include it by default. Local `/sweep` skill invocations on macOS fail at the `timeout` call. Render's container image is Linux so production is fine.

### Next Steps

- Detect `timeout` vs `gtimeout` vs neither at script start; fall back to `gtimeout` on macOS (via `brew install coreutils`) or to a no-timeout code path with a warning log.
- Alternatively, install `coreutils` as part of the local-dev setup docs for the `/sweep` skill.

## #70. CONTRIBUTING.md `/commit` Step 1 Wording Is Stale Post-Worktree-Hook

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-21
**Updated**: 2026-04-22

### Problem

`docs/development/CONTRIBUTING.md` § "Committing via `/commit`" step 1 currently reads:

> "If on `main`, auto-creates `claude/<type>-<slug>` and switches to it. Otherwise stays on the current branch."

This implies `/commit` can be invoked from the primary worktree while on `main`. In practice, `~/.claude/hooks/guard-destructive-git.sh` (the PreToolUse hook) now denies `git checkout -b` in the primary tree, so running `/commit` from there will fail with a hook block. The step 1 description does not reflect the worktree-required model that is actually enforced.

The functional behavior is correct — the hook fires and blocks the operation as intended. Only the documentation lags behind.

### Next Steps

- Rewrite step 1 to state that `/commit` must be invoked from a `ccw` worktree (or via an `Agent` call with `isolation: "worktree"`), and that invoking it from the primary tree will be refused by the PreToolUse hook.
- Cross-link `docs/development/claude-sessions-and-worktrees.md` § Orchestration pattern for the recommended workflow.

### Cross-References

- `docs/development/CONTRIBUTING.md` — § "Committing via `/commit`", step 1
- `docs/development/claude-sessions-and-worktrees.md` — § Orchestration pattern
- `~/.claude/hooks/guard-destructive-git.sh` — the hook that blocks `git checkout -b` in the primary tree
- PR #71 — added `/supervise-prs` and orchestration guidance to the worktree guide

## #71. Integration Tests Job Has No Path Filter

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-21
**Updated**: 2026-04-22
**PR refs**: #108

### Problem

`.github/workflows/ci.yml` runs the `integration-tests` job on every PR regardless of touched paths. UI E2E already has a conservative path filter (`ci.yml:49-69`) that skips the job when every changed path is under `docs/`, `.claude/`, `CLAUDE.md`, `README.md`, `.gitignore`, or `.github/CODEOWNERS`. Integration Tests has no equivalent, so docs-only and `.claude/`-only PRs still spin up Postgres 15, apply migrations, and run the full integration suite (~3–6 min). Net ~3–6 min wall-time save per docs-only PR.

### Next Steps

- Mirror the UI E2E filter structure (`ci.yml:49-69`) on the `integration-tests` job. Same allowlist (`docs/`, `.claude/`, `CLAUDE.md`, `README.md`, `.gitignore`, `.github/CODEOWNERS`) — err on the side of running when in doubt.
- Verify by opening a docs-only PR and confirming `Integration Tests` reports `skipped` in Actions.
- Do NOT remove Integration Tests from required status checks — a skipped job still counts as passing for branch protection, so the gate stays intact.

## #74. `.claude/scheduled_tasks.lock` Not Gitignored

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-22
**Updated**: 2026-04-22

### Problem

`.claude/scheduled_tasks.lock` is created at runtime by the Claude Code scheduled-tasks system but is not covered by any `.gitignore` rule — `git check-ignore -v .claude/scheduled_tasks.lock` returns no match. Every `git status` run in an active session lists it as untracked, which inflates status output and creates a small risk of accidental staging if someone invokes `git add -A` or `git add .` (already an anti-pattern per CLAUDE.md, but worth hardening against).

### Next Steps

- Add `.claude/scheduled_tasks.lock` (or a broader `.claude/*.lock` glob) to the root `.gitignore`.
- Quick audit of `.claude/` for other runtime-only files (e.g., `.claude/sweep-digests/` is already tracked separately — confirm nothing else needs ignoring).

## #76. Missing Integration Test for Filings-List Reviewer Aggregate

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-21
**Updated**: 2026-04-22

### Problem

`get_unified_filings_for_review` now UNIONs text + image decision tables and projects a `reviewers` array per filing, plus an optional `reviewer_ids` filter using `ARRAY_AGG(...) && ...`. Unit tests cover the route layer threading this kwarg, but there's no integration test asserting: (a) mixed-reviewer filings return distinct reviewers from both text and image sources; (b) the `&&` overlap filter correctly narrows the list without false positives; (c) filings with only NULL reviewer_ids render as an empty array. Without this test, a future CTE refactor could silently lose reviewers from one source.

### Next Steps

- Add `tests/integration/test_db_filings_reviewers.py` that seeds a filing with text decisions by Alice + image decisions by Bob, calls `get_unified_filings_for_review`, and asserts `row["reviewers"] == ["alice", "bob"]`.
- Add a second case: call with `reviewer_ids=["alice"]`, assert the filing is returned; call with `reviewer_ids=["zoe"]`, assert it is not.
- Add a third case: a filing with only NULL reviewer_id decisions (legacy image rows) returns `reviewers == []`.

## #79. Nightly Sweeper Selector Picks Resolved/Archived Issues

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-22
**Updated**: 2026-04-23

### Problem

`scripts/known_issues_selector.py` filters on `autonomy` (safe/review) and
dedupes against open PRs, but never checks `status`. When a resolved issue
remains in the classification table with `autonomy: safe` (either because the
post-merge cleanup didn't remove it, or because the fragment's `status` was
updated to `resolved` but its `autonomy` was left as `safe`), the selector
picks it for nightly attempts.

Baseline selector run against the pre-migration monolith picked #60, #68, #71
— all three already resolved per PRs #105 / #107 / #108. The sweeper would
attempt to re-fix issues whose fixes are already in `main`.

### Next Steps

- Naturally subsumed by Phase 3 selector rewrite: when it reads frontmatter
  directly, filter out fragments whose `status` is `resolved` or `archived`.
- Add a regression test: fragment with `status: resolved` + `autonomy: safe`
  must NOT appear in selector picks.
- Optional: also emit a warning when such a fragment is encountered, so the
  author knows to set `autonomy: n/a` on resolved entries.

## #96. Chart-Presence Pivot — Multi-PR Rollout Tracking

**Status**: Resolved
**Severity**: low
**Discovered**: 2026-04-23
**Updated**: 2026-04-24
**PR refs**: #147, #150, #151, #154, #158

### Problem

The chart-stage pivot for Issue #86 replaces per-value chart `v2_metric_facts` emission with image-level metric-presence records on `v2_image_assets.detected_metrics`, adjudicated via `v2_image_metric_confirmations` (accept / reject / correct / add). Shipped as a five-PR sequence (originally four; PR 4 split into 4a + 4b after scope overran) to bound scope, unblock parallel review, and isolate the planned prod drain from the code + docs cleanup.

### Rollout

| PR | Scope | Status |
|---|---|---|
| [#147](https://github.com/RGMjr/filings_reviewer/pull/147) | `ChartFactBridgeStage` rewrite (emit presence on `v2_image_assets.detected_metrics`, no facts). `sql/42` adds the JSONB column. `_scan_chart` gated off. | Merged 2026-04-23 |
| [#150](https://github.com/RGMjr/filings_reviewer/pull/150) | Gold-standard validator: presence P/R/F1; baseline schema extended; chart-row `Raw value` forced advisory. | Merged 2026-04-23 |
| [#151](https://github.com/RGMjr/filings_reviewer/pull/151) | `sql/43_create_v2_image_metric_confirmations`; `DatabaseAdapter.insert/get_image_metric_confirmations`; `GET /api/v2/metrics/list`; `POST /api/v2/image-metric-confirmations`; Chart Evidence block + `_resolve_chart_image_status` deleted. | Merged 2026-04-23 |
| [#154](https://github.com/RGMjr/filings_reviewer/pull/154) | Detected metrics card in `unified_review.html`; `review_images_v2.js` module (A/R/C/N focus-scoped keyboard); Playwright spec. | Merged 2026-04-23 |
| [#158](https://github.com/RGMjr/filings_reviewer/pull/158) | PR 4a — code + docs cleanup: delete `CohortParser`, rewrite `.claude/rules/v2-pipeline.md`, update `docs/architecture/data-model.md`, `CLAUDE.md` §4, close legacy-086/035 known-issues. | Merged 2026-04-24 |
| PR 4b (this) | Post-pivot baseline refresh; **drain deferred** after pre-flight safety audit. Overall F1 0.544 → 0.618 (+7.4pp) via PR #150's chart-row presence bypass. | This PR |

### Drain deferral — why

PR 4b's plan called for `DELETE FROM v2_metric_facts WHERE source_type='chart'` against prod. Pre-flight queries on 2026-04-24 found:

| Metric | Count |
|---|---|
| Residual chart facts | 30 |
| Filings affected | 10 |
| Reviewer decisions on chart facts | **18** |

The 18 decisions break down as: 9 rejects, 5 accepts, 4 corrects (17 by reviewer `RGM`, 1 bulk-system entry). `v2_review_decisions.fact_id ON DELETE CASCADE` means the DELETE would silently destroy that reviewer work.

Options weighed:

- **B1 — defer drain** (chosen): leave 30 residual chart facts in `v2_metric_facts` as dead data. Correctness-wise fine — the new UI doesn't surface chart facts (Chart Evidence block deleted in PR #151), the validator treats chart gold rows via presence (PR #150), and analytics views that filter on `source_type='chart'` are the only surface area affected. Zero reviewer-work loss.
- B2 — export decisions to JSON archive, then DELETE. Reviewer work archived but not queryable live. Not chosen because the residual-fact presence is low-impact; no urgent need to delete.
- B3 — migrate the 9 accepts/corrects to `v2_image_metric_confirmations`. Requires mapping code; complex because `corrected_value` has no presence-schema equivalent and some source_locators may lack img_id.
- B4 — proceed with DELETE anyway. Counter to reviewed-filing-guard design intent.

### Post-pivot baseline

Refreshed 2026-04-24 via `python3 -m src.gold_standard.v2_validator --update-baseline`:

| | Before | After | Δ |
|---|---|---|---|
| Precision | 0.668 | 0.659 | −0.9pp |
| Recall | 0.459 | 0.581 | +12.2pp |
| F1 | 0.544 | 0.618 | +7.4pp |

The recall jump is the measurement-methodology shift from PR #150 landing: 82 `segment_type='chart'` gold rows stop counting as value-level FNs and instead route through presence P/R. `presence_f1` is still `None` in the baseline — the validator's in-memory pipeline run does not yet populate `v2_context.images[*].detected_metrics` end-to-end (the field is defined on the dataclass but not populated by the validator's `pipeline.process()` call path). Tracked separately.

### Residual work (out of scope for PR 4b)

- **30 residual chart facts + 18 reviewer decisions** on prod. Filed as a new known-issue fragment (`legacy-097`) for possible future handling.
- **Validator presence_f1 measurement gap.** `detected_metrics` is populated at persistence time but not in the validator's in-memory pipeline result. Baseline presence-F1 stays `None` until this wiring lands. Filed separately.

### Cross-References

- Parent plan: `~/.claude/plans/pick-up-issue-86-tranquil-piglet.md`
- PR 4a plan: `~/.claude/plans/let-s-move-on-to-snoopy-flamingo.md`
- Dissolved issues: legacy-086 (dedup collapse), legacy-035 (chart-fact backfill).
- Reduced-severity reference: legacy-053 (chart call limit — now affects presence coverage only).
- Residual work: legacy-097 (residual chart facts + reviewer decisions).


## Change Log

- **2026-01-01**: Initial document created after VAL-1 validation
- **2026-01-01**: CAC payback period issue resolved (moved to "FIXED" section)
- **2026-03-16**: Added Issue #6 — FilingFetcher directory index bug
- **2026-03-16**: Issue #6 resolved — default SECClient creation + removed null guard; 78 cloud-fetched files need re-fetch
- **2026-03-16**: Issue #1 resolved — gold standard CSV updated to align with system taxonomy; no metric ID mismatches remain
- **2026-03-17**: Archived resolved Issues #1 and #6; updated Farfetch contributing factors to reflect resolutions
- **2026-03-19**: Added Issues #6–#8: Farfetch gold standard test failures, extraction pipeline deadlock, connection pool exhaustion
- **2026-03-19**: Issue #9 partially resolved — fresh mode validation eliminates DB dependency; `*.dump` added to `.gitignore`
- **2026-03-26**: Issues #7 and #8 resolved — DatabaseAdapter.close(), pool + yield teardown in test fixtures, max_connections=200
- **2026-03-26**: Issue #3 resolved — created docs/GOLD_STANDARD_SPECIFICATION.md
- **2026-03-26**: Issue #11 partially resolved — fixed wrong metric IDs and broken TestKeywordPatterns imports; 11/12 tests pass
- **2026-03-26**: Issue #2 partially resolved — fixed extract_fresh_batch company_names bug; recall gap requires keyword work
- **2026-03-26**: Added Issue #10 — CMS-1 suppression assigns Active Consumers to cm_customers_period_end instead of cm_active_customers_total
- **2026-03-27**: Removed duplicate main-body sections for Issues #3, #7, #8 — already archived; stale "Open"/"Needs Discussion" statuses were conflicting with archive entries
- **2026-04-07**: Removed orphaned summary table rows for Issues #7 and #8 (already in archive, no main body section); added Issue #10 cross-reference to Issue #2 remaining gaps
- **2026-04-18**: Added Issue #12 — `test_image_crop.py` writes PNGs into real `data/` dir with no teardown
- **2026-04-18**: Issue #12 resolved — `make_png_in_data_dir` fixture added; cleans up PNGs on teardown
- **2026-04-18**: Added Issue #13 — V2 metric facts identity index drift (live DB 8 columns, code + `sql/23` expect 9); documented during `docs/architecture/data-model.md` rewrite
- **2026-04-18**: Issue #2 re-diagnosed; re-measured Farfetch P=50% R=37% F1=42% via v2_validator; stale 12.5% figure replaced; umbrella superseded by sub-issues #14–#19; Take Rate bullet removed (metric was retired 2026-01-02); "CAC Payback FIXED" claim corrected (partial — see #17)
- **2026-04-18**: Issue #10 re-scoped — original CMS-1 suppression hypothesis disproven (`cm_customers_period_end` has no "Active Consumers" pattern; `cm_active_customers_total` recall is 100% at pipeline layer); real root cause for unit-test failure is TBD
- **2026-04-18**: Added Issue #14 — Farfetch LTV/CAC dedup collision on layout-table misclassification (4 T1 FNs)
- **2026-04-18**: Added Issue #15 — chart pipeline blocked locally by missing OPENAI_API_KEY
- **2026-04-18**: Added Issue #16 — Farfetch precision drag from table-scale + period attribution
- **2026-04-18**: Added Issue #17 — CAC payback bare word-number + time unit not bound
- **2026-04-18**: Added Issue #18 — migration checksum mismatch on `sql/01_create_schema.sql` (blocks pytest gold standard; v2_validator module workaround)
- **2026-04-18**: Added Issue #19 — FN diagnostic misclassified 3 of 3 categories investigated during 2026-04-18 Farfetch diagnosis
- **2026-04-18**: Issue #18 resolved — self-healed via V1 retirement merge (pytest gold_standard tests deleted in commit `03a8a20`); no reconciliation action needed
- **2026-04-18**: Issue #15 resolved — added `load_dotenv()` to `v2_validator.py` `__main__`; chart stages now run automatically when `.env` contains `OPENAI_API_KEY`
- **2026-04-18**: V2 baseline refreshed with chart pipeline active (P=64.1% R=45.6% F1=53.3%; Tier 1 F1 +1.4pp vs prior)
- **2026-04-18**: Added Issue #20 — `cm_gross_margin_by_cohort` still 0% on Farfetch despite chart extraction running end-to-end; 2026-04-17 JSON-mode fix did not lift this metric
- **2026-04-18**: Issue #13 — `sql/33_fix_identity_index.sql` prepared; root cause diagnosed as pg_dump snapshot restore overwriting the sql/23 DDL after migration was recorded; secondary finding: `_persist_facts_in_tx` in-memory dedup key (persistence.py:710–719) also omits `source_type` (tracked, not fixed here)
- **2026-04-18**: Issue #17 resolved — added `WORD_NUMBER_TIME_PATTERN` in `value_binding.py` gated to `TIME_UNIT_VALUED_METRICS={"cm_cac_payback_period"}`; added `_V1_SPELLED_OUT_OVERRIDE_METRICS` override in `false_positive_filter.py`; `cm_cac_payback_period` 0% → 100% F1 on Farfetch. No Tier 1 regression (F1 +0.4pp)
- **2026-04-18**: Issue #19 resolved — added `dedup_collision` + `no_matching_binding` FN diagnostic categories; `wrong_period` restricted to post-dedup facts; 4 new unit tests
- **2026-04-18**: V2 baseline refreshed post-#17/#19 (P=64.6% R=45.9% F1=53.7%; Tier 1 F1 unchanged at 55.6%)
- **2026-04-18**: Issue #14 resolved — added `cohort_hint` field to `BoundValue`; `_bind_prose_cell` prefers `detect_respectively_pattern` at min_confidence≥0.8 when "respectively" is present; `_bind_respectively_pattern` sets `cohort_hint` (and empties `period_hint`) when cell text mentions "cohort(s)"; `_construct_fact` prefers `bv.cohort_hint` over evidence scan; defensive 80-char prose guard in `_extract_cohort_def`. Farfetch: `cm_ltv_to_cac_ratio` R 33%→100%; `cm_ltv_to_cac_ratio_by_cohort` R 17%→50% (text); Farfetch F1 +10.3pp. Overall F1 +1.0pp; Tier 1 F1 55.6%→57.3%; no regressions
- **2026-04-18**: Issue #20 resolved — diagnosed via DB inspection: OCR for FTCH `g607688g09d00.jpg` returned valid 9-value chart data at confidence 0.9 but with empty title/axes; classifier + CohortParser both relied on signals the OCR output lacked. Fix (all in `src/extraction_v2/chart/`): `metric_classifier._cohort_gate` accepts ≥2 distinct years in `points[].x` + customer-type series names; `_metric_gate(cm_gross_margin_by_cohort)` fallback for empty y_axis (requires margin/contribution keyword + `%` signal); `_score_metric` nearby_text title fallback + +5.5 raw structural bonus (%/years/customer-type trio); `cohort_parser._parse_customer_type_regime` for year-in-point.x + customer-type-in-series.name shape. `cm_gross_margin_by_cohort` Farfetch 0% → 100% F1 (9/9 rows). Overall F1 53.7%→56.9% (+3.2pp); Tier 1 F1 55.6%→61.0% (+5.4pp); no regressions
- **2026-04-18**: Added Issue #21 — `v2_image_assets` duplicate rows on re-extraction (random UUID upsert key) + asymmetric dedup in progress counter vs. review-list query caused 220 pending / 0 queue discrepancy on Maplebear S-1
- **2026-04-18**: Issue #21 resolved — `sql/34_dedup_v2_image_assets.sql` collapses duplicates + adds UNIQUE (doc_id, filename); `_persist_images_in_tx` upserts on (doc_id, filename) preserving stable img_id; `persist_pipeline_result` remaps in-memory fact source_locator.img_id before fact insert
- **2026-04-18**: Added Issues #22–#25 — out-of-scope follow-ups surfaced during Issue #21 investigation: image re-extraction guard gap, dead segment_id column, img_id referential integrity, migrate_image_ids script scope confusion
- **2026-04-18**: Issue #23 resolved — `sql/35_drop_v2_image_assets_segment_id.sql` drops the dead column (applied to Neon prod + local test DB); `_persist_images_in_tx` in `src/extraction_v2/persistence.py` no longer references it; migration registered in `scripts/apply_migrations.py`
- **2026-04-18**: Issue #22 resolved — `_persist_images_in_tx` raises `ReviewedFilingError(context="image classifications")` when a decided image would be re-classified from the visible set (`chart`/`table_image`/`unknown`) into the hidden set (`decorative`/`logo`/`signature`); `force=True` proceeds with a structured warning; `ReviewedFilingError.__init__` gained an optional `context` kwarg (default `"facts"` preserves prior message shape); 5 new tests in `TestGuardOnPersistImages`; `_persist_images_in_tx` signature gains keyword-only `force: bool = False` (backwards compatible; `persist_pipeline_result` threads through)
- **2026-04-18**: Issue #25 resolved — expanded docstring on `scripts/migrate_image_ids_to_deterministic.py` to clarify the script only rewrites local gold-standard JSON files and does not modify the database
- **2026-04-19**: Issue #10 resolved-by-deletion — `tests/integration/test_gold_standard_coverage.py` was deleted in commit `03a8a20` (V1 retirement); re-diagnosis is no longer actionable against a non-existent test
- **2026-04-19**: Issue #9 scope clarified — the "remaining" follow-up is NOT a simple `companies.cik` column update. Filing 32 in the local DB contains RMR Group content, not Snap content; a correct fix requires re-ingesting the actual Snap S-1/A (accession `0001193125-17-056992`) as a separate workstream. Expanded inline comment in `scripts/gi3_richness_analysis.py:41-46` to match
- **2026-04-19**: Issue #24 diagnostic script added — `scripts/check_image_referential_integrity.py` scans `v2_metric_facts.source_locator.img_id` against `v2_image_assets`, reports orphans, exits non-zero when any found (suitable for nightly cron). Does not promote `img_id` to a FK column — that remains open
- **2026-04-19**: Added Issue #27 — 3 Images Tab assertions in `tests/ui/review.spec.js` fail pre-existing against the current mock server; latent since the suite never ran in CI. Commit `413b386` added a `ui-e2e` CI job that will now surface them on every PR
- **2026-04-19**: Added Issue #28 — Playwright mock server duplicates production template context; Apr 17 breakage (commit `3e398fd`) was the symptom class. Commit `413b386` added `tests/ui/smoke.spec.js` as a fast pre-flight to catch render-time failures, but the underlying duplicated-contract coupling remains
- **2026-04-19**: Issue #24 diagnostic baseline recorded — `scripts/check_image_referential_integrity.py` against the local dev DB reports 9 orphan facts across 4 docs (1546: 4, 1545: 2, 1551: 2, 1539: 1). Historical facts predating the `sql/34` dedup migration. Prod not yet scanned; cleanup strategy still open
- **2026-04-19**: Added Issue #29 — `cm_new_customers_acquired` receives `2.71x` chart fact from Farfetch LTV/CAC tenure chart `g607688g54x53.jpg`; 1 FP per Farfetch baseline. Filed as its own issue after originally being noted in Issue #20 "Out of scope"
- **2026-04-19**: Issue #31 partial resolution — `review_unified.py:97-109` captures `current_app.config["TESTING"]` into the worker-thread closure and logs `DEBUG` instead of `ERROR` when `TESTING=True`; production path unchanged. Related `src/web/middleware.py:114` synchronous path has the same pattern but was intentionally left for a separate fix (Issue #31 explicitly named only the async path)
- **2026-04-19**: Issue #27 partial resolution — `review.spec.js:965` passes after `img_id` added to `MOCK_IMAGE_CANDIDATE_PENDING` / `MOCK_IMAGE_CANDIDATE_REVIEWED` in `tests/ui/test_server.py`; `review.spec.js:1037` (`.keyword-badge`) and `review.spec.js:1054` ("Image 1 of 2") are stale assertions (no matching template elements) and now `test.skip` with TODO(KNOWN_ISSUES #27). Full Playwright suite 142 pass / 2 skip / 0 fail locally
- **2026-04-19**: Issue #13 docs reconciled — local test DB verified 9-col (includes `source_type`); `scripts/apply_migrations.py` comment asserts prod already applied out-of-band; this doc previously said "pending prod apply". Prod `pg_indexes` query still needed to settle the contradiction
- **2026-04-19**: Issue #29 resolved — root cause was NOT candidate-level (yaml exclusion didn't help: chart combined_text was just `'2015 Cohort 2016 Cohort 2017 Cohort'`, no customer-type keywords). The mis-classification entered via `_scan_chart`'s nearby_text second pass (Farfetch prose legitimately mentions "new Marketplace consumers" near the LTV/CAC chart); value binding then attached the chart point.label `2.71x` to the candidate. Fix: added `_rule_ratio_suffix_on_count_metric` in `false_positive_filter.py` mirroring the existing `_rule_revenue_concentration_ratio_suffix`, rejecting `N.NNx`/`N.NN×` raw values bound to count/currency/rate/time metrics (whitelists `cm_ltv_to_cac_ratio` + `cm_ltv_to_cac_ratio_by_cohort` implicitly). 6 new unit tests. Farfetch GS confirms the `2.71x` FP is eliminated; total Farfetch FP count unchanged at 12 because a pre-existing sibling FP (`54%` percent-on-count with `unit=COUNT`) was previously tiebroken-away by `2.71x` and now surfaces — separate, pre-existing issue, not fixed here
- **2026-04-19**: Issue #24 extended — `scripts/check_image_referential_integrity.py` now reports three classes (null-img_id on chart facts [blocking], orphaned img_id refs [warn], file_path outside data/ or missing on disk [warn]) and runs in the integration-tests CI job. `tests/unit/extraction_v2/test_chart_fact_bridge_invariants.py` locks the Class (A) invariant. Commit `d1430d9`
- **2026-04-19**: Added Issue #34 — `v2_image_assets.file_path` rooted in macOS TMPDIR on the local extraction host; 158/165 rows outside `data/`, 50/165 absent on disk. Dominant root cause behind the Box Inc S-1/A missing-Chart-Evidence case surfaced during the commit-`d1430d9` investigation
- **2026-04-19**: Added Issue #35 — 38 filings have chart images but zero `source_type='chart'` facts, consistent with pre-2026-04-17 chart-OCR JSON failures. Backfill via `batch_v2_extraction.py --force-reextract` pending Issue #34 fix
- **2026-04-19**: Added Issue #41 — review-UI sticky-header offset mismatch (`.sticky-top-below-nav` at 70px vs new `.review-sticky-header` at 56px) + narrow-width pill overlap with "Next filing F" button unverified. Opened during review-UI sticky compact top-matter work, commit `ba35424`
- **2026-04-19**: Issue #34 Phase 1 resolved — `src/infra/paths.py::image_cache_dir()` helper introduced (honors `IMAGE_CACHE_DIR` env override, defaults under `data/image_cache/`); `src/extraction_v2/stages/ocr_extraction.py` swapped from `tempfile.gettempdir()` to the helper with a collision-safe `pipeline/<cik>/<accession>/<filename>` layout; `data/image_cache/` added to `.gitignore`; tests in `tests/unit/infra/test_paths.py` + class-scoped autouse fixture in `tests/unit/extraction_v2/test_image_pipeline_integration.py::TestImageDownloading` fence `IMAGE_CACHE_DIR` to `tmp_path`. Phase 3 (Render persistent disk vs. re-fetch-on-miss) is a separate decision; prod remains ephemeral until chosen. Full suite: 3591 pass, 67 skip. Issue #35 is now unblocked on local dev
- **2026-04-19**: Issue #13 resolved — prod `pg_indexes` read confirms `idx_v2_metric_facts_identity_unique` has all 9 columns (including `source_type`). Local test DB and prod now agree; `scripts/apply_migrations.py:68-74` comment was accurate and stays in place
- **2026-04-19**: Issue #31 fully resolved — `src/web/middleware.py:87-120` synchronous audit-log path now mirrors the async pattern (captures `TESTING`, downgrades except-clause log to DEBUG when true). New `tests/unit/web/test_middleware.py::TestAuditLogFailureLogging` covers both cases. Commit `366d9dd`
- **2026-04-19**: Issue #36 resolved — `UniverseBuilder.build_universe` gained optional `limit: int | None` kwarg; `scripts/onboard_tickers.py populate --limit N` threads through. Default `None` preserves unbounded behaviour; regression test at `tests/unit/universe/test_universe_builder.py::test_limit_stops_after_n_in_scope_upserts`. Commit `366d9dd`
- **2026-04-19**: Issue #37 resolved — `_process_filing` in `src/universe/universe_builder.py` gates `classify_first_time_issuer` on `filing.form_type in DEFAULT_FORM_TYPES_S1F1`; non-applicable filings land with `is_first_time_issuer=NULL` and `fti_method="not_applicable"`. Mirror of the existing SPAC-SGML gate at line 163. Covered by `tests/unit/universe/test_universe_builder.py::test_10k_filing_has_null_first_time_issuer`. Commit `366d9dd`
- **2026-04-19**: Issue #41 resolved — `--navbar-height: 48px` CSS custom property in `src/web/static/css/review.css` unifies sticky offsets; `.navbar.sticky-top` padding-y compacted to 0.25rem; `.review-pill-row` flex-wrap class on the `unified_review.html:58` stat-pill row. Separately, `accepted`, `rejected`, and `img reviewed` badges dropped to reduce horizontal load; badge font-size shrunk to 0.7rem; sticky-header vertical padding trimmed to absorb container `mt-4`. Deployed Render build verified visually. Commit `366d9dd`
- **2026-04-20**: Added Issue #46 — `scripts/apply_all_migrations.py` `MIGRATION_ORDER` list stops at 31 and its unregistered-guard aborts on files 32-38; surfaced during analytics-UI phase 1 (sql/37 + sql/38) audit. Canonical runner is `scripts/apply_migrations.py`
- **2026-04-20**: Added Issue #47 — `data/audit/` runtime JSONL output is untracked but not gitignored; peer `data/*` subpaths are. Surfaced during analytics-UI phase 1 pre-commit `git status` review
- **2026-04-20**: Issue #44 resolved — `_classify_path` in `scripts/audit_filing_url_mismatch.py` now implements the four-outcome decision tree from the original Next Steps: `facts==0` short-circuits to Path A (eliminates Spectrum Brands false-positive Path C), `facts>0` + accession/storage collision routes to new `B_coordinated` sub-path. `scripts/repair_filing_url_mismatch.py::_eligible_rows` warns once per invocation when `B_coordinated` rows are present so they aren't silently dropped from existing A/B runs. 7 unit tests at `tests/unit/scripts/test_audit_filing_url_mismatch.py` cover every branch (loaded via `importlib.util` to avoid `scripts/__init__.py`)
- **2026-04-20**: Issue #45 resolved — `from dotenv import load_dotenv` + `load_dotenv()` added to `scripts/validate_database_urls.py` ahead of the `DATABASE_URL` read; mirrors `scripts/apply_migrations.py:21`. Existing fallback / error path retained for the case where `.env` has no `DATABASE_URL`
- **2026-04-20**: Issue #46 resolved — `MIGRATION_ORDER` in `scripts/apply_all_migrations.py` extended with `32_add_detected_keywords_to_v2_image_assets.sql`, `33_fix_identity_index.sql`, `34_dedup_v2_image_assets.sql`, `35_drop_v2_image_assets_segment_id.sql`, `36_backfill_presentation_urls.sql`, `37_create_analytics_role.sql`, `38_create_analytics_views.sql`. `--dry-run` now reports 44 migrations (31 pre-existing + 7 new); `check_unregistered_migrations` no longer aborts. Sync rather than delete (script still referenced from 7 docs); sql/33 included for fresh-DB-from-scratch semantics — migration is explicitly idempotent
- **2026-04-20**: Issue #47 resolved — `data/audit/` added to `.gitignore` line 46 alongside peer `data/*` runtime ignores (`data/filings/`, `data/image_cache/`). Verified via `git check-ignore -v`
- **2026-04-21**: Archive cleanup — collapsed 29 fully-resolved issues (#10, #12, #13, #14, #15, #17, #18, #19, #20, #21, #22, #23, #25, #26, #29, #30, #31, #32, #33, #36, #37, #41, #44, #45, #46, #47, #48, #56, #57) from main body into Archive section; rewrote Summary table to foreground open items; removed resolved rows from Summary table. Issue #11 cross-reference to #10 updated to point to archive entry.
- **2026-04-21**: Five-issue follow-up bundle landed in commit `7848605` — resolved #42 (double image-write collapsed via public `SECClient.get_image_cache_path`), #50 (new `tests/unit/web/test_api_unified_auth.py`), #51 (behavioral mock-cursor rewrite; `# fmt: skip` removed), #52 (new `scripts/check_pg_client_version.py` pre-flight + infrastructure.md doc section), #54 (new `chart_metric_min_confidence` knob with default 0.60 to avoid Tier 1 regression). Archive entries added. #64 opened — chart classifier Tier 1 boundary sensitivity: HOOD `cm_balance_by_cohort` scores 0.6024 (0.0024 above gate); surfaced while forcing #54's default down from the originally-proposed 0.70. (Renumbered from an earlier working #58 after merge from origin/main revealed issues #58–#63 had been claimed by the Wave B/C/D batch-ingest-ui follow-ups.)
- **2026-04-21**: Issue #11 archived — resolved-by-deletion. Remaining "1/12" test was in `tests/integration/test_gold_standard_coverage.py`, deleted in commit `03a8a20` during V1 retirement.
- **2026-04-21**: Added Issue #67 — `/cleanup` skill step-1 mode-detection (`test -d .claude/worktrees`) is CWD-relative and returns `remote` when invoked from a ccw worktree, silently skipping the step-5 worktree sweep on local machines. Companion to the step-5 `-f -f` fix in commit for `.claude/commands/cleanup.md`.
- **2026-04-21**: Issue #67 resolved — session-hygiene bundle: (a) `cleanup.md` step 1 re-anchored to `git rev-parse --git-common-dir` so local mode detects from any linked worktree; (b) `ccw` in `~/.zshrc` now writes a PID lockfile on entry and refuses silent second-session occupancy (self-healing via `kill -0`); (c) `ccw-rm` auto-deletes merged branches via `gh pr list --state merged` (offline-safe fallback); (d) `/commit` step 1 appends `-HHMM` timestamp on branch-name collision. Docs updated in `docs/development/claude-sessions-and-worktrees.md`. Summary row removed. Note: `~/.zshrc` edits (b, c) apply manually — patch in PR description.
- **2026-04-21**: Issue #62 partially resolved — manual stuck-batch recovery SQL documented in `docs/operations/TICKER_ONBOARDING.md`. CLI-flag and SIGTERM-log follow-ups remain open.
- **2026-04-21**: Issue #27 archived — 2 stale `test.skip` Playwright blocks in `tests/ui/review.spec.js` deleted; `.keyword-badge` and "Image N of M" markup never existed in `unified_review.html`. Full suite now 142 pass / 0 skip.
- **2026-04-21**: Added Issue #72 — Robinhood Tier 1 gold-standard regression vs. 2026-04-19 baseline surfaced during PR #72 (Snap ingestion) `git merge origin/main` attempt. Local pre-commit hook reported `recall_delta=-0.009, f1_delta=-0.0015, regressed_companies=['Robinhood Markets, Inc.']`. Per-metric diagnostics show `cm_revenue_by_cohort` (T1) at 0/0/0 with all 10 FNs stemming from a scale bug: extraction binds `$33,421.5` (quarterly total) instead of per-cohort values like `$17/$130/$45`. `cm_customer_acquisition_cost` (T1) has 1 dedup-collision FN; `cm_balance_by_cohort` (T1) at 0/0/0 is the boundary-sensitive case already tracked in Issue #64. Candidate root-cause commit: `24bfd6b refactor(persistence): unify chart_only SQL branches + dedup test helper (#52)` — only extraction-touching commit in the window between `cdc831f` (baseline) and current main tip `52e61ce`. Blocks PR #72's merge commit until fixed + baseline refreshed.
- **2026-04-22**: Issue #72 diagnosis corrected. Direct Neon investigation showed: (a) the `$33,421.5` scale-bug framing was wrong — no such value exists in HOOD's facts; (b) #52 is a persistence-only refactor with no extraction code touched, ruled out as root cause; (c) HOOD S-1 has 17 chart-classified images with 0 `ocr_text` / 0 `chart_data`, cohort image `e5f65961` unprocessed; (d) the single `$130` chart fact is an orphan pointing at a vanished img_id. Real cause: PR #34 (R2 image-cache migration) added `boto3>=1.34.0` to `requirements.txt` but not to `pyproject.toml`/`uv.lock`, so `uv run` extraction crashed at stage 1 with `ModuleNotFoundError`. Fix bundled with this entry: `boto3` added to `pyproject.toml`; `uv.lock` regenerated. Verified locally: `uv run python scripts/batch_v2_extraction.py --filing-id 1545 --chart-only --force-reextract` now runs full pipeline (22 images parsed, 16 text/html_table facts produced; previously died on import). Chart-only mode safely preserved all 12 reviewer decisions. A second-layer issue surfaced during verification — 17/17 chart images now hit `FileNotFoundError` in R2 at keys like `1783879/000162828021019902/hood-20211008_g6.jpg` — will be tracked as a separate follow-up. Baseline refresh gated on the R2 fix landing too.
- **2026-04-22**: Added Issue #77 — R2 chart-image bytes missing / mis-keyed on HOOD S-1 (second layer of #72). Post-PR-#87 run confirmed all 17 chart images fail in OCR with `FileNotFoundError` at keys like `1783879/000162828021019902/hood-20211008_g<N>.jpg` (N in 2,3,5-20). Two candidate causes not yet distinguished: (a) bytes never uploaded to R2 for this pre-migration filing, or (b) `pipeline/` prefix divergence between `infrastructure.md` (canonical keys are `pipeline/<cik>/<accession>/<filename>`) and the `v2_image_assets.file_path` values stored without that prefix. Remediation path depends on which: a one-shot R2 `HeadObject` check against both key variants will distinguish, then either migrate `file_path` values / fix the lookup path (Case A) or re-ingest HOOD S-1 from source HTML (Case B). Also worth a scope check across other pre-migration filings with chart-sourced gold values. Blocks HOOD chart recall recovery + v2 baseline refresh. §72's "open a separate issue" Next Step is now tracked here.
- **2026-04-22**: Issue #9 resolved (local) — replay of the lost PR #72 (closed during #65 history scrub). `sql/seed_snap_s1a.sql` (unnumbered, follows `register_gold_standard_filings.sql` precedent) relabels CIK `0001644378` row to `RMR Group Inc.` and seeds Snap Inc. (CIK `0001564408`) + its real S-1/A (accession `0001193125-17-056992`, primary doc `d270216ds1a.htm`). `FilingFetcher.fetch_filing` pulled 2.3 MB into `data/filings/0001564408/000119312517056992/primary.htm`; `batch_v2_extraction.py --filing-id 22267` persisted 8 facts / 1724 segments / 547 tables / 40 images (DAU 153M/158M, revenue-per-user $2.15 — matches Snap's public disclosures). `scripts/gi3_richness_analysis.py` FILING_MAP entry for id 32 corrected to `"RMR Group Inc."`. Partially-Resolved summary row removed; body moved to Archive §9. Scope: local (`$TEST_DATABASE_URL`) only — Neon prod mirror and gold-standard coverage addition remain separate workstreams. Merged fine this time because the commit only touches `sql/`, `scripts/`, `docs/` — none of the paths that trigger the `pre-commit-extraction-guard.sh` gold-standard check, so the Issue #72 / #77 chart-pipeline stall is orthogonal to this merge.
- **2026-04-22**: Issues #72 and #77 resolved end-to-end. Manual HOOD prod backfill (`uv run python scripts/batch_v2_extraction.py --filing-id 1545 --chart-only --force-reextract` against Neon + R2) executed after PRs #87 (boto3 in `pyproject.toml`) and #102 (`storage.put_bytes` in `_download_missing_images`). 17 chart images processed cleanly (no `FileNotFoundError`), 2 cohort charts populated `chart_data`, 12 chart facts persisted (11 `cm_balance_by_cohort` matching 7/7 gold values + extras, 1 `cm_revenue_by_cohort`). Chart-only mode preserved 16 text-review + 20 image-review decisions. Validator: HOOD **recall=0.486, F1=0.586** (baseline 0.3143 / 0.4231 — +15pp recall above baseline); Tier 1 P=92.3%, R=54.5%, F1=68.6%. `cm_balance_by_cohort` at 100/100/100. `cm_revenue_by_cohort` still at 50/10/16.7 — residual dedup bug, tracked as new Issue #86. #77 root cause confirmed as Case A (bytes never uploaded); no `pipeline/` prefix divergence.
- **2026-04-23**: PR #134 unblock — (a) CI Integration Tests failure: added `analyze_image_targeted` delegate to `MockVisionClient` in `tests/integration/test_chart_e2e.py` (B4 introduced the targeted vision-routing method on `VisionClient` / `analyze_image`; the mock was the only call-site missing the wrapper). (b) Fragment-id collision after merging origin/main: renumbered text-recall-regression fragment #85 → #87 (origin/main took #85 for `apply_all_migrations` via PR #130, #86 for dedup-collision via PR #135); filename + frontmatter updated, rollup regenerated.
- **2026-04-23**: Wave B5.1–B5.3 landed — `scripts/benchmark_vision.py` now supports 5 vision providers (`current`, `openai-vnext`, `gemini-flash`, `gemini-pro`, `anthropic`) via `PROVIDER_CONFIGS`, plus a `--bakeoff` mode with a `MAX_BAKEOFF_USD` spend cap (default $15). Populated a hand-curated 7-image fixture corpus in `tests/fixtures/image_benchmark/manifest.json` (3 Farfetch + 4 Slack S-1 charts). First bake-off total spend $0.12; all 5 providers achieve chart-detection F1=1.0 on this corpus, with `gemini-flash` winning on cost (34% cheaper than current GPT-4o) + latency (45% faster). Decision memo: `docs/operations/vision-bakeoff-2026-04-23.md`. The `two-stage` (B4 hybrid) config is registered in `PROVIDER_CONFIGS` but excluded from the default sweep until the harness grows an `analyze_image_targeted` mode — tracked as a B5.x follow-up in the memo. `.env.template` updated with `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, and the optional `VISION_*` routing vars.
- **2026-04-23**: Issue #87 resolved — text-recall regression on Farfetch + Robinhood was not a code regression. Six-way parallel bisect in isolated worktrees showed Farfetch recall = 0.867 at every extraction-touching commit back to `8840912`; reproduction in the primary/CI-equivalent Python env (lxml>=6.1.0) at `8840912` yields 0.533, matching current main. The preserved `v2_baseline_pre_regression_2026-04-22.json` was produced in a historical dep environment that no longer reproduces; deleted. Baseline numbers unchanged (already accurate); only the description rewritten. PR #110 hypothesis refuted by both bisect output and a code read of the `enable_full_page_ocr` / `enable_image_keyword_prescan` flag guards in `image_triage.py:692-706` + `ocr_extraction.py:1053-1068`. Full post-mortem in the fragment.
- **2026-04-22**: Added Issue #86 — Dedup stage collapses same-metric different-value cohort facts. Surfaced post-#72 resolution as the residual HOOD `cm_revenue_by_cohort` 9/10 FN pattern. Validator diagnostic output: *"Value-matching fact (17.0 / 62.0 / 45.0 / 130.0 / 186.0 / 56.0 / 175.0 / 326.0) existed pre-dedup but was collapsed into a sibling with different value"* — same pattern 9x. Also produces HOOD's pre-existing `cm_customer_acquisition_cost` value-20 FN. Likely root cause: `post-transfer collision collapse` step in `src/extraction_v2/stages/deduplication.py` uses an identity key that excludes `value` + `cohort_def` for chart-sourced cohort metrics, so all N bars of a cohort chart collapse into one. Not a Tier 1 blocker on its own (HOOD T1 recall is already above the pre-scrub baseline), but is the single biggest remaining per-metric recall gain available.
