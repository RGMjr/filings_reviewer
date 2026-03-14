# Workflow Improvements Recommendations

**Date**: 2025-12-17
**Source**: EXTRACTION_IMPROVEMENT_PLAN.md development
**Status**: Proposed

---

## Executive Summary

While creating the EXTRACTION_IMPROVEMENT_PLAN.md, I identified several opportunities to enhance the orchestrator/worker workflow for improved efficiency, quality, and risk management.

**Key Recommendations**:
1. Add architecture-specific guidance to task selection
2. Enhance worker prompt template with backward compatibility section
3. Improve risk communication in task metadata
4. Clarify parallel vs sequential task dependencies

---

## Recommendation 1: Architecture-Aware Task Selection

### Current State

`instructions_orchestrator.md` lines 36-44 provide task selection strategy:
- Check prerequisites
- Prefer foundation first
- Enable parallelization
- Follow dependency graph
- Ask when unclear

**Gap**: No guidance for architectural changes that span multiple modules.

### Proposed Addition

Add to `instructions_orchestrator.md` after line 44:

```markdown
6. **Consider System-Wide Impact**: For architecture changes affecting multiple modules:
   - Phase foundational changes first (data structures, shared utilities)
   - Enable parallel work on independent modules where possible
   - Plan integration tasks only after component tasks complete
   - Explicitly call out parallel vs sequential dependencies in task table
   - Consider feature flags for staged rollouts of breaking changes
```

### Rationale

- **EXTRACTION_IMPROVEMENT_PLAN experience**: EI-1, EI-2, EI-3 can run in parallel (independent), but EI-4 must follow EI-3 (sequential dependency on FalsePositiveFilter)
- **Clearer planning**: Architects can better optimize parallel work
- **Risk reduction**: Integration tasks properly sequenced

### Impact

- **Architects**: Better guidance on task ordering for architectural work
- **Workers**: Clearer understanding of which tasks can proceed simultaneously
- **Velocity**: More effective parallelization when possible

---

## Recommendation 2: Backward Compatibility Section in Worker Prompts

### Current State

`WORKER_PROMPT_TEMPLATE.md` has sections for:
- Objective
- Prerequisites
- Implementation Requirements
- Error Handling
- Performance Requirements
- Test Requirements

**Gap**: No standard section for backward compatibility considerations.

### Proposed Addition

Add new section after "Performance Requirements" (line 100):

```markdown
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

### When to Include

- Task changes data format stored in database
- Task modifies public API signatures
- Task requires migration of existing data
- Task introduces breaking changes
- Task needs phased rollout due to risk
```

### Update to Checklist

Add to "Checklist for New Worker Prompts" (after line 322):

```markdown
- [ ] If task changes data format, backward compatibility section included
- [ ] If task modifies public APIs, deprecation strategy specified
- [ ] If task is high-risk (Medium/High), feature flag strategy considered
- [ ] If task depends on other in-progress work, conflicts identified in "Do NOT" section
```

### Rationale

- **EI-5 experience**: Cell boundary markers change text format - need to ensure TableRowParser, position mapping, and existing code still work
- **Risk management**: Forces consideration of migration path before implementation
- **Quality**: Prevents breaking changes from surprising downstream systems

### Impact

- **Workers**: Clear guidance on handling breaking changes
- **Quality**: Fewer regressions from format/API changes
- **Risk**: Explicit feature flags enable staged rollouts

---

## Recommendation 3: Enhanced Risk Communication

### Current State

Worker prompt template v2.1 added `RISK LEVEL` field:
```
RISK LEVEL:    [None | Low | Medium | High] (explain if Medium/High)
```

**Gap**: No standard format for risk explanations or mitigation strategies.

### Proposed Enhancement

Enhance risk level documentation in template (line 330):

```markdown
- **v2.2** (2025-12-17): Enhanced risk communication
  - RISK LEVEL explanations should include:
    - **What could go wrong**: Specific failure modes
    - **Impact if it fails**: Scope of damage
    - **Likelihood**: Based on similar past work
    - **Mitigation**: How the task reduces risk
  - Example:
    ```
    RISK LEVEL:    Medium - Changes text extraction format
                   - Risk: TableRowParser position mapping could break
                   - Impact: Cross-row validation fails, false positives return
                   - Likelihood: Medium (text format change)
                   - Mitigation: Extensive position mapping tests in acceptance criteria
    ```
```

