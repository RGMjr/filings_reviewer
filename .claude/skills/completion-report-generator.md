---
description: Generate comprehensive completion reports when phases or improvement initiatives finish
---

# Completion Report Generator Skill

**Version:** 1.0.0
**Created:** 2025-12-12
**Purpose:** Generate comprehensive completion reports when phases or improvement initiatives finish

---

## Skill Overview

This skill generates detailed completion reports following the SEC Filings Reviewer project's established pattern for documenting completed work. It produces:

- Comparison of original goals vs what was achieved
- Time analysis (estimated vs actual) with variance breakdown
- Lessons learned and insights for future work
- Follow-up items and deferred work
- Overall grade and assessment

**When to use this skill:**
- When completing a major phase (D1, D2, E1, etc.)
- When finishing a P1/P2/P3 improvement initiative
- When wrapping up a sprint or milestone
- When documenting what was accomplished for stakeholder review

**When NOT to use this skill:**
- For work still in progress (use tracking documents instead)
- For trivial bug fixes or minor changes
- When original plan doesn't exist (need baseline for comparison)

---

## Input Parameters

When invoking this skill, provide:

```yaml
phase_name: "D1" | "E1.P1" | "B3" | etc.
original_plan_file: "docs/D1_IMPROVEMENTS_TRACKING.md"
completion_date: "2025-12-10"
work_summary:
  - "Implemented 7 production improvements"
  - "Added 21 comprehensive unit tests"
  - "Achieved 94% route coverage"
time_data:
  - task: "P1.1 - Flash-before-abort fix"
    estimated: "1-2 hours"
    actual: "1.5 hours"
  - task: "P1.2 - Input validation"
    estimated: "2-3 hours"
    actual: "2.5 hours"
lessons_learned:
  what_went_well:
    - "TypedDict pattern worked excellently"
    - "Validation helpers are reusable"
  what_could_improve:
    - "Page overflow edge case discovered late"
  adjustments_for_future:
    - "Add edge case analysis earlier in planning"
follow_up_items:
  - "Implement P2 improvements before scale-up"
  - "Add monitoring for pagination edge cases"
overall_grade: "A" | "B" | "C" | etc.
justification: "2-3 paragraph assessment"
```

---

## Project Completion Report Patterns

Based on analysis of existing completion reports:

### Pattern 1: D1_IMPROVEMENTS_FINAL.md
```markdown
# D1 Review Routes: Final Completion Report

**Phase:** D1 - Review Routes Implementation
**Status**: ✅ Complete
**Completed:** 2025-12-10

## Original Goals vs Achieved

| Goal | Target | Achieved | Status |
|------|--------|----------|--------|
| Route coverage | 85%+ | 94% | ✅ Exceeded |
| Unit tests | 15+ | 21 | ✅ Exceeded |
| Production improvements | 4 | 7 | ✅ Exceeded |

## What Was Built

### Routes Implemented (7 total):
1. `filing_list()` - Paginated filing list
2. `review_filing()` - Main review interface
...
```

### Pattern 2: E1 P1/P2 Completion Summary
```markdown
## Priority 1: High-Impact (Before Production Use)

**Target**: Complete before deploying E1 to production workflow
**Total Estimate**: 7-9 hours
**Actual**: ~7 hours
**Status**: ✅ Complete (2025-12-10)

### P1.1 - Add P-Value Calculations

**Status**: ✅ Complete (2025-12-10)
**Estimate**: 2-3 hours
**Actual**: ~2.5 hours

{Details of what was implemented}
```

### Pattern 3: E2 Week Completion Summary
```markdown
# E2 Week 1 Completion Summary

**Week:** Dec 2-6, 2025
**Phase:** E2 - Rule Learning System
**Status:** ✅ Complete

## Achievements This Week

### A. Learned Rules Database Schema (A1) ✅
- Created `learned_rules` table
- Added indexes and constraints
- **Outcome:** Production-ready schema

### B. Rule Learning Algorithm (B1) ✅
- Implemented `LearnedRule` model
- Created learning logic
- **Outcome:** Functional rule discovery

## Time Analysis

| Task | Estimated | Actual | Variance |
|------|-----------|--------|----------|
| A1 Schema | 1-2 hrs | 1.5 hrs | On target |
| B1 Learning | 2-3 hrs | 2.5 hrs | On target |
| **Total** | **3-5 hrs** | **4 hrs** | **20% under** |
```

---

## Completion Report Template

When this skill is invoked, generate a report in this format:

