---
id: 323
source: gh
slug: metricfact-doc-id-field-semantic-confusion
title: MetricFact.doc_id dataclass field is semantically confused
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 323
note: Field named doc_id but holds Document UUID; never read, never persisted — misleading comment too.
---

### Problem

The `MetricFact` dataclass field at `src/extraction_v2/models.py:320` is
named `doc_id` with the comment `# Filing ID`, but its value is the
`Document.doc_id` UUID (populated from `context.document.doc_id` in
`src/extraction_v2/stages/fact_construction.py:229`). The DB-write path
(`_fact_to_params` in `src/extraction_v2/persistence.py:982`) ignores
`fact.doc_id` and uses the function's `filing_id` arg directly, so the
field is effectively dead but the naming is a trap for future readers.
Surfaced while resolving legacy-038.

### Next Steps

- Decide whether to rename the field, delete it, or re-purpose it to
  actually hold the filing_id; update the misleading `# Filing ID` comment.
- Sweep `fact.doc_id` and `MetricFact(doc_id=...)` callers (only test
  fixtures and `fact_construction.py:229` populate it).
