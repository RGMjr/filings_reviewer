---
autonomy: n/a
discovered: 2026-04-22
estimated: XS
id: 79
note: Filter selector picks on status=open or partially-resolved
severity: low
slug: sweeper-picks-resolved-and-archived-issues
source: legacy
status: resolved
title: Nightly Sweeper Selector Picks Resolved/Archived Issues
touches:
- scripts/known_issues_selector.py
updated: 2026-04-23
---

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
