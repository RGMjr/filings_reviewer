# WORKER PROMPT: Task GS-5 - CLAUDE.md Workflow Documentation

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GS-5
TASK NAME:     Document gold standard validation workflow in CLAUDE.md
WORKSTREAM:    Testing Infrastructure
SOURCE:        Gold Standard Regression Testing Framework Plan
STATUS:        COMPLETE
COMPLETION:    2026-01-01
TIME ESTIMATE: 20-30 minutes
TIME ACTUAL:   ~10 minutes
RISK LEVEL:    None (documentation only)
TASK SIZE:     XS
DEPENDS ON:    GS-2, GS-4
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════

## Objective

Add a section to CLAUDE.md documenting the mandatory gold standard validation workflow for keyword and extraction logic changes.

**Business Rationale**: Claude Code and developers need clear instructions on when and how to run gold standard validation. This ensures the testing process is followed consistently.

**Current Behavior**: No documented workflow for gold standard validation in CLAUDE.md.

**Desired Behavior**: CLAUDE.md contains a clear, mandatory workflow section that Claude Code follows when modifying keyword patterns or extraction logic.

## Prerequisites

- GS-2 complete (validation script enhanced)
- GS-4 complete (pytest integration available)

## Files to Modify

1. **`CLAUDE.md`** - Add Gold Standard Validation section

## Implementation Requirements

### Content to Add

Add a new section "## Gold Standard Validation" after the "Key Design Decisions" section:

```markdown
## Gold Standard Validation (Required for Keyword/Extraction Changes)

**When to Run**: Before committing changes to:
- `config/metric_keywords.yaml`
- `src/extraction/` modules
- `src/review/candidate_generator.py`
- `src/review/keyword_matching.py`

**Validation Workflow**:

1. **Quick Check** (during development):
   ```bash
   python scripts/validate_against_gold_standard.py --all --mode fresh --baseline
   ```
   Review delta: positive = improvement, negative = regression.

2. **Formal Validation** (before commit):
   ```bash
   pytest -m gold_standard --gold-standard-mode=fresh
   ```
   All tests must pass. Regressions cause test failures.

3. **If Regression Detected**:
   - Investigate false negatives (missed metrics)
   - Check if trade-off is intentional (precision vs recall)
   - If intentional, document rationale in commit message
   - If unintentional, fix before committing

4. **Update Baseline** (after intentional changes):
   ```bash
   python scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline
   ```
   Commit the updated `data/gold_standard/baseline_metrics.json`.

**Key Metrics**:
- **Precision**: % of generated candidates that are correct
- **Recall**: % of gold standard metrics that were found
- **F1**: Harmonic mean of precision and recall

**Thresholds**:
- Regression tolerance: 1% (configurable via `--tolerance`)
- Tests fail if any metric drops below baseline - tolerance
```

### Placement

- Add after "Key Design Decisions" section (line ~45)
- Before "Documentation" section

### Formatting

- Use consistent markdown formatting with rest of file
- Include copy-pasteable commands
- Keep concise but complete

## Acceptance Criteria

- [ ] "Gold Standard Validation" section added to CLAUDE.md
- [ ] "When to Run" lists affected files
- [ ] Quick check command documented
- [ ] Formal validation command documented
- [ ] Regression handling workflow documented
- [ ] Baseline update command documented
- [ ] Key metrics explained
- [ ] Thresholds documented
- [ ] Commands are copy-pasteable

## Do NOT

- Remove or modify other sections of CLAUDE.md
- Add redundant documentation
- Include implementation details (keep user-focused)

## Verification Commands

```bash
# Check section exists
grep -q "Gold Standard Validation" CLAUDE.md

# Check all key commands are present
grep -q "validate_against_gold_standard.py" CLAUDE.md
grep -q "pytest -m gold_standard" CLAUDE.md
grep -q "update-baseline" CLAUDE.md
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Verification for Task GS-5: CLAUDE.md Documentation
set -e

echo "═══════════════════════════════════════════════════════════════════════════════"
echo "Verifying Task GS-5: CLAUDE.md Workflow Documentation"
echo "═══════════════════════════════════════════════════════════════════════════════"

cd "/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings Analysis/Filings review tool/filings_reviewer"

echo "Checking: Gold Standard Validation section exists..."
grep -q "Gold Standard Validation" CLAUDE.md

echo "Checking: Quick check command documented..."
grep -q "validate_against_gold_standard.py.*--baseline" CLAUDE.md

echo "Checking: pytest command documented..."
grep -q "pytest -m gold_standard" CLAUDE.md

echo "Checking: Update baseline command documented..."
grep -q "update-baseline" CLAUDE.md

echo "Checking: metric_keywords.yaml mentioned..."
grep -q "metric_keywords.yaml" CLAUDE.md

echo "═══════════════════════════════════════════════════════════════════════════════"
echo "All acceptance criteria verified for Task GS-5!"
echo "═══════════════════════════════════════════════════════════════════════════════"
```

## Critical Evaluation Phase

**Required for all tasks. Depth scales with task size (XS = quick scan).**

After verification passes but BEFORE committing:
1. Quick scan for obvious issues
2. Verify commands match actual implementation
3. **User Approval (REQUIRED)** - STOP and ask user before proceeding
4. Commit and Push

## Reference

- **Issue source**: Gold Standard Regression Testing Framework Plan
- **Dependencies**: GS-2, GS-4
- **Related**: CLAUDE.md Key Design Decisions

---

**Last Updated**: 2025-12-31
**Format Version**: 2.4
