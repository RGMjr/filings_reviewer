---
autonomy: n/a
discovered: '2026-04-21'
estimated: —
id: 71
note: Resolved in PR #108; retained for audit trail
pr_refs:
- 108
severity: low
slug: integration-tests-job-has-no-path-filter
source: legacy
status: archived
title: Integration Tests Job Has No Path Filter
touches: []
updated: '2026-04-22'
---

### Problem

`.github/workflows/ci.yml` runs the `integration-tests` job on every PR regardless of touched paths. UI E2E already has a conservative path filter (`ci.yml:49-69`) that skips the job when every changed path is under `docs/`, `.claude/`, `CLAUDE.md`, `README.md`, `.gitignore`, or `.github/CODEOWNERS`. Integration Tests has no equivalent, so docs-only and `.claude/`-only PRs still spin up Postgres 15, apply migrations, and run the full integration suite (~3–6 min). Net ~3–6 min wall-time save per docs-only PR.

### Next Steps

- Mirror the UI E2E filter structure (`ci.yml:49-69`) on the `integration-tests` job. Same allowlist (`docs/`, `.claude/`, `CLAUDE.md`, `README.md`, `.gitignore`, `.github/CODEOWNERS`) — err on the side of running when in doubt.
- Verify by opening a docs-only PR and confirming `Integration Tests` reports `skipped` in Actions.
- Do NOT remove Integration Tests from required status checks — a skipped job still counts as passing for branch protection, so the gate stays intact.
