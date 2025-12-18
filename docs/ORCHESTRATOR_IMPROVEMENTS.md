# Orchestrator System Improvement Recommendations

**Created**: 2025-12-17
**Last Updated**: 2025-12-18
**Purpose**: Recommendations to enhance the task orchestration system based on GOLDMINE_REMEDIATION_PLAN experience

---

## Current System Assessment

### Strengths
✅ Clear separation: Architect (delegator) vs Worker (executor)
✅ Template v2.1 is concise and requirements-focused (vs v1.0's 434 lines)
✅ Explicit metadata: time estimates, risk levels, parallel execution
✅ Verification commands are copy-pasteable
✅ "Do NOT" section prevents conflicts

### Gaps Identified
While creating the goldmine remediation plan with 18 tasks, I identified several opportunities to improve the orchestrator workflow.

---

## Recommended Improvements

### 1. Add Dependency Visualization to Template

**Problem**: Task dependencies are described in text but not structured.

**Current** (instructions_orchestrator.md line 100-107):
```markdown
## State Tracking

After each task is assigned, update your mental model:
- Which tasks are complete (✅)
- Which tasks are in progress (🔵)
- Which tasks are now unblocked and available
- What the critical path is
```

**Recommendation**: Add structured dependency tracking to WORKER_PROMPT_TEMPLATE.md

**Add to template header block** (after line 27):
```markdown
DEPENDS ON:    [Comma-separated task IDs] (e.g., "L1, L2" or "None")
UNLOCKS:       [Tasks that become available after this one] (e.g., "L4, L5, L6")
BLOCKS:        [Tasks blocked by this one] (e.g., "L3" or "None")
```

**Benefits**:
- Orchestrator can auto-compute critical path
- Easy to identify parallel execution opportunities
- Workers understand why task is/isn't available

**Example**:
```markdown
TASK ID:       GR-5
DEPENDS ON:    GR-4 (tiered thresholds must exist)
UNLOCKS:       GR-10 (validation can run with new pipeline)
BLOCKS:        GR-10 (validation needs pipeline integration)
```

---

### 2. Add Task Size Categories

**Problem**: "2-3 hours" estimates don't communicate task complexity.

**Recommendation**: Add SIZE field to categorize tasks

**Add to template header** (after TIME ESTIMATE):
```markdown
TASK SIZE:     [XS | S | M | L | XL] (XS=<30min, S=30min-2hr, M=2-4hr, L=4-8hr, XL=>8hr)
```

**Usage**:
- **XS** (Quick Win): Lower threshold (15 min implementation + 15 min testing)
- **S** (Small): Add pattern list (1-2 hours)
- **M** (Medium): Tiered threshold system (4 hours)
- **L** (Large): New module with tests (6-8 hours)
- **XL** (Extra Large): Should be split into smaller tasks

**Benefits**:
- Architects can suggest "want a quick win? try GR-8 (XS)"
- Better sprint planning (mix of S/M/L tasks)
- Flag XL tasks for decomposition

---

### 3. Add Progress Tracking Commands

**Problem**: No standard way to track completion across multiple tasks.

**Recommendation**: Add progress tracking section to plan documents

**Add to all plan documents** (after "Task Breakdown"):
```markdown
## Progress Tracker

**Last Updated**: 2025-12-17

| Task ID | Status | Assignee | Started | Completed | Notes |
|---------|--------|----------|---------|-----------|-------|
| GR-1    | ✅     | Claude   | 12-17   | 12-17     | Deployed to prod |
| GR-2    | 🔵     | Claude   | 12-17   | -         | In progress |
| GR-3    | 🟡     | -        | -       | -         | Ready |
| GR-4    | ⚪     | -        | -       | -         | Blocked by GR-3 |

**Legend**: ⚪ Blocked | 🟡 Ready | 🔵 In Progress | ✅ Complete | ❌ Cancelled
```

**Update instructions_orchestrator.md**:
```markdown
## After Task Assignment

1. Update the Progress Tracker table in the plan document
2. Change task status from 🟡 READY → 🔵 IN PROGRESS
3. Add assignee name and start date
4. Save the plan document
5. Generate worker prompt
```

**Benefits**:
- Visual progress tracking
- Easy to see what's available vs blocked
- Historical record of who did what

---

### 4. Add "PARALLEL WITH" Auto-Suggestions

**Problem**: Architect must manually determine which tasks can run in parallel.

**Recommendation**: Add parallel execution hints to template

**Already exists in v2.1!** (line 26):
```markdown
PARALLEL WITH: [Other tasks that can run simultaneously, or "None"]
```

**Enhancement**: Add to instructions_orchestrator.md:

```markdown
## Suggesting Next Task (Enhanced)

When user completes a task:

1. **Mark task complete** in Progress Tracker
2. **Check UNLOCKS field** - which tasks are now unblocked?
3. **Check PARALLEL WITH** - which tasks can run with those unblocked?
4. **Suggest options**:
   - "GR-2 is now ready. It can run in parallel with GR-3 and GR-6."
   - "Would you like to work on GR-2 next, or should I generate prompts for all 3 parallel tasks?"

## Multi-Task Assignment

If user wants to work on parallel tasks:

1. Generate WORKER PROMPT for each task
2. Number them: "### Task 1/3: GR-2", "### Task 2/3: GR-3", etc.
3. User can assign each to different workers or queue them
```

**Benefits**:
- Maximize parallelization
- Architect actively suggests parallel work
- Faster completion of phases

---

### 5. Add Acceptance Criteria Verification Script

**Problem**: Workers manually check each acceptance criterion.

**Recommendation**: Generate verification script from acceptance criteria

**Add to template** (after Verification Commands):
```markdown
## Auto-Generated Verification Script

**Copy this entire block to verify all acceptance criteria:**

```bash
#!/bin/bash
# Auto-generated from acceptance criteria for Task [ID]
# Run this script to check all requirements

set -e  # Exit on any error

echo "Verifying Task [ID]: [Name]"
echo "=================================="

# Criterion 1: [Description]
echo "✓ Checking: [criterion]..."
[verification command]

# Criterion 2: Test coverage
echo "✓ Checking: Test coverage ≥ [X]%..."
TEST_DATABASE_URL="..." pytest ... --cov-report=term | grep "TOTAL.*[X]%"

# Criterion 3: Type safety
echo "✓ Checking: mypy passes..."
mypy [files] --strict

# All tests pass
echo "✓ Running full test suite..."
TEST_DATABASE_URL="..." pytest tests/unit/[module]/ --no-cov -q

echo "=================================="
echo "✅ All acceptance criteria verified!"
```
\`\`\`

**Example for GR-2**:
```bash
#!/bin/bash
set -e
echo "Verifying GR-2: Subscriber Patterns"
echo "===================================="

echo "✓ Checking: 4 subscriber patterns added..."
grep -q "subscribers?" src/extraction/segment_enricher.py || exit 1

echo "✓ Checking: Test coverage ≥ 90%..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  pytest tests/unit/extraction/test_segment_enricher_usage_tiered.py \
  --cov=src.extraction.segment_enricher --cov-report=term | grep "TOTAL.*9[0-9]%"

echo "✓ Running subscriber pattern tests..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  pytest tests/unit/extraction/test_segment_enricher_usage_tiered.py \
  -k subscriber -v

echo "===================================="
echo "✅ GR-2 verification complete!"
```

**Benefits**:
- One-command verification
- Fewer mistakes (forget to check criterion)
- Easier code review

---

### 6. Add "Quick Win" Fast-Track

**Problem**: Some tasks are 15-30 minutes but treated same as 4-hour tasks.

**Recommendation**: Add quick win workflow to orchestrator

**Add to instructions_orchestrator.md**:
```markdown
## Quick Win Fast-Track

For tasks with TIME ESTIMATE <1 hour AND RISK LEVEL = NONE:

**Streamlined Process**:
1. Skip formal worker prompt generation
2. Provide 2-3 sentence summary of task
3. List files to modify and what to change
4. Provide verification command
5. User executes immediately

**Example**:
```
User: "I want a quick win"
Assistant: "GR-8 is a 1-hour quick win with zero risk:
- Add NaN/Inf validation in src/extraction/segment_enricher.py line 1033
- Import math, check math.isnan(score) or math.isinf(score), return 0.0
- Add 2 tests for NaN and Inf cases
- Verify: pytest tests/unit/extraction/test_segment_enricher.py -k nan

Ready to execute?"
```

**Criteria for Fast-Track**:
- Time estimate ≤1 hour
- Risk level = NONE
- No dependencies (or all dependencies complete)
- Clear, simple implementation
```

**Benefits**:
- Momentum from quick completions
- Less overhead for simple tasks
- Better developer experience

---

### 7. Add Risk-Specific Instructions

**Problem**: MEDIUM/HIGH risk tasks need extra care but no specific guidance.

**Recommendation**: Add risk-level templates

**Add to WORKER_PROMPT_TEMPLATE.md**:
```markdown
## Risk Level Guidelines

### NONE / LOW Risk Tasks
- Standard workflow applies
- Single reviewer sufficient

### MEDIUM Risk Tasks
**Additional Requirements**:
- [ ] Create feature flag for rollback (if logic change)
- [ ] Add integration test covering rollback scenario
- [ ] Test on staging environment before production
- [ ] Document rollback procedure in task completion
- [ ] Two reviewers required

**Example Feature Flag**:
```python
# For GR-5 (pipeline integration - MEDIUM risk)
class ExtractionConfig:
    enable_tiered_selection: bool = True  # Set False to rollback

if config.enable_tiered_selection:
    # New tiered logic
else:
    # Old single-threshold logic (fallback)
```

### HIGH Risk Tasks
**Flag for Decomposition**:
- HIGH risk usually means task is too large
- Suggest: "This task is HIGH risk. Should we break it into smaller tasks?"
- If keeping HIGH risk:
  - [ ] Create detailed rollback plan
  - [ ] Feature flag required
  - [ ] Staging deployment mandatory
  - [ ] A/B test if possible
  - [ ] Three reviewers required
  - [ ] Document all risks in completion report
```

---

### 8. Add Completion Report Template

**Problem**: No standard format for documenting completed work.

**Recommendation**: Add COMPLETION_REPORT_TEMPLATE.md

**Create new file**: `docs/COMPLETION_REPORT_TEMPLATE.md`
```markdown
# Task [ID] Completion Report

**Task Name**: [Full name]
**Completed**: [YYYY-MM-DD]
**Completed By**: [Name]
**Time Actual**: [Hours] (estimated: [Hours])
**Files Changed**: [Count]

## Summary

[2-3 sentences: what was done]

## Changes Made

### Files Modified
- `path/to/file.py` ([N] lines changed)
  - [Brief description of changes]
  - [Key functions/classes added]

### Files Created
- `path/to/newfile.py` ([N] lines)
  - [Purpose of new file]

## Test Coverage

- **Tests Added**: [N] new tests
- **Coverage Before**: [X]%
- **Coverage After**: [Y]%
- **Coverage Delta**: +[Y-X]%

## Verification

- [ ] All acceptance criteria met
- [ ] All tests passing
- [ ] mypy --strict passes
- [ ] No regressions
- [ ] Code reviewed
- [ ] Deployed to [staging/production]

## Impact

**Before**:
- [Metric before change]
- [Problem example]

**After**:
- [Metric after change]
- [Improvement achieved]

## Lessons Learned

- [What went well]
- [What was challenging]
- [What would be done differently]

## Next Steps

- [Follow-up tasks unlocked]
- [Recommendations for future work]
```

**Update instructions_orchestrator.md**:
```markdown
## After Task Completion

1. Update Progress Tracker (status ✅, completion date)
2. Ask worker to create completion report using template
3. Save report to `docs/completion_reports/[TASK-ID]_completion.md`
4. Check UNLOCKS field → suggest next tasks
```

---

### 9. Add Batch Task Assignment

**Problem**: For highly parallel phases, generating 5 prompts one-by-one is tedious.

**Recommendation**: Support batch prompt generation

**Add to instructions_orchestrator.md**:
```markdown
## Batch Task Assignment

If user says "generate prompts for GR-2, GR-3, GR-6, GR-7":

**Output Format**:
```markdown
# Batch Assignment: 4 Parallel Tasks

These tasks can all run in parallel (no dependencies).

---

## Task 1/4: GR-2 - Subscriber Patterns

[Full worker prompt]

---

## Task 2/4: GR-3 - Usage Definition Boost

[Full worker prompt]

---

## Task 3/4: GR-6 - Platform Patterns

[Full worker prompt]

---

## Task 4/4: GR-7 - Engagement Patterns

[Full worker prompt]

---

**Execution Strategy**:
- Assign each task to different worker, OR
- Queue all tasks for single worker
- Each task is independently verifiable
- All tasks contribute to same milestone (e.g., Phase 1)
```
\`\`\`

**Architect Checklist for Batch**:
- [ ] Verified all tasks have no interdependencies
- [ ] Verified all have completed prerequisites
- [ ] Numbered tasks clearly (1/4, 2/4, etc.)
- [ ] Listed execution strategy
```

---

### 10. Add Plan Health Check

**Problem**: No way to validate plan document before using it.

**Recommendation**: Add health check script

**Create**: `scripts/validate_plan.py`
```python
#!/usr/bin/env python3
"""Validate plan document structure and dependencies."""

import re
import sys
from pathlib import Path

def validate_plan(plan_path: Path) -> list[str]:
    """Return list of issues found."""
    issues = []
    content = plan_path.read_text()

    # Check for required sections
    required_sections = [
        "Task Breakdown for Orchestrator/Architect",
        "Dependency Graph",
        "Success Criteria"
    ]
    for section in required_sections:
        if section not in content:
            issues.append(f"Missing required section: {section}")

    # Extract all task IDs
    task_pattern = r'\*\*ID\*\*:\s*([A-Z]+-\d+)'
    task_ids = set(re.findall(task_pattern, content))

    # Check dependencies reference valid tasks
    dep_pattern = r'\*\*Prerequisites\*\*:.*?([A-Z]+-\d+)'
    for match in re.finditer(dep_pattern, content):
        dep_id = match.group(1)
        if dep_id not in task_ids:
            issues.append(f"Task {dep_id} referenced but not defined")

    # Check all tasks have required fields
    task_sections = content.split('#### ')[1:]  # Split by task headers
    for task in task_sections:
        if '**ID**:' not in task:
            issues.append(f"Task missing ID field")
        if '**Time Estimate**:' not in task:
            issues.append(f"Task missing Time Estimate")
        if '**Risk Level**:' not in task:
            issues.append(f"Task missing Risk Level")

    return issues

if __name__ == "__main__":
    plan_file = Path(sys.argv[1])
    issues = validate_plan(plan_file)

    if issues:
        print(f"❌ Found {len(issues)} issues in {plan_file.name}:")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)
    else:
        print(f"✅ {plan_file.name} is valid")
        sys.exit(0)
```

**Usage**:
```bash
python scripts/validate_plan.py docs/GOLDMINE_REMEDIATION_PLAN.md
```

**Add to instructions_orchestrator.md**:
```markdown
## Before Starting a Plan

1. **Validate plan structure**:
   ```bash
   python scripts/validate_plan.py docs/[PLAN].md
   ```

2. **Check for issues**:
   - Missing sections
   - Invalid task references
   - Circular dependencies
   - Missing required fields

3. If validation fails, inform user of issues
```

---

## Implementation Priority

### Phase 1: Critical Improvements (Do First) ✅ COMPLETE (2025-12-18)
1. **Dependency Visualization** ✅ - Added DEPENDS ON, UNLOCKS, BLOCKS fields to template v2.3
2. **Progress Tracker** ✅ - Added Progress Tracker table format to orchestrator instructions
3. **Task Size Categories** ✅ - Added TASK SIZE field (XS/S/M/L/XL) to template v2.3

**Effort**: 2-3 hours to update templates and orchestrator instructions
**Actual**: ~1 hour (implemented 2025-12-18)

### Phase 2: Quality of Life (Do Soon)
4. **Parallel Suggestions** - Maximize efficiency
5. **Batch Assignment** - Reduce overhead
6. **Quick Win Fast-Track** - Better developer experience

**Effort**: 3-4 hours

### Phase 3: Advanced Features (Nice to Have)
7. **Risk-Specific Instructions** - Better safety
8. **Completion Reports** - Better documentation
9. **Verification Scripts** - Fewer errors
10. **Plan Health Check** - Prevent bad plans

**Effort**: 5-6 hours

---

## Updated Template Example

Here's what the header would look like with all improvements:

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-2
TASK NAME:     Extend usage patterns to capture subscriber metrics
WORKSTREAM:    Pattern Coverage
SOURCE:        GOLDMINE_REMEDIATION_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    -
TIME ESTIMATE: 2 hours (research 30 min, implementation 60 min, testing 30 min)
TASK SIZE:     S (Small: 1-2 hours)
TIME ACTUAL:   -
RISK LEVEL:    LOW (additive patterns, no breaking changes)
DEPENDS ON:    None (standalone)
UNLOCKS:       GR-10 (validation can include subscriber patterns)
BLOCKS:        None
PARALLEL WITH: GR-1, GR-3, GR-6, GR-7 (all pattern additions are independent)
═══════════════════════════════════════════════════════════════════════════════
```

---

## Migration Path

### For Existing Plans

1. **Add Task Breakdown sections** (if missing)
2. **Add Progress Tracker table**
3. **Add SIZE and DEPENDS ON/UNLOCKS fields** to each task
4. **Validate** with health check script

### For New Plans

1. **Use enhanced template** from day one
2. **Run health check** before committing
3. **Update Progress Tracker** after each task

---

## Benefits Summary

| Improvement | Time Saved | Quality Impact | Developer Experience |
|-------------|------------|----------------|---------------------|
| Dependency Visualization | 20% on planning | Fewer conflicts | Clear prerequisites |
| Progress Tracker | 10% on coordination | Better visibility | Know what's available |
| Task Size Categories | 15% on planning | Better estimates | Right-sized tasks |
| Parallel Suggestions | 30% on execution | Faster completion | Less waiting |
| Batch Assignment | 40% on admin | Same | Less tedious |
| Quick Win Fast-Track | 50% for small tasks | Same | Momentum |
| Verification Scripts | 25% on verification | Fewer errors | Confidence |
| Completion Reports | 15% on documentation | Better history | Clear impact |

**Overall Impact**: 30-40% faster project execution with better quality and developer experience.

---

**Status Update** (2025-12-18):
- ✅ Phase 1 Complete - Dependency visualization, progress tracker, and task size categories implemented
- 🟡 Phase 2 Available - Parallel suggestions, batch assignment, quick win fast-track
- ⚪ Phase 3 Blocked by Phase 2 - Risk-specific instructions, completion reports, verification scripts, plan health check

**Recommended Next Steps**:
1. ~~Implement Phase 1 improvements~~ ✅ Complete (2025-12-18)
2. Apply new template (v2.3) to active plan documents
3. Implement Phase 2 improvements when workflow bottlenecks appear
4. Gather feedback and iterate on Phase 1 features
5. Roll out Phase 3 based on observed value

**Implementation References**:
- `docs/WORKER_PROMPT_TEMPLATE.md` - v2.3 with TASK SIZE, DEPENDS ON, UNLOCKS, BLOCKS fields
- `instructions_orchestrator.md` - Progress Tracker table format and dependency guidance
