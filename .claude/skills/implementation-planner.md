# Implementation Planner Skill

**Purpose:** Generate structured implementation plans following the SEC Filings Reviewer project's planning methodology.

**When to use this skill:**
- Starting a new feature or component
- Planning a multi-phase improvement initiative
- Breaking down complex tasks into trackable work streams
- Creating improvement roadmaps (P1/P2/P3 prioritization)

**When NOT to use this skill:**
- Simple single-file changes
- Bug fixes without architectural impact
- Tasks that don't require phased implementation
- Ad-hoc exploratory work

---

## Project Planning Methodology

### Phase Naming Convention

Work is organized into **parallel work streams** (A, B, C, D, E) with **sequential phases** (1, 2, 3...):

- **Stream A**: Foundation/Infrastructure (database, models, core setup)
- **Stream B**: Core Logic (algorithms, processing, business logic)
- **Stream C**: User Interface Foundation (templates, static files, UI framework)
- **Stream D**: User Interface Features (routes, forms, interactive components)
- **Stream E**: Analysis/Advanced Features (ML, reporting, optimization)

**Examples:**
- `A1` - Create database schema file
- `A2` - Create data models
- `A3` - Add database adapter methods
- `B1` - Implement core algorithm
- `D1` - Create web routes

### Dependency Graph Notation

```
A1 ─┬─> A2 ──> A3 ─┬─> B1 ──> B2 ──> B3
    │              │
    │              └─> D1 ──> D2 ──> D3
    │              │
C1 ──> C2 ──> C3 ─┘  └─> E1 ──> E2
```

**Rules:**
- Arrows show "must complete before" dependencies
- Items at same indentation level can run in parallel
- Branches show where streams diverge
- All streams eventually merge (implementation complete)

### Priority Levels (for Improvements)

**P1 - Critical (Must Have):**
- Blocks production deployment
- Fixes critical bugs or security issues
- Enables core functionality
- Time: Complete before any production use

**P2 - Important (Should Have):**
- Significantly improves quality
- Needed before scale-up
- Enhances user experience
- Time: Complete before major expansion

**P3 - Future (Nice to Have):**
- Incremental improvements
- Exploratory features
- Optimizations
- Time: Prioritize based on usage data

### Time Estimation Ranges

- **30 minutes** - Simple config changes, minor edits
- **1 hour** - Single file creation, simple tests
- **2-3 hours** - Module implementation, comprehensive tests
- **3-4 hours** - Complex module with multiple files
- **1 day (5-6 hours)** - Full component with tests and docs
- **2-3 days** - Multiple components with integration
- **1 week** - Major feature with UI + backend + tests

Always provide **ranges** (e.g., "2-3 hours") to account for uncertainty.

---

## Skill Instructions

When this skill is invoked, you should:

### Step 1: Analyze the Task

1. **Read the task description** provided by the user
2. **Identify logical components:**
   - What database changes are needed? (Stream A)
   - What core logic/algorithms? (Stream B)
   - What UI foundation? (Stream C)
   - What user-facing features? (Stream D)
   - What analysis/advanced features? (Stream E)
3. **Identify dependencies:**
   - What must be done first?
   - What can run in parallel?
   - What blocks other work?

### Step 2: Structure the Plan

