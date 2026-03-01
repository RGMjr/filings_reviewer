---
description: Evaluate refactoring opportunities and compare implementation approaches with risk/benefit analysis
---

# Refactor Evaluator Skill

**Version:** 1.0.0
**Created:** 2025-12-12
**Purpose:** Evaluate refactoring opportunities and compare implementation approaches systematically

---

## Skill Overview

This skill evaluates whether a module needs refactoring, assesses multiple refactoring approaches, and recommends the best path forward. It produces:

- Complexity analysis (lines of code, cyclomatic complexity, coupling metrics)
- Multiple approach comparison (Approach A vs B vs C)
- Risk assessment for each approach
- Step-by-step migration path
- Rollback plan in case of issues

**When to use this skill:**
- When a module exceeds complexity thresholds (>500 lines, high coupling)
- Before major refactoring work (to evaluate options systematically)
- When deciding between "keep as-is" vs "refactor"
- When multiple refactoring approaches are possible

**When NOT to use this skill:**
- For modules under 300 lines with clear structure
- When refactoring approach is obvious
- For trivial code cleanup (formatting, naming)
- When time constraints don't allow for analysis

---

## Input Parameters

When invoking this skill, provide:

```yaml
target_module: "src/path/to/module.py"
complexity_concerns:
  - "970 lines, too large"
  - "Multiple responsibilities (parsing, filtering, scoring)"
  - "High coupling to 5+ other modules"
refactor_reason: "Extract helper modules to improve testability"
consider_approaches:
  - "Approach A: Extract to 3 helper modules"
  - "Approach B: Split into classes"
  - "Approach C: Keep as-is with inline refactoring"
constraints:
  - "Must maintain 95%+ test coverage"
  - "Cannot break existing API"
  - "Need to complete in 1-2 days"
```

---

## Refactoring Analysis Framework

### Phase 1: Complexity Assessment

**Metrics to Evaluate:**

1. **Lines of Code (LOC)**
   - Under 200 lines: Excellent (no refactoring needed)
   - 200-400 lines: Good (monitor for growth)
   - 400-700 lines: Consider refactoring
   - Over 700 lines: Strong refactoring candidate

2. **Cyclomatic Complexity**
   - Under 10 per function: Simple
   - 10-20 per function: Moderate (acceptable)
   - 20-40 per function: High (consider simplification)
   - Over 40 per function: Very high (refactor needed)

3. **Function Count**
   - 1-10 functions: Focused module
   - 10-20 functions: Moderate size
   - 20+ functions: Large (may need splitting)

4. **Dependency Coupling**
   - 0-3 imports: Low coupling (good)
   - 4-7 imports: Moderate coupling
   - 8-15 imports: High coupling (consider decoupling)
   - 15+ imports: Very high coupling (refactor candidate)

5. **Responsibilities Count**
   - 1 clear responsibility: SOLID compliant ✅
   - 2-3 related responsibilities: Acceptable
   - 4+ responsibilities: Violates Single Responsibility Principle ❌

### Phase 2: Refactoring Triggers

**When to refactor:**
- ✅ LOC > 500 AND complexity high
- ✅ Multiple distinct responsibilities (violates SRP)
- ✅ Testing is difficult (many mocks needed)
- ✅ Frequent bugs in the module
- ✅ Hard to understand/modify (takes >30min to comprehend)
- ✅ High coupling blocking parallel development

**When to defer refactoring:**
- ❌ Module works well, no bugs
- ❌ Test coverage already 95%+
- ❌ Low change frequency (touched <3 times/year)
- ❌ Refactoring would break many downstream dependencies
- ❌ Team lacks time for careful migration

### Phase 3: Approach Comparison

For each candidate approach, evaluate:

1. **Complexity Reduction**
   - How much will LOC decrease per module?
   - Will cyclomatic complexity improve?
   - Will responsibilities be clearer?

