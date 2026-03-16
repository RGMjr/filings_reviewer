# Merge Readiness Check Skill

**Purpose:** Perform a thorough pre-merge assessment of the current branch. Report all blockers before any merge action is taken.

**When to use:** Before merging any branch into main, or when asked to assess merge readiness.

---

## Steps

Run all of the following checks. Do NOT skip steps or assume things are fine without verifying.

1. **CI status** — Check whether all CI checks pass on this branch (`gh pr checks` or `gh run list`). Any failing check is a blocker.

2. **Unregistered migrations** — Check `sql/` for migration files. Verify each migration is registered in the correct order with no gaps or FK dependency issues.

3. **Import integrity** — Run `ruff check --select=F401,F811,E902 src/ tests/` to detect missing imports, unused imports, or syntax errors.

4. **Full test suite** — Run `pytest -x -q`. All tests must pass.

5. **Type checks** — Run `mypy src/review/ --strict`. No new errors allowed.

6. **Uncommitted changes** — Run `git status`. Flag any uncommitted or untracked files that might belong in the PR.

7. **Branch is up to date** — Run `git log main..HEAD --oneline` and `git log HEAD..main --oneline`. Flag if the branch is behind main.

---

## Output Format

Report findings as a numbered list of blockers and warnings:

```
BLOCKERS (must fix before merge):
1. [blocker description]

WARNINGS (should review):
1. [warning description]

CLEAR:
- [checks that passed]
```

---

## Rules

- Do NOT merge, force-merge, or push anything. This skill only reports findings.
- Do NOT interpret ambiguous user input as approval to merge.
- If all checks pass, state clearly: "All checks pass. Ready to merge." and wait for the user to issue the merge command explicitly.
