# Known Issues and Future Improvements

This document tracks known issues, limitations, and planned improvements identified during extraction system development.

**Last Updated**: 2026-03-22

---

## 9. Snap Filing (ID 32/33) — Mislabeled Data (Validation DB Dependency Resolved)

**Status**: Partially resolved — validation DB dependency eliminated; Snap CIK fix still pending
**Severity**: Low (Snap not yet in gold standard; gold standard validation no longer DB-dependent)
**Discovered**: 2025-12-27 (HRV-5)
**Investigated**: 2026-03-19
**Updated**: 2026-03-19

### Problem

Filing ID 33 (and later reorganized to ID 32 in `gi3_richness_analysis.py`) is labeled "Snap"
but the CIK on record (`0001644378`) belongs to **RMR Group Inc.** (a REIT management company),
confirmed via SEC EDGAR API.

The local dev DB validation dataset was found to be **empty** as of 2026-03-19. The backup file
`filings_backup.dump` contains only schema, not data.

### Confirmed Facts

- Filing 33 CIK `0001644378` = RMR Group Inc. (confirmed 2026-03-19 via SEC API)
- Snap's correct CIK = `0001564408`, form S-1/A, filed 2017-02-27, accession `0001193125-17-056992`
- `gi3_richness_analysis.py` FILING_MAP comment was stale (said "IDs 31/33" were wrong; actually
  IDs 32/34 had RLX Technology / Vodka Brands data per GR-FINAL_VALIDATION.md 2025-12-26)

### Root Cause

CIK `0001644378` was mistakenly used for Snap instead of `0001564408` when originally ingested.

### Resolution (2026-03-19)

The empty local validation DB is no longer a blocker. Gold standard validation now runs in
**fresh mode** (`pytest -m gold_standard --gold-standard-mode=fresh -v`), which re-extracts
candidates directly from locally cached HTML files without requiring a populated database.

`test_gold_standard_regression.py` now supports `--gold-standard-mode=fresh`, making the
validation reproducible without any database setup. The `*.dump` pattern is now in `.gitignore`
to prevent accidentally committing production database dumps.

### Remaining (Low Priority)

- Upsert Snap with correct CIK `0001564408` and add to gold standard (separate task, not blocking)

### Partial Fix Applied (2026-03-19)

- Corrected stale comment in `gi3_richness_analysis.py` FILING_MAP
- Added inline note on Snap CIK pending fix

---

## 6. Gold Standard Coverage Tests Failing for Farfetch

**Status**: Open
**Severity**: Medium
**Discovered**: 2026-03-19

### Problem

Two tests in `tests/integration/test_gold_standard_coverage.py` were observed failing:
- `test_candidate_generation_finds_active_consumers`
- `test_candidate_generation_finds_number_of_orders`

These failures were seen during a full suite run and appear unrelated to recent context-type tracking changes.

### Likely Cause

