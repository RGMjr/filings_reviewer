# WORKER PROMPT TEMPLATE - LITE (v1.0)

**Purpose**: Lightweight template for XS/S tasks (<2 hours). Use full template for M/L/XL tasks.

**When to Use**:
- Bug fixes
- Minor enhancements
- Configuration changes
- Documentation updates
- Tasks with clear, bounded scope

---

# WORKER PROMPT: Task [ID] - [Short Title]

```
TASK ID:       [ID]
TASK NAME:     [1-line description]
SIZE:          [XS | S] (XS=<30min, S=30min-2hr)
RISK:          [None | Low]
```

## Objective

[1-2 sentences: What and why]

## Changes Required

| File | Change |
|------|--------|
| `path/to/file.py` | [Brief description] |

## Acceptance Criteria

- [ ] [Criterion 1]
- [ ] [Criterion 2]
- [ ] Tests pass: `pytest [path] -v`
- [ ] No regressions: `pytest tests/unit/ -q`

## Do NOT

- [Any constraints]

## Verify

```bash
# Single command to verify completion
pytest [test_path] -v && echo "✅ Done"
```

---

**Format Version**: 1.0 (Lite)
