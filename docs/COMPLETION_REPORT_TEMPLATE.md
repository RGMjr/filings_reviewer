# COMPLETION REPORT TEMPLATE (v1.0)

**Purpose**: Standard format for documenting completed task work. Creates a historical record of what was done, enabling knowledge transfer and future reference.

**When to Use**: After completing any task that has a worker prompt. Required for M/L/XL tasks; recommended for S tasks; optional for XS tasks.

---

# Task [ID] Completion Report

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:        [ID]
TASK NAME:      [Full name from worker prompt]
COMPLETED:      [YYYY-MM-DD]
COMPLETED BY:   [Name/Agent]
TIME ESTIMATE:  [From worker prompt]
TIME ACTUAL:    [Actual hours spent]
VARIANCE:       [+/-X hours] ([reason if significant])
FILES CHANGED:  [Count]
TESTS ADDED:    [Count]
═══════════════════════════════════════════════════════════════════════════════
```

## Summary

[2-3 sentences: What was done and the key outcome. Focus on business value delivered.]

## Changes Made

### Files Modified

| File | Lines Changed | Description |
|------|---------------|-------------|
| `path/to/file.py` | +X/-Y | [Brief description] |
| `path/to/test.py` | +X/-Y | [Brief description] |

### Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `path/to/new.py` | X | [Purpose] |

### Key Code Changes

[Bullet points of significant changes - what functions/classes were added/modified]

- **`function_name()`** - [What it does]
- **`ClassName`** - [What it does]
- **Config change** - [What was configured]

## Test Coverage

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Coverage % | X% | Y% | +Z% |
| Test Count | N | M | +K |
| Pass Rate | 100% | 100% | - |

### Tests Added

- `test_scenario_1` - [What it tests]
- `test_scenario_2` - [What it tests]
- `test_edge_case` - [What it tests]

## Verification Results

```bash
# Command run:
[exact command]

# Output summary:
[key output lines or "All N tests passed"]
```

### Acceptance Criteria Checklist

- [x] [Criterion 1 from worker prompt]
- [x] [Criterion 2 from worker prompt]
- [x] All new tests pass
- [x] All existing tests pass
- [x] mypy --strict passes
- [x] No regressions

## Evaluation Findings

### Code Quality
- [x] No linting/type issues
- [x] DRY followed
- [Notes if any]

### Test Assessment
- [x] Edge cases covered
- [x] Negative tests exist
- [Notes if any]

### Architecture Alignment
- [x] Follows CLAUDE.md patterns
- [Notes if any]

### Improvements Identified
1. **[Improvement 1]**: [Description] → [Implemented/Deferred/Rejected]
2. **[Improvement 2]**: [Description] → [Implemented/Deferred/Rejected]

### User Decisions
- Approved: [List of approved improvements]
- Deferred: [List of deferred items with reason]
- Rejected: [List of rejected items with reason]

### Suggested Follow-Up Tasks (from deferred items)
| Task ID | Description | Priority | Rationale |
|---------|-------------|----------|-----------|
| [PARENT-ID]-F1 | [From deferred improvement 1] | [Low/Medium/High] | [Why this should be done] |
| [PARENT-ID]-F2 | [From deferred improvement 2] | [Low/Medium/High] | [Why this should be done] |

*Note: Add these to plan document backlog or create worker prompts as appropriate.*

## Impact

### Before Task

- [Problem or limitation that existed]
- [Example of the issue]

### After Task

- [How the problem is solved]
- [Quantifiable improvement if available]

### Metrics (if applicable)

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| [Metric name] | X | Y | Z% |

## Lessons Learned

### What Went Well

- [Thing that worked well]
- [Approach that was effective]

### Challenges Encountered

- [Challenge 1] → [How resolved]
- [Challenge 2] → [How resolved]

### Recommendations for Future

- [Suggestion for similar tasks]
- [Technical debt identified]
- [Follow-up work needed]

## Unlocked Tasks

Tasks now available after this completion:

- **[Task ID]** - [Name] (was blocked by this task)
- **[Task ID]** - [Name] (prerequisite satisfied)

## References

- **Worker Prompt**: `docs/WORKER_PROMPT_TASK_[ID].md`
- **Plan Document**: `docs/[PLAN_NAME].md`
- **Related Commits**: [commit hash(es)]
- **PR/Review**: [link if applicable]

---

**Report Generated**: [YYYY-MM-DD HH:MM]
**Report Version**: 1.0
```

---

## Template Usage Guidelines

### Required Sections

Always include:
- Header block with metadata
- Summary
- Changes Made
- Test Coverage
- Verification Results
- Acceptance Criteria Checklist
- Evaluation Findings (code quality, tests, architecture, improvements, user decisions)

### Optional Sections

Include when relevant:
- **Impact**: When task has measurable business impact
- **Lessons Learned**: For M/L/XL tasks or when challenges encountered
- **Unlocked Tasks**: When task was blocking other work

### Tips for Good Reports

1. **Summary**: Write for someone who hasn't read the worker prompt
2. **Changes Made**: Be specific about what changed, not why
3. **Test Coverage**: Include actual numbers from pytest output
4. **Verification**: Copy-paste actual command and output
5. **Lessons Learned**: Focus on actionable insights

### File Naming Convention

```
docs/completion/[TASK-ID]_COMPLETION_SUMMARY.md
```

Examples:
- `docs/completion/EI-1_COMPLETION_SUMMARY.md`
- `docs/completion/GR-5_COMPLETION_SUMMARY.md`

### When to Skip Sections

- **XS tasks**: Header + Summary + Verification + abbreviated Evaluation Findings (quick scan only, skip detailed checklists, just note "No improvements identified" or list 1-2 items)
- **S tasks**: Can skip Lessons Learned if straightforward; standard Evaluation Findings (checklists + 1-2 improvements max)
- **M/L/XL tasks**: Include all relevant sections with full Evaluation Findings

---

## Version History

- **v1.1** (2025-12-31): Added Evaluation Findings section
  - New section after Acceptance Criteria Checklist
  - Code quality, test assessment, and architecture alignment checklists
  - Improvements tracking with disposition (Implemented/Deferred/Rejected)
  - User decisions log (Approved/Deferred/Rejected items)
  - Suggested Follow-Up Tasks table for deferred improvements
  - Complements WORKER_PROMPT_TEMPLATE.md v2.5 Critical Evaluation Phase

- **v1.0** (2025-12-18): Initial template
  - Standard format for completion reports
  - Metadata header block
  - Test coverage tracking
  - Lessons learned section
  - Based on ORCHESTRATOR_IMPROVEMENTS.md Phase 3 recommendations

---

**Template maintained by**: Claude Code & Project Team
