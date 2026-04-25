# chart_type product decision

**Date:** 2026-04-25
**Author:** Claude (design review)
**Status:** Recommendation, awaiting user approval
**Related:** [gh-196 known-issue fragment](../known-issues/gh-196-ml-triage-feed-from-legacy-image-decisions.md), PR #198, PR #192, PR #151

## Context

PR #198 (gh-196) ported `scripts/export_image_training_data.py` to UNION the legacy `v2_image_review_decisions` and the new `v2_image_metric_confirmations` (schema from PR #151; reviewer UI from PR #192). The port is partial: confirmations emit `chart_type=NULL`. We need a decision on how to handle the missing signal.

Two options on the table:

- **(A)** Extend `v2_image_metric_confirmations` to capture `chart_type` (three sub-options on *who* fills it).
- **(B)** Rework `scripts/benchmark_vision.py` and the triage model to not depend on `chart_type`.

This memo recommends one path. It is intentionally direct about downsides — both options have material costs.

## Background facts grounding the decision

- Today's training data: **851 legacy rows + 1 confirmation-derived row** in Neon prod. chart_type is intact for ~99.9% of training data right now, but erodes as confirmations grow.
- Two `chart_type` enums coexist in the codebase and **do not align**:
  - `v2_image_review_decisions.chart_type` (sql/29, reviewer-assigned, 7 values): `cohort_table, cohort_parfait, line_chart, bar_chart, stacked_bar, other_chart, mixed`. Semantic.
  - `v2_image_assets.chart_type` (sql/09, OCR/chart-read stage, 6 values): `bar, line, pie, stacked_bar, area, unknown`. Structural.
  - The reviewer-only categories `cohort_table` and `cohort_parfait` — exactly the values used to define **Tier-1** in stratification — have no equivalent in the Vision-emitted enum.
- `v2_image_classifications` (sql/45, the new Vision-API metric-classify audit) has **no chart_type column**. `ImageClassificationRecord` (`src/extraction_v2/models.py:695`) does not carry chart_type. `CLASSIFY_PROMPT` requests metric IDs, confidence, rejection_reason, reasoning — not chart shape.
- chart_type consumers, all on origin/main:
  - `scripts/benchmark_vision.py:_CORPUS_QUERY` (line ~187) reads `d.chart_type` from `v2_image_review_decisions` only.
  - `scripts/benchmark_vision.py:_stratify_corpus` (line ~242): `MAX_PER_STRATUM=30`, `TIER1_TARGET=40`, `HARD_OCR_TARGET=20`. Stratum bucket key is `stratum_label(decision, chart_type, rejection_reason)`.
  - `src/gold_standard/image_eval.py`: `TIER1_CHART_TYPES = {cohort_table, cohort_parfait, mixed}`; `HARD_OCR_CHART_TYPES = {cohort_table, cohort_parfait, stacked_bar, mixed}`. Both reference the reviewer enum.
  - `scripts/export_image_training_data.py`: chart_type is column 30 in `OUTPUT_COLUMNS`. Legacy path emits the reviewer value; confirmations path emits NULL → empty string.

## Recommendation

**Option B (rework stratification to drop chart_type), with a hybrid replacement.**