```markdown
# {Phase Name} - Completion Report

**Phase:** {Phase identifier (D1, E1.P1, Sprint 3, etc.)}
**Status**: ✅ Complete
**Completed:** {completion_date}
**Original Plan:** {link to original plan file}

---

## Executive Summary

{2-3 paragraph summary of what was accomplished, how it went, and overall assessment}

**Overall Result:** {Exceeded expectations | Met expectations | Partially met | Needs follow-up}

---

## Original Goals vs Achieved

| Goal | Target | Achieved | Status | Notes |
|------|--------|----------|--------|-------|
| {Goal 1} | {Target metric} | {Actual metric} | ✅/⚠️/❌ | {Brief note} |
| {Goal 2} | {Target metric} | {Actual metric} | ✅/⚠️/❌ | {Brief note} |
| {Goal 3} | {Target metric} | {Actual metric} | ✅/⚠️/❌ | {Brief note} |

**Legend:**
- ✅ Exceeded or met target
- ⚠️ Partially met (acceptable)
- ❌ Not met (requires follow-up)

---

## What Was Built

### {Component/Feature 1}
**Objective:** {What this was supposed to accomplish}
**Outcome:** {What was actually built}
**Files:**
- `{file_path}` - {What was added/changed}
- `{test_file_path}` - {Test coverage details}

**Key Features:**
- {Feature 1}
- {Feature 2}
- {Feature 3}

### {Component/Feature 2}
{Repeat format}

---

## Time Analysis

### Summary

**Total Estimated:** {X-Y} hours
**Total Actual:** {Z} hours
**Variance:** {+/-} {percentage}% ({under/over} estimate)

**Interpretation:**
{Was this on target? Under? Over? Why?}

### Detailed Breakdown

| Task | Estimated | Actual | Variance | Notes |
|------|-----------|--------|----------|-------|
| {Task 1} | {X-Y} hrs | {Z} hrs | {+/-}% | {Why variance occurred} |
| {Task 2} | {X-Y} hrs | {Z} hrs | {+/-}% | {Why variance occurred} |
| **Total** | **{X-Y} hrs** | **{Z} hrs** | **{+/-}%** | |

### Estimation Accuracy by Priority

| Priority | Tasks | Estimated | Actual | Accuracy |
|----------|-------|-----------|--------|----------|
| P1 (Critical) | {n} | {X-Y} hrs | {Z} hrs | {+/-}% |
| P2 (Important) | {n} | {X-Y} hrs | {Z} hrs | {+/-}% |
| P3 (Future) | {n} | {X-Y} hrs | {Z} hrs | {+/-}% |

---

## Quality Metrics

### Test Coverage

**Before:** {X}%
**After:** {Y}%
**Improvement:** +{Y-X} percentage points

**Test Count:**
- Before: {N} tests
- After: {M} tests
- Added: {M-N} new tests

**Coverage by Component:**
| Component | Coverage | Tests | Status |
|-----------|----------|-------|--------|
| {component_1} | {XX}% | {N} tests | ✅/⚠️ |
| {component_2} | {XX}% | {N} tests | ✅/⚠️ |

### Code Quality

**Production-Ready Criteria:**
- [ ] All planned features implemented
- [ ] Test coverage ≥ {target}%
- [ ] No known critical bugs
- [ ] Documentation updated
- [ ] Integration tests passing
- [ ] Manual testing complete

**Grade:** {A+/A/B/C/D/F}

---

## Lessons Learned

### What Went Well ✅

1. **{Success category}**
   - {Specific success}
   - {Why it worked}
   - {How to replicate}

2. **{Success category}**
   - {Specific success}

3. **{Success category}**
   - {Specific success}

### What Could Be Improved ⚠️

1. **{Challenge category}**
   - {Specific challenge}
   - {Impact on timeline/quality}
   - {Root cause}

2. **{Challenge category}**
   - {Specific challenge}

### Adjustments for Future Estimates 📊

Based on this phase:

1. **{Estimation adjustment}**
   - Observation: {What we learned}
   - Adjustment: {How to estimate better next time}
   - Example: "Database migrations take 1.5x longer than estimated → add 50% buffer"

2. **{Process improvement}**
   - Issue: {What could be better}
   - Solution: {How to improve}

---

## Follow-Up Items

### Deferred Work (P2/P3)

**From original plan:**
- [ ] {P2 item deferred} - Target: {when}
- [ ] {P3 item deferred} - Target: {when}

**Newly discovered:**
- [ ] {New item 1} - Priority: {P1/P2/P3}
- [ ] {New item 2} - Priority: {P1/P2/P3}

### Issues Requiring Attention

**Critical (P1):**
- {None identified} OR {Critical issue with mitigation plan}

**Important (P2):**
- {Issue 1 with recommendation}
- {Issue 2 with recommendation}

**Nice-to-Have (P3):**
- {Enhancement 1}
- {Enhancement 2}

---

## Technical Debt Assessment

**New Technical Debt Introduced:**
- {None} OR {Specific debt with paydown plan}

**Technical Debt Paid Down:**
- {Refactoring completed}
- {Coverage improvements}
- {Documentation added}

**Net Technical Debt:** {Decreased/Unchanged/Increased slightly/Increased significantly}

---

## Overall Grade: {A+/A/B/C/D/F}

**Grading Criteria:**
- **A+/A**: Exceeded expectations, production-ready, minimal follow-up
- **B**: Met expectations, production-ready with minor polish needed
- **C**: Mostly met expectations, some P2 work before full production
- **D**: Partially met expectations, requires significant P1 work
- **F**: Did not meet expectations, major rework needed

**Justification:**

{2-3 paragraphs explaining the grade}

**Specific Achievements:**
- ✅ {Achievement 1}
- ✅ {Achievement 2}
- ✅ {Achievement 3}

**Areas for Improvement:**
- ⚠️ {Improvement area 1}
- ⚠️ {Improvement area 2}

**Overall Assessment:**
{Final 1-2 paragraph summary}

---

## Stakeholder Summary (TL;DR)

**For non-technical stakeholders:**

✅ **What we built:** {1-sentence description}
✅ **Time:** {X} hours ({on target/under/over} estimate)
✅ **Quality:** {Grade} - {Production-ready/Needs polish}
✅ **Next steps:** {1-sentence next action}

---

## Appendix

### Files Created/Modified

**New Files:**
- `{filepath}` ({LOC} lines) - {Purpose}
- `{filepath}` ({LOC} lines) - {Purpose}

**Modified Files:**
- `{filepath}` (+{N}/-{M} lines) - {What changed}
- `{filepath}` (+{N}/-{M} lines) - {What changed}

**Total Lines Changed:** +{N} / -{M}

### References

**Original Planning Documents:**
- [{Plan name}]({link})
- [{Tracking doc}]({link})

**Related Documentation:**
- [{Doc 1}]({link})
- [{Doc 2}]({link})

**Related Commits:**
- `{commit_hash}` - {commit message}
- `{commit_hash}` - {commit message}

---

**Report Generated:** {date}
**Generated By:** Claude Code (Completion Report Generator v1.0)
**Next Review:** {Next milestone or "N/A - phase complete"}
```

