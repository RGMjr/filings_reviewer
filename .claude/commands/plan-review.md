# Plan Review

**Purpose:** Critically evaluate the current plan for CLAUDE.md adherence, scope discipline, and maximum concurrency before exiting plan mode.

**Usage:** `/plan-review [optional focus area]`

---

## Instructions

Evaluate the current plan critically and carefully:

1. **CLAUDE.md adherence** — Re-read CLAUDE.md (project + global). Verify every planned action complies. Flag any violations, especially:
   - Scope creep beyond what was requested
   - Missing pre-implementation gate checklist (if 3+ files touched)
   - Out-of-scope refactoring or "improvements"
   - Implementation rules: execute ONLY specified steps, no extras

2. **Concurrency maximization** — Review the plan for opportunities to run steps in parallel. Identify independent work streams that can be executed concurrently (e.g., via parallel sub-agents). Restructure the plan to maximize concurrent development where dependencies allow.

3. **Minimal path** — Confirm the plan represents the smallest set of changes that achieves the goal. Flag anything unnecessary.

4. **Risk check** — Identify shared imports, migration ordering, and tests that depend on changed behavior. What could break?

5. **Update the plan file** with any corrections or concurrency improvements found.

$ARGUMENTS
If additional focus area specified above, give extra attention to that aspect of the plan during review.
