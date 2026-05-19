# Analytics UI Runbook

**Purpose:** Operator guide for the browser-based query/visualization layer
pointed at the filings database. Covers the read-only DB role, the
`v_analytics_*` views, and the (future) self-hosted Metabase deployment.

> **Pivot status (2026-05-13):** The presence-aware analytics surface
> landed as `v_analytics_metric_presence` (and the company/tier-1 rollup
> views) in migration `202605131507_tier1_disclosure_analytics.sql`. The
> earlier-planned `v_doc_metric_presence` name is superseded. Existing
> `v_analytics_fact_wide` and `v_analytics_coverage_matrix` remain valid
> for advisory-fact analyses. See
> [`text-pipeline-presence-pivot-plan.md`](text-pipeline-presence-pivot-plan.md)
> and [`metabase-tier1-reporting.md`](metabase-tier1-reporting.md).

## What this layer is for

The extraction pipeline produces structured data in Neon Postgres
(presence in `v2_text_metric_presence` — primary; advisory facts in
`v2_metric_facts`; image classifications, segments, tables, etc.). Two
audiences need to query it:

- **Researchers (you)** — want ad-hoc slice/dice exploration: "which companies
  disclosed NRR?", "what does our extraction look like per source_type?"
- **Collaborators (CMASB members)** — want curated dashboards that answer
  specific questions without writing SQL.

Rather than build both in the Flask app, we deliver this via a self-hosted
Metabase instance pointed at a read-only Postgres role. The database layer
(role + curated views) lives in migrations 37–38; the Metabase service itself
is deployed later via `render.yaml`.

## Database layer (migrations 37–38)

### The `metabase_ro` role — `sql/37_create_analytics_role.sql`

- `metabase_ro` is the **only** role an external BI tool should use.
- Privileges: `CONNECT` on the current DB, `USAGE` on `public`, `SELECT` on all
  current and future tables in `public`.
- Guardrails: `statement_timeout=30s`, `idle_in_transaction_session_timeout=60s`,
  `lock_timeout=5s`. These cap blast radius from runaway queries or BI tool bugs.
- **Password:** the migration creates the role with a placeholder password
  (`change_me_immediately`). After applying, rotate it with:

  ```sql
  ALTER ROLE metabase_ro PASSWORD '<secure value>';
  ```

  Store the real value in an env var (`METABASE_DB_PASSWORD`) — never in the
  migration file.

### The analytics views — `sql/38_create_analytics_views.sql`

| View | Grain | Use |
|------|-------|-----|
| `v_analytics_fact_wide` | 1 row / primary `v2_metric_fact` (advisory under the pivot) | Surface for advisory-fact analysis (trends, QA, per-company values). Note: chart-native metrics no longer auto-populate facts post-#86. |
| `v_analytics_coverage_matrix` | 1 row / (company × active metric) | Powers "who discloses what" heatmap dashboards. Includes `has_fact` / `has_accepted_fact` flags. Superseded for presence-based coverage by `v_analytics_metric_presence` (below). |

### Tier-1 disclosure views — `sql/202605131507_tier1_disclosure_analytics.sql`

| View | Grain | Use |
|------|-------|-----|
| `v_analytics_metric_tiers` | 1 row / metric | Catalog of `metric_id → tier (1|2)`. Tier-1 list mirrors `config/metric_keywords.yaml`; if that set changes, edit the inline `CASE` and re-apply the migration. |
| `v_analytics_metric_presence` | 1 row / (filing × metric) | Unified presence surface: FULL OUTER JOIN of `v2_text_metric_presence` and reviewer-confirmed `v2_image_metric_confirmations` (decisions `accept|correct|add`, superseded admin rows excluded). Carries `evidence_segment_ids` / `image_ids` JSONB for future drill-through. Supersedes the planned `v_doc_metric_presence` referenced in earlier drafts. |
| `v_analytics_company_metric_disclosure` | 1 row / (company × metric) | Dedup of `v_analytics_metric_presence` across in-scope filings per company (`is_in_scope_phase1 = TRUE`). Joined to `industry_sic_buckets` and `v_analytics_metric_tiers`. |
| `v_analytics_company_tier1_summary` | 1 row / in-scope company | Distinct count of Tier-1 metrics disclosed per company, plus the `0/1/2/3/4/5+` `disclosure_bucket` and `industry_bucket`. Primary surface for the four Metabase tier-1 reports — see [`metabase-tier1-reporting.md`](metabase-tier1-reporting.md). |

