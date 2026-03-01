# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**Batch Ingestion E2E Test (earnings-call-exploration, 2026-03-01)**
- `scripts/ingest_transcripts.py` tested end-to-end with HuggingFace source
- 3 bugs fixed during E2E: field mapping (`symbol` not `ticker`), company upsert (partial unique index), persistence (v2_documents.doc_id is UUID, not filing_id)
- Added migration 13: expanded v2_segments section_type CHECK to include transcript types
- 6 transcripts (CRM + MSFT) persisted to local DB, 11 unique facts extracted
- FMP deferred; HuggingFace free source validated as working path

**Phase B complete. All targets met: R=72.9%, P=71.3%, F1=72.1%**

## Current Focus

Phase C: Presentation Support
- PDF-to-HTML converter (pdfplumber or docling)
- SEC 8-K presentation source
- Chart pipeline tuning for presentation charts
- Target: >40% recall on presentations

## Test Status

- Unit tests: 346+ pass (gold standard 6/6 pass); no regressions
- SEC gold standard: P=88.9%, R=63.7%, F1=74.2% (baseline 2026-02-28)
- Transcript benchmark: R=72.9%, P=71.3%, F1=72.1% (94 annotations, 16 files; 2026-03-01)

## Key Learnings

**Phase B:**
- OPERATOR section suppression cleanly eliminates boilerplate FPs without affecting transcript metrics
- Gaming/fintech keywords skipped — no matching canonical metrics exist; adding keywords without metrics is a no-op
- Baseline discrepancy: transcript_baseline.json showed P=62.9% vs CLAUDE.md's 70.1% — baseline.json was stale; re-anchor after each A+ session

**Transcript (from Phase A+):**
- MSFT converter bug: speaker-pattern check must run BEFORE section detection
- PYPL FP explosion (15 FPs, small bare numbers) — _BARE_SMALL_NUMBER_THRESHOLD raised to 400 for prepared_remarks

## Next Work (Prioritized)

1. **Phase C: Presentation Support** — PDF-to-HTML, 8-K source, chart tuning
2. **SEC: AOV wrong_period** — Farfetch period mismatch; WP-08 scope

## Blockers or Warnings

- Farfetch chart FNs (8) require Vision API; not addressable in current test environment
- Production DB migration: run on staging first, verify SEC data unaffected

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 60 lines - distill, don't dump.
