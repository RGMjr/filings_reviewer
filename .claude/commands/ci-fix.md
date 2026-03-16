# CI Fix Skill

**Purpose:** Autonomously iterate on CI failures — ruff, mypy, pytest — until all checks pass green in a single run. No human babysitting required.

**When to use:** Any time CI is failing and you want it fixed without managing each cycle manually.

---

## Loop Protocol

Work autonomously. Do NOT stop to ask questions mid-loop. Diagnose, fix, re-run, repeat. Only stop when all checks pass or you hit a blocker you cannot resolve (see Escalation below).

### Step 1: Ruff

```bash
ruff check src/ tests/
```

For each violation:
- Auto-fixable (imports, formatting): run `ruff check --fix src/ tests/`
- Manual (logic errors, unused variables with side effects): read the file and apply the minimal fix
- Do NOT suppress violations with `# noqa` unless they are genuinely unfixable false positives

Re-run ruff after fixes. Proceed to Step 2 only when ruff is clean.

### Step 2: Mypy

```bash
mypy src/review/ --strict
```

For each error:
- Read the file at the reported line before touching anything
- Apply the minimal type annotation or cast — do not restructure code
- Do NOT add `# type: ignore` unless the error is a known mypy limitation with no better fix
- If fixing one error causes another, continue — do not revert unless you're looping

Re-run mypy after fixes. Proceed to Step 3 only when mypy is clean.

### Step 3: Pytest (unit)

```bash
pytest tests/unit/ -x -q --tb=short
```

For each failure:
- Read the test and the source file it's testing before touching anything
- Apply the minimal fix to source code (not the test, unless the test is wrong)
- Re-run the full unit suite after each fix — not just the failing test
- If your fix breaks a previously passing test, revert it and find a different approach
- Do NOT delete or skip tests

Re-run full unit suite. Proceed to Step 4 only when all unit tests pass.

### Step 4: Pytest (integration, if DB available)

```bash
pytest tests/integration/ -x -q --tb=short
```

If this errors immediately with a DB connection error (`psycopg.OperationalError`), skip — Docker is not running. Note this in your final report.

Otherwise, fix integration failures using the same protocol as Step 3.

---

## Loop Termination

**Success:** All checks pass in a single run (ruff clean + mypy clean + pytest unit pass + integration pass or skipped). Proceed to Step 5.

**Stuck:** If you apply a fix, re-run, and the same failure reappears after 2 attempts with different approaches, stop and escalate (see below).

**Cascading:** If fixing one thing keeps breaking something else after 3 full loop iterations, stop and escalate.

### Step 5: Report and commit

Before committing, output a summary:

```
CI Fix Summary
==============
Ruff: [N violations fixed / already clean]
Mypy: [N errors fixed / already clean]
Pytest unit: [N failures fixed / already passing]
Pytest integration: [N failures fixed / skipped (no DB) / already passing]

Files changed:
- path/to/file.py — [what was wrong and what was changed]
- ...
```

Then run `/commit` (or follow the commit skill protocol manually) to commit all fixes in a single commit with message: `fix: resolve CI failures — [brief summary]`

---

## Escalation (when to stop and report)

Stop and report to the user — do NOT guess or force a fix — if:

- A test failure requires understanding business logic you don't have context for
- A mypy error requires changing a public API or function signature
- A ruff violation is in a file that appears auto-generated
- You've made 3+ attempts on the same failure with different approaches and it keeps failing
- The failure is in a test marked `@pytest.mark.integration` that requires live data or external services

Report: what you fixed, what you couldn't fix, and why.

---

## Rules

- Fix only what CI is complaining about. Do not refactor, clean up, or improve adjacent code.
- Never use `--no-verify` to skip the pre-commit hook.
- Never delete tests.
- Never use `# noqa` or `# type: ignore` as a first resort.
- Minimal changes only — if a one-line fix works, don't rewrite the function.