The migration also creates the seed table `industry_sic_buckets` (SIC code → primary bucket, snapshot of `config/industry_sic_codes.yaml`). The companion doc `metabase-tier1-reporting.md` has copy-pastable SQL for the four reports.

### Image-review progress view — `sql/202605191650_v_analytics_image_review_progress.sql`

| View | Grain | Use |
|------|-------|-----|
| `v_analytics_image_review_progress` | 1 row / non-decorative `v2_image_assets` row | Per-image review state derived from the `v2_image_metric_confirmations` rollup, mirrors `DatabaseAdapter._derive_image_review_state`. Powers the "Image Confirmations" box on `/v2/review/stats`. |

Columns: `img_id`, `filing_id`, `review_status` (raw), `classification`, `detected_count`, `total_confirmation_count`, `positive_count`, `detected_decided_count`, `has_no_relevant_sentinel`, `image_review_state` (`'pending'` / `'relevant'` / `'no_relevant'`).

**Counter-definition change (2026-05-19).** `DatabaseAdapter.get_image_review_progress_v2()` now sources `reviewed_count` / `not_relevant_count` / `pending_count` from this view, NOT from the raw `v2_image_assets.review_status` column. Pre-fix, "Reviewed Images" counted only the rare `mark_complete=true` path; per-metric reviews accumulated in `v2_image_metric_confirmations` but never flipped `review_status`, so the tile reported a small fraction of actual reviewer effort. The new definition counts:

- `image_review_state='relevant'` — all detected metrics decided with ≥1 accept/correct/add, OR legacy `review_status='reviewed'`.
- `image_review_state='no_relevant'` — raw `'skipped'` / `'auto_rejected'`, or all detected metrics rejected via per-metric flow. Splits into:
  - `rejected_not_relevant_count` — sentinel `decision='reject'` + `rejection_reason='no_relevant_metrics'` on a zero-detected image (the explicit "Reject all — no relevant metrics" reviewer action).
  - `skipped_count` — raw `'skipped'` without a sentinel row (the "Skip image" button path).

The view intentionally diverges from `_derive_image_review_state` on one edge: legacy `review_status='reviewed'` images with no per-metric rows count as `'relevant'` here (kept as a positive signal for backward compat with historical V1 reviewer activity), where the Python derive function — used only for queue-thumbnail indicators — returns `'pending'`.

Expect the prod `reviewed_count` to jump on first deploy: the user-reported "Reviewed Images = 658" was the pre-fix `mark_complete=true` count; the post-fix number reflects the full reviewer-effort surface.

Both views use `CREATE OR REPLACE`, so the migration is safe to re-apply after
editing. If a column or join changes, bump the migration number and add a new
file — do not edit in place (violates migration checksum tracking in
`scripts/apply_migrations.py`).

### Adding a new analytics view

1. Write the view definition in a new migration `sql/NN_<name>.sql` (next
   unused number; see `.claude/rules/sql.md`).
2. Use the `v_analytics_*` namespace to distinguish from the internal `v_*`
   review views in `sql/09_v2_schema.sql`.
3. Reference `v_analytics_fact_wide` where possible instead of re-joining raw
   tables — that keeps the analytical shape consistent.
4. Add a `COMMENT ON VIEW` explaining grain and purpose.
5. Register the file in `MIGRATIONS` inside `scripts/apply_migrations.py`.
6. Apply locally, query as `metabase_ro`, confirm results.

## Applying the migrations

### Local (Docker Compose Postgres)