### Add Risk Matrix Reference

Add to orchestrator instructions (line 37):

```markdown
2. **Prefer Foundation First**:
   - Data model changes before logic changes
   - Low-risk tasks before high-risk tasks when no dependencies
   - Proven components (reused from existing code) before new components

   **Risk Levels Guide**:
   - **None**: Read-only analysis, no code changes
   - **Low**: Reusing existing components, additive changes only, no format changes
   - **Medium**: Modifying extraction logic, changing data formats, complex integration
   - **High**: Breaking changes, database schema changes, architectural refactoring
```

### Rationale

- **EI-3 vs EI-5**: EI-3 (integrate existing filter) is Low risk; EI-5 (change text format) is Medium risk - risk matrix helps prioritize
- **Transparency**: Clearer communication of risk factors
- **Informed decisions**: User can make better task ordering decisions

### Impact

- **Architects**: Better risk assessment when suggesting tasks
- **Workers**: Better understanding of what makes a task risky
- **Users**: Can make informed decisions on task ordering

---

## Recommendation 4: Clarify Parallel vs Sequential Dependencies

### Current State

Task tables show prerequisites but don't explicitly show parallel capability:

```markdown
| Task ID | Name | Prerequisites | Time Est | Risk | Status |
```

**Gap**: "Prerequisites: None" doesn't distinguish between "can start immediately" vs "wait for others to finish even though no code dependency."

### Proposed Enhancement

Keep existing `PARALLEL WITH` field in individual task headers (already in template v2.1):
```
PARALLEL WITH: [Other tasks that can run simultaneously, or "None"]
```

**Add guidance** to orchestrator (line 43):

```markdown
3. **Enable Parallelization**: If multiple tasks have completed prerequisites, suggest those that enable parallel work

   **Parallelization Examples**:
   - ✅ **Safe Parallel**: EI-1 (candidate_generator.py), EI-2 (false_positive_filter.py), EI-3 (value_extractor.py) - different files
   - ❌ **Sequential Required**: EI-3 must complete before EI-4 - EI-4 builds on EI-3's filter integration
   - ⚠️ **Coordination Needed**: EI-4 and EI-5 can run parallel but must coordinate for integration testing
```

### Rationale

- **Velocity**: Enables workers to start multiple tasks when parallelizable
- **Avoids conflicts**: Clearly marks when sequential work required
- **Resource optimization**: Team can split work effectively

### Impact

- **Architects**: Better communication of parallelization opportunities
- **Workers**: Can safely start multiple tasks if working in parallel
- **Velocity**: Reduces idle time waiting for prerequisites

---

## Recommendation 5: Integration Testing Guidance

### Current State

Worker prompt template covers unit tests well but integration testing is ad-hoc.

**Gap**: No standard pattern for integration testing across multiple tasks.

### Proposed Addition

Add to `WORKER_PROMPT_TEMPLATE.md` after "Test Requirements" section:

```markdown
### Integration Testing (Multi-Task Features)

[Include when task is part of larger feature requiring multiple tasks]

**Integration Test Responsibility**:
- **This Task**: [What integration tests this task should include]
- **Deferred to [Task ID]**: [What integration tests wait for later task]
- **Coordination**: [How this task's tests interact with other tasks' tests]

**Example**:
```markdown
**Integration Test Responsibility**:
- **This Task (EI-3)**: Test that FalsePositiveFilter integrates correctly in ValueExtractor
- **Deferred to EI-6**: Full end-to-end pipeline test with all 5 fixes
- **Coordination**: EI-4 will test row validation with the filter from EI-3
```
```

### Add to Checklist

```markdown
- [ ] If task is part of multi-task feature, integration test responsibility clarified
- [ ] If integration tests deferred, specify which task will handle them
```

### Rationale

