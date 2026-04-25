# Human Review System

**Status:** V2 unified review (presence-pivot mid-rollout)
**Last Updated:** 2026-04-25

> **This is a pointer document.** The original V1 design doc (candidate
> generator, pattern analyzer, rule applicator, `review_candidates` /
> `review_decisions` tables, `/api/decisions` endpoints, `review.js`) was
> retired and archived at
> [`archive/historical/HUMAN_REVIEW_SYSTEM-pre-presence.md`](archive/historical/HUMAN_REVIEW_SYSTEM-pre-presence.md).

## Active review surfaces

The V2 unified review UI is at `/v2/review/<filing_id>` and serves three
surfaces against a single filing:

1. **Text facts (advisory under the pivot).** Per-fact accept / reject /
   correct decisions persist to `v2_review_decisions`. The
   `v2_review_decision_updates_fact` trigger promotes
   `v2_metric_facts.review_status` accordingly. PR3 of the text-presence
   pivot will add a parallel **presence confirmation** surface
   (`v2_text_presence_confirmations`, sql/48) so reviewers can confirm or
   override per-(doc, metric) presence directly. Until then, presence is
   computed from facts + chart detections + definitions.
2. **Image presence (primary post-#86).** Per-image, per-metric reviewer
   adjudications for chart-presence detections — accept / reject / correct
   / add / skip — persist to `v2_image_metric_confirmations`
   (sql/43, sql/47). The reviewer UI surfaces both rule-based detections
   from `v2_image_assets.detected_metrics` and Vision-classifier
   predictions from `v2_image_classifications`. An accept / correct / add
   promotes a value-less chart `v2_metric_facts` row
   (one per `(doc_id, metric_id)`, `review_status='accepted'`); reject /
   skip / undo roll it back when no other accepting confirmation remains.
3. **Manual value entry.** When CMASB needs a numeric value the pipeline
   did not capture (typical for chart-native metrics under the pivot),
   reviewers use the "Add Missed Metric" modal which posts to
   `POST /api/v2/missed-metric` (`src/web/routes/api_unified.py`). The
   resulting `MetricFact` carries `extraction_method='manual'` and feeds
   into `MetricPresenceStage` on the next re-extraction.

## Reviewer-work protection

Re-extraction of a filing with human review decisions requires explicit
`force=True` / `--force-reextract`. Three guards in
`V2PersistenceAdapter` raise `ReviewedFilingError` otherwise: text-fact
guard on `v2_review_decisions`, image-confirmation guard on
`v2_image_metric_confirmations`, and a hidden-class transition guard in
`_persist_images_in_tx`. See Core Design Principle #6 in `CLAUDE.md`.

## Where to look for details

| Topic | Source |
|---|---|
| Pivot rollout (PR1–PR5) and interface contract | [`operations/text-pipeline-presence-pivot-plan.md`](operations/text-pipeline-presence-pivot-plan.md) |
| Schema for presence + confirmations + classifications | [`architecture/data-model.md`](architecture/data-model.md) |
| MetricPresenceStage and pipeline flow | [`architecture/extraction-pipeline.md`](architecture/extraction-pipeline.md) |
| Vision metric-classifier | [`architecture/llm-integration.md`](architecture/llm-integration.md) |
| V2 review routes (HTML + API) | `src/web/routes/review_unified.py`, `src/web/routes/api_unified.py` |
| Reviewer-UI tests (Playwright) | `tests/e2e/` |
| Historical V1 design (archived) | [`archive/historical/HUMAN_REVIEW_SYSTEM-pre-presence.md`](archive/historical/HUMAN_REVIEW_SYSTEM-pre-presence.md) |
