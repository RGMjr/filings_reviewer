# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**M5-5: Presentation Gold Standard Annotation Session (earnings-call-exploration, 2026-03-11)**
- Discovered and fixed bug in `sec_presentation_source._get_8k_exhibits()`: exhibit type filter compared against icon type ("text.gif") instead of exhibit type — always returned 0 results. Also extended to accept `.htm` files alongside `.pdf`.
- EDGAR discovery redesigned: large tech companies don't file PDF presentations as 8-K exhibits; instead use `*exhibit99[0-9]*` filename pattern to find HTML earnings releases.
- Annotated 5 files: CRM (Q3+Q4 FY26), META (Q4 2025), SNAP (Q3+Q4 2025); 7 accepted annotations.
- Initial benchmark: **R=100.0%, P=36.8%, F1=53.8%** (7 annotations; CRM 100/100/100, META 100/100/100, SNAP 100/29/45). High FP rate on SNAP due to image-based investor letter (all text from alt-text in image tags).
- Baseline saved to `data/presentation_results/presentation_baseline.json`.
- Tests: 3664 unit tests pass (0 failures, 8 skipped); coverage 78.75%

**Phase D + M5 Tooling (earnings-call-exploration, 2026-03-03)**
- M5 gold standard tooling: `review_presentation_annotations.py`, `merge_presentation_annotations.py`, `validate_presentation_extraction.py` — mirrors transcript pipeline; 41 unit tests
- `preannotate_presentations.py` (M5-1) was already in place; completes the full preannotate→review→merge→validate cycle for presentations
- Phase D: `check_new_documents.py` (source monitoring, --json), checkpointing + --resume + --max-failures + SIGINT in both ingest scripts, `ingest_all.py` unified wrapper; 23 unit tests
- Docs: `docs/BATCH_INGESTION.md` (new), `docs/V2_MIGRATION_GUIDE.md` updated, CLAUDE.md updated
- Tests: 3659 unit tests pass (0 failures, 8 skipped); gold standard 6/6 pass, no extraction regressions
- M5-5 (sample annotation session on real PDFs) remains to be done interactively

**Phase C: Presentation Support (earnings-call-exploration, 2026-03-02, 72cd1c6 + 5b3b247)**
- `presentation_converter.py`: pdfplumber PDF→HTML (page→section, tables, images, title-slide detection)
- `sec_presentation_source.py`: EDGAR 8-K exhibit downloader with idempotent cache
- Section types: TITLE_SLIDE, KEY_METRICS, FINANCIAL_OVERVIEW, GUIDANCE, APPENDIX (migration 14)
- FP filter: suppresses TITLE_SLIDE/APPENDIX facts and bare integers <1000
- Period inference extended for slide title patterns ("Q4 FY2025 Results", "Full Year 2024")
- Tests: 3595 passing (37 converter, 19 source, 19 e2e); SEC gold standard unchanged (P=88.9%, R=63.7%)
- M5 (gold standard on real PDFs) deferred pending manual annotation

**ADBE FP Cluster Fix (earnings-call-exploration, 2026-03-02)**
- `_rule_revenue_as_arr` improved: compound "recurring revenue" escape + proximity tiebreaker for standalone "ARR". Handles "ARR of $578M and revenue of $4.15B" — "revenue" closer to $4.15B → correctly rejected.
- `_rule_percent_on_count_metric` added: rejects PERCENT on count-only metrics (MAU/DAU/customers). MAU/DAU escape: year-over-year context → legitimate growth rate preserved.
- ADBE FPs: 11 → 7 (4 fixed: 2 MAU adoption FPs + 2 revenue-as-ARR FPs). Remaining 7: revenue farther than 35 chars, bare decimal, "$2B" as Unit.COUNT (not CURRENCY).
- Overall benchmark improvement: **R=75.8%, P=74.2%, F1=75.0%** (from R=74.7%, P=70.1%, F1=72.3%)

**Phase A+ Cleanup: Scoring Bug Fix (earnings-call-exploration, 2026-03-02)**
- Fixed date key mismatch bug in transcript validator: added `_normalize_date()` to handle `M/DD/YY` format and strip `_HH_MM_SS` time suffixes from HTML filenames
- Normalized dates in ADSK_2025-02-27 and MSFT_2025-01-29 gold standard CSVs (was `2/27/25`, `1/29/25`)
- Previously, 4 files were silently unmatched (MSFT_2025-01-29, ADSK_2025-02-27, CRM_2019-12-03, CRM_2020-02-25); now 20/22 files match annotations
- Corrected benchmark (91 annotations, 20 files): **R=74.7%, P=70.1%, F1=72.3%** — all Phase A+ targets met (R≥65% ✓, P≥70% ✓, F1≥67% ✓)