1. **Assign phase labels** (A1, A2, B1, etc.) based on:
   - Work stream category (A/B/C/D/E)
   - Sequential order within stream (1, 2, 3...)
   - Dependencies (can't be B2 until B1 is done)

2. **Group into parallel opportunities:**
   ```
   Can start immediately (parallel):
   - Stream A (A1, A2)
   - Stream C (C1, C2)

   After A3 complete (parallel):
   - Stream B (B1, B2)
   - Stream D (D1, D2)
   - Stream E (E1, E2)
   ```

3. **Create dependency graph** using the notation above

4. **Estimate time** for each task (use ranges)

### Step 3: Generate Documentation

Create **TWO documents**:

#### Document 1: Main Implementation Plan

Use this template structure:

```markdown
# {Feature Name} Implementation Plan

## Setup Tasks (Before Implementation)
- [ ] Create branch: `git checkout -b feature/{feature-name}`
- [ ] Copy plan to: `docs/{FEATURE}_PLAN.md`

---

## Problem Summary

{Describe the problem being solved - 2-3 paragraphs}

**Examples of issues:**
- {Specific example 1}
- {Specific example 2}
- Root cause: {Why current approach fails}

---

## Solution: {Approach Name}

{Describe the solution approach - 2-3 paragraphs}

**Key components:**
1. {Component 1}
2. {Component 2}
3. {Component 3}

---

## Implementation Plan

### Sprint 1: {Stream Name} (Day X)

**Create:** `{filepath}`

**Objective:** {What this accomplishes}

**Algorithm/Approach:**
1. {Step 1}
2. {Step 2}
3. {Step 3}

**Key {features/methods/components}:**
- `{item_1}` - {description}
- `{item_2}` - {description}

**Create:** `{script_filepath}` (if applicable)

---

{Repeat for each sprint/stream}

---

## Files to Create

| File | Purpose |
|------|---------|
| `{filepath}` | {Description} |
| `{filepath}` | {Description} |

---

## Critical Reference Files

| File | What to reference |
|------|-------------------|
| `{existing_file}:{line_range}` | {What pattern to follow} |
| `{existing_file}` | {What to reference} |

---

## Parallel Work Streams

### Stream A: {Name} (No dependencies)
```
A1. {task}
A2. {task}
A3. {task}
```

### Stream B: {Name} (Depends on A1, A2)
```
B1. {task}
B2. {task}
B3. {task}
```

{Repeat for all streams}

### Dependency Graph
```
A1 ─┬─> A2 ──> A3 ─┬─> B1 ──> B2
    │              │
    │              └─> D1 ──> D2
C1 ──> C2 ─────────┘
```

**Can start immediately (parallel):**
- Stream A (A1, A2)
- Stream C (C1, C2)

**After A3 complete (parallel):**
- Stream B (B1, B2, B3)
- Stream D (D1, D2)

---

## Task Checklist

### Phase 1: {Name} (Can run in parallel)
- [ ] **A1** {Task description} ({time estimate})
  - [ ] {Subtask}
  - [ ] {Subtask}
- [ ] **A2** {Task description} ({time estimate})
- [ ] **C1** {Task description} ({time estimate})

### Phase 2: {Name} (After A3)
- [ ] **A3** {Task description} ({time estimate})

### Phase 3: {Name} (After A3, can run in parallel)
- [ ] **B1** {Task description} ({time estimate})
- [ ] **D1** {Task description} ({time estimate})

{Continue for all phases}

---

## Expected Workflow

1. {Step 1 with command examples}
2. {Step 2 with command examples}
3. {Step 3}
   ```bash
   # Example commands
   {command}
   ```
4. {Continue workflow}
5. Iterate until {success criteria}
```

#### Document 2: Improvement Tracking (for P1/P2/P3 improvements)

**Only create this if the task involves improvements/enhancements.**

Use this template structure:

```markdown
# {Component} - Improvement Tracking

**Purpose**: Track recommended improvements to {component}

**Status**: 🟡 Not Started
**Created**: {date}
**Target Completion**: TBD

---

## Quick Status

| Priority | Total | Complete | In Progress | Not Started |
|----------|-------|----------|-------------|-------------|
| P1 (High) | {n} | 0 | 0 | {n} |
| P2 (Medium) | {n} | 0 | 0 | {n} |
| P3 (Future) | {n} | 0 | 0 | {n} |
| **TOTAL** | **{n}** | **0** | **0** | **{n}** |

---

## Priority 1: High-Impact (Before Production Use)

**Target**: Complete before deploying to production
**Total Estimate**: {X-Y} hours

### P1.1 - {Improvement Name}

**Status**: ⬜ Not Started
**Priority**: P1
**Estimate**: {X-Y} hours
**Actual**: - (fill when complete)
**Assigned**: -
**Completed**: - (fill when complete)

**Objective**: {Clear statement of what this improves}

**Tasks**:
- [ ] {Specific task 1}
- [ ] {Specific task 2}
- [ ] {Specific task 3}

**Files to Modify**:
- `{filepath}` - {What to change}
- `{filepath}` - {What to add}

**Success Criteria**:
- [ ] {Measurable outcome 1}
- [ ] {Measurable outcome 2}
- [ ] {Measurable outcome 3}

**Notes**:
{Implementation notes, examples, warnings}

---

{Repeat for each improvement}

---

## Completion Checklist

### Before Production Deployment:
- [ ] All P1 improvements complete
- [ ] Tests passing
- [ ] Documentation updated

### Before Major Scale-Up:
- [ ] All P2 improvements complete
- [ ] Performance benchmarks met
- [ ] Edge cases covered

### Future Work:
- [ ] P3 improvements prioritized based on usage

---

## Notes & Decisions

### {Date} - {Event}
- {Note or decision}
- {Rationale}
- {Outcome}

---

**Last Updated**: {date}
**Next Review**: {milestone}
```

### Step 4: Validation

Before presenting the plan, validate:

1. **All dependencies are valid**
   - No circular dependencies
   - Parallel streams don't conflict (modify same files)

2. **Estimates are reasonable**
   - Simple tasks: 30min - 2 hours
   - Medium tasks: 2-4 hours
   - Complex tasks: 1-2 days
   - No single task > 1 week

3. **Phase numbering is sequential**
   - A1 → A2 → A3 (not A1 → A3)
   - Each stream starts at 1

4. **All referenced files exist** (or clearly marked as "to create")

5. **Success criteria are measurable**
   - Coverage percentages
   - Test counts
   - Feature completeness
   - Performance targets

---

## Example: Human Review System

**Input:** "Build human-in-the-loop review system with Flask UI for reviewing metric extraction candidates and learning patterns from decisions"

**Output:** Generated `docs/HUMAN_REVIEW_SYSTEM_PLAN.md` with:

**Streams Identified:**
- Stream A: Database schema and models (A1, A2, A3)
- Stream B: Candidate generation and features (B1, B2, B3)
- Stream C: Flask app foundation (C1, C2, C3, C4)
- Stream D: Review interface (D1, D2, D3, D4, D5, D6)
- Stream E: Pattern analysis (E1, E2)

**Dependency Graph:**
```
A1 ─┬─> A2 ──> A3 ─┬─> B1 ──> B2 ──> B3
    │              │
    │              └─> D1 ──> D2 ──> D3 ──> D4 ──> D5 ──> D6
    │              │
C1 ──> C2 ──> C3 ─┘  └─> E1 ──> E2
```

**Parallel Opportunities:**
- Can start immediately: Streams A (A1, A2) and C (C1, C2, C3, C4)
- After A3: Streams B, D, and E can all run in parallel

**Time Estimates:**
- A1 (schema): 1-2 hours
- B1 (candidate generation): 2-3 hours
- D1 (review routes): 3-4 hours
- E1 (pattern analyzer): 4-5 hours
- Total: ~30-40 hours

**Critical References:**
- `src/extraction/metric_classifier.py:57-188` - Keyword patterns
- `src/infra/db.py` - Database adapter pattern
- `sql/03_create_analysis_schema.sql` - Schema conventions

---

## Example: E1 Pattern Analyzer Improvements

**Input:** "After evaluating E1 pattern_analyzer.py, we need to implement 11 improvements across P1/P2/P3 priorities"

**Output:** Generated `docs/E1_IMPROVEMENTS_TRACKING.md` with:

**Priority Breakdown:**
- P1 (Critical): 3 improvements, 7-9 hours total
  - P1.1: Add p-value calculations (2-3 hrs)
  - P1.2: Cross-validation for stability (3-4 hrs)
  - P1.3: Pattern conflict detection (2 hrs)

- P2 (Important): 4 improvements, 11-15 hours total
  - P2.1: Multi-feature conjunctive patterns (4-5 hrs)
  - P2.2: Database-side evaluation (3-4 hrs)
  - P2.3: Pattern explanations (2-3 hrs)
  - P2.4: Feature engineering helpers (2-3 hrs)

- P3 (Future): 4 improvements, TBD
  - P3.1: A/B testing framework
  - P3.2: Temporal stability analysis
  - P3.3: Interactive pattern explorer UI
  - P3.4: Pattern export to rule engine

**Each improvement includes:**
- Clear objective
- Task breakdown with time estimates
- Actual time tracking (filled when complete)
- Assigned owner
- Completion date tracking
- Files to modify
- Success criteria
- Implementation notes

---

## Key Patterns to Follow

### 1. Always Include Setup Section
```markdown
## Setup Tasks (Before Implementation)
- [ ] Create branch: `git checkout -b feature/{name}`
- [ ] Copy plan to: `docs/{FEATURE}_PLAN.md`
```

### 2. Always Include Problem → Solution → Plan Structure
1. Problem Summary (why we're doing this)
2. Solution approach (how we'll solve it)
3. Implementation plan (what to build)

### 3. Always Break Into Phases
- Phase 1: Foundation (can run in parallel)
- Phase 2: Integration (after foundation)
- Phase 3: Features (after integration)

### 4. Always Show Parallel Opportunities
```markdown
**Can start immediately (parallel):**
- Stream A (A1, A2)
- Stream C (C1, C2)

**After A3 complete (parallel):**
- Stream B (B1, B2)
- Stream D (D1, D2)
```

### 5. Always Include Critical References
Point to existing files that show the pattern to follow

### 6. Always Provide Expected Workflow
Show the user the sequence of commands/actions to execute the plan

### 7. For Improvements: Always Use P1/P2/P3 Structure
- P1: Must have before production
- P2: Should have before scale-up
- P3: Nice to have, prioritize later

---

## Common Mistakes to Avoid

❌ **Don't:**
- Create tasks without time estimates
- Skip dependency analysis
- Make all tasks sequential (miss parallelization)
- Use vague success criteria ("make it better")
- Reference files that don't exist without noting they're "to be created"
- Create circular dependencies (A depends on B, B depends on A)

✅ **Do:**
- Provide time ranges (2-3 hours, not "2 hours")
- Identify all parallel work opportunities
- Use measurable success criteria (95% coverage, 10 tests passing)
- Reference existing files with line numbers when relevant
- Validate dependency graph is acyclic
- Include example commands in workflow section

---

## Skill Output Format

When invoked, generate:

1. **Summary** (present to user before generating full docs):
   ```
   I'll create an implementation plan for: {feature}

   Identified {N} work streams:
   - Stream A: {description} ({N} tasks, {X-Y} hours)
   - Stream B: {description} ({N} tasks, {X-Y} hours)

   Total estimate: {X-Y} hours ({N} days)

   Parallel opportunities: {description}

   I'll generate:
   1. Main plan: docs/{FEATURE}_PLAN.md
   2. Tracking doc: docs/{FEATURE}_TRACKING.md (if P1/P2/P3 improvements)

   Proceed with generation? (yes/no)
   ```

2. **Generate documents** after user confirmation

3. **Present summary** of what was created:
   ```
   ✅ Created docs/{FEATURE}_PLAN.md
   ✅ Created docs/{FEATURE}_TRACKING.md

   Next steps:
   1. Review the plan
   2. Create branch: git checkout -b feature/{name}
   3. Start with parallel streams A and C
   4. Track progress using checkboxes
   ```

---

## Testing the Skill

To verify this skill works correctly:

1. **Simple test**: "Plan implementation of a database migration for new table 'metrics_archive'"
   - Should generate: Simple plan with A1 (SQL), A2 (db.py methods), A3 (tests)
   - Should take: 30-60 minutes to execute plan

2. **Medium test**: "Plan implementation of API endpoints for metrics CRUD operations"
   - Should generate: B1 (models), D1 (routes), D2 (tests)
   - Should identify: Flask route patterns to follow
   - Should take: 4-6 hours to execute plan

3. **Complex test**: "Plan implementation of advanced reporting dashboard with charts"
   - Should generate: Multi-stream plan (DB + backend + UI)
   - Should show: Parallel opportunities
   - Should take: 2-3 days to execute plan

4. **Improvements test**: "After reviewing module X, plan 8 improvements across P1/P2/P3"
   - Should generate: Improvement tracking document
   - Should include: Priority breakdown, time estimates, success criteria

---

## Version History

- **v1.1** (2025-12-12): Enhanced time and completion tracking
  - Added "Actual" time field for recording actual hours spent
  - Added "Completed" date field for tracking completion dates
  - Enhanced documentation to emphasize time tracking importance
  - Matches actual usage patterns from E1/D1 improvement tracking

- **v1.0** (2025-12-11): Initial skill creation
  - Supports main implementation plans
  - Supports P1/P2/P3 improvement tracking
  - Includes dependency graphs and parallel work identification
  - Based on HUMAN_REVIEW_SYSTEM_PLAN.md and E1_IMPROVEMENTS_TRACKING.md patterns
