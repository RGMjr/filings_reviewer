---
description: Validate documentation accuracy against current codebase and flag stale or incorrect content
---

# Documentation Sync Validator Skill

**Version:** 1.1.0
**Created:** 2025-12-12
**Updated:** 2026-02-04
**Purpose:** Validate that documentation stays in sync with code as the project evolves

---

## Skill Overview

This skill validates documentation against the current codebase to detect staleness, inconsistencies, and outdated references. It produces:

- List of stale file references (files mentioned but don't exist)
- Outdated coverage percentages (docs say X%, actual is Y%)
- Incorrect line number references
- Outdated architecture diagrams
- Missing documentation for new features
- Recommendations for fixes

**When to use this skill:**
- After major refactoring (e.g., extracting modules)
- Before releases or milestones
- Quarterly documentation maintenance
- When onboarding reveals confusion
- After renaming files or restructuring

**When NOT to use this skill:**
- Immediately after creating new features (docs may lag intentionally)
- For minor code changes (formatting, comments)
- When no significant refactoring has occurred

---

## Input Parameters

When invoking this skill, provide:

```yaml
scope: "all" | "specific_docs"  # Validate all docs or specific files
doc_files:  # If scope is "specific_docs"
  - "CLAUDE.md"
  - "docs/architecture/system-overview.md"
check_types:  # What to validate
  - "file_references"     # Do referenced files exist?
  - "coverage_metrics"    # Are coverage %s current?
  - "line_numbers"        # Are line number references accurate?
  - "status_markers"      # Are "Complete" statuses accurate?
  - "module_structure"    # Does architecture match code?
strictness: "high" | "medium" | "low"  # How strict to be
output_format: "report" | "fixes"  # Report issues OR generate fixes
```

---

## Validation Framework

### Check Type 1: File References

**What to check:**
- File paths mentioned in docs exist in codebase
- Glob patterns like `src/review/*.py` match expected files
- Test files mentioned exist in `tests/` directory

**Examples of issues:**
```markdown
# STALE REFERENCE DETECTED
Doc: CLAUDE.md "Architecture" section
Reference: "src/review/candidate_generator.py (970 lines)"
Issue: File now 450 lines (refactored), doc says 970
Severity: Medium
Fix: Update to "src/review/candidate_generator.py (~450 lines)"
```

```markdown
# MISSING FILE DETECTED
Doc: docs/architecture/extraction-pipeline.md
Reference: "src/extraction/metric_parser.py"
Issue: File does not exist (maybe renamed or deleted?)
Severity: High
Fix: Update reference or remove section
```

---

### Check Type 2: Coverage Metrics

**What to check:**
- Coverage percentages in docs match actual coverage
- Test counts match actual test counts
- Module-specific coverage claims are accurate

**Examples of issues:**
```markdown
# OUTDATED COVERAGE METRIC
Doc: CLAUDE.md "Testing Standards" section
Claim: "Review modules: 56-97% coverage"
Actual: Review modules now 95-98% coverage
Severity: Medium
Fix: Update to current range

# INCORRECT TEST COUNT
Doc: DEVELOPMENT_PLAN.md
Claim: "386 tests passing"
Actual: 475 tests passing (89 more tests added)
Severity: Medium
Fix: Update test count and celebrate improvement
```

---

### Check Type 3: Line Number References

**What to check:**
- Line number references in docs still point to correct code
- Code at referenced lines matches doc description
- Ranges (e.g., "lines 123-135") are still accurate

**BEST PRACTICE:** Avoid hardcoded line number references in documentation. Instead use:
- Section names (e.g., "CLAUDE.md 'Architecture' section")
- Function/class names (e.g., "the `extract_metrics()` function")
- Code search patterns (e.g., "lines containing `@require_api_key`")

**Examples of issues:**
```markdown
# STALE LINE REFERENCE
Doc: docs/D1_IMPROVEMENTS_EVALUATION.md
Reference: "Line 247: flash() followed by abort(404)"
Issue: Code moved to line 198 after refactoring
Severity: Low (informational - may be historical)
Action: Replace with section reference or add note "(historical reference)"
```

---

### Check Type 4: Status Markers

**What to check:**
- Phases marked "Complete" have completion reports
- "In Progress" phases have recent commit activity
- "Not Started" phases haven't secretly started

**Examples of issues:**
```markdown
# COMPLETION STATUS MISMATCH
Doc: DEVELOPMENT_PLAN.md
Claim: "Review routes (D1) - COMPLETE"
Issue: No D1_IMPROVEMENTS_FINAL.md completion report found
Severity: High
Fix: Create completion report OR update status to "In Progress"

# OUTDATED PROGRESS
Doc: DEVELOPMENT_PLAN.md
Claim: "E1 Pattern Analyzer - IN PROGRESS"
Issue: E1 marked complete in E1_IMPROVEMENTS_TRACKING.md
Severity: Medium
Fix: Update status to "COMPLETE"
```

---

### Check Type 5: Module Structure

**What to check:**
- Architecture diagrams match actual file structure
- Module descriptions match actual responsibilities
- Dependency diagrams match actual imports

**Examples of issues:**
```markdown
# ARCHITECTURE MISMATCH
Doc: CLAUDE.md "Architecture" section (lines 9-22)
Claim: "src/review/candidate_generator.py # Generate review candidates"
Issue: Module now delegates to 5 helper modules (refactored)
Severity: High
Fix: Update to show modular architecture:
  candidate_generator.py (orchestrator)
  ├── number_parsing.py
  ├── keyword_matching.py
  ├── false_positive_filter.py
  ├── context_extraction.py
  └── confidence_scoring.py
```

---

## Validation Report Template

```markdown
# Documentation Sync Validation Report

**Generated:** {date}
**Scope:** {all docs | specific docs}
**Files Checked:** {N} documentation files
**Issues Found:** {N} issues ({X} high, {Y} medium, {Z} low)

---

## Executive Summary

**Overall Documentation Health:** {Excellent/Good/Needs Attention/Critical}

**Key Findings:**
- {Finding 1 with severity}
- {Finding 2 with severity}
- {Finding 3 with severity}

**Recommended Actions:**
- {Priority 1 action}
- {Priority 2 action}
- {Priority 3 action}

---

## Issues by Severity

### High Severity ({N} issues)

**Definition:** Issues that mislead developers or block understanding

#### Issue #1: {Title}

**Location:** `{doc_file}` - "{section_name}" section
**Type:** {File Reference | Coverage Metric | Status Marker | etc.}
**Problem:** {What's wrong}
**Impact:** {How this misleads developers}

**Current State (in docs):**
```markdown
{What the doc currently says}
```

**Actual State (in code):**
```python
{What the code actually is}
```

**Recommended Fix:**
```markdown
{What the doc should say}
```

**Priority:** {P1/P2/P3}
**Effort:** {5 min | 30 min | 1 hour | etc.}

---

### Medium Severity ({N} issues)

{Same format as high severity}

---

### Low Severity ({N} issues)

{Same format - these are informational or historical references}

---

## Issues by Document

### CLAUDE.md ({N} issues)

| Section | Type | Severity | Issue Summary | Fix Effort |
|---------|------|----------|---------------|------------|
| Testing Standards | Coverage | Medium | Coverage outdated (68% -> 71%) | 2 min |
| Architecture | Structure | High | Architecture diagram outdated | 15 min |

**Total Fix Time:** {X} minutes

---

### DEVELOPMENT_PLAN.md ({N} issues)

{Same format}

---

## Quick Wins (< 5 minutes each)

These issues can be fixed very quickly:

1. **Update coverage percentage** in CLAUDE.md "Testing Standards" section
   - Change: "68%" -> "71%"
   - Time: 1 minute

2. **Update test count** in DEVELOPMENT_PLAN.md
   - Change: "386 tests" -> "475 tests"
   - Time: 1 minute

3. **Fix file reference** in docs/architecture/extraction-pipeline.md
   - Change: "metric_parser.py" -> "value_extractor.py"
   - Time: 2 minutes

**Total Quick Win Time:** {X} minutes for {N} fixes

---

## Fix Priority Matrix

| Priority | Issues | Est. Time | When to Fix |
|----------|--------|-----------|-------------|
| P1 (Critical) | {N} | {X} hrs | Immediately (blocks understanding) |
| P2 (Important) | {N} | {X} hrs | This week (causes confusion) |
| P3 (Nice-to-have) | {N} | {X} hrs | Next maintenance cycle |

---

## Automated Fixes

The following fixes can be automated:

### Fix #1: Update Coverage Metrics

**Script:**
```bash
# Run coverage, extract percentage, update CLAUDE.md
pytest --cov=src --cov-report=term | grep "TOTAL" | awk '{print $4}' | sed 's/%//'
# Update CLAUDE.md "Testing Standards" section with new percentage
```

**Files affected:** 3
**Safety:** High (just numbers, low risk)

### Fix #2: Update Test Counts

**Script:**
```bash
# Count tests
pytest --collect-only -q | grep "test" | wc -l
# Update docs with count
```

**Files affected:** 2
**Safety:** High

---

## Manual Fixes Required

The following issues require human judgment:

### Issue #1: Architecture Diagram Outdated

**Location:** CLAUDE.md "Architecture" section
**Problem:** Doesn't reflect refactored candidate_generator.py structure
**Why Manual:** Need to decide level of detail to show
**Estimated Time:** 15 minutes

**Suggested Fix:**
Update architecture section to show:
```
src/review/                   # Human-in-the-Loop Review System
├── models.py                 # Data classes (ReviewCandidate, ReviewDecision, etc.)
├── candidate_generator.py # Generate review candidates (orchestrator, ~450 lines)
│   ├── number_parsing.py     # Extract and parse numbers (P1.3)
│   ├── keyword_matching.py   # Find metric keywords (P1.3)
│   ├── false_positive_filter.py # Filter false positives (P1.3)
│   ├── context_extraction.py # Extract context (P1.3)
│   └── confidence_scoring.py # Multi-signal confidence (220 lines)
```

---

## Validation Checklist

Use this to validate docs manually:

### File References
- [ ] All `src/` paths in CLAUDE.md exist
- [ ] All `tests/` paths in CLAUDE.md exist
- [ ] All `docs/` cross-references resolve
- [ ] Glob patterns (e.g., `src/**/*.py`) match expected files

### Metrics
- [ ] Coverage percentages current (within 2%)
- [ ] Test counts current (within 10 tests)
- [ ] LOC estimates current (within 20%)
- [ ] Module-specific coverage claims accurate

### Status Markers
- [ ] "Complete" phases have completion reports
- [ ] "In Progress" phases have recent commits
- [ ] Phase numbering sequential (no gaps like A1->A3)

### Architecture
- [ ] Directory structure matches diagrams
- [ ] Module descriptions match actual code
- [ ] Dependency diagrams match imports

### Line Numbers
- [ ] Avoid hardcoded line references (prefer section names)
- [ ] Historical references noted as historical
- [ ] Ranges still accurate (if used)

---

## Prevention Strategies

**To reduce documentation drift:**

1. **Update docs in same PR as code changes:**
   - Refactoring module? Update CLAUDE.md in same commit
   - Completing phase? Create completion report immediately

2. **Run validation quarterly:**
   - Schedule: Jan, Apr, Jul, Oct
   - Takes ~30 minutes
   - Prevents accumulation of drift

3. **Use CI to check:**
   - Script to verify file references exist
   - Script to extract coverage and compare to docs
   - Fail PR if major discrepancies

4. **Add validation to completion reports:**
   - When completing phase, validate related docs
   - Include "Updated documentation" in completion checklist

5. **Avoid hardcoded line numbers:**
   - Use section names instead: `CLAUDE.md "Architecture" section`
   - Use function/class names: `the extract_metrics() function`
   - Use search patterns: `grep -n "pattern" file.py`

---

## Skill Instructions

When this skill is invoked:

### Step 1: Scan Documentation

1. **Find all documentation files:**
   ```bash
   find . -name "*.md" -not -path "*/node_modules/*"
   ```

2. **Identify files to check:**
   - CLAUDE.md (always check)
   - DEVELOPMENT_PLAN.md (always check)
   - .claude/rules/*.md (context-specific rules)
   - docs/ directory files (if scope="all")
   - User-specified files (if provided)

### Step 2: Extract References

For each doc file:

1. **Extract file paths:**
   - Regex: `src/[a-zA-Z0-9_/]+\.py`
   - Regex: `tests/[a-zA-Z0-9_/]+\.py`
   - Glob patterns: `src/**/*.py`

2. **Extract metrics:**
   - Coverage percentages: `(\d+)%`
   - Test counts: `(\d+) tests`
   - LOC: `(\d+) lines`

3. **Extract line numbers:**
   - Format: `file.py:123`
   - Format: `lines 123-135`
   - **Flag these for conversion to section references**

4. **Extract status markers:**
   - "Complete"
   - "In Progress"
   - "Not Started"

### Step 3: Validate Against Codebase

For each reference:

1. **Check file exists:**
   ```bash
   test -f "src/path/to/file.py"
   ```

2. **Check coverage:**
   ```bash
   pytest --cov=src --cov-report=term
   ```

3. **Check line numbers (if still used):**
   ```bash
   sed -n '123p' src/path/to/file.py
   ```

4. **Check structure:**
   ```bash
   ls src/review/*.py  # Compare to docs
   ```

### Step 4: Categorize Issues

For each discrepancy:

1. **Assign severity:**
   - High: Misleading, blocks understanding
   - Medium: Outdated but not blocking
   - Low: Historical reference or minor

2. **Estimate fix effort:**
   - Quick win: < 5 minutes
   - Easy: 5-15 minutes
   - Medium: 15-60 minutes
   - Hard: > 1 hour

3. **Assign priority:**
   - P1: Fix immediately
   - P2: Fix this week
   - P3: Fix in next maintenance cycle

### Step 5: Generate Report

1. **Summary section:**
   - Total issues by severity
   - Total fix time estimate
   - Overall health grade

2. **Issues by severity:**
   - High/Medium/Low sections
   - Include recommended fixes

3. **Quick wins section:**
   - List all < 5 minute fixes
   - Encourage immediate action

4. **Prevention recommendations:**
   - Based on types of issues found
   - Suggest process improvements

---

## Usage Examples

### Example 1: Post-Refactoring Validation

**User Request:**
```
Use documentation-sync-validator skill to check:
- CLAUDE.md
- docs/architecture/system-overview.md

After refactoring candidate_generator.py (extracted 5 modules)
Focus on: file_references, module_structure
```

**Output:**
- Report showing 8 issues in CLAUDE.md
- Architecture diagram needs update (15 min)
- 5 quick wins (update LOC counts)

---

### Example 2: Pre-Release Validation

**User Request:**
```
Use documentation-sync-validator skill to validate:
- All docs (scope: "all")
- All check types
- Strictness: high

Before v2.0 release
```

**Output:**
- Comprehensive report with 23 issues
- P1: 3 issues (fix immediately)
- P2: 12 issues (fix this week)
- P3: 8 issues (defer)

---

### Example 3: Quarterly Maintenance

**User Request:**
```
Use documentation-sync-validator skill for:
- Quarterly doc maintenance
- Focus on: coverage_metrics, status_markers
- Output: fixes (generate fix patches)
```

**Output:**
- List of automated fixes
- Shell script to apply fixes
- Remaining manual fixes documented

---

## Best Practices

### For Accurate Validation

1. **Run after code changes:**
   - Post-refactoring (always)
   - Post-feature-completion
   - Before major milestones

2. **Use strict mode for releases:**
   - Catch all issues before releasing
   - High severity = blocker

3. **Track issues over time:**
   - Are same docs always stale?
   - Identify root causes

### For Efficient Fixes

1. **Do quick wins first:**
   - Builds momentum
   - Reduces issue count fast

2. **Batch similar fixes:**
   - Update all coverage metrics together
   - Update all file references together

3. **Automate where possible:**
   - Coverage metrics: automate
   - Test counts: automate
   - File existence: automate

### For Robust Documentation

1. **Use section names, not line numbers:**
   - Bad: `CLAUDE.md:42-49`
   - Good: `CLAUDE.md "Architecture" section`

2. **Reference functions/classes by name:**
   - Bad: `See line 150 of candidate_generator.py`
   - Good: `See the generate_candidates() function`

3. **Use grep patterns for dynamic lookups:**
   - `grep -n "def extract_metrics" src/extraction/*.py`

---

## Integration with Other Skills

**Use before this skill:**
- **completion-report-generator**: Complete work first
- **refactor-evaluator**: Finish refactoring first

**Use after this skill:**
- **implementation-planner**: Plan documentation fixes
- Update docs based on validation report

---

## Automation Opportunities

### CI Integration

```yaml
# .github/workflows/doc-validation.yml
name: Documentation Validation

on:
  pull_request:
    paths:
      - 'src/**/*.py'
      - 'tests/**/*.py'

jobs:
  validate-docs:
    runs-on: ubuntu-latest
    steps:
      - name: Validate file references
        run: python3 scripts/validate_doc_references.py
      - name: Check coverage metrics
        run: python3 scripts/check_coverage_in_docs.py
      - name: Report issues
        if: failure()
        run: echo "Documentation out of sync!"
```

---

## Version History

**1.1.0** (2026-02-04)
- Removed hardcoded line number references to CLAUDE.md
- Updated to use section names instead of line numbers
- Added best practices for avoiding line number references
- Added references to `.claude/rules/*.md` context-specific rules
- Updated examples to reflect current CLAUDE.md structure (109 lines)

**1.0.0** (2025-12-12)
- Initial skill creation
- Validates file references, coverage metrics, line numbers, status markers, architecture
- Generates priority matrix and quick wins list
- Includes automation scripts for common fixes
- Prevention strategies to reduce future drift

---

## Related Skills

- **completion-report-generator**: Create reports that document current state
- **refactor-evaluator**: Plan refactoring that will affect docs
- **code-module-grader**: Grade code quality (docs should reflect this)

---

## Notes

- This skill prevents embarrassing outdated documentation
- Run quarterly at minimum (more often during active development)
- Quick wins should be fixed immediately (< 5 minutes each)
- Automate coverage and test count updates
- Historical references should be labeled as "(historical)" to avoid confusion
- Major refactorings should include documentation update in same PR
- **Avoid hardcoded line number references** - use section names or function names instead