```bash
DATABASE_URL="postgresql://postgres:postgres@localhost:5433/filings_analysis" \
    python3 scripts/apply_migrations.py
```

Then set the real password:

```bash
psql "$DATABASE_URL" -c "ALTER ROLE metabase_ro PASSWORD 'local_dev_pw';"
```

Smoke-test:

```bash
psql "postgresql://metabase_ro:local_dev_pw@localhost:5433/filings_analysis" \
    -c "SELECT COUNT(*) FROM v_analytics_fact_wide;"
```

A `DELETE` attempt must fail:

```bash
psql "postgresql://metabase_ro:local_dev_pw@localhost:5433/filings_analysis" \
    -c "DELETE FROM v2_metric_facts;"  # expect: ERROR: permission denied
```

### Neon (production)

1. Apply migrations with `DATABASE_URL` set to the Neon URL:

   ```bash
   DATABASE_URL="postgresql://...@host.neon.tech/filings_analysis?sslmode=require" \
       python3 scripts/apply_migrations.py
   ```

2. Rotate the role password:

   ```bash
   psql "$DATABASE_URL" -c "ALTER ROLE metabase_ro PASSWORD '<from METABASE_DB_PASSWORD>';"
   ```

3. Record the password in Render's environment variables for the future
   Metabase service — not in the repo.

## Current deployment

Metabase runs as the `filings-metabase` service defined in `render.yaml`:

