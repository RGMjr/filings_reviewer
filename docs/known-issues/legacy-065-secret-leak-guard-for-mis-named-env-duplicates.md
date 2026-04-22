---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 65
severity: n/a
slug: secret-leak-guard-for-mis-named-env-duplicates
source: legacy
status: archived
title: Secret-Leak Guard for Mis-Named Env Duplicates
touches: []
updated: '2026-04-22'
---

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
