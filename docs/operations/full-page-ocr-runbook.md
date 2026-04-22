# Full-Page-Scan OCR Runbook

How to operate the two optional image-OCR entry points introduced in the
full-page-OCR feature branch: `FULL_PAGE_OCR_ENABLED` (Path A) and
`IMAGE_KEYWORD_PRESCAN_ENABLED` (Path B). Both ship default-off.

## What each path does

### Path A — full-page-scan filing

Fires on filings that are effectively page-image decks — no HTML body
text, just JPG pages (PayPal 8-Ks are the prototypical case). The
detector in `src/extraction_v2/stages/image_triage.py` gates on three
conditions that must **all** hold:

1. `image_count >= 5`
2. `images_per_page = image_count / max(1, total_text_chars / 2000) >= 1.5`
3. `>=70%` of images are "page-shaped" (portrait aspect 0.7–0.85, width
   900–1300, or dimensionless-but-large)

When the detector fires, every page-shaped image is reclassified as
`FULL_PAGE_SCAN` and the OCR stage calls
`VisionClient.analyze_image_for_text` on each. Extracted text is
appended to `context.segments` with `source_type='image_ocr'` and
`source_img_id` pointing at the asset. The existing `candidate_generation
→ value_binding → fact_construction` pipeline runs unchanged on those
segments. If the vision response flags the page as chart-bearing, the
existing chart-extraction path runs on the same image as a second pass.

Per-filing cap: `MAX_FULL_PAGE_OCR_CALLS_PER_DOCUMENT = 30`. Chart
re-passes share `MAX_CHART_CALLS_PER_DOCUMENT = 10`.

### Path B — image-level Tier-1 keyword pre-scan

For filings that did **not** trigger Path A, pre-scan runs on ambiguous
images only: `classification == UNKNOWN` and
`0.2 <= relevance_score < 0.3`. Each ambiguous image gets one cheap
`analyze_image_for_text` call; if the OCR text contains any Tier-1
keyword (`cohort`, `retention`, `ltv`, `cac`, `revenue concentration`,
etc. — see `OCRExtractionStage.TIER1_KEYWORDS_RE`), the image is
promoted to `CHART` or `TABLE_IMAGE` and the existing structured
extraction runs as a second call. If no Tier-1 keyword matches, the
OCR text is recorded on `v2_image_assets.ocr_text` for audit but no
segment is synthesized and the image stays `UNKNOWN`.

Per-filing cap: `MAX_PRESCAN_CALLS_PER_DOCUMENT = 10`. Worst-case cost
per filing: ~$1 (10 pre-scans + 10 escalations at ~$0.05 each).

## Turning the flags on

Both flags live on `PipelineConfig` (`src/extraction_v2/pipeline.py`):

```python
PipelineConfig(
    enable_full_page_ocr=True,           # Path A
    enable_image_keyword_prescan=True,   # Path B
)
```

Env-driven opt-in is explicitly handled by the backfill script and can
be plumbed into CLI runners via an `os.environ.get("FULL_PAGE_OCR_ENABLED")`
check. The `PipelineConfig` dataclass itself is pure data — it does not
read environment variables.

Recommended rollout (matches the feature-branch plan):

1. **PR 1** — Phases 1–4 merge behind both flags default-off. CI green.
2. **Dev smoke test** — Set `FULL_PAGE_OCR_ENABLED=true` in dev. Run
   `scripts/backfill_full_page_ocr.py --confirm --filing-ids <one>` on
   exactly one PayPal pre-2024 8-K. Inspect the synthesized segments
   and any resulting facts manually.
3. **Prod Path A** — Flip `FULL_PAGE_OCR_ENABLED=true` in prod. Run the
   backfill over all 12 pre-2024 PayPal 8-Ks.
4. **Dev Path B** — After Path A is stable, flip
   `IMAGE_KEYWORD_PRESCAN_ENABLED=true` in dev. Re-extract 5 known
   "investor-deck style" filings (text + embedded image tables).
   Spot-check for false positives.
5. **Prod Path B** — Once clean, flip the flag in prod. Ongoing ingest
   picks up new filings organically.

## Dry-run + backfill (Path A)

The backfill script is `scripts/backfill_full_page_ocr.py`.

