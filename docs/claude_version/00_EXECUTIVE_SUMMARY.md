# Executive Summary: V2 Production Readiness — Claude Version

**Date**: 2026-02-24
**Author**: Synthesized from Codex (15 files) and Antigravity (8 files) plans
**Current branch**: `v2-rewrite`
**Gold standard**: P=78.6%, R=79.2%, F1=78.9% (2026-02-24, confidence≥0.5)

---

## What Each Plan Gets Right (and Wrong)

### Codex Version (15 files, 10 workstreams)

**Gets right:**
- Checksum verification for migrations (WS-01): correct design, the `schema_migrations` ledger with SHA-256 checksums is exactly what's needed
- Non-blocking audit logging framing (WS-03): correctly identifies the synchronous `after_request` hook as a production risk
- Review query scalability (WS-04): correctly identifies `get_v2_facts_for_filing()` and `get_v2_filings_with_facts()` as unbounded full-table loads
- OCR robustness concern (WS-08): legitimate gap, though low-priority for initial production launch
- Separation of bootstrap vs. forward migrations: good operational discipline

**Gets wrong:**
- **8-engineer staffing**: This codebase is operated by 1–2 people with AI agent support. 10 workstreams across 8 engineers is fantasy planning.
- **7 evidence artifacts in `artifacts/readiness/`**: Governance overhead that creates work without improving the product. A green CI pipeline is the artifact.
- **4 release gates (A/B/C/D)**: Overkill. One release gate with 4 criteria is sufficient.
- **WS-09 (db.py modularization)**: Pure refactoring of a 4,000-line file during a hardening sprint is high regression risk for zero user-visible benefit.
- **WS-10 (extraction quality parity)**: Sets a quality *target* without knowing the current score. As of 2026-02-24, F1=78.9% already exceeds reasonable thresholds.
- **WS-02 (web auth alignment)**: CSRF + session hardening for an internal tool used by 1–2 operators is disproportionate. Defer.
- **Neither plan accounts for uncommitted WIP** on `v2-rewrite`: batch runner (511 lines), definition extraction stage, quality scoring, and migration 11 are all untracked.

### Antigravity Version (8 files, 7 PRDs)

**Gets right:**
- Pragmatic scope: PRD-01 through PRD-04 are mostly done (batch runner built, test DB working, recall at 78.9%)
- RWLO-E execution loop: good fit for AI-agent execution (Recon → Write → Lock → Evaluate → Operate)
- PRD-05 migration safety: simpler than Codex WS-01 but includes the key "failure test" (mutated SQL triggers checksum error)
- PRD-07 correctly identifies async audit logging as a web concern

**Gets wrong:**
- **Quality targets are stale**: PRD-03 targets F1=69.6% — already achieved at 78.9%. The work item is done.
- **PRD-01 (sequential bulk runner)**: Already built as `scripts/batch_v2_extraction.py` (511 lines, parallel via ProcessPoolExecutor, checkpointing, SIGINT handling). Do not rebuild.
- **PRD-04 (docs update)**: Docs are partially updated; migration counts and gold standard scores need refreshing. Not a standalone workstream.
- **PRD-06 (concurrent batch orchestration)**: Duplicates what `batch_v2_extraction.py` already does. Verify before building.
- **Does not mention CI pipeline**: No GitHub Actions workflow exists for `v2-rewrite`. This is a gap.
- **Does not mention pagination**: Unbounded queries exist in `db.py:3907` and `db.py:3946`. Not addressed.

---

## Current State Assessment (2026-02-24)

### Already built (do not rebuild)
| Item | Location | Status |
|------|----------|--------|
| Batch runner with SIGINT/resume | `scripts/batch_v2_extraction.py` | Built, uncommitted |
| Definition extraction stage | `src/extraction_v2/stages/definition_extraction.py` | Built, uncommitted |
| Quality scoring module | `src/extraction_v2/quality_scoring.py` | Built, uncommitted |
| Migration 11 (v2_metric_definitions) | `sql/11_v2_definitions.sql` | Built, uncommitted |
| V2 test suite | `tests/unit/extraction_v2/` | Built, uncommitted |
| Gold standard F1=78.9% | `data/gold_standard/v2_baseline.json` | Committed |

### Genuinely missing (must build)
| Gap | Risk if unaddressed |
|-----|---------------------|
| `apply_migrations.py` replays all SQL every run — no history tracking | Silent data corruption if schema drift occurs; idempotency relies on `IF NOT EXISTS` only |
| No GitHub Actions workflow for `v2-rewrite` | No automated regression detection on PRs |
| Audit logging is synchronous in `after_request` hook (`review_v2.py:46`) | DB hiccup blocks HTTP response; 30s timeout hangs reviewer session |
| `get_v2_filings_with_facts()` and `get_v2_facts_for_filing()` fetch all rows | Full-table load grows linearly with extraction history |
| WIP files not committed | Work is lost if branch is damaged; CI cannot test it |

### Intentionally deferred (not worth doing now)
| Item | Reason |
|------|--------|
| Web auth hardening (CSRF, sessions) | Internal tool, 1–2 operators, no external exposure |
| db.py modularization (4,000 lines) | High regression risk, zero user-visible benefit |
| Extraction precision (Snowflake per-tier FPs) | F1=78.9% is production-usable; 22/27 FPs are a known data issue |
| sec_client.py TODO cleanup | Trivially small, not blocking |

---

## Synthesis Rationale

The five work items that matter are:

1. **WI-01 Migration Safety**: Ingest the ledger-based approach from Codex WS-01, simplified to in-place rewrite of `apply_migrations.py` rather than a new script + directory restructure.
2. **WI-02 CI Pipeline**: Missing from both plans. GitHub Actions workflow for `v2-rewrite` is the most leveraged piece of infrastructure missing.
3. **WI-03 Land and Validate WIP**: Neither plan addresses the uncommitted WIP. Must commit and validate first.
4. **WI-04 Async Audit**: Fire-and-forget thread (not a queue manager). Codex WS-03 is over-engineered for a single `after_request` hook.
5. **WI-05 Review Pagination**: Codex WS-04 is correct but over-scoped. `limit`/`offset` on two existing methods is sufficient.

**Agent execution model**: Ralph loops with `--isolated` for risky changes (migrations, CI), standard Ralph for the WIP landing. No 8-engineer team. No PR templates. No artifact directories.

---

## Quality Gate (Single Gate)

Before merging `v2-rewrite` → `main`:
1. All Tier 1 items (WI-01 through WI-04) merged
2. CI pipeline green on `v2-rewrite`
3. Gold standard F1 ≥ 78.0% (1% regression tolerance from current 78.9%)
4. Batch runner `--dry-run --limit 50` completes without crash or unhandled exception