**Phase A+ Stragglers (earnings-call-exploration, 2026-03-02)**
- Removed 3 phantom ADSK revenue_concentration annotations (text absent from HuggingFace transcript HTML)
- Added `almost` to APPROX_PREFIXES in value_binding.py — recovers META "almost a billion" FN
- Resolved 6 git merge conflicts across persistence.py, pipeline.py, value_binding.py, period_inference.py, false_positive_filter.py, db.py — all files parse cleanly

**Batch Ingestion E2E Test (earnings-call-exploration, 2026-03-01)**
- `scripts/ingest_transcripts.py` tested end-to-end with HuggingFace source
- 3 bugs fixed during E2E: field mapping (`symbol` not `ticker`), company upsert (partial unique index), persistence (v2_documents.doc_id is UUID, not filing_id)
- Added migration 13: expanded v2_segments section_type CHECK to include transcript types
- 6 transcripts (CRM + MSFT) persisted to local DB, 11 unique facts extracted
- FMP deferred; HuggingFace free source validated as working path

**Phase B complete. All targets met: R=72.9%, P=71.3%, F1=72.1%**

**V2 Production Promotion (2026-03-01)**:
- Merged PR #27 (v2-rewrite → main) via merge commit `2dd707e` — 155 commits
- Shared modules extracted: `src/shared/keyword_config.py`, `src/shared/models.py`
- V1 retirement: 12 extraction modules deleted, 8 scripts deleted, 31 test files deleted

**WP-15–22.5 (2026-02-28)**: FP rules, batch hardening, logging, UI parity, V1/V2 comparison script
- SEC gold standard: **P=92.8%, R=77.6%, F1=84.5%**; Migration 12: drop V1 FK constraints

## Current Focus

- **Phase D-FMP: FMP API source** — `FMPTranscriptSource` for broader transcript corpus
- **SEC: AOV wrong_period** — Farfetch period mismatch; WP-08 scope

## Test Status

- Unit tests: 3664 pass, 0 fail, 8 skipped; coverage 78.75% (2026-03-11)
- SEC gold standard: P=88.9%, R=63.7%, F1=74.2% (baseline 2026-02-28, unchanged)
- Transcript benchmark: R=75.8%, P=74.2%, F1=75.0% (91 annotations, 20 files; 2026-03-02)
- Presentation benchmark: R=100.0%, P=36.8%, F1=53.8% (7 annotations, 5 files; 2026-03-11)

## Key Learnings

**ADBE FP Fix:**
- MAU growth rates ("growing 23% YoY") are ACCEPTED in gold standard — blanket percent-on-count rule needs YoY escape for MAU/DAU
- "$2B" parsed as Unit.COUNT (value_raw="2B", not "$2B") — currency_on_count check misses it; would need Unit.COUNT suppression for large values
- Revenue-as-ARR proximity tiebreaker: "recurring revenue" compound phrase MUST be detected before applying distance calc (word order: recurring < revenue < value)

**Phase B:**
- OPERATOR section suppression cleanly eliminates boilerplate FPs without affecting transcript metrics
- Gaming/fintech keywords skipped — no matching canonical metrics exist; adding keywords without metrics is a no-op
- Baseline discrepancy: transcript_baseline.json showed P=62.9% vs CLAUDE.md's 70.1% — baseline.json was stale; re-anchor after each A+ session

**Transcript (from Phase A+):**
- MSFT converter bug: speaker-pattern check must run BEFORE section detection
- PYPL FP explosion (15 FPs, small bare numbers) — _BARE_SMALL_NUMBER_THRESHOLD raised to 400 for prepared_remarks

**V2 persistence (from WP-23):**
- `Document.doc_id` must be UUID not `str(filing_id)`; `v2_metric_facts` ON CONFLICT had no unique index — use delete-then-insert; apply migration 11 before batch
- `source_segments` has FK deps in migrations 07/08/09 — requires migration 12 before dropping

## Next Work (Prioritized)

1. **Presentation precision hardening** — SNAP FP rate is 71% (12 FPs on image-based investor letter). Consider suppressing extraction from image-only HTML (no meaningful text nodes), or raising FP thresholds for count metrics without explicit context.
2. **Phase D-FMP: FMP API source** — `FMPTranscriptSource` for broader transcript corpus
3. **SEC: AOV wrong_period** — Farfetch period mismatch; WP-08 scope

## Blockers or Warnings

- Farfetch chart FNs (8) require Vision API; not addressable in current test environment
- Production DB migration: run on staging first, verify SEC data unaffected
- Snowflake tables have many colspan/grid-gap warnings — extraction works but may have binding gaps; accepted for now

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 65 lines - distill, don't dump.
