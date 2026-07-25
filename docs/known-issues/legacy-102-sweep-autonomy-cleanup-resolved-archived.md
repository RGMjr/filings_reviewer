---
autonomy: n/a
discovered: '2026-04-24'
estimated: XS
id: 102
severity: low
slug: sweep-autonomy-cleanup-resolved-archived
source: legacy
status: archived
title: Resolved/Archived Issues Retain Non-`n/a` Autonomy — Sweep Logs Noisy
touches:
  - docs/known-issues/
updated: '2026-04-24'
---

### Problem

The nightly sweep emits a warning per issue when `status` is `resolved` or `archived`
but `autonomy` is still set to a selector value (`skip`, `safe`, `review`). As of
2026-04-24, at least 12 fragments trigger this: #9, #11, #27, #28, #34, #35, #49,
#60, #79, #85, #86, #88. The sweep still runs correctly, but the log output is noisy
and obscures real selector warnings.

### Next Steps

- For each flagged fragment, set `autonomy: n/a` (the canonical value for closed issues).
- Run the sweep selector locally to confirm zero warnings after the change.
- The nightly sweep can self-fix this (autonomy: safe, XS) — mark as a sweep candidate.
