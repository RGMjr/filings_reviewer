---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 18
severity: n/a
slug: migration-checksum-mismatch-on-sql-01-create-schema-sql
source: legacy
status: archived
title: Migration Checksum Mismatch on `sql/01_create_schema.sql`
touches: []
updated: '2026-04-22'
---

Self-healed via V1 retirement merge (commit `03a8a20`); the gold-standard pytest fixtures that triggered the checksum guard were deleted along with the V1 review tables. No reconciliation action needed. See commit `03a8a20`.