- **EXTRACTION_IMPROVEMENT_PLAN experience**: EI-1 through EI-5 need integration testing, but can't fully test until EI-6
- **Clarity**: Workers know what to test now vs what to defer
- **Quality**: Ensures integration tests happen (assigned to specific task)

### Impact

- **Workers**: Clear scope of testing responsibility
- **Quality**: No integration test gaps
- **Velocity**: Don't waste time writing integration tests prematurely

---

## Recommendation 6: Add EXTRACTION_IMPROVEMENT_PLAN to Orchestrator

### Current State

`instructions_orchestrator.md` lists available plans (line 15-19):
- SEGMENTATION_IMPROVEMENT_PLAN.md
- GOLDMINE_IMPROVEMENT_PLAN.md
- GOLDMINE_1_IMPROVEMENT_PLAN.md
- HUMAN_REVIEW_SYSTEM_TASKS.md

**Gap**: EXTRACTION_IMPROVEMENT_PLAN.md not listed.

### Proposed Change

Add to line 19:

```markdown
- **`docs/EXTRACTION_IMPROVEMENT_PLAN.md`** - Extraction & candidate quality fixes (EI-series tasks)
```

### Impact

- **Completeness**: Orchestrator knows about all available plans
- **Usability**: Users can select EXTRACTION plan

---

## Implementation Priority

### High Priority (Immediate)

1. **Add EXTRACTION_IMPROVEMENT_PLAN to orchestrator** (Rec #6)
   - Trivial change, enables immediate use

2. **Backward Compatibility section in template** (Rec #2)
   - Critical for EI-5 and any future architectural work

### Medium Priority (Next Template Update)

3. **Enhanced risk communication** (Rec #3)
   - Improves decision-making quality

4. **Parallel vs sequential guidance** (Rec #4)
   - Improves velocity on multi-task workstreams

### Low Priority (Future Enhancement)

5. **Integration testing guidance** (Rec #5)
   - Nice-to-have, addresses specific multi-task coordination

6. **Architecture-aware task selection** (Rec #1)
   - Useful for future architectural work

---

## Summary of Changes

### Files to Modify

1. **`instructions_orchestrator.md`**
   - Add line 19a: EXTRACTION_IMPROVEMENT_PLAN.md
   - Add section 6 (after line 44): Architecture-aware task selection
   - Add risk levels guide (after line 37)
   - Add parallelization examples (after line 43)

2. **`docs/WORKER_PROMPT_TEMPLATE.md`**
   - Add "Backward Compatibility" section (after line 100)
   - Update checklist (after line 322): 4 new items
   - Add "Integration Testing" guidance (after Test Requirements)
   - Add version v2.2 to version history (line 330)

### Estimated Time

- **Modifications**: 30-45 minutes
- **Testing**: 15-30 minutes (verify template still renders correctly)
- **Documentation**: Already complete (this document)

**Total**: 1-2 hours

---

## Validation Criteria

After implementing these recommendations:

- [ ] Orchestrator lists EXTRACTION_IMPROVEMENT_PLAN.md
- [ ] Worker prompt template v2.2 includes backward compatibility section
- [ ] Checklist includes backward compatibility items
- [ ] Risk levels guide added to orchestrator
- [ ] Parallelization examples documented
- [ ] Integration testing guidance added
- [ ] Version history updated with rationale
- [ ] All existing prompts still render correctly (backward compatible)

---

## Benefits Summary

| Recommendation | Benefit | Effort |
|----------------|---------|--------|
| #1: Architecture task selection | Better parallelization, lower risk | 15 min |
| #2: Backward compatibility section | Fewer breaking changes, clearer migration | 20 min |
| #3: Enhanced risk communication | Better informed decisions | 15 min |
| #4: Parallel vs sequential clarity | Higher velocity | 10 min |
| #5: Integration test guidance | No test gaps | 15 min |
| #6: Add EXTRACTION plan to list | Immediate usability | 5 min |
| **Total** | **Improved quality, velocity, risk management** | **1-2 hours** |

---

**Recommendation**: Implement all 6 recommendations as a batch. They're complementary and low-effort for high impact.

---

**Author**: Claude Code
**Last Updated**: 2025-12-17
**Status**: Awaiting review and approval
