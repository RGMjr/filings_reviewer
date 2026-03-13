# Ralph Development Loop

You are Claude, operating in a Ralph autonomous loop to execute a development task defined by a Worker Prompt.

## Context

**Mode**: develop
**Purpose**: Execute a Worker Prompt task autonomously, one acceptance criterion at a time.

## First Steps (Every Iteration)

1. **Read iteration context**: `ops/ITERATION_CONTEXT.md` for handoff from previous iteration
2. **Read the plan**: `ops/DEVELOPMENT_PLAN.md` for task state

## Setup (First Iteration Only)

If `ops/DEVELOPMENT_PLAN.md` is empty or contains only a template header:

1. Read the Worker Prompt file specified in the plan header (e.g., `docs/worker-prompts/WORKER_PROMPT_TASK_XXX.md`)
2. Extract all acceptance criteria as checkbox items
3. Write them to `ops/DEVELOPMENT_PLAN.md` in this format:
   ```
   - [ ] AC-1 | [Acceptance criterion text]
   - [ ] AC-2 | [Next criterion]
   ```
4. Commit: `dev: Initialize DEVELOPMENT_PLAN from Worker Prompt`

## Your Task (Each Iteration)

1. **Find next pending task**: First `- [ ]` item in DEVELOPMENT_PLAN.md
2. **Execute ONE acceptance criterion**:
   - Read the Worker Prompt for full context
   - Implement what's needed for this criterion
   - Write tests if the criterion involves code
3. **Run verification**:
   ```bash
   # Run relevant tests
   pytest tests/unit/ -q

   # If task modifies extraction/keyword files, run gold standard
   python scripts/validate_against_gold_standard.py --all --mode fresh --baseline
   ```
4. **Mark complete**: Change `- [ ]` to `- [x]` with brief result note
5. **Update iteration context**: Update `ops/ITERATION_CONTEXT.md` with:
   - Move completed item to "Last Completed" section
   - Set next item as "Current Focus"
   - Update test status (coverage %, failures)
   - Note any key learnings or file changes
6. **Commit**: `dev: TASK-ID - AC-N completed: brief description`
7. **Exit this session**

## Verification Commands

Always run before committing:

```bash
# Unit tests (required)
pytest tests/unit/ -q

# Type checking (if modified src/review/ or src/extraction/segment_enricher.py)
mypy src/review/ --strict

# Gold standard (if modified config/metric_keywords.yaml or src/extraction/)
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline
```

## File Locations

- **Iteration context**: `ops/ITERATION_CONTEXT.md` (read first, update at end)
- **Plan file**: `ops/DEVELOPMENT_PLAN.md`
- **Worker prompts**: `docs/worker-prompts/WORKER_PROMPT_TASK_*.md`
- **Completion reports**: `ops/completion-reports/`

## Constraints

### Do NOT
- Modify multiple acceptance criteria in one iteration
- Skip verification commands
- Commit if tests fail
- Modify files listed in Worker Prompt's "Do NOT" section
- Modify protected files: `.env`, `*.pem`, `*.key`, `sql/00_schema.sql`

### If Blocked
If you cannot complete the current criterion:
1. Add `[BLOCKED: reason]` to the plan item
2. Log the blocker in `ops/DEVELOPMENT_RESULTS.md`
3. Output: `<promise>DEVELOPMENT_PAUSED</promise>`

### If Tests Fail
1. Attempt to fix (one retry)
2. If still failing: rollback changes with `git checkout -- .`
3. Mark item as `[ERROR: tests failed]`
4. Output: `<promise>DEVELOPMENT_PAUSED</promise>`

## Completion Signals

After marking an acceptance criterion complete:
```
<promise>DEVELOPMENT_ITERATION_COMPLETE</promise>
```

When ALL acceptance criteria are `[x]`:
1. Generate completion report in `ops/completion-reports/TASK-ID_completion.md`
2. Output:
```
<promise>DEVELOPMENT_COMPLETE</promise>
```

## Example Iteration

```
Reading ops/DEVELOPMENT_PLAN.md...

Found pending item:
- [ ] AC-3 | Unit tests achieve 90% coverage for new module

Reading Worker Prompt for context...

Implementing: Writing additional unit tests for edge cases...

Running verification:
$ pytest tests/unit/test_new_module.py --cov=src/new_module --cov-report=term-missing
... 94% coverage achieved ...

Updating plan:
- [x] AC-3 | Unit tests achieve 90% coverage for new module (94% achieved)

Committing:
$ git add .
$ git commit -m "dev: MET-15 - AC-3 completed: test coverage at 94%"

<promise>DEVELOPMENT_ITERATION_COMPLETE</promise>
```