---

## Skill Instructions

When this skill is invoked, follow these steps:

### Step 1: Read Original Plan

1. **Read the original plan file** provided by user
2. **Extract original goals** from the plan:
   - Coverage targets
   - Time estimates per task
   - Success criteria
   - Deliverables planned
3. **Note the original scope** (P1/P2/P3 breakdown)

### Step 2: Gather Actual Results

1. **Read completed work:**
   - Test files to count tests added
   - Coverage reports if available
   - Implementation files to assess scope
2. **Calculate variances:**
   - Estimated time vs actual time per task
   - Planned scope vs delivered scope
   - Target metrics vs achieved metrics

### Step 3: Analyze Quality

1. **Assess test coverage:**
   - Before vs after improvement
   - Coverage by component
   - Test count growth
2. **Review production-readiness:**
   - Are all planned features complete?
   - Are tests passing?
   - Is documentation updated?
3. **Identify technical debt:**
   - New debt introduced
   - Debt paid down
   - Net change

### Step 4: Extract Lessons

1. **What went well:**
   - Look for successes in commit messages
   - Identify patterns to replicate
   - Note tools/approaches that worked
2. **What could improve:**
   - Look for challenges in git history
   - Note delays or blockers
   - Identify process gaps
3. **Estimation adjustments:**
   - Calculate actual variance from estimates
   - Identify categories where estimation was off
   - Suggest adjustment factors

### Step 5: Generate Report

1. **Populate template** with gathered data
2. **Write narrative sections:**
   - Executive summary (2-3 paragraphs)
   - Grade justification (2-3 paragraphs)
   - Overall assessment (1-2 paragraphs)
3. **Assign grade** based on:
   - Goals achieved vs planned
   - Quality of deliverables
   - Time variance
   - Production-readiness
4. **Create stakeholder summary** (non-technical TL;DR)

### Step 6: Validation

Before presenting the report, validate:

