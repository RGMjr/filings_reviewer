---
id: 263
source: gh
slug: filing-fetcher-8k-exhibit-branch-duplication
title: FilingFetcher.fetch_filing duplicates 8-K exhibit-99-1 logic across cold-fetch and cached-backfill branches
status: open
severity: low
autonomy: safe
estimated: S
touches:
  - src/filing_fetcher/filing_fetcher.py
discovered: '2026-04-27'
updated: '2026-04-27'
gh_issue: 263
---

### Problem

`FilingFetcher.fetch_filing` (`src/filing_fetcher/filing_fetcher.py:339-390`) implements the 8-K exhibit-99-1 fetch in **two near-identical blocks**:

1. **Cold-fetch branch** (~line 339) — when `html_path` does not yet exist: download primary, call `get_exhibit_99_1_url`, fetch the exhibit, validate combined content, write.
2. **Cached-backfill branch** (~line 371) — when `html_path` exists but lacks the exhibit separator: read existing, call `get_exhibit_99_1_url`, fetch the exhibit, write combined.

Both branches share the same call to `sec_client.get_exhibit_99_1_url`, the same `session.get` + `raise_for_status`, and the same `f"{primary}\n{_EXHIBIT_SEPARATOR}\n{exhibit}"` concatenation pattern.

Every bug fix in this area requires matched edits across both branches. Recent precedent:

- **legacy-058** (PR #251) — added `get_exhibit_99_1_url` and the fetch+concat. Both branches needed the new code.
- **legacy-115** (PR #260) — added the PDF skip+warn guard. Both branches needed the gate.

The day someone forgets one branch, we ship a half-fix: the cold-fetch path behaves correctly but cached filings (the common case in re-extraction) do not, or vice versa. The duplication is invisible at the call site — there's no shared helper and no test that asserts the two branches stay in sync.

### Next Steps

- Extract a helper (sketch): `def _maybe_append_exhibit_991(self, base_html: str, html_path: Path, cik: str, accession_number: str, validate_combined: bool) -> str | None` that handles `get_exhibit_99_1_url` → PDF guard → fetch → concat → optional combined-content validation, returning the combined HTML or `None` on skip.
- Cold-fetch branch: call with `base_html=response.text`, `validate_combined=True`.
- Cached-backfill branch: call with `base_html=existing`, `validate_combined=False` (existing primary already validated when it was first written).
- Existing integration tests in `tests/integration/filing_fetcher/test_8k_exhibit_fetch.py` already cover both branches and should pass unchanged.

### Out of scope

This is a refactor, not a bug fix. Defer until someone is touching this code path for an unrelated reason — the duplication is a hazard, not a current breakage.
