## Summary
<!-- Brief description of what this PR does -->


## Changes
<!-- Bullet points of key changes -->
-


## Test Plan

- [ ] Unit tests pass (`pytest tests/unit/ -x -q`)
- [ ] Integration tests pass (if applicable)
- [ ] Manual/UI testing completed for user-facing changes

---

## Extraction Code Checklist

<!--
Complete this section if the PR modifies `src/extraction_v2/**` or `config/metric_keywords.yaml`.
Mark items N/A otherwise.
-->

- [ ] **Gold standard validation passed locally OR N/A** — `python3 -m src.gold_standard.v2_validator --fail-on-regression` exits clean (the pre-commit hook enforces this, but confirm explicitly in the PR description if you skipped via `--no-verify`).
- [ ] **Decision log** — Added an entry in `docs/architecture/extraction-decisions.md` if this change alters extraction logic, adds/removes metrics, modifies classification thresholds, or fixes a bug that reveals a design decision. N/A otherwise.
- [ ] **Keyword config** — Followed `/metric-lifecycle` guidance for any `metric_keywords.yaml` edits. N/A otherwise.

### Decision Log Entry (if applicable)

<!--
**Decision:** [What was decided]
**Rationale:** [Why this approach]
**Date:** [YYYY-MM-DD]
-->
