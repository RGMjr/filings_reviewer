# Plan: Conditionally skip tests in /commit

## Context
The `/commit` command always runs the full test suite, even for docs-only or command-definition changes. This wastes time when no functional code has changed.

## CLAUDE.md conflict
CLAUDE.md Testing Standards says: "Before committing: Run the full test suite (`pytest -x -q`)."
This plan relaxes that rule for non-code commits, so **both files must be updated together** to stay consistent.

## Definition of "code changes"
Staged files that should trigger lint + tests:
- `src/**` (any file — Python code, config)
- `tests/**`
- `scripts/**`
- `config/**` (keyword YAML affects extraction behavior)
- `pyproject.toml`, `requirements.txt` (dependency changes)
- `sql/**` (schema changes)

Files that do NOT trigger lint + tests:
- `docs/**`, `*.md` (including CLAUDE.md, README, etc.)
- `.claude/**` (commands, rules, plans)
- Static web assets (`src/web/static/**/*.css`, `*.js`, `*.html` templates) — debatable, but these aren't tested by pytest

## Changes

### File 1: `.claude/commands/commit.md`

**Step 1** — Add guard: "Check staged files (`git diff --cached --name-only`). If no code files are staged (see definition above), skip lint with a note. Otherwise run `ruff check src/ tests/`."

**Step 2** — Same guard: "If no code files are staged, skip tests with a note. Otherwise run `pytest -x -q`."

**Step 3** — Coverage sub-bullet: only check coverage percentage if pytest was actually run.

All other steps (3's remaining sub-bullets, 4-7, Rules) unchanged.

### File 2: `CLAUDE.md`

Update Testing Standards bullet from:
> **Before committing**: Run the full test suite (`pytest -x -q`).

To:
> **Before committing**: Run the full test suite (`pytest -x -q`) when staged changes include code files (`src/`, `tests/`, `scripts/`, `config/`, `sql/`, `pyproject.toml`, `requirements.txt`). Docs-only and config-command-only commits may skip tests.

## Verification
- Stage only `.claude/commands/commit.md` → `/commit` should skip lint and tests
- Stage a `src/` Python file → `/commit` should run lint and tests as before
- Confirm CLAUDE.md testing standards section matches the new behavior
