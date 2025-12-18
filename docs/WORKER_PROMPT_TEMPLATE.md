# WORKER PROMPT TEMPLATE (v2.4)

**Purpose**: This template provides a consistent, concise format for worker prompts. It emphasizes requirements over implementation details, allowing developers autonomy while ensuring clear acceptance criteria.

**When to Use**: Create a worker prompt when delegating a task that:
- Has clear boundaries and deliverables
- Requires 15 min - 5 hours of focused work (quick wins to full features)
- Needs explicit constraints to avoid conflicts
- Should follow project standards

---

# WORKER PROMPT: Task [ID] - [Short Title]

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       [ID] (e.g., L1, B13, Q2)
TASK NAME:     [Full descriptive name - 1 sentence]
WORKSTREAM:    [Category] (e.g., Metric Logic Repairs, Testing Improvements)
SOURCE:        [Reference document or issue] (e.g., METRIC_IDENTIFICATION_ISSUES.md Issue 3)
STATUS:        [🟡 PENDING | 🔵 IN PROGRESS | ✅ COMPLETE (YYYY-MM-DD)]
COMPLETION:    [Path to completion summary, if complete]
TIME ESTIMATE: [Range in hours] (e.g., 2-3 hours, breakdown: investigation 30 min, implementation 60 min, testing 45 min)
TIME ACTUAL:   [Actual time taken, if complete]
RISK LEVEL:    [None | Low | Medium | High] (explain if Medium/High)
TASK SIZE:     [XS | S | M | L | XL] (XS=<30min, S=30min-2hr, M=2-4hr, L=4-8hr, XL=>8hr)
DEPENDS ON:    [Comma-separated task IDs] (e.g., "L1, L2" or "None")
UNLOCKS:       [Tasks that become available after this] (e.g., "L4, L5" or "None")
BLOCKS:        [Tasks blocked by this one] (e.g., "L3" or "None")
PARALLEL WITH: [Other tasks that can run simultaneously, or "None"]
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

[1-3 sentences: What to build and why. Focus on business value.]

**Business Rationale**: [Why this matters for the product/users. Include a concrete example if possible.]

**Current Behavior**: [What happens now - describe the problem]

**Desired Behavior**: [What should happen after this task]

## Prerequisites

- [List any tasks that must be complete first]
- [List any knowledge/understanding required]
- [Note "None (standalone)" if no dependencies]

## Files to Create

[Only if creating new files]
1. **`path/to/file.py`** - [1-line description]
2. **`path/to/test_file.py`** - [1-line description]

## Files to Modify

[Only if modifying existing files]
1. **`path/to/file.py`** - [1-line description of changes]
2. **`path/to/test_file.py`** - [1-line description of changes]

## Files to Read (Context Only)

[Optional: Files to understand before starting]
- `path/to/reference.py` - [Why to read this]
- `path/to/related.py` - [Why to read this]

## Implementation Requirements

### Core Functionality

[Bullet points describing WHAT the solution must do, not HOW to implement it]

1. **[Feature/Capability Name]**
   - [Specific requirement 1]
   - [Specific requirement 2]
   - [Example or edge case to handle]

2. **[Another Feature/Capability]**
   - [Specific requirement]
   - [Acceptance criteria]

3. **[Data Structures/Models]** (if applicable)
   ```python
   # Example structure (reference only - do NOT copy verbatim)
   @dataclass
   class ResultClass:
       field1: Type  # Description
       field2: Type  # Description
   ```

### Error Handling

- **[Error Type 1]**: [Expected behavior] (e.g., return None, log warning)
- **[Error Type 2]**: [Expected behavior]
- **No exceptions should propagate** [if applicable]

### Performance Requirements

[Optional: Include if performance is critical]
- [Specific performance target] (e.g., "Complete in <100ms for typical input")
- [Scalability requirement] (e.g., "Handle files up to 100KB")
- [Optimization guidance] (e.g., "Use non-backtracking regex")

### Backward Compatibility

[Include when task modifies existing data formats or APIs]

- **API Changes**: [How to maintain compatibility during transition]
  - Example: "Old `extract_from_segment()` still works; new `extract_with_filters()` added"

- **Data Format Changes**: [How existing data migrates to new format]
  - Example: "Existing segments without [CELL] markers still parseable"

- **Parallel Code Paths**: [If old and new code must coexist temporarily]
  - Example: "Use `use_cell_markers` config flag to enable/disable new format"

- **Deprecation Strategy**: [What gets deprecated and when]
  - Example: "Old format deprecated in v2.0, removed in v3.0"