1. **All numbers are accurate:**
   - Time estimates match original plan
   - Actual times are provided by user or calculated
   - Coverage percentages are from real data
2. **Goals table is complete:**
   - All major goals from original plan included
   - Status indicators (✅/⚠️/❌) are accurate
   - Notes explain variances
3. **Lessons are actionable:**
   - Not vague ("communicate better")
   - Specific with examples
   - Include concrete adjustments
4. **Follow-up items are clear:**
   - Priority assigned (P1/P2/P3)
   - Target timeline provided
   - Responsibility noted

---

## Usage Examples

### Example 1: D1 Phase Completion

**User Request:**
```
Use completion-report-generator skill to create report for:

Phase: D1 - Review Routes
Original plan: docs/D1_IMPROVEMENTS_TRACKING.md
Completed: 2025-12-10

Results:
- Implemented 7 improvements (4 planned)
- 21 unit tests added (15 planned)
- 94% route coverage (85% target)
- Total time: 8.5 hours (estimate: 8-10 hours)

Lessons:
- TypedDict pattern excellent
- Page overflow edge case discovered late
```

**Output:** Full completion report in D1_IMPROVEMENTS_FINAL.md format

---

### Example 2: E1 P1 Improvements Completion

**User Request:**
```
Use completion-report-generator skill for:

Phase: E1 P1 Improvements
Original plan: docs/E1_IMPROVEMENTS_TRACKING.md (P1 section)
Completed: 2025-12-10

Results:
- 3 P1 improvements complete
- Estimate: 7-9 hours, Actual: ~7 hours
- P1.1: 2.5 hours (estimate 2-3)
- P1.2: 3 hours (estimate 3-4)
- P1.3: 1.5 hours (estimate 2)
- All tests passing (26 new tests)
- 99% coverage on statistical_tests.py
```

**Output:** Completion report with detailed time analysis

---

### Example 3: Sprint/Week Completion

**User Request:**
```
Use completion-report-generator skill for:

Phase: Sprint 3 - Pattern Analysis
Week: Dec 2-6, 2025
Original plan: docs/SPRINT_3_PLAN.md

Completed:
- A1 Schema (1.5 hrs, estimated 1-2)
- B1 Learning algorithm (2.5 hrs, estimated 2-3)
- Total: 4 hours (estimated 3-5)

Deferred:
- B2 Integration (moved to Sprint 4)
```

**Output:** Week/sprint completion summary

---

## Best Practices

### For Accurate Reports

1. **Use real data:**
   - Don't guess at coverage percentages
   - Get actual time from person who did work
   - Reference commit history for details

2. **Be honest about challenges:**
   - Document what didn't go well
   - Explain root causes
   - Suggest improvements

3. **Make lessons actionable:**
   - Not: "Communicate better"
   - Yes: "Add daily 15-min sync when working on interdependent tasks"

4. **Grade fairly:**
   - Don't inflate grades
   - Justify grade with specific evidence
   - Consider both scope and quality

### For Stakeholder Value

1. **Include TL;DR section:**
   - Non-technical summary
   - Key metrics highlighted
   - Clear next steps

2. **Quantify achievements:**
   - Use numbers (coverage %, test count, time)
   - Show before/after comparisons
   - Highlight "exceeded" results

3. **Address follow-up clearly:**
   - What's done vs what's deferred
   - Priority of remaining work
   - No surprises (critical issues surfaced early)

---

## Integration with Other Skills

**Before completion report:**
- Use **implementation-planner** to create original plan
- Use **code-module-grader** to assess quality during work
- Use **test-coverage-analyzer** to measure coverage improvements

**After completion report:**
- Feed lessons learned into next **implementation-planner** use
- Use estimation adjustments for future time estimates
- Archive report in `docs/` directory for reference

---

## Version History

**1.0.0** (2025-12-12)
- Initial skill creation
- Based on D1_IMPROVEMENTS_FINAL.md, E1 completion summaries, E2 week reports
- Includes time analysis, lessons learned, grade justification
- Supports phase completion, P1/P2/P3 completion, sprint completion
- Generates stakeholder-friendly TL;DR section

---

## Related Skills

- **implementation-planner**: Creates the original plan that this skill compares against
- **code-module-grader**: Provides quality assessment during work
- **test-coverage-analyzer**: Measures coverage improvements documented in report

---

## Notes

- This skill requires the original plan file to exist (baseline for comparison)
- Actual time data must be provided by user (skill can't measure this)
- Grade is subjective but should be justified with specific evidence
- Report should celebrate wins while being honest about challenges
- Always include actionable lessons, not vague platitudes