- **Image:** `docker.io/metabase/metabase:v0.59.8` (pinned; see "Upgrade
  procedure" below for bumping).
- **Region:** `ohio` (matches the other services).
- **Plan:** Render Standard (2 GB RAM). Disk: 1 GB at `/metabase-data`.
  Starter (512 MB) is not enough — Metabase's JVM OOMs during first-boot
  schema migration with ~124 MB of available heap.
- **App DB:** H2 file at `/metabase-data/metabase.db` (persistent). Upgrade to
  Postgres before opening to a wider audience — see "On-ramp to public access".
- **Autodeploy:** off. Upgrades happen manually from the Render dashboard to
  avoid restarting Metabase (and dropping in-progress dashboard edits) on every
  `main` push.
- **Health check:** `/api/health`.
- **Cost:** ~$25/mo (Standard) + ~$0.25/mo (1 GB disk).

### Env vars on the Metabase service

All set in `render.yaml`:

| Key | Value | Purpose |
|-----|-------|---------|
| `MB_DB_TYPE` | `h2` | App DB backend |
| `MB_DB_FILE` | `/metabase-data/metabase.db` | Path under the persistent disk |
| `MB_ENCRYPTION_SECRET_KEY` | generated once by Render | Encrypts stored data-source credentials at rest. **Must stay stable** — rotating it makes the stored Neon password unreadable and the data-source must be re-added in the admin UI. |
| `MB_SITE_URL` | set after first deploy | e.g. `https://filings-metabase.onrender.com`; required for correct share links. `sync: false` so the value is entered via the Render dashboard once the service URL is known. |
| `MB_JETTY_PORT` | `3000` | Default Metabase HTTP port |

Neon's URL and the `metabase_ro` password are **not** on this service. They are
entered once inside the Metabase admin UI when adding the data source, and
stored (encrypted by `MB_ENCRYPTION_SECRET_KEY`) in the H2 app DB.

### First-login setup (one-time)

1. After the service goes Live, open `https://<render-url>/` and create the
   admin account. **Disable public signup** under Admin → Settings →
   Authentication.
2. Set `MB_SITE_URL` in the Render dashboard to the service URL; restart the
   service so emails and share links use the right host.
3. Admin → Databases → Add database → PostgreSQL. Use the Neon host/port, the
   database name from `DATABASE_URL`, username `metabase_ro`, password from
   `METABASE_DB_PASSWORD`. Enable "Use a secure connection (SSL)" — Neon
   requires it.
4. On that data source's sync settings, set "Scanning for field values" to
   **Never** and "Syncing database schema" to **Daily**. This caps compute
   spend on Neon; raise later only if dashboards feel stale.
5. Browse data → confirm both `v_analytics_fact_wide` and
   `v_analytics_coverage_matrix` appear.

### Upgrade procedure

1. Pick the target tag from https://github.com/metabase/metabase/releases
   (prefer a `v0.N.M` where `N` matches or is one greater than the currently
   deployed major; read the upgrade notes for breaking changes).
2. Edit `image.url` in `render.yaml` on a branch, open a PR (CI is green
   trivially — no app code changed).
3. Merge. Autodeploy is off, so the service keeps running the old image.
4. From the Render dashboard, trigger a manual deploy of `filings-metabase`.
5. Wait for `/api/health` to return 200, log in, verify dashboards render.
6. **Rollback:** revert the `render.yaml` change and trigger another manual
   deploy.

Metabase major versions are backwards-compatible within a line (0.N.M → 0.N.M+x)
and forward-compatible for app DB (H2 is migrated automatically on startup).
Downgrades across majors are **not** supported — snapshot the disk before
major bumps.

## On-ramp to public access

Everything below becomes safe because the database layer already enforces
read-only + query timeouts:

1. **Migrate Metabase's own app DB from H2 to Postgres.** Create a tiny Neon
   database (or a second schema in the existing one) and use Metabase's
   built-in `load-from-h2` command to copy the H2 state. Update `MB_DB_TYPE=postgres`
   + `MB_DB_CONNECTION_URI` on the service. Required before any multi-instance
   or reliable-backup setup.
2. **Enable Metabase's public-link feature** on the specific curated
   dashboards that should be shared openly. Other dashboards stay
   authenticated.
3. **Put rate limiting / a CDN** (Cloudflare free tier) in front of the public
   URLs to absorb surprise traffic.
4. **Back up the app DB** regularly — whichever backend is in use. Dashboards
   and questions live only in the app DB; losing it means rebuilding every
   dashboard by hand.

## Troubleshooting

- **"password authentication failed"** as `metabase_ro` — the migration created
  the role with a placeholder password. Run the `ALTER ROLE ... PASSWORD` step.
- **Queries hit the 30s timeout** — either the query is genuinely wrong-shaped,
  or a dashboard is doing N+1 queries. Profile with `EXPLAIN ANALYZE` as the
  owner role; do not raise the timeout without cause.
- **Metabase shows stale data** — Metabase caches. In the admin panel,
  "Sync database schema now" / "Re-scan field values now" force refresh.

## Reviewer rollup pattern

The unified review UI surfaces a distinct-reviewer list per filing via the
`ARRAY(SELECT DISTINCT UNNEST(...))` pattern in `get_unified_filings_for_review`
(`src/infra/db.py`). Future per-filing reviewer analytics views should reuse
this shape rather than picking a single "primary reviewer":

```sql
-- Text decisions contribute mf.doc_id + rd.reviewer_id; image decisions
-- contribute va.doc_id + ird.reviewer_id. UNION ALL then array_agg + DISTINCT.
SELECT
  filing_id,
  ARRAY(SELECT DISTINCT r FROM UNNEST(array_agg(reviewer_id)) r
        WHERE r IS NOT NULL) AS reviewers
FROM (
  SELECT mf.doc_id AS filing_id, rd.reviewer_id
  FROM v2_review_decisions rd
  JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
  WHERE rd.reviewer_id IS NOT NULL
  UNION ALL
  SELECT va.doc_id, ird.reviewer_id
  FROM v2_image_review_decisions ird
  JOIN v2_image_assets va ON va.img_id = ird.img_id
  WHERE ird.reviewer_id IS NOT NULL
) combined
GROUP BY filing_id;
```

Pre-fix image decisions (before the API bug fix that populates `reviewer_id`)
have `reviewer_id = NULL` and are excluded from the rollup — render as `—` in
the UI; do not backfill historical rows.

## Related files

- `sql/37_create_analytics_role.sql`
- `sql/38_create_analytics_views.sql`
- `scripts/apply_migrations.py` (registration list)
- `render.yaml` (`filings-metabase` service block)
