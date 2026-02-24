# WORKER PROMPT: Task PRD-03 - V2 Quality Tuning (Phase 1)

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       PRD-03
TASK NAME:     Tune V2 Candidate Generation to close the F1 recall gap
WORKSTREAM:    Extraction Logic (Phase 1 Tactical)
STATUS:        🟡 PENDING
RISK LEVEL:    Medium (Requires Gold Standard validation)
TASK SIZE:     M
DEPENDS ON:    PRD-02 (Recommended)
BLOCKS:        None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective
Tune V2 logic to improve its extraction F1 score (`69.6%`) to meet or exceed V1 (`74.1%`), bridging the recall gap while defending precision.

**Business Rationale**: Production needs both V2 speed and V1 accuracy. 

## Hybrid Execution Loop Expectations
1. **Recon**: Run the gold baseline test and explicitly list the top 3 missing metrics (false negatives) before attempting a code fix.
2. **Evaluate Gate**: Require F1 score comparison sign-off from User before committing.

## Implementation Requirements
1. **Analyze**: Find why `candidate_generation.py` or `value_binding.py` fails on valid metrics.
2. **Tune**: Adjust matching scope, bounding box logic, or string parsing rules securely.
3. **Do NOT**: Bypass `mypy` types or add LLM loops here.

## Verification Commands
```bash
mypy src/extraction_v2/ --strict
pytest -m gold_standard --gold-standard-mode=fresh -v
```

## Acceptance Criteria
- [ ] Documentation of the false negative investigation provided in chat.
- [ ] Gold Standard F1 score improves (`> 69.6%`).
- [ ] Tests remain passing.
