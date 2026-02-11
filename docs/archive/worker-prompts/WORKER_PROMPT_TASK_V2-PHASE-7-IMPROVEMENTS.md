# Worker Prompt: V2-PHASE-7 Value Binding Improvements

## Task ID: V2-PHASE-7-IMPROVEMENTS

## Metadata
- **Size**: S (30 min - 2 hr)
- **Risk**: Low
- **Depends on**: V2-PHASE-7 (complete)

## Objective

Implement three improvements to the Value Binding Stage:
1. Add billion scale support to number parsing
2. Make proximity window configurable
3. Improve sentence boundary detection for text binding

## Implementation Requirements

### 1. Billion Scale Support
- Add "billion" and "B" to the scale indicators in `_parse_number()`
- Handle "$1.2B" → 1,200,000,000
- Handle "1.5 billion" → 1,500,000,000
- Add unit tests for billion parsing

### 2. Configurable Proximity Window
- Add `proximity_window: int = 100` parameter to `ValueBindingStage.__init__()`
- Replace hardcoded `100` in `_find_nearby_numbers()` with the configurable value
- Add test verifying custom window works

### 3. Better Sentence Boundary Detection
- Add `_find_sentence_bounds()` method that finds sentence start/end around a position
- Use regex for sentence boundaries: `[.!?]\s+[A-Z]` or start/end of text
- In `_bind_text_candidate()`, prefer values within the same sentence
- Add higher confidence (+0.1) for same-sentence bindings
- Add tests for sentence boundary detection

## Files to Modify

- `src/extraction_v2/stages/value_binding.py` - All three improvements
- `tests/unit/extraction_v2/test_value_binding.py` - New tests

## Acceptance Criteria

- [ ] `_parse_number()` handles "billion", "B", "$1.2B" correctly
- [ ] `ValueBindingStage.__init__()` accepts `proximity_window` parameter
- [ ] `_find_nearby_numbers()` uses configurable window
- [ ] `_find_sentence_bounds()` method exists and works
- [ ] Same-sentence bindings get confidence bonus
- [ ] All existing tests still pass
- [ ] New tests for all three improvements
- [ ] Coverage remains ≥90%
- [ ] `mypy --strict` passes
- [ ] `ruff check` passes

## Verification Commands

```bash
# Run tests
pytest tests/unit/extraction_v2/test_value_binding.py -v

# Check coverage
pytest tests/unit/extraction_v2/test_value_binding.py --cov=src/extraction_v2/stages/value_binding --cov-report=term-missing --cov-fail-under=90

# Type checking
mypy src/extraction_v2/stages/value_binding.py --strict

# Linting
ruff check src/extraction_v2/stages/value_binding.py
```

## Do NOT

- Change the public API of `ValueBindingStage.process()`
- Modify other stages or pipeline.py
- Add external NLP dependencies (use regex only)
