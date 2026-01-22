# Extraction Plan

**Created**: 2026-01-21
**Purpose**: Track bulk extraction of SEC S-1/F-1 filings
**Mode**: Ralph autonomous loop

---

## Instructions

1. Add filings to extract below (one per line)
2. Format: `[ ] CIK | Company Name | Form Type | Notes`
3. Run `./ops/loop.sh extract` to start the loop
4. Ralph will process one filing per iteration, marking `[x]` when complete

---

## Filings to Extract

### Priority 1: Gold Standard Filings (Re-extraction)
<!-- These filings have gold standard data for validation -->

- [ ] 0001740260 | Farfetch | F-1 | Gold standard: 67 metrics
- [ ] 0001640147 | Snowflake | S-1 | Gold standard: 24 metrics

### Priority 2: Existing Filings (Re-extraction after changes)
<!-- Re-extract after keyword/pipeline changes -->

- [ ] 0001467623 | DocuSign | S-1 |
- [ ] 0001744676 | Samsara | S-1 |
- [ ] 0001679788 | Coinbase | S-1 |
- [ ] 0001594805 | Shopify | F-1 |
- [ ] 0001477449 | Teladoc | S-1 |

### Priority 3: New Filings (First-time extraction)
<!-- Add new filings here -->

<!-- Example format:
- [ ] 0001234567 | Company Name | S-1 | Source: SEC EDGAR search
-->

---

## Completed

<!-- Filings move here after successful extraction -->

- [x] 0001764925 | Slack Technologies | S-1 | 80 segments, 29 candidates (gold standard: 25 metrics)

---

## Errors

<!-- Filings with extraction errors logged here -->

---

## Statistics

| Metric | Count |
|--------|-------|
| Total Filings | 8 |
| Completed | 1 |
| Errors | 0 |
| Remaining | 7 |

---

## Notes

- Large filings (>2MB) may take 30-60 seconds
- Check `ops/AGENTS.md` for troubleshooting commands
- If loop stalls, check for database connection issues
