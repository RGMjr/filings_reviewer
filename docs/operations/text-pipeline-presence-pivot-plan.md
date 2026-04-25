# Text-pipeline presence-first pivot

Rollout doc for the text-extraction pivot that mirrors the chart-presence pivot (PR #147). Under this pivot, extraction's primary scoring surface shifts from per-fact accuracy to per-(document, metric) presence detection, plus reviewer confirmation. Fact emission continues as an advisory evidence layer — not deleted, not migrated.

Strategic direction memo: `~/.claude/projects/.../memory/project_presence_first_extraction_direction.md`.

## Program status

| PR | Scope | Status | Migration |
|---|---|---|---|
| PR1 | Schema + presence emission + `presence_only` persistence mode | **Landed** (PR #182) | sql/46 |
| PR2 | Gold-standard presence scoring + validator + Tier 1 gate flip | **Landed** (this PR) | — (no schema) |
| PR3 | Reviewer UI surfaces presence (`v2_text_presence_confirmations`) | Pending | sql/48 |
| PR4 | Tier-1 definition/methodology LLM classifier | Pending | sql/49 |
| PR5 | MetricPresenceStage chart-contribution removal (cleanup) | Pending | — |

Full plan files live under `~/.claude/plans/text-presence-pr*.md` and `~/.claude/plans/text-presence-pivot-index.md`.

## PR2 status (2026-04-25)

PR2 ships the validator + gate flip without the originally-planned new module or new SQL migration.

**Structural deviation from the original plan:**
- The plan assumed a `v_doc_metric_presence` SQL view + `v2_image_metric_presence` table shipped by image-review Wave 1. **Image-review explicitly out-of-scoped both** (`~/.claude/plans/our-disclosures-review-web-deep-blossom.md` line 30); chart-derived presence is now captured by promoting reviewer accept/correct/add decisions into `v2_metric_facts` (`source_type='chart'`, `review_status='accepted'`, PR #192/sql/47).
- Validator gate reads presence **live from `PipelineResult.presences`** (output of `MetricPresenceStage`, which already aggregates text + chart `image.detected_metrics` + definitions). No DB roundtrip. No view shipped in PR2.
- The plan's "three corpora" assumption (filing/presentation/transcript) was stale: the live `v2_validator.py` reads only `data/gold_standard/golden_set_260408.csv` (filing corpus). Transcript and presentation pipelines have separate validators (`scripts/validate_transcript_extraction.py` etc.). **PR2 scope is filing-corpus only**; transcript and presentation Tier-1 presence gates are tracked as follow-up work.
- No new `presence_derivation.py` module — presence projection happens inline in `validate_filing()` from the already-loaded `entries_by_company` dict.

**Code changes:**
- `src/gold_standard/v2_validator.py`: `ValidationResult` gains `metric_presence_tp/fp/fn` + per-metric breakdowns. `validate_filing()` projects expected presence from gold rows, intersects with `v2_result.presences`. `compute_metrics()` aggregates per-tier; `AggregateMetrics` exposes `tier1_presence_recall` / `tier2_presence_recall`. `print_presence_tier_report()` renders the new section with `[GATE]` / `[informational]` markers.
- `src/gold_standard/baseline.py`: `BaselineMetrics` gains `tier1_presence_recall` / `tier2_presence_recall` (None on pre-PR2 baselines; loader tolerates absence). `compare_to_baseline()` flips: only Tier-1 presence-recall regression sets `has_regression=True`. Overall fact P/R/F1, per-company drops, chart `presence_f1`, Tier-2 presence-recall are still surfaced but tagged `[informational]`. `ComparisonResult` gains `tier1_presence_recall_delta` / `tier2_presence_recall_delta`.
- `scripts/backfill_text_presence.py`: new operational script. Defaults to `$TEST_DATABASE_URL`; refuses prod unless `--allow-prod` + `ALLOW_PROD_BACKFILL=yes`. Uses `persist_pipeline_result(presence_only=True)` to populate `v2_text_metric_presence` for reviewed filings without touching `v2_metric_facts` (no `ReviewedFilingError` risk).
- Tests: extended `tests/unit/gold_standard/test_baseline.py` (gate-flip semantics, tier-field round-trip, pre-PR2 backwards compat) and `tests/unit/gold_standard/test_v2_validator.py` (presence aggregation, tier rollup).

**Baseline numbers (regenerated 2026-04-25, post-#182 + post-#192):**
- Tier 1 presence-recall: **85.3%** — the new `tier1_presence_recall` gate metric.
- Tier 2 presence-recall: **91.3%** (informational).
- Tier 1 fact-recall: 50.5% (informational under PR2).
- Tier 2 fact-recall: 36.0% (informational).
- 12 filings ran; ~16s per filing, 193s total wall clock at 4 workers.

**Follow-up workstreams (deferred):**
- Tier-1 presence-recall gate for `scripts/validate_transcript_extraction.py` (transcript corpus).
- Tier-1 presence-recall gate for the presentation pipeline.
- Production run of `scripts/backfill_text_presence.py` against Neon prod (operational; gated behind `--allow-prod` + `ALLOW_PROD_BACKFILL=yes`).
- Investigate the gold-standard companies whose `filing.html` is missing — separate diligence ticket.

## Cross-pivot coordination with image-review redesign

A parallel image-review redesign (`~/.claude/plans/our-disclosures-review-web-deep-blossom.md`) is in flight and will land at **sql/47** with three artifacts that the text pivot depends on:

- `v2_image_metric_presence` (per-image grain, reviewable)
- `v2_image_presence_confirmations` (reviewer decisions: `accept/reject/correct/skip/add`)
- `v_doc_metric_presence` **VIEW** (UNION of text + image presence at doc grain):
  ```sql
  CREATE VIEW v_doc_metric_presence AS
    SELECT doc_id, canonical_metric_id AS metric_id, 'text' AS source
      FROM v2_text_metric_presence
    UNION
    SELECT ia.doc_id, imp.metric_id, 'image' AS source
      FROM v2_image_metric_presence imp
      JOIN v2_image_assets ia USING (img_id);
  ```

### Agreement (2026-04-24)

1. **`ImageAsset.detected_metrics` in-memory contract is being dropped** by image-review Wave 2. The list is no longer populated after Wave 1 transition ends. Dual-write during the transition keeps the chart-source branch in `MetricPresenceStage` (src/extraction_v2/stages/metric_presence.py:86-95) working until PR5 removes it.
2. **Text-presence stops aggregating chart contribution.** PR5 (this program) removes the chart-source branch in `MetricPresenceStage` after image-review Wave 1 lands. Non-blocking — image-review agreed to dual-write.
3. **PR2 queries `v_doc_metric_presence`, not `v2_text_metric_presence`,** for Tier 1 gate math. The view captures both text and image presence symmetrically.
4. **Landing order for the gate transition:** image-review Wave 2 Agent C resets the chart-fact recall baseline FIRST; text PR2 flips the Tier 1 gate from fact-recall to presence-recall SECOND.
5. **Per-table ownership:** `v2_text_metric_presence` owns text at doc grain; `v2_image_metric_presence` owns image at per-image grain. No unified confirmations table.

Full rationale in `~/.claude/plans/text-presence-pivot-index.md` and memory `project_text_image_presence_coordination.md`.

---

## Landed in PR1 — interface contract for downstream PRs

PR2/PR3/PR4 must read this section instead of the PR1 plan file. Names below match the landed code; they are authoritative.

### Migration

`sql/46_v2_text_metric_presence.sql` creates table `v2_text_metric_presence`:

| Column | Type | Notes |
|---|---|---|
| `presence_id` | `UUID PRIMARY KEY` | `DEFAULT gen_random_uuid()` |
| `doc_id` | `BIGINT NOT NULL` | FK → `filings(filing_id)` ON DELETE CASCADE |
| `canonical_metric_id` | `TEXT NOT NULL` | Metric taxonomy ID |
| `score` | `DOUBLE PRECISION NOT NULL` | Max across contributing signals; `CHECK (0 ≤ score ≤ 1)` |
| `detected_at_stage` | `TEXT NOT NULL` | Stage name that first surfaced the metric |
| `evidence_segment_ids` | `JSONB NOT NULL DEFAULT '[]'` | Sorted list of segment IDs |
| `advisory_value_count` | `INTEGER NOT NULL DEFAULT 0` | Count of contributing facts |
| `advisory_fact_ids` | `JSONB NOT NULL DEFAULT '[]'` | Contributing fact_ids (no FK; facts may be deleted independently) |
| `pipeline_version` | `TEXT NOT NULL` | Currently `"2.0.0"` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | `DEFAULT NOW()` |

Uniqueness: `UNIQUE (doc_id, canonical_metric_id)` (one row per metric per filing).
Indexes: `(doc_id)`, `(canonical_metric_id)`.

### Dataclass

`src.extraction_v2.models.MetricPresence`:

```python
@dataclass
class MetricPresence:
    canonical_metric_id: str
    score: float
    detected_at_stage: str
    evidence_segment_ids: list[str] = field(default_factory=list)
    advisory_value_count: int = 0
    advisory_fact_ids: list[str] = field(default_factory=list)
```

Field names match SQL column names 1:1 except for the DB-managed columns (`presence_id`, `doc_id`, `pipeline_version`, `created_at`, `updated_at`) which are attached at persist time.

### Stage

`src.extraction_v2.stages.metric_presence.MetricPresenceStage` runs as the **final stage** in `V2Pipeline._setup_stages`, after `ValidationStage`. Enum: `PipelineStage.METRIC_PRESENCE = "metric_presence"`.

The stage reads:

- `context.deduplicated_facts` (falls back to `context.facts` when dedup didn't run)
- `context.images` (contributes `image.detected_metrics`)
- `context.definitions` (contributes at floor score `_DEFINITION_ONLY_PRESENCE_SCORE = 0.5`)

And writes `context.presences: list[MetricPresence]`.

Scoring: max across contributing signals. Evidence: union of segment IDs from facts + definitions (chart-only presences have empty `evidence_segment_ids`). `advisory_fact_ids` lists contributing fact IDs (empty when presence comes solely from charts or definitions).

### PipelineResult field

`PipelineResult.presences: list[MetricPresence]` is populated from `context.presences` at pipeline completion.

### Persistence

`V2PersistenceAdapter._persist_presence_in_tx(cur, presences, filing_id) -> int` upserts on `(doc_id, canonical_metric_id)`. Called from `persist_pipeline_result` as step 8 (after facts, definitions, and image classifications). Idempotent; never touches `v2_metric_facts` or `v2_review_decisions`.

`persist_pipeline_result` signature:

```python
def persist_pipeline_result(
    self,
    result: PipelineResult,
    filing_id: int,
    document_type: str = "sec_filing",
    ticker: str | None = None,
    document_date: date | None = None,
    transcript_source: str | None = None,
    *,
    force: bool = False,
    chart_only: bool = False,
    presence_only: bool = False,
) -> PersistenceResult
```

New kwarg `presence_only=False`. When `True`:

- Step 5 (`_persist_facts_in_tx`) is skipped entirely — no DELETE, no INSERT on `v2_metric_facts`, no `ReviewedFilingError` possible.
- All other idempotent steps (document, tables, images, segments, definitions, image classifications, presence) run as normal.
- Mutually exclusive with `chart_only`; combining raises `ValueError`.

`PersistenceResult` gains `presences_upserted: int = 0`; `total_upserted` property includes it.

### Interface invariants

- Presence rows are never deleted by the persistence layer — only the CASCADE on `filings.filing_id` removes them.
- `_persist_presence_in_tx` is pure upsert; re-running extraction overwrites `score`, `evidence_segment_ids`, `advisory_*`, `pipeline_version`, and `updated_at`.
- `advisory_fact_ids` is an advisory JSONB list, **not** a FK. Facts may be deleted by `force=True` re-extraction without cascading to presence rows — presence is a document-level claim, independent of which specific fact rows currently back it.
- `presence_only=True` does NOT bypass the image-re-classification guard inside `_persist_images_in_tx`; that guard is orthogonal and still fires on hidden-class transitions.

### How downstream PRs reference this contract

Each of PR2/PR3/PR4 has a plan file in `~/.claude/plans/text-presence-pr*.md` that points fresh sessions here. Read this section first; the PR plan file then describes the incremental changes the PR makes.

---

## Known pre-PR1 gap closed alongside

`scripts/apply_migrations.py` and `scripts/apply_all_migrations.py` were missing `44_extend_image_rejection_reason_enum.sql` and `45_create_v2_image_classifications.sql` in their ordered lists (landed in PR #162 without registration). The pre-commit `migration-order-check` guard was blocking PR1 until these were registered; PR1 registered all three (44, 45, 46) to unblock. If this gap reappears on other branches created from pre-#162 heads, they will hit the same guard.
