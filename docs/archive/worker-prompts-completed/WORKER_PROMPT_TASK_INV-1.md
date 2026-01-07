# WORKER PROMPT: Task INV-1 - Farfetch Extraction Failure Investigation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       INV-1
TASK NAME:     Investigate Farfetch Extraction Failure and Document Fix Alternatives
WORKSTREAM:    Extraction Pipeline Debugging
SOURCE:        Manual investigation request (2026-01-06)
STATUS:        ✅ COMPLETE
COMPLETION:    2026-01-06
TIME ESTIMATE: 2-3 hours
TIME ACTUAL:   ~2.5 hours
RISK LEVEL:    None (read-only investigation, no code changes)
TASK SIZE:     M
DEPENDS ON:    None
UNLOCKS:       INV-1-FIX (Fix implementation task)
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Investigate why the Farfetch filing (filing_id=31) fails to extract segments in reasonable time, identify the root cause, and produce a detailed report with alternative fix approaches.

**Business Rationale**: The Farfetch S-1 filing is a high-value document for human review quality assessment. Without extraction, it cannot be included in the review system. Understanding this failure will also help prevent similar issues with other large filings.

**Current Behavior**: When running `python scripts/rerun_single_filing.py --filing-id 31`:
- Process outputs 26 HRV-22 warnings about text/HTML mismatches
- Process takes ~105 seconds (vs 5.5s for comparable Slack filing)
- Appears to "hang" due to slow processing that exceeds user patience

**Desired Behavior**: Produce a comprehensive investigation report documenting the root cause and fix alternatives.

## Investigation Summary

### Root Cause Identified

The slowdown is caused by `_compute_element_offsets()` method at `html_segmenter.py:659-711`:

1. **BeautifulSoup HTML Normalization**: BeautifulSoup normalizes HTML during parsing (lowercases tags, reorders attributes)
2. **String Matching Failure**: The method uses `html.find(element_html)` to locate elements in original HTML
3. **100% Lookup Failure**: All 7,760 Farfetch elements fail to find their position because `str(element)` differs from original HTML
4. **Full Scan Per Element**: When lookup fails, search_start never advances, forcing full 2.75MB scan for each element
5. **Cumulative Impact**: ~21 billion character comparisons total

### Performance Data

| Filing | File Size | Elements | Time | Segments | Offset Success |
|--------|-----------|----------|------|----------|----------------|
| Slack | 3.6MB | ~8,500 | 5.5s | 2,243 | Normal |
| Farfetch | 2.6MB | 7,760 | 105s | 2,537 | 0% |

### Alternative Approaches Documented

1. **Approach A: Disable Offset Computation for Large Filings** (RECOMMENDED)
   - Skip `_compute_element_offsets()` when HTML > 1MB or element count > 5,000
   - Low risk, immediate relief
   - Offset data is optional (used for UI highlighting only)

2. **Approach B: Use lxml Parser with Native Source Position**
   - Switch to lxml for `sourceline` and `sourcepos` attributes
   - Medium complexity, requires regression testing

3. **Approach C: Lazy Offset Computation with Caching**
   - Compute offsets on-demand with pre-built index
   - High complexity, significant refactoring

## Deliverables

- [x] Investigation report: `docs/investigation/INV-1_FARFETCH_EXTRACTION_REPORT.md`
- [x] Root cause identified with code line references
- [x] Three alternative approaches documented with pros/cons
- [x] Comparison matrix completed
- [x] Recommendation provided with rationale
- [x] Validation plan documented

## Files Created

1. `docs/investigation/INV-1_FARFETCH_EXTRACTION_REPORT.md` - Complete investigation report

## Files Read (Context)

- `src/extraction/html_segmenter.py` - Primary segmentation logic
- `scripts/rerun_single_filing.py` - Script exhibiting the failure
- `data/filings/0001740915/000119312518252315/primary.htm` - The failing file

## Next Steps

1. Create follow-up task INV-1-FIX to implement Approach A
2. After implementation: Re-run Farfetch extraction and verify < 30 seconds
3. Run gold standard validation to ensure no regression

---

**Completed**: 2026-01-06
**Format Version**: 2.6