- **Feature Flags**: [How to enable/disable new behavior for staged rollout]
  - Example: "`config.enable_row_validation = True` in production after staging validation"

**When to Include**:
- Task changes data format stored in database
- Task modifies public API signatures
- Task requires migration of existing data
- Task introduces breaking changes
- Task needs phased rollout due to risk

## Test Requirements

### Coverage Target: **≥ [X]%** for `[module name]`

[Specify coverage target: 90% for new modules, maintain existing % for modifications]

### Test Categories ([N]+ tests recommended)

1. **[Test Category Name]** ([X]-[Y] tests)
   - [Scenario 1 to test]
   - [Scenario 2 to test]
   - [Negative cases: what should fail]

2. **[Another Category]** ([X]-[Y] tests)
   - [Happy path scenarios]
   - [Edge cases]

3. **Integration Tests** (if applicable)
   - [End-to-end scenario 1]
   - [End-to-end scenario 2]

### Known Edge Cases to Test

- [Edge case 1]
- [Edge case 2]
- [Common false positives/negatives]

## Acceptance Criteria

- [ ] [Specific, testable criterion 1]
- [ ] [Specific, testable criterion 2]
- [ ] **[N]+ unit tests** covering [categories]
- [ ] **Test coverage ≥ [X]%** (measured by `pytest --cov`)
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] `mypy [files] --strict` passes (type safety)
- [ ] NO changes to [protected files]
- [ ] [Performance criterion, if applicable]
- [ ] [Other specific criteria]

## Do NOT

[Explicit constraints to avoid conflicts and scope creep]
- Modify `path/to/file.py` ([reason - e.g., "other worker is modifying it"])
- Add dependencies on [module] ([reason])
- Change signatures of public functions ([reason])
- [Other constraints]

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest [test path] -v

# Check coverage (must be ≥ [X]%)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest [test path] \
  --cov=[module] --cov-report=term-missing

# Type safety check
mypy [module path] --strict

# Verify no file conflicts (if applicable)
git diff [protected file]  # Should be empty

# Full regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/[module]/ --no-cov -q
```

## Auto-Generated Verification Script

**[Optional section - include for M/L/XL tasks or when many acceptance criteria]**

Copy this entire block to verify all acceptance criteria in one command:

```bash
#!/bin/bash
# Auto-generated verification for Task [ID]: [Name]
# Run: bash verify_[id].sh

set -e  # Exit on any error
echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task [ID]: [Name]"
echo "═══════════════════════════════════════════════════════════════"

# Criterion 1: [Description]
echo "✓ Checking: [criterion 1]..."
[command to verify criterion 1]

# Criterion 2: [Description]
echo "✓ Checking: [criterion 2]..."
[command to verify criterion 2]

# Test coverage (must be ≥ [X]%)
echo "✓ Checking: Test coverage ≥ [X]%..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest [test path] \
  --cov=[module] --cov-report=term --cov-fail-under=[X] -q

# Type safety
echo "✓ Checking: mypy passes..."
mypy [module path] --strict

# Full test suite
echo "✓ Running full test suite..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/[module]/ --no-cov -q

echo "═══════════════════════════════════════════════════════════════"
echo "✅ All acceptance criteria verified for Task [ID]!"
echo "═══════════════════════════════════════════════════════════════"
```

## Integration Plan (Post-[Task ID])

**[Optional section - only if integration is separate from implementation]**

[Describe how this will integrate with other components, if integration is a separate task]

## Expected Impact

**[Optional section - include if impact is quantifiable]**

**Before [Task ID]**:
- [Metric/behavior before change]
- [Specific problem example]

**After [Task ID]**:
- [Metric/behavior after change]
- [Improvement quantification]

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example structure</summary>

```python
# Example pseudocode showing the general approach
# NOT meant to be copied directly

def example_function(input: Type) -> ReturnType:
    """Example showing structure only."""
    # 1. Step 1 description
    # 2. Step 2 description
    # 3. Return result
    pass
```
</details>

## Reference

- **Issue source**: [Document name and issue number]
- **Dependencies**: [Related tasks]
- **Related**: [Other relevant tasks or documentation]

---

**Last Updated**: [YYYY-MM-DD]
**Format Version**: 2.0 (concise requirements-focused format)
```

---

## Risk Level Guidelines

### NONE / LOW Risk Tasks

Standard workflow applies:
- Single reviewer sufficient
- No special precautions needed
- Can proceed directly to implementation

