# Extraction Team

Two-agent team for extraction code changes. Ensures every modification to keyword
config, classifiers, or FP rules is validated against gold standard before commit.

## Agents

| Agent | Role | Model | Max Turns |
|-------|------|-------|-----------|
| `extraction-implementer` | Makes code/config changes, self-tests | inherit | 20 |
| `gold-standard-validator` | Validates quality, detects regressions | inherit | 15 |
| `extraction-reviewer` | Reviews against 5 extraction rules (optional) | sonnet | 12 |

## Task Sequence

### Phase 1: Implement

```python
# Spawn the implementer with the specific task
Task(
    subagent_type="extraction-implementer",
    prompt="""
    Task: <describe the extraction change>

    Requirements:
    - Follow the 5 extraction rules in .claude/rules/extraction.md
    - All keyword patterns go in config/metric_keywords.yaml
    - Self-test with: pytest tests/unit/ -x -q
    - Do NOT commit — leave that for after validation
    """,
    description="Implement extraction change"
)
```

### Phase 2: Validate

After the implementer completes, spawn the validator:

```python
# Spawn the validator to check for regressions
Task(
    subagent_type="gold-standard-validator",
    prompt="""
    The extraction-implementer just completed changes. Validate:

    1. Run: python3 -m src.gold_standard.v2_validator
    2. Report precision/recall/F1 deltas
    3. If regression >1%: diagnose root cause with file:line references
    4. Status: PASS or REGRESSION DETECTED
    """,
    description="Validate gold standard"
)
```

### Phase 3: Fix (if regression)

If the validator reports a regression, send findings back to the implementer:

```python
Task(
    subagent_type="extraction-implementer",
    prompt="""
    Gold standard regression detected. Validator findings:
    <paste validator output>

    Fix the regression while preserving the intended change.
    Re-run self-tests after fixing.
    """,
    description="Fix extraction regression"
)
# Then re-validate (repeat Phase 2)
```

### Phase 4: Review (optional)

After validation passes, optionally review for rule compliance:

```python
Task(
    subagent_type="extraction-reviewer",
    prompt="Review staged extraction changes against the 5 extraction rules",
    description="Review extraction changes"
)
```

### Phase 5: Commit

Only after validation PASSES:
```bash
git add <specific-changed-files>
git commit -m "feat: <description of extraction change>"
```

## When to Use This Team

- Adding/modifying keyword patterns in `metric_keywords.yaml`
- Changing classifier logic in `src/extraction_v2/`
- Modifying FP filter rules in `src/review/false_positive_filter.py`
- Changing candidate generation in `src/review/candidate_generator.py`
- Any change that could affect extraction precision or recall

## When NOT to Use This Team

- Test-only changes (use `test-runner` agent directly)
- Documentation changes
- Web UI changes
- Database migrations (unless they affect extraction output)