2. **Maintainability Improvement**
   - Easier to test?
   - Easier to understand?
   - More reusable components?

3. **Risk Level**
   - How much code needs to change?
   - How many tests need updating?
   - How likely are bugs introduced?
   - Can it be done incrementally?

4. **Effort Required**
   - Time estimate (hours/days)
   - Number of files affected
   - Amount of test refactoring

5. **Breaking Changes**
   - Does API change?
   - Do downstream modules need updates?
   - Is migration path clear?

---

## Refactor Evaluation Template

When this skill is invoked, generate this analysis:

```markdown
# Refactoring Evaluation: {module_name}

**Module:** `{file_path}`
**Current LOC:** {N} lines
**Evaluated:** {date}
**Evaluator:** Claude Code (Refactor Evaluator Skill v1.0)

---

## Executive Summary

**Recommendation:** {Refactor with Approach X | Keep as-is | Defer until {milestone}}

**Justification (TL;DR):**
{1-2 sentence summary of why this recommendation}

**If refactoring:**
- **Approach:** {Approach X name}
- **Effort:** {X-Y} hours ({N} days)
- **Risk:** {Low/Medium/High}
- **Priority:** {P1/P2/P3}

---

## Current State Analysis

### Complexity Metrics

| Metric | Current | Threshold | Assessment |
|--------|---------|-----------|------------|
| Lines of Code | {N} | 500 | {✅ Below / ⚠️ Near / ❌ Exceeds} |
| Functions | {N} | 20 | {✅ / ⚠️ / ❌} |
| Cyclomatic Complexity (avg) | {N} | 15 | {✅ / ⚠️ / ❌} |
| Import Count | {N} | 10 | {✅ / ⚠️ / ❌} |
| Responsibilities | {N} | 2 | {✅ / ⚠️ / ❌} |

**Overall Complexity Grade:** {A/B/C/D/F}

### Detailed Analysis

**Lines of Code:** {N} lines
- Code: {N} lines
- Comments: {N} lines
- Blank: {N} lines
- Assessment: {Under/At/Over} threshold

**Responsibilities Identified:**
1. {Responsibility 1} (lines {X-Y})
2. {Responsibility 2} (lines {X-Y})
3. {Responsibility 3} (lines {X-Y})

**Coupling Analysis:**
- Direct imports: {N} modules
- Reverse dependencies: {N} modules import this
- Coupling score: {Low/Medium/High/Very High}

**Most Coupled To:**
1. `{module_1}` ({N} references)
2. `{module_2}` ({N} references)
3. `{module_3}` ({N} references)

**Function Complexity Breakdown:**
| Function | LOC | Complexity | Assessment |
|----------|-----|------------|------------|
| {func_1} | {N} | {N} | {✅/⚠️/❌} |
| {func_2} | {N} | {N} | {✅/⚠️/❌} |
| {func_3} | {N} | {N} | {✅/⚠️/❌} |

**Most Complex Functions:**
1. `{function_name}` - {N} lines, complexity {N}
2. `{function_name}` - {N} lines, complexity {N}

---

## Refactoring Triggers Analysis

| Trigger | Present? | Severity | Notes |
|---------|----------|----------|-------|
| LOC > 500 AND high complexity | {Yes/No} | {High/Med/Low} | {Details} |
| Multiple responsibilities (SRP violation) | {Yes/No} | {High/Med/Low} | {Details} |
| Testing difficulty | {Yes/No} | {High/Med/Low} | {Details} |
| Frequent bugs | {Yes/No} | {High/Med/Low} | {Details} |
| Hard to understand/modify | {Yes/No} | {High/Med/Low} | {Details} |
| High coupling blocks parallel work | {Yes/No} | {High/Med/Low} | {Details} |

**Triggers Present:** {N} of 6
**Recommendation:** {Strong candidate / Moderate candidate / Weak candidate / Not a candidate}

---

## Refactoring Approaches

### Approach A: {Name (e.g., "Extract Helper Modules")}

**Strategy:** {1-2 sentence description of approach}

**Proposed Structure:**
```
Before (1 module):
src/review/candidate_generator.py (970 lines)