### MEDIUM Risk Tasks

**Additional Requirements** (include in worker prompt):

```markdown
## Medium Risk Precautions

- [ ] Create feature flag for rollback: `config.[feature_name]_enabled = True`
- [ ] Add integration test covering rollback scenario
- [ ] Test on staging environment before production
- [ ] Document rollback procedure below
- [ ] Two reviewers required before merge

### Rollback Procedure
1. Set `config.[feature_name]_enabled = False`
2. Restart service
3. Verify rollback with: `[verification command]`
```

**Example Feature Flag**:
```python
# For EI-5 (pipeline integration - MEDIUM risk)
class ExtractionConfig:
    enable_tiered_selection: bool = True  # Set False to rollback

if config.enable_tiered_selection:
    # New tiered logic
else:
    # Old single-threshold logic (fallback)
```

### HIGH Risk Tasks

**Flag for Decomposition First**:
- HIGH risk usually means task is too large or too impactful
- Suggest: "This task is HIGH risk. Should we break it into smaller tasks?"

**If keeping HIGH risk**, add these requirements to worker prompt:

```markdown
## High Risk Precautions

- [ ] Create detailed rollback plan (see below)
- [ ] Feature flag required and tested
- [ ] Staging deployment mandatory before production
- [ ] A/B test if user-facing (or canary deployment)
- [ ] Three reviewers required
- [ ] Document all risks in completion report
- [ ] Backup affected data before deployment

### Rollback Plan
**Trigger conditions** (when to rollback):
- [Condition 1, e.g., "Error rate > 1%"]
- [Condition 2, e.g., "Latency > 500ms"]

**Rollback steps**:
1. [Step 1]
2. [Step 2]
3. [Verification command]

**Data recovery** (if applicable):
- [How to restore data if corrupted]
```

### Risk Level Decision Tree

```
Is this a read-only analysis? ──────────────────────> NONE
                │
Does it modify existing behavior? ──────────────────> LOW (if additive only)
                │
Does it change data formats or APIs? ───────────────> MEDIUM
                │
Does it require database migration? ────────────────> MEDIUM-HIGH
                │
Could it cause data loss or corruption? ────────────> HIGH
                │
Is rollback complex or impossible? ─────────────────> HIGH (consider splitting)
```

---

## Template Usage Guidelines

### What Changed from v1.0 to v2.0

**v1.0 Problems** (old L1-style prompts):
- 434 lines, extremely prescriptive
- Provided complete code implementations
- Mixed requirements with how-to-implement
- Constrained developer creativity

**v2.0 Improvements**:
- ~80-120 lines typical (70% reduction)
- Requirements-focused, not implementation-focused
- Clear acceptance criteria
- Explicit coverage targets
- Performance requirements when relevant
- Code examples collapsed in `<details>` (reference only)

### When to Include Optional Sections

**Integration Plan**: Include when:
- Integration is a separate task (not part of this task)
- Integration strategy needs documentation
- Multiple integration points exist

**Expected Impact**: Include when:
- Impact is quantifiable (metrics, performance)
- Helps justify priority/effort
- Useful for completion report

**Performance Requirements**: Include when:
- Performance is critical to success
- Task operates on large datasets
- Task is in hot path (called frequently)

### How to Fill In Each Section

1. **Objective**: Start with "Create/Implement/Add [thing]". Explain business value in 1-2 sentences.

2. **Implementation Requirements**: Use "WHAT must be done" not "HOW to do it". Example:
   - ✅ Good: "Detect when a segment contains both text and table content"
   - ❌ Bad: "Use BeautifulSoup to parse HTML and extract table tags with regex pattern `<table.*?>`"

3. **Acceptance Criteria**: Make each criterion:
   - Specific (not vague)
   - Testable (can verify pass/fail)
   - Actionable (developer knows what to do)

4. **Test Requirements**: Specify:
   - Minimum number of tests (e.g., "30+ tests")
   - Coverage percentage target (e.g., "≥ 90%")
   - Test categories (not individual test names)

