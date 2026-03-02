## Summary
<!-- Brief description of what this PR does -->


## Changes
<!-- Bullet points of key changes -->
-


## Test Plan
<!-- How was this tested? -->
- [ ] Unit tests pass (`pytest tests/unit/`)
- [ ] Integration tests pass (if applicable)
- [ ] Manual testing completed


---

## Extraction Code Checklist

<!--
If this PR modifies extraction code, please review the checklist below.
Check items that apply, or mark N/A if this PR doesn't touch extraction.
-->

**Does this PR modify any of these paths?**
- `src/extraction/**`
- `src/extraction_v2/**`
- `config/metric_keywords.yaml`

If **yes**, please complete this checklist:

- [ ] **Decision Log**: Does this change warrant an entry in `docs/architecture/extraction-decisions.md`?
  - *Add an entry if: changing extraction logic, adding/removing metrics, modifying classification thresholds, or fixing a bug that reveals a design decision*

- [ ] **Gold Standard Validation**: Did you run `pytest -m gold_standard --gold-standard-mode=fresh -v`?
  - *Required for extraction changes to ensure no regression in extraction quality*

- [ ] **Keyword Config**: If modifying `metric_keywords.yaml`, did you follow the `/metric-lifecycle` guide?

### Decision Log Entry (if applicable)

<!--
If adding a decision log entry, paste a brief summary here:

**Decision:** [What was decided]
**Rationale:** [Why this approach]
**Date:** [YYYY-MM-DD]
-->


---

<!--
Note: This template serves as a gentle reminder for extraction changes.
Not all checkboxes need to be checked - use judgment based on the scope of changes.
-->
