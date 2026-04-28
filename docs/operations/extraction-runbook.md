# Extraction Operations Runbook

**Last Updated:** 2026-04-25

> **Pivot status (2026-04-25):** Under the chart-presence pivot (#86, 2026-04-23) and text-presence PR1 (#182, 2026-04-16), the V2 extraction pipeline emits **presence** as the primary scoring surface (`v2_text_metric_presence`) plus advisory facts (`v2_metric_facts`). This runbook covers V2 only; V1 has been deleted from the repo (`src/extraction/`). The legacy V1 candidate / `source_segments` / `review_candidates` flow no longer exists. See [`text-pipeline-presence-pivot-plan.md`](text-pipeline-presence-pivot-plan.md).

This runbook documents the correct procedures for re-extracting filings under the V2 pipeline. **Following these procedures is critical** to avoid stale data issues and to respect the reviewed-filing guard (`ReviewedFilingError`).

---

## Quick Reference

| Task | Command |
|------|---------|
| Re-extract single filing (V2 pipeline) | `DATABASE_URL="..." python3 scripts/run_v2_extraction.py --filing-id <ID>` |
| Re-extract a reviewed filing (forces, requires explicit flag) | `DATABASE_URL="..." python3 scripts/run_v2_extraction.py --filing-id <ID> --force-reextract` |
| Re-extract presence-only (skip fact write; useful for keyword/aggregator changes) | `DATABASE_URL="..." python3 scripts/run_v2_extraction.py --filing-id <ID> --presence-only` |
| Batch re-extract | `DATABASE_URL="..." python3 scripts/batch_v2_extraction.py` |
| Diagnose extraction issues | Run `scripts/run_v2_extraction.py --filing-id <ID>` with `LOG_LEVEL=DEBUG` (see Procedure 4) |

---

## Understanding the Data Flow

```
HTML File
    ↓
V2Pipeline (up to 16 stages; image stages 4–5b conditional)
    ├─ v2_segments              (DOM-native content blocks)
    ├─ v2_tables / v2_table_cells  (header_path / stub_path)
    ├─ v2_image_assets          (incl. detected_metrics JSONB — chart-presence pairs)
    ├─ v2_image_classifications (Vision API metric-classifier audit; Stage 5b)
    ├─ v2_metric_facts          (advisory per-value evidence, with EvidencePack)
    ├─ v2_metric_definitions    (issuer-specific definition / methodology text)
    └─ v2_text_metric_presence  ★ primary scoring surface
                                  one row per (doc_id, canonical_metric_id);
                                  upserted by MetricPresenceStage
```

**Key Insight**: If you modify segmentation logic, keywords, FP rules, or the `MetricPresenceStage` aggregator, you must re-run the V2 pipeline. Presence rows are upserted on `(doc_id, canonical_metric_id)`, so re-extraction is idempotent. The `presence_only=True` mode skips the fact-write step entirely — useful when iterating on aggregation logic or keyword rules without disturbing reviewed facts.

| If you modify... | You must re-run... |
|------------------|-------------------|
| `src/extraction_v2/stages/ingestion.py` (V2 segmentation) | Full re-extraction (`scripts/batch_v2_extraction.py`) |
| `config/metric_keywords.yaml` (keyword patterns) | Full re-extraction; presence rows refresh on the next run |
| `src/extraction_v2/stages/metric_presence.py` (aggregator) | Re-extraction with `--presence-only` is sufficient — does not touch facts |
| `src/extraction_v2/chart/metric_classifier.py` (chart presence rules) | Full re-extraction; updates `v2_image_assets.detected_metrics` |
| LLM prompts | Full re-extraction (`scripts/batch_v2_extraction.py`) |

---

## Procedure 1: Full Re-extraction (Recommended)

Use when: Segmentation, keyword, FP-filter, or LLM-prompt logic changed.

```bash
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/run_v2_extraction.py --filing-id <FILING_ID>
```

**What this does:**
- Runs the V2 unified extraction pipeline (`src/extraction_v2/`) on the specified filing
- Upserts `v2_segments`, `v2_tables`, `v2_image_assets` (with `detected_metrics` JSONB), `v2_metric_facts` (advisory), `v2_metric_definitions`, and `v2_text_metric_presence` (primary scoring surface)
- Idempotent — safe to re-run; presence rows are upserted on `(doc_id, canonical_metric_id)` and `updated_at` advances

If the filing has reviewer decisions on facts or image confirmations, this command will raise `ReviewedFilingError`. Use `--force-reextract` only when you intentionally want to overwrite reviewed work; the reviewer-protection guards exist to prevent silent CASCADE-destruction.

**Image `file_path` is sticky against NULL inbounds (legacy-103, 2026-04-27).** When `--force-reextract` runs and the SEC image fetch fails (transient outage, malformed URL, etc.), the in-memory `ImageAsset` ships with `file_path=None`. The upsert clause `file_path = COALESCE(EXCLUDED.file_path, v2_image_assets.file_path)` preserves the existing R2 storage key in that case while still refreshing every other column from the re-parsed HTML — `classification`, `nearby_text`, `chart_data`, `detected_metrics`, etc. all update normally. Only `file_path` survives a NULL inbound.

---

## Procedure 2: Presence-Only Re-extraction

Use when: You changed `MetricPresenceStage` aggregation logic, the chart-presence classifier, or want to refresh presence scores without touching reviewed facts.

```bash
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/run_v2_extraction.py --filing-id <FILING_ID> --presence-only
```

**What this does:**
- Runs the full pipeline through the final `MetricPresenceStage`
- Calls `V2PersistenceAdapter.persist_pipeline_result(..., presence_only=True)`, which skips the `_persist_facts_in_tx` step entirely
- Upserts presence rows, image classifications, and image-asset `detected_metrics`
- **Does NOT touch `v2_metric_facts`** — no `ReviewedFilingError` on text-fact decisions can fire
- Image confirmation guard still applies to hidden-class transitions

---

## Procedure 3: Manual Re-segmentation Only — RETIRED

The V1 segmenter and `source_segments` table are retired. The V2 pipeline writes to `v2_segments` and runs all downstream stages in one pass — there is no separate "segmentation only" mode. Use Procedure 1.

---

## Procedure 4: Diagnose Extraction Issues

Use when: A filing has missing or incorrect data and you need to investigate.

> **Note:** `scripts/debug_segmentation.py` no longer exists. For V2 pipeline debugging, run `scripts/run_v2_extraction.py` with verbose logging enabled via the `LOG_LEVEL` environment variable.

```bash
# Run V2 extraction with debug-level logging for a single filing
LOG_LEVEL=DEBUG DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/run_v2_extraction.py --filing-id <FILING_ID>
```

**To investigate missing data:**
- Check segment counts using the verification queries below
- Use `raw_text ILIKE` queries to confirm whether target values are present in segments
- If segments look stale (low count), re-run Procedure 1 to re-segment

---

## Procedure 5: Batch Re-extraction

Use when: Re-extracting multiple filings (e.g., after major pipeline changes).

```bash
# 1. Run a limited batch first to verify behavior
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/batch_v2_extraction.py --limit 5

# 2. Verify results before full run (V2 tables)
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
    -c "SELECT COUNT(*) AS docs FROM v2_documents;
        SELECT COUNT(*) AS facts, COUNT(DISTINCT canonical_metric_id) AS metrics FROM v2_metric_facts;
        SELECT COUNT(*) AS presences, COUNT(DISTINCT canonical_metric_id) AS metrics FROM v2_text_metric_presence;"

# 3. Full re-extraction (can take hours)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    python3 scripts/batch_v2_extraction.py
```

---

## Common Pitfalls

### Pitfall 1: Stale Presence
**Symptom:** A keyword change should have promoted a metric to "present" but didn't.
**Cause:** `v2_text_metric_presence` was not refreshed after the keyword/aggregator change.
**Fix:** Run Procedure 1 (full) or Procedure 2 (`--presence-only`) for affected filings.

### Pitfall 2: Missing Keywords
**Symptom:** Values are in segments but not matched to the correct metric.
**Cause:** Keyword patterns in `config/metric_keywords.yaml` don't include company-specific terminology.
**Fix:**
1. Add keywords to `config/metric_keywords.yaml` (the authoritative keyword source).
2. Run Procedure 1 to re-extract; presence rows refresh on next run.

### Pitfall 3: ReviewedFilingError on Re-extraction
**Symptom:** `scripts/run_v2_extraction.py` raises `ReviewedFilingError` and refuses to write.
**Cause:** The filing has reviewer decisions on facts (`v2_review_decisions`) or image-presence confirmations (`v2_image_metric_confirmations`); the guard prevents silent overwrite.
**Fix:** Use `--presence-only` (does not touch facts) when only aggregation changed. Use `--force-reextract` only when you intentionally want to invalidate reviewer work.

### Pitfall 4: Forgetting to Set DATABASE_URL
**Symptom:** Script runs but doesn't affect expected database.
**Cause:** Using wrong database or default connection.
**Fix:** Always explicitly set `DATABASE_URL` environment variable.

---

## Verification Queries

### Check segment count for a filing
```sql
SELECT COUNT(*) AS segment_count,
       SUM(LENGTH(segment_text)) AS total_chars
FROM v2_segments
WHERE doc_id = <FILING_ID>;
```

### Check if specific value is in segments
```sql
SELECT COUNT(*) AS matches
FROM v2_segments
WHERE doc_id = <FILING_ID>
  AND segment_text ILIKE '%<VALUE>%';
```

### Check fact count (advisory) for a filing
```sql
SELECT canonical_metric_id, COUNT(*) AS fact_count, COUNT(*) FILTER (WHERE review_status='accepted') AS accepted
FROM v2_metric_facts
WHERE doc_id = <FILING_ID>
GROUP BY canonical_metric_id
ORDER BY fact_count DESC;
```

### Check presence (primary) for a filing
```sql
SELECT canonical_metric_id, score, detected_at_stage,
       jsonb_array_length(evidence_segment_ids) AS n_segments,
       jsonb_array_length(advisory_fact_ids)    AS n_facts,
       advisory_value_count
FROM v2_text_metric_presence
WHERE doc_id = <FILING_ID>
ORDER BY score DESC;
```

### Check chart-presence detections + reviewer confirmations for a filing
```sql
SELECT ia.img_id, ia.classification, ia.detected_metrics,
       jsonb_agg(jsonb_build_object(
           'reviewer', imc.reviewer_id,
           'decision', imc.decision,
           'detected', imc.detected_metric_id,
           'confirmed', imc.confirmed_metric_id
       )) FILTER (WHERE imc.id IS NOT NULL) AS confirmations
FROM v2_image_assets ia
LEFT JOIN v2_image_metric_confirmations imc USING (img_id)
WHERE ia.doc_id = <FILING_ID>
  AND ia.classification = 'chart'
GROUP BY ia.img_id, ia.classification, ia.detected_metrics;
```

### Compare filing stats before/after
```sql
SELECT f.filing_id, c.company_name,
       COUNT(DISTINCT s.segment_id)                AS segments,
       COUNT(DISTINCT mf.fact_id)                  AS facts,
       COUNT(DISTINCT mf.fact_id) FILTER (WHERE mf.review_status='accepted') AS accepted_facts,
       COUNT(DISTINCT p.presence_id)               AS presences,
       COUNT(DISTINCT ia.img_id) FILTER (WHERE ia.classification='chart') AS charts
FROM filings f
JOIN companies c ON f.company_id = c.company_id
LEFT JOIN v2_segments s            ON f.filing_id = s.doc_id
LEFT JOIN v2_metric_facts mf       ON f.filing_id = mf.doc_id
LEFT JOIN v2_text_metric_presence p ON f.filing_id = p.doc_id
LEFT JOIN v2_image_assets ia       ON f.filing_id = ia.doc_id
WHERE f.filing_id = <FILING_ID>
GROUP BY f.filing_id, c.company_name;
```

---

## Lesson Learned (2024-12-24)

**Issue:** Farfetch and Samsara Vision filings showed 0 candidates despite gold standard values existing in HTML.

**Root Cause:**
1. Database had 80 segments (stale) while current segmenter produces 89,887 segments
2. Keywords like "Active Consumers" (Farfetch) and "Customer A" (Samsara Vision) weren't in patterns

**Resolution:**
1. Re-segmented both filings using current segmenter
2. Added missing keywords to `config/metric_keywords.yaml`
3. Regenerated candidates

**Prevention:**
- After ANY segmenter changes, re-segment affected filings
- After keyword changes in `config/metric_keywords.yaml`, regenerate candidates
- Use verbose V2 extraction logging (Procedure 4) to diagnose before assuming code bugs

---

## Lesson Learned (2025-12-27)

**Issue:** "View SEC Filing" button in human review interface linked to wrong document (exhibit file instead of main S-1).

**Root Cause:**
1. `resolve_primary_document_url()` matched exhibit files containing form patterns (e.g., `exhibit103s-1.htm`) before the actual document (`slacks-1.htm`)
2. Slack's database record pointed to original S-1 instead of final S-1/A amendment
3. `fetch_curated_sample.py` only queried for `S-1`/`F-1`, ignoring amendments

**Resolution:**
1. Fixed `sec_client.py` to filter exhibit files BEFORE pattern matching
2. Updated Slack's database record to point to final S-1/A (accession `0001628280-19-007428`)
3. Modified `fetch_curated_sample.py` to prefer final amendments (S-1/A, F-1/A) over originals

**Prevention:**
- When loading filings, prefer the final S-1/A or F-1/A amendment (most complete disclosure)
- The `resolve_primary_document_url()` now correctly excludes exhibit files from pattern matching
- Verify SEC filing URLs resolve correctly before committing filing data

---

## Recovering filings with stale storage paths

A small number of filings (gh-299) carry `html_storage_path` values pointing
at `/Users/.../OneDrive-CMASB/...` paths that no longer hydrate reliably,
with NULL `html_content`. Re-extraction of these rows fails with
`HTML not found on disk and not in DB` (`scripts/batch_v2_extraction.py:256`).
Use `scripts/migrate_onedrive_html_paths.py` to rewrite the path to the
worktree-relative form and populate `html_content` from the canonical local
copy (or re-fetch from SEC if the local file is missing).

### Audit (read-only)

```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM filings WHERE html_storage_path LIKE '/Users/%/OneDrive-CMASB/%';"
```

### Dry-run

```bash
python3 scripts/migrate_onedrive_html_paths.py
```

Reports the rows that would be rewritten without making any changes.

### Apply

```bash
# Local DB
DATABASE_URL="$TEST_DATABASE_URL" python3 scripts/migrate_onedrive_html_paths.py --apply

# Prod (Neon) — requires both --allow-prod and FILINGS_REVIEWER_ALLOW_PROD_WRITES=1
FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 \
  python3 scripts/migrate_onedrive_html_paths.py --apply --allow-prod
```

### Verify

```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM filings WHERE html_storage_path LIKE '/Users/%/OneDrive-CMASB/%';"
# Expected: 0
```

> **Note (gh-300):** This is a tactical fix. gh-300 will replace
> `html_storage_path` semantics with R2 storage keys, superseding this
> migration's worktree-relative path format.

---

## Migrating filing HTMLs to R2

Post-gh-300, filing source HTML lives in Cloudflare R2 and `filings.html_storage_path`
stores opaque storage keys (`filings/<cik>/<accession>/primary.htm`). The migration
script `scripts/migrate_filing_html_to_r2.py` uploads bytes from
`html_content` (DB) → local disk → SEC re-fetch (in priority order), verifies via
HEAD, then rewrites the column. The selector is self-filtering, so re-running
the script is idempotent — useful when newly fetched filings (still written by
the legacy fetcher path) accumulate.

> See `.claude/rules/infrastructure.md#filing-html-storage` for the storage
> contract and reader-side compatibility notes.

### Audit (read-only)

```bash
psql "$DATABASE_URL" -c "
SELECT COUNT(*) FILTER (WHERE html_storage_path LIKE 'filings/%/%/%') AS r2_keys,
       COUNT(*) FILTER (WHERE html_storage_path IS NOT NULL
                          AND html_storage_path NOT LIKE 'filings/%/%/%') AS not_yet_migrated,
       COUNT(*) AS total
  FROM filings;"
```

### Dry-run

```bash
python3 scripts/migrate_filing_html_to_r2.py
```

Reports the rows that would be migrated without uploading anything.

### Apply

```bash
# Local DB (runs against LocalFilesystemFilingStorage when R2_BUCKET unset)
DATABASE_URL="$TEST_DATABASE_URL" python3 scripts/migrate_filing_html_to_r2.py --apply

# Prod (Neon + R2) — requires both --allow-prod and FILINGS_REVIEWER_ALLOW_PROD_WRITES=1
FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 \
  python3 scripts/migrate_filing_html_to_r2.py --apply --allow-prod
```

### Verify

```bash
psql "$DATABASE_URL" -c "
SELECT COUNT(*) FILTER (WHERE html_storage_path LIKE 'filings/%/%/%') AS r2_keys,
       COUNT(*) FILTER (WHERE html_storage_path IS NOT NULL
                          AND html_storage_path NOT LIKE 'filings/%/%/%') AS not_yet_migrated
  FROM filings;"
# Expected: not_yet_migrated = 0 (or = the count of rows where all sources failed)
```

Spot-check one filing through the refactored extraction path:

```bash
python3 scripts/run_v2_extraction.py --filing-id <ID> --dry-run
```

The log line `read from R2 key filings/<cik>/<accession>/primary.htm` confirms
the R2 short-circuit is engaged.

> **Follow-up (deferred):** `src/filing_fetcher/filing_fetcher.py` still writes
> filesystem paths on fetch. Newly fetched filings are migrated to R2 keys by
> re-running this script. A future PR will refactor the fetcher to write R2
> keys directly. After that, this migration script becomes a one-time cleanup
> tool. The `html_content` column is also retained as a fallback during the
> initial soak; a separate follow-up will drop it once R2 has been stable for
> ≥30 days without incident.