Probably linked to the Farfetch document fetch issue (Issue #2 below) — if the HTML for the Farfetch filing isn't locally available, candidate generation finds nothing. May resolve once the 78 cloud-stored filings are re-fetched on Render.

### Next Steps

- Reproduce in isolation: `python3 -m pytest tests/integration/test_gold_standard_coverage.py -v`
- Confirm whether failure is due to missing HTML file or a pattern regression

---

## 7. Intermittent Deadlock in Extraction Pipeline Integration Test

**Status**: Open
**Severity**: Low (intermittent)
**Discovered**: 2026-03-19

### Problem

`tests/integration/extraction/test_extraction_pipeline_integration.py::TestExtractionPipelineIntegration::test_process_filing_success` intermittently fails with a PostgreSQL deadlock during test setup:

```
psycopg.errors.deadlock_detected: deadlock detected
DETAIL: Process A waits for AccessExclusiveLock on relation X; blocked by Process B.
        Process B waits for AccessExclusiveLock on relation Y; blocked by Process A.
```

Reproduced twice in succession during the 2026-03-19 test session.

### Likely Cause

Two test processes (or test fixtures) are acquiring table-level locks in different orders during setup, creating a deadlock cycle. Possibly triggered by running many integration test sessions in quick succession without full connection teardown between runs.

### Next Steps

- Investigate whether the extraction pipeline test's setup fixture is acquiring locks that conflict with other concurrent fixtures
- Check if adding retry logic on deadlock in the test setup would be sufficient

---

## 8. Connection Pool Exhaustion During Repeated Test Runs

**Status**: Open
**Severity**: Low (operational)
**Discovered**: 2026-03-19

### Problem

Running the integration test suite multiple times in quick succession causes PostgreSQL to hit its connection limit:

```
FATAL: sorry, too many clients already
```

This causes test setup failures (not code failures) and requires a `docker stop/start filings-postgres` to recover.

### Likely Cause

Connection pools from previous test sessions are not being fully closed before the next run starts. The `psycopg_pool` pool workers retry connections in background threads that outlive the pytest session.

### Next Steps

- Check if `DatabaseAdapter` needs an explicit `close()` call in integration test teardown
- Consider increasing PostgreSQL's `max_connections` setting in the Docker compose config as a short-term workaround

---

## 2. Low Farfetch Recall (12.5%)

**Status**: Partially Diagnosed
**Severity**: Medium
**Discovered**: 2026-01-01

### Problem

Only 1 of 8 non-chart Farfetch gold standard values matched during validation.

### Contributing Factors

1. ~~**Metric ID mismatch** (see Issue #1)~~ — resolved; gold standard IDs now aligned
2. ~~**URL issue**: `sec_html_url` for Farfetch resolves to a directory index (see Issue #6)~~ — resolved; re-fetch 78 cloud-stored filings on Render
3. **Value normalization differences**: Gold uses exact values, system may normalize differently
4. **Missing patterns**: Some keywords may not trigger candidate generation

### CAC Payback Period (FIXED)

The CAC payback period value "six" (months) was not being extracted:
- Pattern `\bpayback\s+period\s+(?:on|for)\s+cac\b` added to catch this variant
- Spelled-out number support added to handle "six"
- Now correctly generates candidate for `cm_cac_payback_period: six`

### Remaining Gaps

- Re-evaluate Farfetch recall after cloud re-fetch of 78 filings is complete
- Review Active Consumers, Number of Orders, Take Rate patterns once document fetch is working

---

## 3. Gold Standard Methodology Questions

**Status**: Needs Discussion
**Severity**: Low (process improvement)

### Questions Raised

1. **Metric taxonomy alignment**: Should gold standard use same IDs as extraction system?
2. **Chart value handling**: Current approach marks chart values as "chart" - should they be in separate file?
3. **Value normalization**: Gold uses various formats (800,500 vs 800500) - should normalize?
4. **Metric scope**: What exactly counts as "Active Customers" vs "Paid Customers"?

### Recommendation

Create a gold standard specification document that defines:
- Approved metric IDs (aligned with `config/metric_keywords.yaml`)
- Value normalization rules
- Chart vs text-extractable classification criteria

---

## 4. Spelled-Out Number Parsing Limitations

**Status**: Known Limitation
**Severity**: Low (edge case)

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

---

## 5. Revenue Synonym Context Gating

**Status**: Working as Designed
**Severity**: N/A (architectural decision)

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

---

## Summary

| Issue | Status | Priority | Effort | Impact |
|-------|--------|----------|--------|--------|
| Low Farfetch Recall | Open | Medium | Medium | Blocked pending cloud re-fetch |
| Gold Standard Methodology | Open | Low | Low | Process improvement |
| Spelled-Out Number Limits | Open | Low | High | Edge case coverage |
| Revenue Synonym Gating | Monitor | N/A | N/A | Working as designed |
| Gold Standard Coverage Tests Failing | Open | Medium | Low | Investigate once Farfetch re-fetch complete |
| Extraction Pipeline Deadlock | Open | Low | Low | Intermittent; investigate fixture lock ordering |
| Connection Pool Exhaustion | Open | Low | Low | Recover with docker restart; check pool teardown |
| Snap Filing Mislabeled (Issue #9) | Partially resolved | Low | Low | Snap not in gold standard; validation DB no longer required |

---

## Archive (Resolved Issues)

### Issue #1: Metric ID Mismatch Between Gold Standard and System

**Status**: ✅ Resolved (2026-03-16)

Gold standard CSV (`data/gold_standard/golden_set_251218.csv`) aligned to system taxonomy in `config/metric_keywords.yaml`. No remaining ID mismatches. See git log (2026-03-16) for full resolution details.

### Issue #6: FilingFetcher Downloads Directory Index Instead of Primary Document

**Status**: ✅ Resolved (2026-03-16)

`FilingFetcher` defaulted `sec_client` to `None` and guarded URL resolution behind `if self.sec_client:`, causing directory-index pages to be saved instead of actual filings. Fixed in `src/filing_fetcher/filing_fetcher.py` (lines 81, 295). 78 cloud-fetched filings need re-fetching on Render. See git log (2026-03-16) for full details.

---

## Change Log

- **2026-01-01**: Initial document created after VAL-1 validation
- **2026-01-01**: CAC payback period issue resolved (moved to "FIXED" section)
- **2026-03-16**: Added Issue #6 — FilingFetcher directory index bug
- **2026-03-16**: Issue #6 resolved — default SECClient creation + removed null guard; 78 cloud-fetched files need re-fetch
- **2026-03-16**: Issue #1 resolved — gold standard CSV updated to align with system taxonomy; no metric ID mismatches remain
- **2026-03-17**: Archived resolved Issues #1 and #6; updated Farfetch contributing factors to reflect resolutions
- **2026-03-19**: Added Issues #6–#8: Farfetch gold standard test failures, extraction pipeline deadlock, connection pool exhaustion
- **2026-03-19**: Issue #9 partially resolved — fresh mode validation eliminates DB dependency; `*.dump` added to `.gitignore`
