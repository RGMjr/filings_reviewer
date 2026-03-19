# Parallel Plan Execution Skill

**Purpose:** Execute a multi-phase implementation plan by analyzing dependencies, spawning parallel sub-agents for independent phases, and running dependent phases sequentially — so a 5-phase plan finishes in the time one phase takes today.

**When to use:** Any time you have a numbered implementation plan with 3+ steps and want to maximize parallel execution.

---

## Protocol

### Step 1: Analyze the plan

Read the full plan provided by the user. For each phase/step, identify:
- **Inputs**: what does this phase need to exist before it can start?
- **Outputs**: what does this phase produce that others depend on?
- **Files touched**: which source files does this phase modify?

Flag any phases that touch the same file — they CANNOT run in parallel (merge conflicts).

### Step 1a: Branch protection

If currently on main/master, create and check out a working branch before spawning agents:

    git checkout -b plan-execute/<short-description>

If already on a feature branch, stay on it. Never run plan-execute directly on main.

### Step 2: Build the dependency graph

Group phases into waves:
- **Wave 1**: phases with no dependencies (can start immediately in parallel)
- **Wave 2**: phases that depend only on Wave 1 outputs
- **Wave N**: phases that depend on Wave N-1 outputs

Output the graph to the user before executing:

```
Dependency analysis:
  Wave 1 (parallel): Phase A, Phase C
  Wave 2 (parallel, after Wave 1): Phase B, Phase D
  Wave 3 (sequential, after Wave 2): Phase E

File conflict check:
  No conflicts detected. / Conflict: Phase A and Phase C both modify src/foo.py — serializing.
```

Wait for user confirmation before proceeding if any conflicts were detected.

### Step 3: Execute Wave 1 in parallel

For each phase in Wave 1, spawn a sub-agent using the Agent tool with:
- `subagent_type`: `"general-purpose"`
- `model`: `"sonnet"`
- `isolation`: `"worktree"` — each agent works on an isolated copy of the repo; Agent tool auto-cleans up if no changes are made. This means agents can safely run in parallel even if wave analysis missed a file overlap.
- `run_in_background`: `true` for all but the last (so they run concurrently)
- A self-contained prompt that includes:
  - The exact phase description and all steps
  - Which files to read/modify
  - The success criteria
  - The instruction: "Run pytest tests/unit/ -x -q after your changes. Report pass/fail."
  - The instruction: "Do NOT expand scope. Implement only what is specified."

### Step 4: Collect Wave 1 results

Wait for all Wave 1 sub-agents to complete. For each:
- If passed: note which files were changed
- If failed: report the failure and ask the user whether to continue or stop

Do NOT proceed to Wave 2 if any Wave 1 agent failed, unless the user explicitly says to continue.

### Step 5: Execute subsequent waves

Repeat Steps 3–4 for each remaining wave, in order. Each wave waits for the previous wave to fully complete.

### Step 6: Final validation

After all waves complete, run the full suite yourself:

```bash
ruff check src/ tests/
pytest tests/unit/ -x -q --tb=short
```

Report the final status. If anything fails, invoke the `/ci-fix` protocol to resolve it.

If the plan was executed on a `plan-execute/*` branch, offer to merge to main:

    git checkout main
    git merge plan-execute/<short-description>
    git branch -d plan-execute/<short-description>

Wait for user confirmation before merging. Do not auto-merge.

### Step 7: Summary report

Output a table:

```
Phase Execution Summary
========================
Phase A  | Wave 1 | PASSED | 3 files changed
Phase C  | Wave 1 | PASSED | 1 file changed
Phase B  | Wave 2 | PASSED | 2 files changed
Phase D  | Wave 2 | PASSED | 4 files changed
Phase E  | Wave 3 | PASSED | 1 file changed

Final CI: ruff CLEAN | pytest 3627 passed
```

---

## Sub-agent prompt template

Use this structure when spawning each sub-agent:

```
You are implementing Phase [X] of a multi-phase plan.

SCOPE: Implement ONLY the steps listed below. Do not fix adjacent issues,
refactor unrelated code, or expand scope beyond what is specified.

PHASE DESCRIPTION:
[paste the exact phase description]

STEPS:
[paste the numbered steps]

FILES TO MODIFY:
[list the specific files]

SUCCESS CRITERIA:
[list measurable outcomes]

AFTER COMPLETING:
1. Run: pytest tests/unit/ -x -q --tb=short
2. Report: pass/fail, which files you changed, and a one-line summary of what you did.
3. Do NOT commit. Do NOT push.
```

---

## Rules

- Never spawn sub-agents that touch the same file in the same wave.
- Never proceed to the next wave if the current wave has failures.
- Each sub-agent implements ONLY its assigned phase — no scope expansion.
- Always run a full CI check after all waves complete.
- If the plan has only 1-2 steps, skip the parallel machinery and just execute sequentially.
- If on main, create a `plan-execute/<description>` branch before spawning agents. Never execute directly on main.