```bash
# List candidate filings + estimated cost (no DB writes, no vision calls)
DATABASE_URL=postgresql://... python3 scripts/backfill_full_page_ocr.py --dry-run

# List candidates scoped to PayPal pre-2024 8-Ks
DATABASE_URL=postgresql://... python3 scripts/backfill_full_page_ocr.py --dry-run \
    --cik 0001633917 --form-type 8-K --filing-date-before 2024-01-01

# Commit — requires FULL_PAGE_OCR_ENABLED=true
FULL_PAGE_OCR_ENABLED=true DATABASE_URL=postgresql://... \
    python3 scripts/backfill_full_page_ocr.py --confirm \
        --cik 0001633917 --form-type 8-K --filing-date-before 2024-01-01
```

The script refuses `--confirm` unless `FULL_PAGE_OCR_ENABLED=true` is
set in the environment. It also skips filings with rows in
`v2_review_decisions` unless `--force-reextract` is supplied (standard
reviewed-filing guard — see `.claude/rules/v2-pipeline.md`).

A JSON run summary is written to `logs/full_page_ocr_backfill_<ts>.json`.

## Verification SQL

Use these queries after running the backfill to confirm segments and
facts landed as expected.

```sql
-- Path A coverage check: count OCR'd segments + resulting facts per filing.
SELECT f.accession_number, f.filing_date,
       (SELECT COUNT(*) FROM v2_segments s
        WHERE s.doc_id = f.filing_id AND s.source_type = 'image_ocr') AS ocr_segments,
       (SELECT COUNT(*) FROM v2_metric_facts mf WHERE mf.doc_id = f.filing_id) AS facts,
       (SELECT COUNT(*) FROM v2_image_assets i
        WHERE i.doc_id = f.filing_id AND i.classification = 'full_page_scan') AS page_scan_imgs
FROM filings f
WHERE f.cik = '0001633917' AND f.form_type = '8-K' AND f.filing_date < '2024-01-01'
ORDER BY f.filing_date DESC;

-- Path B coverage check: images that got promoted via pre-scan.
-- Note: post-promotion the classification is CHART or TABLE_IMAGE; the
-- source_type='image_ocr' segments are the authoritative signal.
SELECT f.accession_number, f.filing_date, c.company_name,
       COUNT(DISTINCT s.source_img_id) AS ocr_escalated_imgs,
       COUNT(s.segment_id) AS ocr_segments
FROM filings f
JOIN companies c ON c.company_id = f.company_id
JOIN v2_segments s ON s.doc_id = f.filing_id
WHERE s.source_type = 'image_ocr'
  AND f.cik != '0001633917'  -- exclude Path-A filings
GROUP BY f.accession_number, f.filing_date, c.company_name
ORDER BY f.filing_date DESC;
```

## Rollback

The safest rollback is flip the flag off and let ingestion re-run skip
the OCR paths on any future filings. To remove synthesized segments
from an already-backfilled filing, delete them directly:

```sql
-- Destroy all image-OCR segments for a specific filing.
-- Derived facts will be deleted via ON DELETE CASCADE on v2_metric_facts.
DELETE FROM v2_segments
 WHERE doc_id = <filing_id> AND source_type = 'image_ocr';
```

Note: this cascades to any facts that referenced those segments as
their source, because `v2_metric_facts` has
`ON DELETE CASCADE` against segment rows via `source_locator`. If the
filing had reviewer decisions on those facts they will also be removed
— use `--force-reextract` semantics only when this is acceptable.

## Tuning

Detector thresholds live on `ImageTriageStage` as class constants.
Bump conservatively — the `images_per_page >= 1.5` gate is the primary
precision guard.

- `FULL_PAGE_SCAN_MIN_IMAGES` (5) — absolute floor.
- `FULL_PAGE_SCAN_MIN_RATIO` (1.5) — images per page of text.
- `FULL_PAGE_SCAN_MIN_PAGE_SHAPED_FRACTION` (0.70) — how many images
  must be portrait page-sized.
- `PAGE_SHAPED_ASPECT_MIN/MAX` (0.70 / 0.85), `PAGE_SHAPED_WIDTH_MIN/MAX`
  (900 / 1300) — page-shape envelope.

Pre-scan scope is controlled by:

- `MIN_RELEVANCE_FOR_PROCESSING = 0.3` (upper bound of pre-scan band).
- The pre-scan band lower bound (0.2) is hard-coded in
  `_prescan_ambiguous_images`.
- `TIER1_KEYWORDS_RE` — add phrases as new Tier-1 metrics join the
  portfolio. Precision-first wording preferred.
