# Analytics UI Runbook

**Purpose:** Operator guide for the browser-based query/visualization layer
pointed at the filings database. Covers the read-only DB role, the
`v_analytics_*` views, and the (future) self-hosted Metabase deployment.

## What this layer is for

The extraction pipeline produces structured data in Neon Postgres
(`v2_metric_facts`, `filings`, `companies`, `metrics`, etc.). Two audiences need
to query it:

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
| `v_analytics_fact_wide` | 1 row / primary `v2_metric_fact` | Default surface for ad-hoc exploration. Most questions (trends, QA, per-company) derive from this. |
| `v_analytics_coverage_matrix` | 1 row / (company × active metric) | Powers "who discloses what" heatmap dashboards. Includes `has_fact` / `has_accepted_fact` flags. |

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

## Future: deploying Metabase

Not yet deployed. When ready:

- Add a third service block to `render.yaml` using the official
  `metabase/metabase` image, pinned to a specific version.
- Attach a small persistent disk for the H2 app DB (upgrade to a
  Postgres-backed app DB before going public).
- Connect to Neon using the `metabase_ro` role created above.
- Initial auth: email + password, admin-created accounts, no public signup.

Approximate cost: Render Starter service (~$7/mo) + small disk (~$1/mo).

### On-ramp to public access

Everything below becomes safe because the database layer already enforces
read-only + query timeouts:

1. Migrate Metabase's own app DB from H2 to Postgres (enables backups and
   multi-instance).
2. Enable Metabase's public-link feature on specific curated dashboards.
3. Put rate limiting / a CDN (Cloudflare free tier) in front of public URLs.

## Troubleshooting

- **"password authentication failed"** as `metabase_ro` — the migration created
  the role with a placeholder password. Run the `ALTER ROLE ... PASSWORD` step.
- **Queries hit the 30s timeout** — either the query is genuinely wrong-shaped,
  or a dashboard is doing N+1 queries. Profile with `EXPLAIN ANALYZE` as the
  owner role; do not raise the timeout without cause.
- **Metabase shows stale data** — Metabase caches. In the admin panel,
  "Sync database schema now" / "Re-scan field values now" force refresh.

## Related files

- `sql/37_create_analytics_role.sql`
- `sql/38_create_analytics_views.sql`
- `scripts/apply_migrations.py` (registration list)
- Plan: `~/.claude/plans/i-think-we-need-bright-fountain.md`
