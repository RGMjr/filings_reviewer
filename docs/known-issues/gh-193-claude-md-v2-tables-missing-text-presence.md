---
autonomy: safe
discovered: '2026-04-24'
estimated: XS
gh_issue: 193
id: 193
severity: low
slug: claude-md-v2-tables-missing-text-presence
source: gh
status: open
title: CLAUDE.md V2 tables list missing v2_text_metric_presence
touches:
  - CLAUDE.md
updated: '2026-04-24'
---

### Problem

`CLAUDE.md` (Database section, ~line 44) lists the V2 tables but is missing `v2_text_metric_presence`, which was added in `sql/46_v2_text_metric_presence.sql` (PR #182, merged 2026-04-24).

Future devs reading CLAUDE.md as the canonical project overview won't see this as a V2 table.

### Next Steps

- Add `v2_text_metric_presence` to the V2 tables list in `CLAUDE.md` (~L44).
- Audit whether other recent migrations (sql/42–46) introduced tables also missing from that list — `v2_image_metric_confirmations` and `v2_image_classifications` appear present already, but a sweep is cheap.
- Cross-check `docs/architecture/data-model.md` for the same drift.

### Origin

Surfaced during the migration-numbering convention PR (timestamp scheme + sql/46 collision triage). Out of scope for that PR; filed for follow-up.
