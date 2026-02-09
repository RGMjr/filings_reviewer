# Ralph Worker Prompt Template (Streamlined)

Use this template for autonomous Ralph Loop execution. For interactive sessions or complex architectural tasks, use the full `WORKER_PROMPT_TEMPLATE.md`.

---

```markdown
# TASK: [ID] - [Short Title]

## Objective

[2-3 sentences: What to build and why. Be specific about the outcome.]

## Acceptance Criteria

- [ ] AC-1: [Specific, testable criterion]
- [ ] AC-2: [Next criterion]
- [ ] AC-3: [Continue as needed]
- [ ] AC-N: Tests pass with coverage >= 75%

## Files to Modify

- `src/path/file.py` - [Brief description of change]
- `tests/path/test_file.py` - [What tests to add/modify]

## Files to Read (Context)

- `src/path/reference.py` - [Why this provides useful context]

## Verification

```bash
# Required
pytest tests/unit/[relevant_path]/ -v

# If modifying extraction/keywords
pytest -m gold_standard --gold-standard-mode=fresh -v
```

## Do NOT

- [Specific file or pattern to avoid modifying]
- [Scope boundary - what NOT to change]
```

---

## Template Guidelines

**Keep it under 80 lines total** - Ralph doesn't need:
- Time estimates
- Risk assessments
- Dependency tracking
- Backward compatibility (unless specifically relevant)
- Detailed rationale

**Focus on**:
- Clear acceptance criteria (Ralph works through these one at a time)
- Specific file paths (reduces search time per iteration)
- Explicit scope boundaries (prevents drift)

**Acceptance criteria tips**:
- One testable outcome per criterion
- Include test coverage as final criterion
- Order from foundation to completion

---

## Example: Real Task

```markdown
# TASK: MET-15 - Add customer count metric aliases

## Objective

Add alias support so gold standard validation correctly matches "customer_count" with "cm_customers_period_end" and similar variations.

## Acceptance Criteria

- [ ] AC-1: Add `aliases` field to metric definitions in metric_keywords.yaml
- [ ] AC-2: Implement `resolve_to_canonical()` in keyword_config.py
- [ ] AC-3: Update validate_against_gold_standard.py to use alias resolution
- [ ] AC-4: Tests pass, coverage >= 75% for keyword_config.py

## Files to Modify

- `config/metric_keywords.yaml` - Add aliases field to cm_customers_period_end
- `src/extraction/keyword_config.py` - Add resolve_to_canonical(), get_aliases()
- `scripts/validate_against_gold_standard.py` - Use alias resolution in comparison
- `tests/unit/extraction/test_keyword_config.py` - Add alias resolution tests

## Files to Read (Context)

- `data/gold_standard/baseline_metrics.json` - See current metric ID format

## Verification

```bash
pytest tests/unit/extraction/test_keyword_config.py -v
python3 scripts/validate_against_gold_standard.py --all --mode fresh --baseline
```

## Do NOT

- Modify metric extraction logic (this is validation-only)
- Change canonical metric IDs in YAML
```
