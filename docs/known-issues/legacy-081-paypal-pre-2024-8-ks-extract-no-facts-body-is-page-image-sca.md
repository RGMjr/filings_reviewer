---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 81
severity: medium
slug: paypal-pre-2024-8-ks-extract-no-facts-body-is-page-image-sca
source: legacy
status: open
title: PayPal Pre-2024 8-Ks Extract No Facts — Body Is Page-Image Scans
touches: []
updated: '2026-04-22'
---

### Problem

PayPal's pre-2024 8-K filings (CIK `0001633917`, 12 filings 2021–2023)
are submitted as page-image decks: each "page" is a JPG (~1055×1365),
there is no HTML body text to segment. The existing V2 pipeline
classifies these images as `UNKNOWN` (below `MIN_RELEVANCE_FOR_PROCESSING=0.3`)
so they never reach the OCR stage, and `context.segments` is empty
so `candidate_generation` runs over nothing. DB state: 0 segments,
199 JPGs unprocessed, 0 facts, 0 review decisions across these 12
filings.

### Resolution

Full-page-scan OCR (Path A) + image-level Tier-1 keyword pre-scan
(Path B), both default-off, landed on the `full-page-ocr` branch.
See `.claude/rules/v2-pipeline.md` for the pipeline-level design and
`docs/operations/full-page-ocr-runbook.md` for the operator runbook
(detector thresholds, dry-run/backfill workflow, verification SQL,
rollback).

### Next Steps

1. Merge the feature branch with both flags default-off; CI green.
2. Dev smoke test on one PayPal 8-K; eyeball segments + facts.
3. Enable `FULL_PAGE_OCR_ENABLED=true` in prod; run
   `scripts/backfill_full_page_ocr.py --confirm --cik 0001633917 --form-type 8-K --filing-date-before 2024-01-01`.
4. Stability permitting, enable `IMAGE_KEYWORD_PRESCAN_ENABLED=true`
   and re-extract 5 investor-deck-style filings to exercise Path B.