Rationale: the reviewer surface has shifted from image-level to per-metric (PR #151 schema, PR #192 UI). The semantic categories `cohort_table` / `cohort_parfait` carried two signals — "this image is hard to OCR" and "this image likely contains Tier-1 cohorted metrics." The latter is now captured directly and more reliably by `detected_metrics` (sql/42) and `v2_image_metric_confirmations.confirmed_metric_id`. Stratifying by Tier-1 metric ID is a *stronger* signal than chart shape for the bake-off harness's purpose, which is presence-first metric classification — not chart-shape recognition. Sub-option A3 (Vision-API capture) is the worst path because the two existing enums don't align: the prod Vision pipeline emits structural shapes; reviewers assign semantic shapes; asking the Vision API to produce "cohort_parfait" reliably is unproven prompt-engineering work. Sub-options A1/A2 (UI capture) re-introduce image-level workflow into a UI that just moved to per-metric — workflow regression for a feature whose primary consumer is solvable other ways.

Honest downside of B: hard-OCR stratification loses fidelity. `cohort_table` and `cohort_parfait` are visually distinctive (dense, multi-column, axis-heavy) in a way that `detected_metrics ∋ cm_revenue_by_cohort` does not always predict. We accept a noisier hard-OCR bucket in exchange for not maintaining a parallel labeling axis.

## Implementation sketch (Option B)

### Phase 1 — Replace tier-1 stratification with metric-presence signal

- `src/gold_standard/image_eval.py`:
  - Replace `TIER1_CHART_TYPES` with `TIER1_METRIC_IDS` (frozenset). Source from CLAUDE.md's Tier-1 list; the same 15 metric IDs are already enumerated in `_TIER1_FACTS_QUERY` in `benchmark_vision.py` and can be lifted.
  - Rewrite `is_tier1_image(chart_type)` → `is_tier1_image(detected_metrics: list[str] | None) -> bool`. Returns True if any element ∈ `TIER1_METRIC_IDS`.
  - Rewrite `stratum_label` to accept `detected_metrics` instead of `chart_type`; bucket key becomes e.g. `tier1/cm_revenue_by_cohort` or `chart/no-tier1`.
- `scripts/benchmark_vision.py`:
  - `_CORPUS_QUERY`: UNION `v2_image_review_decisions` and `v2_image_metric_confirmations` (mirror the precedence rule already in `export_image_training_data.py`); SELECT `v.detected_metrics` from `v2_image_assets`.
  - `_stratify_corpus` callsites: pass `detected_metrics` instead of `chart_type`.
  - Manifest entries: drop `chart_type`, `is_tier1`, `is_hard_ocr`. Add `detected_metrics`, `is_tier1` (metric-presence-derived), and a hard-OCR proxy field (see Phase 2).

### Phase 2 — Replace hard-OCR stratification with image-density proxy

We don't have OCR text length at corpus-build time, so the cleanest density measure is unavailable. Practical alternatives, in order of preference:

1. **`v2_image_assets.classification = 'table_image'`** as a hard-OCR bucket bias — table images are the dense-text case par excellence. (Free; already populated.)
2. **Aspect ratio + minimum dimension threshold** — `min(w,h) >= 600 AND w*h >= 480000` as a heuristic for dense cohort tables / parfaits. (Free; already in DB.)
3. **A new `chart_density` field on `v2_image_classifications`** — out of scope for this PR; only worth doing if (1)+(2) prove insufficient.

Validation step before merging Phase 1+2: build the corpus both ways from current legacy rows (chart_type-based vs proxy-based), compute Jaccard overlap on the hard-OCR bucket. If overlap ≥ 0.6, ship; if not, revisit.

### Phase 3 — Drop chart_type from training feature set

- `scripts/export_image_training_data.py`:
  - Remove `chart_type` from `OUTPUT_COLUMNS`.
  - Remove `chart_type` from both query SELECT lists and row dicts.
- ML team coordination:
  - Retrain triage model without chart_type on existing 852-row corpus. Compare AUC / precision@K to last baseline.
  - If degradation > 2 pp on AUC, escalate to Option A1 fallback (see Risks).

### Phase 4 — Documentation

- Update `docs/known-issues/gh-196-ml-triage-feed-from-legacy-image-decisions.md`:
  - Move "Still open" items to "Resolution status" referencing the new PR.
  - Flip `status: partially-resolved` → `resolved` once retrain validates.
- Add a paragraph to `docs/operations/image-pipeline-modernization-plan.md` under "stratification" (or to the chart-presence pivot doc set if no such section exists).
- This change is a direct consequence of the 2026-04-23 chart-presence pivot — note that lineage explicitly in the doc update.

## Risks and open questions

1. **Hard-OCR proxy fidelity is unproven.** The (classification + dimension) heuristic may underweight cohort parfaits (typically chart-classified, modest dimensions, but text-dense). *Mitigation:* Phase 2 validation step before merging. *Escalation:* image-density column on sql/45.
2. **Triage model AUC degradation.** chart_type may carry signal beyond tier-1 / hard-OCR stratification — for example, it likely discriminates `decorative` vs `chart` more sharply than the V2 `classification` column, which has known inaccuracy on that boundary. *Mitigation:* Phase 3 retrain measures this directly. *Fallback:* Option A1 — add nullable `chart_type TEXT` to `v2_image_metric_confirmations` and capture image-level via a small UI addition (one dropdown surfaced after the per-metric A/R/C/Add loop completes for an image).
3. **Manifest reproducibility.** The current manifest embeds `chart_type` in bucket names via `stratum_label`. Switching to metric-derived labels invalidates existing manifest snapshots. New benchmark runs are not backwards-comparable to pre-change baselines on a per-stratum basis (corpus-level metrics still are, since img_id set is broadly stable).
4. **`detected_metrics` quality for legacy rows.** sql/42 was added recently; backfill coverage for old `v2_image_assets` rows determines whether legacy rows can be re-stratified. *Action item:* verify backfill coverage on the 851 legacy rows before relying on `detected_metrics` as the tier-1 signal.
5. **Mixed-shape images.** Reviewer enum has `mixed`; metric presence has no equivalent. A "mixed" image with multiple Tier-1 metrics still buckets as Tier-1 (correct). One with two non-Tier-1 metrics in one frame would not. Probably fine, but worth eyeballing on the 851-row corpus.
6. **Quantification gap.** The prompt asked us to quantify what the triage model loses by dropping chart_type. We cannot do this a priori without running the retrain — the empirical comparison in Phase 3 *is* the quantification. The Phase 3 gate (>2 pp AUC drop → fall back to A1) is the honest answer.
7. **ML team coordination dependency.** Option B's merge gate is the retrain comparison. If the ML team is not ready to retrain on the unified feed (or doesn't have a recent baseline), Phase 3 stalls. *Action item:* confirm ML team capacity before opening the issue, or scope the retrain into the implementation issue itself.

