---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 52
severity: n/a
slug: pg-dump-version-mismatch-silent-failure
source: legacy
status: archived
title: '`pg_dump` Version-Mismatch Silent Failure'
touches: []
updated: '2026-04-22'
---

New `scripts/check_pg_client_version.py` pre-flight that compares `pg_dump` major version against server major version and errors loudly on mismatch. `.claude/rules/infrastructure.md` gains a `### pg_dump client version` subsection documenting the PG16+ client requirement for Neon (PG15). Script confirmed the 14→15 mismatch on the reference machine. See commit `7848605`.
