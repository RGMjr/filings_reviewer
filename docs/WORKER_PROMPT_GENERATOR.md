# Worker Prompt Generator - Meta-Prompt for Claude Code Headless Mode

**Purpose**: This meta-prompt generates high-quality WORKER_PROMPT_TASK_XX.md files using Claude Code in headless mode with Opus 4.5.

---

## Command to Run

```bash
claude-code \
  --model opus-4.5 \
  --headless \
  --edit \
  --write \
  --prompt "$(cat docs/WORKER_PROMPT_GENERATOR.md)" \
  --context "TASK_ID=[XX] PLAN_DOC=[path/to/plan.md]"
```

---

## Meta-Prompt for Worker Prompt Generation

```markdown
# Generate Worker Prompt: Task [TASK_ID]

You are generating a worker prompt for Task [TASK_ID] following the project's standardized template.

## Instructions

1. **Read Required Documents**
   - Read `/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings Analysis/Filings review tool/filings_reviewer/docs/WORKER_PROMPT_TEMPLATE.md` (template format)
   - Read `/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings Analysis/Filings review tool/filings_reviewer/instructions_orchestrator.md` (orchestrator context)
   - Read the plan document: `[PLAN_DOC]` (task details)

2. **Extract Task Information**
   - Locate Task [TASK_ID] in the plan document
   - Extract: objective, prerequisites, dependencies, risk level, time estimate, files affected
   - Identify all DEPENDS ON, UNLOCKS, BLOCKS, PARALLEL WITH relationships

3. **Generate Worker Prompt**
   - Follow WORKER_PROMPT_TEMPLATE.md structure exactly
   - Use template version 2.4 format
   - Ensure all required sections are present
   - Keep length to 80-150 lines (requirements-focused, not prescriptive)
   - Include auto-generated verification script for M/L/XL tasks

4. **Validate Generated Prompt**
   - [ ] Task ID is unique and follows convention
   - [ ] TASK SIZE matches TIME ESTIMATE (XS=<30min, S=30min-2hr, M=2-4hr, L=4-8hr, XL=>8hr)
   - [ ] All dependency fields populated (DEPENDS ON, UNLOCKS, BLOCKS)
   - [ ] Risk level specified with explanation if Medium/High
   - [ ] Implementation requirements focus on WHAT not HOW
   - [ ] Coverage target is explicit (e.g., ≥ 90%)
   - [ ] Acceptance criteria are specific and testable
   - [ ] Verification commands are copy-pasteable
   - [ ] Backward compatibility section included if data format changes
   - [ ] Risk mitigation strategy if Medium/High risk

5. **Write Output**
   - Write to: `docs/WORKER_PROMPT_TASK_[TASK_ID].md`
   - Use exact template format
   - Include current date in STATUS field

## Template Structure to Follow

```markdown
# WORKER PROMPT: Task [ID] - [Short Title]

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       [ID]
TASK NAME:     [Full descriptive name]
WORKSTREAM:    [Category]
SOURCE:        [Reference document]
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: [Range with breakdown]
TIME ACTUAL:   N/A
RISK LEVEL:    [None | Low | Medium | High] (explain if Medium/High)
TASK SIZE:     [XS | S | M | L | XL]
DEPENDS ON:    [Task IDs or "None"]
UNLOCKS:       [Task IDs or "None"]
BLOCKS:        [Task IDs or "None"]
PARALLEL WITH: [Task IDs or "None"]
═══════════════════════════════════════════════════════════════════════════════

## Objective

[1-3 sentences: What to build and why]

**Business Rationale**: [Why this matters with concrete example]

**Current Behavior**: [What happens now]

**Desired Behavior**: [What should happen after]

## Prerequisites

[List dependencies or "None (standalone)"]

## Files to Create

[Only if creating new files - otherwise omit section]

## Files to Modify

[Only if modifying - otherwise omit section]

## Files to Read (Context Only)

[Optional: Files to understand first]

## Implementation Requirements

### Core Functionality

[WHAT the solution must do - NOT HOW]

1. **[Feature/Capability Name]**
   - [Specific requirement]
   - [Example or edge case]

### Error Handling

- **[Error Type]**: [Expected behavior]

### Performance Requirements

[Only if critical - otherwise omit]

### Backward Compatibility

[Only if task changes data formats or APIs - otherwise omit]

## Test Requirements

### Coverage Target: **≥ [X]%** for `[module name]`

### Test Categories ([N]+ tests recommended)

1. **[Category]** ([X]-[Y] tests)
   - [Scenario to test]

### Known Edge Cases to Test

- [Edge case 1]

## Acceptance Criteria

- [ ] [Specific, testable criterion 1]
- [ ] **[N]+ unit tests** covering [categories]
- [ ] **Test coverage ≥ [X]%**
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] `mypy [files] --strict` passes (if applicable)

## Do NOT

