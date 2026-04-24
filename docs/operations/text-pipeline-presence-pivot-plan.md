# Text-pipeline presence-first pivot

Rollout doc for the text-extraction pivot that mirrors the chart-presence pivot (PR #147). Under this pivot, extraction's primary scoring surface shifts from per-fact accuracy to per-(document, metric) presence detection, plus reviewer confirmation. Fact emission continues as an advisory evidence layer — not deleted, not migrated.

Strategic direction memo: `~/.claude/projects/.../memory/project_presence_first_extraction_direction.md`.

## Program status

| PR | Scope | Status |
|---|---|---|
| PR1 | Schema + presence emission + `presence_only` persistence mode | **Landed** (this PR) |
| PR2 | Gold-standard presence derivation + validator + Tier 1 gate flip | Pending |
| PR3 | Reviewer UI surfaces presence (`v2_text_presence_confirmations`) | Pending |
| PR4 | Tier-1 definition/methodology LLM classifier | Pending |

Full plan files live under `~/.claude/plans/text-presence-pr*.md` and `~/.claude/plans/text-presence-pivot-index.md`.

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
