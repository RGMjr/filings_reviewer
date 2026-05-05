---
id: 504
source: gh
slug: text-decision-source-field-check-cleanup
title: Drop rejection_reason/reviewer_notes from text_decision_phrase_findings CHECK constraint
status: open
severity: low
autonomy: review
estimated: XS
touches:
  - sql/202605011906_add_text_decision_analysis.sql
discovered: 2026-05-05
updated: 2026-05-05
gh_issue: 504
note: deferred follow-up to PR 4 of the text-decision worth-doing plan; cutover depends on row-retention behaviour
---

### Problem

After PR 4 (`feat(text-analysis): drop free-text n-gram mining`), `scripts/analyze_text_decision_patterns.py` no longer writes `text_decision_phrase_findings` rows with `source_field IN ('rejection_reason', 'reviewer_notes')`. The CHECK constraint at `sql/202605011906_add_text_decision_analysis.sql:58` still permits all three legacy values to keep historical rows valid; the dead values stay in the constraint until historical rows age out.

### Next Steps

After historical rows have been observably absent for ≥4 weeks of analysis runs, file a follow-up timestamped migration to drop the dead values from the CHECK constraint. Verify the table is clean before applying:

```sql
SELECT count(*) FROM text_decision_phrase_findings
WHERE source_field IN ('rejection_reason', 'reviewer_notes');
```

Must return zero. If not, investigate before dropping.

Autonomy is `review` (not `safe`) because the right cutover moment depends on retention behaviour the sweeper can't observe alone.