After (6 modules):
src/review/candidate_generator.py (~450 lines) - Orchestrator
src/review/number_parsing.py (~80 lines) - Number extraction
src/review/keyword_matching.py (~70 lines) - Keyword proximity
src/review/false_positive_filter.py (~65 lines) - False positive rules
src/review/context_extraction.py (~50 lines) - Context helpers
src/review/confidence_scoring.py (~220 lines) - Scoring logic
```

**Benefits:**
- ✅ {Benefit 1 with quantification}
- ✅ {Benefit 2}
- ✅ {Benefit 3}

**Drawbacks:**
- ⚠️ {Drawback 1}
- ⚠️ {Drawback 2}

**Complexity Reduction:**
- Main module: 970 → ~450 lines (-53%)
- Average module size: ~160 lines (well below 500 threshold)
- Cyclomatic complexity: Reduced by ~40% per module

**Effort Estimate:**
- Module extraction: 3-4 hours
- Test refactoring: 2-3 hours
- Integration testing: 1-2 hours
- **Total: 6-9 hours (1-2 days)**

**Risk Assessment:**
- **Risk Level:** {Low/Medium/High}
- **Risk Factors:**
  - {Risk 1 with mitigation}
  - {Risk 2 with mitigation}
- **Rollback Plan:** {How to revert if issues arise}

**Migration Path:**
1. {Step 1 with validation}
2. {Step 2 with validation}
3. {Step 3 with validation}

**Breaking Changes:** {None/Minimal/Significant}
- API changes: {None OR list of changes}
- Downstream impacts: {None OR list of affected modules}

---

### Approach B: {Name (e.g., "Split Into Classes")}

{Same format as Approach A}

---

### Approach C: {Name (e.g., "Keep As-Is")}

**Strategy:** Do not refactor; address issues through other means

**Rationale:**
- {Reason 1 why refactoring not worth it}
- {Reason 2}

**Alternative Improvements:**
- {Improvement 1 without refactoring}
- {Improvement 2 without refactoring}

**Risks of Not Refactoring:**
- ⚠️ {Risk 1 of deferring}
- ⚠️ {Risk 2 of deferring}

---

## Approach Comparison Matrix

| Criterion | Approach A | Approach B | Approach C |
|-----------|------------|------------|------------|
| **Complexity Reduction** | {High/Med/Low} | {High/Med/Low} | {N/A} |
| **Maintainability Gain** | {High/Med/Low} | {High/Med/Low} | {N/A} |
| **Test Impact** | {X tests affected} | {Y tests affected} | {0 tests} |
| **Effort (hours)** | {X-Y} | {X-Y} | {0} |
| **Risk Level** | {Low/Med/High} | {Low/Med/High} | {Low} |
| **Breaking Changes** | {Yes/No} | {Yes/No} | {No} |
| **Incremental?** | {Yes/No} | {Yes/No} | {N/A} |
| **Reversible?** | {Yes/No} | {Yes/No} | {N/A} |

**Scoring (1-5 scale, 5 = best):**
| Approach | Complexity | Maintainability | Risk (inverse) | Effort (inverse) | **Total** |
|----------|------------|-----------------|----------------|------------------|-----------|
| Approach A | {N} | {N} | {N} | {N} | **{Total}** |
| Approach B | {N} | {N} | {N} | {N} | **{Total}** |
| Approach C | {N} | {N} | {N} | {N} | **{Total}** |

**Winner by Score:** {Approach X}

---

## Recommendation

### Selected Approach: {Approach X}

**Why this approach:**
{2-3 paragraphs explaining why this approach is best given the tradeoffs}

**When to execute:**
- **Priority:** {P1/P2/P3}
- **Timing:** {Immediate / Next sprint / After {milestone}}
- **Blockers:** {None OR list of prerequisites}

**Success Criteria:**
- [ ] {Criterion 1 - measurable}
- [ ] {Criterion 2 - measurable}
- [ ] {Criterion 3 - measurable}

---

## Implementation Plan

### Phase 1: Preparation ({time estimate})

**Before starting refactor:**
- [ ] Create branch: `git checkout -b refactor/{module-name}`
- [ ] Document current API: List all public functions/classes
- [ ] Ensure 100% test coverage on module being refactored
- [ ] Create backup of current implementation
- [ ] Communicate to team (if shared module)

### Phase 2: Extract Modules ({time estimate})

**Step-by-step extraction:**

**Step 1: Extract {helper_1} ({time})**
- [ ] Create `src/{path}/{helper_1}.py`
- [ ] Move {functionality} to new module
- [ ] Add imports to original module
- [ ] Run tests → ensure all pass
- [ ] Commit: `git commit -m "Extract {helper_1}"`

**Step 2: Extract {helper_2} ({time})**
- [ ] Create `src/{path}/{helper_2}.py`
- [ ] Move {functionality} to new module
- [ ] Update imports
- [ ] Run tests → ensure all pass
- [ ] Commit

{Repeat for each extraction}

### Phase 3: Integration ({time estimate})

- [ ] Update all imports in downstream modules
- [ ] Run full test suite
- [ ] Update documentation (CLAUDE.md, docstrings)
- [ ] Run mypy type checking
- [ ] Manual smoke testing

### Phase 4: Validation ({time estimate})

- [ ] Verify test coverage ≥ original coverage
- [ ] Check for performance regressions
- [ ] Review code complexity metrics (should be improved)
- [ ] Get code review approval
- [ ] Merge to main branch

**Total Estimated Time:** {X-Y} hours

---

## Risk Management

### Risks and Mitigations

**Risk 1: {Risk description}**
- **Likelihood:** {Low/Medium/High}
- **Impact:** {Low/Medium/High}
- **Mitigation:** {How to prevent/minimize}
- **Contingency:** {What to do if it occurs}

**Risk 2: {Risk description}**
- **Likelihood:** {Low/Medium/High}
- **Impact:** {Low/Medium/High}
- **Mitigation:** {How to prevent/minimize}
- **Contingency:** {What to do if it occurs}

### Rollback Plan

**If critical issues arise:**

1. **Immediate rollback (< 1 hour):**
   ```bash
   git revert {refactor_commits}
   git push origin main
   ```

2. **Partial rollback (keep some improvements):**
   - Revert problematic extraction: `git revert {specific_commit}`
   - Keep working extractions
   - Fix issues in follow-up PR

3. **Forward fix (issues are minor):**
   - Fix bugs without reverting
   - Add missing tests
   - Document issues in follow-up ticket

**Decision criteria:**
- Rollback if: {Critical functionality broken OR tests failing OR performance degradation > 20%}
- Forward fix if: {Minor bugs OR edge cases OR documentation gaps}

---

## Testing Strategy

### Test Coverage Requirements

**Before refactoring:**
- Current coverage: {X}%
- Requirement: Coverage must not decrease

**During refactoring:**
- Each extracted module: 95%+ coverage
- Integration tests: Updated to cover new structure
- Original tests: Should pass with minimal changes

**After refactoring:**
- Target coverage: ≥ {original}%
- New tests for extracted modules: {N} tests
- Updated tests: {N} tests

### Test Refactoring Needed

**Tests that will need updates:**
1. `{test_file_1}` - {What needs to change}
2. `{test_file_2}` - {What needs to change}

**New test files to create:**
1. `tests/unit/review/test_{helper_1}.py` - {Coverage goal}
2. `tests/unit/review/test_{helper_2}.py` - {Coverage goal}

**Estimated test refactoring effort:** {X-Y} hours

---

## Downstream Impact Analysis

### Modules That Import This Module

**Direct importers ({N} modules):**
1. `{module_1}` - {How it uses the module}
2. `{module_2}` - {How it uses the module}

**Changes required:**
- {None OR specific changes needed}

**Effort to update downstream:** {X} hours OR {No changes needed}

### Documentation Updates

**Files that reference this module:**
1. `CLAUDE.md` - Update architecture diagram
2. `docs/architecture/extraction-pipeline.md` - Update descriptions
3. Docstrings in {N} files

**Effort to update docs:** {X} hours

---

## Validation Checklist

Before marking refactoring complete:

### Functionality
- [ ] All original tests pass without modification (or minimal modification)
- [ ] New tests added for extracted modules
- [ ] Integration tests verify modules work together
- [ ] Manual testing confirms behavior unchanged

### Code Quality
- [ ] Each module has single, clear responsibility
- [ ] LOC per module < 500 lines
- [ ] Average complexity per function < 15
- [ ] Type hints on all public functions
- [ ] Docstrings updated

### Coverage
- [ ] Overall coverage ≥ original coverage
- [ ] Each extracted module ≥ 95% coverage
- [ ] No untested code paths introduced

### Documentation
- [ ] CLAUDE.md updated with new architecture
- [ ] Docstrings explain extracted modules
- [ ] README updated (if user-facing changes)
- [ ] Migration guide (if breaking changes)

### Performance
- [ ] No performance regressions (benchmarks pass)
- [ ] Memory usage unchanged
- [ ] Import time acceptable

---

## Example: candidate_generator.py Refactoring

**Historical Context:**

The `candidate_generator.py` module was successfully refactored in 2025-12 using Approach A (Extract Helper Modules).

**Original State:**
- 970 lines of code
- Multiple responsibilities: number parsing, keyword matching, filtering, scoring
- Difficult to test individual components
- High complexity (avg 20+ per function)

**Refactoring Executed:**
- Extracted 5 helper modules
- Reduced to ~450 lines in main module
- Each helper < 100 lines
- Test coverage maintained at 98%

**Approach Used:**
```
Approach A: Extract Helper Modules
- number_parsing.py (55 statements, 95% coverage)
- keyword_matching.py (49 statements, 100% coverage)
- false_positive_filter.py (45 statements, 100% coverage)
- context_extraction.py (34 statements, 100% coverage)
- confidence_scoring.py (220 lines, 100% coverage)
```

**Results:**
- ✅ Main module reduced 53% (970 → 450 lines)
- ✅ Average module size: ~100 lines
- ✅ Each module has single responsibility
- ✅ Test coverage improved (98% → 98% maintained)
- ✅ Easier to test (isolated components)
- ✅ Easier to understand (clear boundaries)

**Effort:**
- Estimated: 6-9 hours
- Actual: ~8 hours
- On target ✅

**This is the gold standard for module extraction refactoring in this project.**

---

## Related Skills

- **code-module-grader**: Use after refactoring to verify improvement
- **implementation-planner**: Use to plan the refactoring work
- **test-coverage-analyzer**: Ensure coverage maintained during refactoring
- **completion-report-generator**: Document refactoring results

---

## Version History

**1.0.0** (2025-12-12)
- Initial skill creation
- Based on candidate_generator.py refactoring (Approach 2)
- Includes complexity analysis framework
- Provides approach comparison matrix
- Includes step-by-step migration path
- Risk assessment and rollback planning

---

## Notes

- This skill requires reading the target module to analyze complexity
- Recommendations are based on objective metrics (LOC, complexity, coupling)
- Always include "Keep As-Is" as Approach C for comparison
- Migration path should be incremental (small commits, tests pass after each step)
- Rollback plan is critical for production modules
- Reference candidate_generator.py refactoring as exemplar