## Estimated effort

- **Option B (recommended):** 1 PR — benchmark + export code change + retrain validation. ~1 week engineering + 2–3 days ML retrain. If hard-OCR proxy validation fails, +3 days for an image-density column (sql/46 migration + classify-stage emit).
- **Option A1 fallback (only if B retrain regresses):** 1 schema PR (nullable `chart_type` column add + 7-value enum CHECK + UI dropdown after per-metric loop + route change in `src/web/routes/api_unified.py` + backfill from legacy table) + 1 retrain PR. ~2 weeks engineering. Adds reviewer friction: the new UX is image-level *after* metric-level, which is awkward versus the legacy "Y → chart_type select" fast path.
- **Option A3 (Vision-API capture) — not recommended:** 1 PR — extend `CLASSIFY_PROMPT` + `ImageClassificationRecord` + sql/45 migration + bake-off prompt evaluation. ~2 weeks plus prompt-engineering iteration of unknown duration. High risk of low precision on `cohort_table` / `cohort_parfait` recognition.

---

**User action requested:** approve the recommendation (Option B with hybrid stratification + retrain validation gate) so an issue can be opened with the implementation sketch above. If you'd prefer to lock in Option A1 up front to preserve the chart_type signal regardless of empirical impact, say so and I'll redraft.

---

# Addendum (2026-04-25): empirical findings invalidate Option B's premise

After the main memo was written we ran the Risk #4 verification query against Neon prod — coverage of each candidate stratification signal on the existing 851-row legacy corpus. The numbers force a recommendation flip.

## Query results (read-only, against `DATABASE_URL`)

Tier-1 set: the 15 metric IDs enumerated in CLAUDE.md ("Tier 1 must-not-miss"). Legacy chart_type Tier-1 set: `chart_type IN ('cohort_table', 'cohort_parfait', 'mixed')` — 24 of 851 rows.