- [Constraint 1 - e.g., don't modify file X]
- [Constraint 2 - e.g., don't change API signatures]

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest [test path] -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest [test path] --cov=[module] --cov-report=term-missing

# Type check (if applicable)
mypy [module path] --strict
```

## Auto-Generated Verification Script

[Include for M/L/XL tasks - provides complete verification in single command]

## Reference

- **Issue source**: [Document and issue number]
- **Dependencies**: [Related tasks]

---

**Last Updated**: [YYYY-MM-DD]
**Format Version**: 2.4
```

## Key Principles

### Requirements-Focused, Not Prescriptive
- ❌ BAD: "Step 1: Create class ExactName with method foo()"
- ✅ GOOD: "Detect patterns in text with confidence scoring 0.0-1.0"

### Specific Acceptance Criteria
- ❌ BAD: "Add tests"
- ✅ GOOD: "30+ unit tests covering happy path, edge cases, and error conditions"

### Explicit Constraints
- ❌ BAD: Assume developer knows what not to change
- ✅ GOOD: "Do NOT modify src/review/config.py - Task EI-2 is modifying it"

### Risk Communication
For Medium/High risk, explain:
- **What could go wrong**: Specific failure modes
- **Impact if it fails**: Scope of damage
- **Likelihood**: Based on past experience
- **Mitigation**: How task reduces risk

Example:
```
RISK LEVEL:    Medium - Changes text extraction format
               - Risk: Position mapping could break in TableRowParser
               - Impact: Cross-row validation fails, false positives return
               - Likelihood: Medium (text format change similar to past issues)
               - Mitigation: Extensive position mapping tests (10+ scenarios)
```

### Dependency Visualization
Use dependency fields to enable critical path analysis:
- **DEPENDS ON**: Prerequisites that must complete first
- **UNLOCKS**: Tasks that become available after this completes
- **BLOCKS**: Tasks explicitly blocked by this one
- **PARALLEL WITH**: Tasks that can run simultaneously

## Context Gathering Strategy

Before generating the prompt, gather this information:

1. **From Plan Document**:
   - Task description and objective
   - Prerequisites and dependencies
   - Time estimate and risk level
   - Expected files to modify

2. **From Codebase** (if files mentioned):
   - Read mentioned files to understand current state
   - Check for existing tests to understand coverage
   - Identify related modules for "Do NOT" constraints

3. **From Related Tasks**:
   - Check DEPENDS ON tasks - what do they provide?
   - Check UNLOCKS tasks - what do they need?
   - Check PARALLEL WITH tasks - any file conflicts?

## Output Requirements

1. **File Location**: `docs/WORKER_PROMPT_TASK_[TASK_ID].md`
2. **Format**: Exact match to template v2.4
3. **Length**: 80-150 lines (not 400+)
4. **Verification**: All template checklist items satisfied

## Common Pitfalls to Avoid

1. ❌ **Over-prescriptive**: Don't provide step-by-step code
2. ❌ **Under-specified**: Don't leave acceptance criteria vague
3. ❌ **Missing context**: Don't skip "Do NOT" constraints
4. ❌ **Wrong focus**: Requirements (WHAT) not implementation (HOW)
5. ❌ **No verification**: Always provide copy-paste verification commands

## Success Criteria

The generated worker prompt is successful if:
- Developer can start work without asking clarifying questions
- Acceptance criteria are 100% verifiable (pass/fail)
- Risk level accurately reflects potential impact
- Dependencies clearly communicated
- Verification commands work as written
- Length is appropriate (not bloated with implementation details)
```

---

## Example Usage

### Generate Prompt for Task EI-3

```bash
# Set environment variables
export TASK_ID="EI-3"
export PLAN_DOC="docs/EXTRACTION_IMPROVEMENT_PLAN.md"

# Run Claude Code in headless mode
claude-code \
  --model opus-4.5 \
  --headless \
  --edit \
  --write \
  --prompt "$(cat docs/WORKER_PROMPT_GENERATOR.md | sed "s/\[TASK_ID\]/$TASK_ID/g" | sed "s|\[PLAN_DOC\]|$PLAN_DOC|g")"
```

### Batch Generate Multiple Prompts

```bash
# Generate prompts for EI-3, EI-4, EI-5 in parallel
for TASK_ID in EI-3 EI-4 EI-5; do
  claude-code \
    --model opus-4.5 \
    --headless \
    --edit \
    --write \
    --prompt "$(cat docs/WORKER_PROMPT_GENERATOR.md | sed "s/\[TASK_ID\]/$TASK_ID/g" | sed "s|\[PLAN_DOC\]|docs/EXTRACTION_IMPROVEMENT_PLAN.md|g")" &
done
wait
```

---

## Version History

- **v1.0** (2025-12-18): Initial meta-prompt for automated worker prompt generation
  - Based on WORKER_PROMPT_TEMPLATE.md v2.4
  - Follows instructions_orchestrator.md guidance
  - Supports headless mode with edit/write permissions
  - Uses Opus 4.5 for high-quality generation

---

**Maintained by**: Project Team
**For questions**: See instructions_orchestrator.md
