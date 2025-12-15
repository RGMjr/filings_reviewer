```
WORKER PROMPT: Task Q1 - Define SegmentDict TypedDict

## Context
You are implementing Task Q1 from MASTER_TASK_LIST.md. This is a code quality refactoring
task that improves type safety by replacing Dict[str, Any] with a proper TypedDict.

## Objective
Define a `SegmentDict` TypedDict in `src/review/models.py` that precisely describes the
structure of segment dictionaries used throughout the review module.

## Background
Currently, `candidate_generator.py` and other review modules receive segment data as
`Dict[str, Any]`. This loses type information and allows invalid data to pass silently.
A TypedDict will:
1. Document the expected segment structure
2. Enable mypy to catch type errors at development time
3. Improve IDE autocomplete and documentation

## Required Steps

### Step 1: Analyze Current Usage
Read these files to understand how segment dicts are used:
- `src/review/candidate_generator.py` (main consumer)
- `src/review/models.py` (where TypedDict will be added)
- `src/infra/db.py` (method `get_source_segments_for_filing` returns segments)

Look for:
- Which keys are accessed on segment dicts (e.g., `segment['text']`, `segment['segment_id']`)
- Which keys are required vs optional
- The expected types of each value

### Step 2: Define SegmentDict
Add to `src/review/models.py`:

```python
from typing import TypedDict, NotRequired

class SegmentDict(TypedDict):
    segment_id: int
    filing_id: int
    # ... add all required fields
    # Use NotRequired for optional fields
```

### Step 3: Add Docstring
Include a docstring explaining:
- What this TypedDict represents
- Where segment dicts come from (db.get_source_segments_for_filing)
- Example usage

### Step 4: Export from __init__.py
If `src/review/__init__.py` exists and exports models, add SegmentDict to exports.

### Step 5: Verify Type Safety
Run: `mypy src/review/models.py --strict`
Ensure zero errors.

## Constraints
- DO NOT modify `candidate_generator.py` signatures yet (that's Task Q2)
- DO NOT modify `src/infra/db.py` (out of scope)
- DO NOT change any runtime behavior - this is type annotations only
- KEEP the existing ReviewCandidate, ReviewDecision, and other models unchanged

## Expected Output Structure
The SegmentDict should include at minimum:
- segment_id: int
- filing_id: int
- text: str
- segment_type: str (e.g., "paragraph", "table", "heading")
- section_name: str | None
- position: int (ordinal position in filing)

Examine actual usage to confirm all fields.

## Definition of Done
- [ ] SegmentDict TypedDict defined in `src/review/models.py`
- [ ] Docstring explains purpose and usage
- [ ] `mypy src/review/models.py --strict` passes with zero errors
- [ ] Existing tests still pass: `pytest tests/unit/review/test_models.py -v` (if exists)
- [ ] No functional changes to any module

## Estimated Time
30 minutes
```