---
paths:
  - "src/extraction/**"
  - "src/extraction_v2/**"
  - "src/review/candidate_generator*"
  - "src/review/false_positive_filter*"
  - "src/review/keyword_matching*"
  - "src/review/pattern_analyzer*"
  - "config/metric_keywords.yaml"
---

# Agent Dispatch Rules

> **Canonical pattern list:** `config/extraction_patterns.txt`
> The paths in the YAML frontmatter above are for Claude Code rule matching only.
> Scripts and hooks read from the canonical file.

When editing files matched by this rule, you MUST use the appropriate agent team
instead of doing the work directly. This ensures extraction changes are always
validated before commit.

## Extraction Changes → Extraction Team

**Trigger:** Any edit to extraction code, keyword config, FP rules, or candidate generation.

**Required action:** Spawn the extraction team (implementer + validator):

```
Task(subagent_type="extraction-implementer", prompt="<task description>")
  ↓ on completion
Task(subagent_type="gold-standard-validator", prompt="Validate extraction quality after recent changes")
  ↓ if regression detected
Task(subagent_type="extraction-implementer", prompt="Fix regression: <validator findings>")
  ↓ on completion
Task(subagent_type="gold-standard-validator", prompt="Re-validate after regression fix")
```

**Do NOT:**
- Edit extraction files directly in an interactive session
- Skip the gold-standard-validator after extraction-implementer completes
- Commit extraction changes without a passing validation

**Pre-commit review (optional but recommended):**
After validation passes, spawn the reviewer:
```
Task(subagent_type="extraction-reviewer", prompt="Review staged extraction changes against the 5 rules")
```

## Large Refactors (>5 files) → Refactor Team

**Trigger:** Task touches more than 5 files across `src/`.

**Required action:** Spawn the refactor team:

```
Task(subagent_type="general-purpose", prompt="<implementation task>")
  ↓ on completion
Task(subagent_type="test-runner", prompt="Run full test suite")
  ↓ if failures
Task(subagent_type="general-purpose", prompt="Fix test failures: <runner findings>")
```

## Decision Flowchart

```
Is the change touching extraction/keyword/FP files?
  YES → Use extraction team (implementer + validator)
  NO  → Is it touching >5 files?
          YES → Use refactor team (implementer + test-runner)
          NO  → Interactive session is fine
```

## Escalation

If an interactive session has already made 3+ commits touching extraction files,
STOP and switch to the extraction team pattern for remaining work.