| Candidate signal | Total rows | Identifies as Tier-1 | Coverage of legacy Tier-1 set |
|---|---|---|---|
| Legacy `d.chart_type` (definitional) | 851 | 24 | 100% |
| `v2_image_assets.detected_metrics` JSONB has any Tier-1 metric (Phase 1 primary) | 851 | 1 | **4.2%** |
| `v2_image_assets.chart_data` populated (input for backfill via `ChartMetricClassifier`) | 851 | 5 | **20.8%** |
| `classification = 'table_image'` (Phase 2 hard-OCR proxy #1) | 55 | 0 | **0%** |
| Dense dimensions `min(w,h) ≥ 600 AND w*h ≥ 480000` (Phase 2 hard-OCR proxy #2) | 273 | 1 | **4.2%** |

Jaccard between the legacy chart_type Tier-1 set and the `detected_metrics` Tier-1 set: **0.000** — completely disjoint. All 24 legacy Tier-1 images carry `classification='chart'` with no special dimensional signature.

## Why both phases of Option B fail on the historical corpus

- **`detected_metrics` was never backfilled on legacy rows.** sql/42 added the column; `ChartFactBridgeStage` only writes it on new extractions. Phase 1's primary signal effectively does not exist for the 851 rows.
- **`chart_data` is on only 45 of 851 rows.** OCR/Vision was never run against the other ~800 — they were reviewed without chart-data being persisted. Even running `ChartMetricClassifier` as a backfill step recovers only ~21% of the legacy Tier-1 set.
- **Phase 2 proxies have zero discriminative power for legacy Tier-1.** Neither `classification='table_image'` nor the dimension heuristic overlaps materially with the legacy Tier-1 set. The hard-OCR bucket replacement in Phase 2 isn't noisier than legacy — it's empty.

## Cost to make Option B work anyway

To use `detected_metrics` as the Tier-1 signal on existing data, we would need to:

1. Run OCR/Vision-extract on the ~800 chart-classified images currently lacking `chart_data`. Vision API spend on the order of $5–20; multi-hour batch.
2. Run `ChartMetricClassifier` against the result.
3. Backfill `v2_image_assets.detected_metrics` on those rows.

This is doable but it's a real backfill workstream that wasn't in the original Option B effort estimate. Adding it changes Option B's effort from "1 PR, ~1 week" to "~2.5 weeks including backfill + retrain validation," with new failure modes (Vision API rate limits, classifier accuracy on stale chart images).

## Revised recommendation: **Option A1, narrow scope**

The original analysis chose B partly on the premise that chart_type signal could be reconstructed cheaply from existing schema. That premise broke. With the empirical data in hand, A1 becomes the materially better path:

- **Preserves stratification on the existing 851-row corpus** — chart_type is already there, intact, no work needed.
- **Bounded forward cost** — schema change + small UI addition, no Vision API spend, no batch backfill.
- **Bounded UX cost** — image-level chart_type capture happens once per image, decoupled from the per-metric A/R/C/Add flow. Lower friction than the original memo feared if surfaced as an *optional* prompt rather than a required step.
- **Vision-API path stays explicitly out of scope** — the two-enum collision (semantic vs structural) makes prompt-engineering for "cohort_parfait" recognition a separate workstream that A1 does not depend on.

## A1-narrow specification (sketch — full design deferred to implementation issue)

- **Schema.** Add `reviewer_chart_type TEXT NULL` to `v2_image_assets` with the legacy 7-value CHECK constraint (`cohort_table, cohort_parfait, line_chart, bar_chart, stacked_bar, other_chart, mixed`). **Do not** add chart_type to `v2_image_metric_confirmations` — chart_type is image-level, repeating it per metric is a denormalization smell and re-aligning with the existing reviewer enum is what makes the feature reusable.
- **Capture surface.** Add a small dropdown in `unified_review.html`'s image tab, surfaced after the per-metric card when at least one accept/correct/add decision exists on the image. Optional — leaving null is allowed. Single POST endpoint, e.g. `POST /api/v2/images/<img_id>/chart-type`.
- **Backfill.** One-time SQL: `UPDATE v2_image_assets SET reviewer_chart_type = d.chart_type FROM v2_image_review_decisions d WHERE v2_image_assets.img_id = d.img_id AND d.chart_type IS NOT NULL`. Trivial; preserves all 851 rows of historical signal in one statement.
- **Consumers.** `scripts/benchmark_vision.py:_CORPUS_QUERY` and `scripts/export_image_training_data.py` read `v.reviewer_chart_type` (single-source, no UNION needed since the column is uniformly populated for legacy and going forward). Existing `is_tier1_image` / `is_hard_ocr_image` / `TIER1_CHART_TYPES` / `HARD_OCR_CHART_TYPES` references in `src/gold_standard/image_eval.py` keep working with no logic change.
- **Vision-API path explicitly out of scope.** sql/45 / `image_classify.py` could capture chart_type later if a downstream need emerges; the two-enum collision (semantic vs structural) makes prompt-engineering for "cohort_parfait" recognition a separate, larger workstream.

## What changes from the original memo's plan

- Phase 1 (stratification rework) — **dropped.** No path for it on legacy data.
- Phase 2 (hard-OCR proxy) — **dropped.** Both proxies have zero overlap with the legacy hard-OCR set.
- Phase 3 (drop chart_type from training feature set) — **dropped.** chart_type stays as a feature, populated for both legacy and new rows.
- "ML team coordination" merge gate — **dropped.** No retrain comparison required for this PR; chart_type fidelity stays at parity with today's training.
- Phase 4 documentation update — preserved, but now describes the schema add rather than the stratification rework.

## Effort estimate (revised)

- **Single PR.** Timestamp-named migration (per `.claude/rules/sql.md`) + backfill SQL + UI change + API endpoint + consumer query updates + tests. ~3–5 days engineering. No retrain prerequisite. No Vision API spend.
- Compared to original Option B: cheaper, narrower scope, no batch backfill, no ML team dependency, no manifest-reproducibility risk (since the existing stratification helpers keep working unchanged).

---

**Revised user action requested:** approve the flip to A1-narrow, and reopen #196 (or open a fresh issue) with the implementation sketch above. If you'd rather defer the entire question and let `benchmark_vision.py` continue using only the legacy table for now (acceptable until confirmation count meaningfully grows), say so and I'll redraft once more.
