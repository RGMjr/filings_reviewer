---
autonomy: n/a
discovered: '2026-04-21'
estimated: —
id: 76
note: Resolved in fresh-branch replay of PR #109
pr_refs: []
severity: low
slug: missing-integration-test-for-filings-list-reviewer-aggregate
source: legacy
status: archived
title: Missing Integration Test for Filings-List Reviewer Aggregate
touches: []
updated: '2026-04-22'
---

### Problem

`get_unified_filings_for_review` now UNIONs text + image decision tables and projects a `reviewers` array per filing, plus an optional `reviewer_ids` filter using `ARRAY_AGG(...) && ...`. Unit tests cover the route layer threading this kwarg, but there's no integration test asserting: (a) mixed-reviewer filings return distinct reviewers from both text and image sources; (b) the `&&` overlap filter correctly narrows the list without false positives; (c) filings with only NULL reviewer_ids render as an empty array. Without this test, a future CTE refactor could silently lose reviewers from one source.

### Next Steps

- Add `tests/integration/test_db_filings_reviewers.py` that seeds a filing with text decisions by Alice + image decisions by Bob, calls `get_unified_filings_for_review`, and asserts `row["reviewers"] == ["alice", "bob"]`.
- Add a second case: call with `reviewer_ids=["alice"]`, assert the filing is returned; call with `reviewer_ids=["zoe"]`, assert it is not.
- Add a third case: a filing with only NULL reviewer_id decisions (legacy image rows) returns `reviewers == []`.