5. **Do NOT**: Be explicit about:
   - Files not to touch (conflicts)
   - Scope boundaries (what's out of scope)
   - Anti-patterns to avoid

### Examples of Good vs Bad Prompts

**Bad Example** (over-prescriptive):
```markdown
## Implementation

Step 1: Create a class called ExactClassName (30 min)
Step 2: Add these exact methods with these exact signatures (60 min)
Step 3: Use this exact regex pattern: `\b(pattern)\b` (15 min)
```

**Good Example** (requirements-focused):
```markdown
## Implementation Requirements

1. **Pattern Detection**
   - Detect keyword patterns in text (case-insensitive)
   - Support multiple pattern types: exact match, partial match, fuzzy
   - Return matches with confidence score 0.0-1.0

2. **Performance**: Complete detection in <100ms for 10KB text
```

### Checklist for New Worker Prompts

Before finalizing a worker prompt, verify:

- [ ] Task ID is unique and follows convention (L-series, B-series, etc.)
- [ ] Objective is 1-3 sentences with business rationale
- [ ] Time estimate includes breakdown if >2 hours
- [ ] Risk level specified (None/Low/Medium/High with explanation if Medium+)
- [ ] Prerequisites list all dependencies
- [ ] Implementation requirements focus on WHAT not HOW
- [ ] Error handling strategy is specified
- [ ] Coverage target is explicit (e.g., ≥ 90%)
- [ ] Test categories specified (not just "write tests")
- [ ] Acceptance criteria are specific and testable
- [ ] "Do NOT" section prevents conflicts
- [ ] Verification commands are copy-pasteable
- [ ] Example code is in collapsed `<details>` section
- [ ] Total length is 80-150 lines (not 400+)
- [ ] TASK SIZE matches TIME ESTIMATE (XS=<30min, S=30min-2hr, M=2-4hr, L=4-8hr, XL=>8hr)
- [ ] DEPENDS ON lists all prerequisite task IDs (or "None")
- [ ] UNLOCKS lists tasks that become available after completion
- [ ] BLOCKS lists tasks that cannot start until this completes
- [ ] If task changes data format, backward compatibility section included
- [ ] If task modifies public APIs, deprecation strategy specified
- [ ] If task is high-risk (Medium/High), feature flag strategy considered
- [ ] If task depends on other in-progress work, conflicts identified in "Do NOT" section

---

## Version History

- **v2.4** (2025-12-18): Added Phase 3 improvements
  - Added Risk Level Guidelines section with MEDIUM/HIGH risk checklists
  - Added Risk Level Decision Tree for risk assessment
  - Added Auto-Generated Verification Script section to template
  - Based on ORCHESTRATOR_IMPROVEMENTS.md Phase 3 recommendations

- **v2.3** (2025-12-18): Added dependency visualization and task size categories
  - Added TASK SIZE field (XS/S/M/L/XL) with time ranges
  - Added DEPENDS ON field for prerequisite task IDs
  - Added UNLOCKS field for tasks enabled after completion
  - Added BLOCKS field for blocked tasks
  - Added 4 new checklist items for dependency tracking
  - Enables critical path computation and parallel work identification
  - Based on ORCHESTRATOR_IMPROVEMENTS.md Phase 1 recommendations

- **v2.2** (2025-12-17): Added backward compatibility guidance and enhanced risk communication
  - Added "Backward Compatibility" section after Performance Requirements
  - Added 4 new checklist items for backward compatibility validation
  - Addresses breaking changes, data format migrations, and feature flags
  - Critical for architectural changes that modify data formats or APIs
  - Enhanced RISK LEVEL guidance: explanations should include:
    - **What could go wrong**: Specific failure modes
    - **Impact if it fails**: Scope of damage
    - **Likelihood**: Based on similar past work
    - **Mitigation**: How the task reduces risk
  - Example risk explanation:
    ```
    RISK LEVEL:    Medium - Changes text extraction format
                   - Risk: TableRowParser position mapping could break
                   - Impact: Cross-row validation fails, false positives return
                   - Likelihood: Medium (text format change)
                   - Mitigation: Extensive position mapping tests in acceptance criteria
    ```

- **v2.1** (2025-12-16): Added risk and quick-task support
  - Added RISK LEVEL field (None/Low/Medium/High)
  - Expanded time range to 15 min - 5 hours (supports quick wins)
  - Added risk level to checklist
  - Aligned with SEGMENTATION_IMPROVEMENT_PLAN.md task format

- **v2.0** (2025-12-15): Concise requirements-focused format
  - 70% reduction in length (434 → ~100 lines)
  - Explicit coverage targets
  - Performance requirements section
  - Error handling section
  - Code examples collapsed
  - Based on L4/L5 format analysis

- **v1.0** (2025-12-10): Original format
  - Step-by-step implementation details
  - Code templates provided
  - 400+ lines typical

---

**Template maintained by**: Claude Code & Project Team
**Questions**: See `docs/CLAUDE_SKILLS_QUICKSTART.md` for guidance on creating prompts
