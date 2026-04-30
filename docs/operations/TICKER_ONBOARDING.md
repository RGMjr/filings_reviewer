# Ticker Onboarding Runbook

`scripts/onboard_tickers.py` — discover and onboard SEC filings filtered by
form type, year, and everyday-language industry (e.g. `--industry software`).

Use this when you want to ingest a *subset* of the universe (e.g. "2015
software S-1/F-1s we haven't processed yet") without running the full
date-range sweep via `build_universe_real.py`.

---

## Quick reference

```bash
# 1. Populate the year's universe (one-time per year; idempotent).
python3 scripts/onboard_tickers.py populate --year 2015

# 2. Preview: which 2015 software S-1/F-1s are unextracted?
python3 scripts/onboard_tickers.py discover \
    --industry software --year 2015 --form-type s1f1

# 3. Execute end-to-end fetch + V2 extraction for first 3 matches:
python3 scripts/onboard_tickers.py onboard \
    --industry software --year 2015 --form-type s1f1 --limit 3

# 4. Dry-run first (recommended):
python3 scripts/onboard_tickers.py onboard \
    --industry software --year 2015 --form-type s1f1 --dry-run
```

## Subcommands

### `discover` (read-only)

Prints the resolved SIC-code list for the industry, then two buckets of
candidates:

- **NEW (not yet extracted)** — rows with no `v2_documents` entry; ready to onboard.
- **ALREADY EXTRACTED — default: SKIP** — rows with an existing `v2_documents` entry; `onboard` ignores these unless `--include-already-extracted` is passed.

No database writes. Use this to sanity-check filters before running `onboard`.

### `populate` (one-time per year)

Thin wrapper over `UniverseBuilder.build_universe(YYYY-01-01, YYYY-12-31)`.
Visits every SEC daily-index file in the year, classifies each S-1/S-1/A/F-1/F-1/A
against the SPAC, first-time-issuer, and offering-type rules, and upserts into
`companies`/`filings`.

Idempotent — re-running is safe (upserts) and refreshes `companies.industry_code`
from EDGAR submissions. Expect ~1 minute for 500+ filings at SEC's 10 req/s
rate limit.

Why needed: SEC daily-index files don't carry SIC codes, so the universe must be
populated before an industry filter can apply. If `discover` returns zero rows
for a year you expected matches in, run `populate --year YYYY` first.

### `onboard` (fetch + extract)

Runs the full pipeline on the `NEW` bucket:

1. `FilingFetcher.fetch_filing` — download HTML (cached; idempotent).
2. `process_filing` — V2 pipeline: section classification → tables → images →
   OCR → candidates → binding → FP filter → period → facts → dedup → validation.
3. `V2PersistenceAdapter.persist_pipeline_result` — transactional write of
   facts + segments + images.

Failures are reported per filing; the run continues to the next filing.

## Re-extraction guard

The primary safety goal: never silently re-extract a filing. Re-extraction
destroys previous facts and (with `--force-reextract`) can CASCADE-destroy
human review decisions via `v2_review_decisions.fact_id ON DELETE CASCADE`.

### Default behavior

`onboard` processes only the `NEW` bucket. `ALREADY EXTRACTED` filings are
printed with a `SKIP` label and left untouched. No prompts fire.

### `--include-already-extracted`

Adds the `ALREADY EXTRACTED` bucket to an interactive per-filing prompt:

```
Filing 12345 (0001234567, —, Square Inc., S-1, 2015-10-14) is already extracted.
Re-extract?  [a]ll remaining  [y]es this one  [N]o (default, skip)  [q]uit:
```

- `a` → apply "yes" to every remaining already-extracted filing (no further prompts).
- `y` → re-extract this one, continue prompting for the rest.
- `N` (or Enter) → skip this one, continue.
- `q` → abort before any fetch or extraction runs. Safe escape.

### `--yes`

Skips the per-filing prompt above and auto-confirms re-extraction for all
already-extracted filings. Requires `--include-already-extracted`. Logs a
prominent warning. Use only in scripted runs where the operator has verified
the filter.

### Second guard: reviewed filings

If a chosen re-extraction target has rows in `v2_review_decisions`, the CLI
pauses BEFORE calling the persistence adapter and prompts:

```
WARNING: Filing 12345 (Square Inc.) has N review decision(s) from M reviewer(s).
Re-extracting will PURGE these decisions (no archive; recovery requires DB backup).
Purge and re-extract? [y/N]:
```

Only `y` proceeds. `N` skips that filing.

`--yes` does NOT bypass this second prompt — it only auto-confirms the first
(already-extracted) prompt. Deliberate design: purging reviewer work should
always require a live human confirmation. If you need a scripted path to force
purge, insert filings into a list, review them manually, then call
`scripts/run_v2_extraction.py --force-reextract --filing-id N` per filing.

## Industry → SIC mapping

Everyday names resolve via `config/industry_sic_codes.yaml`:

```yaml
industries:
  software:
    description: "Prepackaged software and computer services"
    sic_codes:
      - "7370"  # SERVICES-COMPUTER PROGRAMMING, DATA PROCESSING, ETC.
      - "7371"  # SERVICES-COMPUTER PROGRAMMING SERVICES
      - "7372"  # SERVICES-PREPACKAGED SOFTWARE
      - "7373"  # SERVICES-COMPUTER INTEGRATED SYSTEMS DESIGN
      - "7374"  # SERVICES-COMPUTER PROCESSING & DATA PREPARATION
      - "7377"  # SERVICES-COMPUTER RENTAL & LEASING
aliases:
  saas: software
  "computer services": software
```

The CLI prints the resolved codes on every run. To add an industry, edit the
YAML; codes must be 4-digit numeric strings (validated at load). Only codes
that appear in SEC's published list should be added — other codes are never
assigned to `companies.industry_code` by the pipeline, so including them is a
silent no-op.

SIC reference (live, verified 2026-04-19):
<https://www.sec.gov/corpfin/division-of-corporation-finance-standard-industrial-classification-sic-code-list>

### Null `industry_code` caveat

The discovery query filters with `c.industry_code = ANY(sic_codes)` which
excludes rows where `industry_code IS NULL`. Companies upserted before SIC
resolution landed — or whose EDGAR submissions record returned no SIC —
will NOT appear under any `--industry` filter.

If you suspect this is hiding valid rows, re-run `populate --year YYYY` to
refresh `industry_code` via `UniverseBuilder._process_filing → get_company_info`.
Future: explicit `--refresh-sic` flag (deferred; see plan).

## Shell-filing caveat

The industry filter relies on SEC's SIC classification + first-time-issuer
heuristics. Shell companies sometimes pass both: they get assigned a software
SIC and are flagged as first-time issuers, but their filings contain no
customer metrics. Example (from the 2015 software discover): SPELZON CORP,
JAREX SOLUTIONS CORP, Broke Out Inc., TODEX CORP, OPTILEAF, INC.

Mitigations (combine as needed):

- **`--exclude-amendments`** — drops `S-1/A` and `F-1/A` from the form-type
  set, keeping only original `S-1` / `F-1`. Removes many (not all) pure-amendment
  shells. For the 2015 software cohort this cut 41 candidates to 22.
- **Visual review** — the discover table shows company name, form, and date.
  Recognize shells by distinctive names (ALL CAPS single-word companies,
  generic "-CORP"/"INC"), and pass `--limit N` with a hand-picked list if
  targeted onboarding is needed.

Name-based auto-filtering was considered and rejected — too unreliable.

## When bare amendments legitimately yield 0 facts

Small S-1/A amendments often contain only diff-level changes (e.g., a revised
risk-factor paragraph) without restating financials or customer disclosures.
Example: Intellicheck Mobilisa S-1/A (2015-01-06, filing 1806) — 60 KB total,
zero occurrences of "customer" — correctly produces 0 facts. Not a bug.

If your `onboard` run reports `fact_count=0` for an amendment, confirm the
filing has customer content before filing a bug report.

## Flag reference

| Flag | Subcommands | Purpose |
|---|---|---|
| `--industry NAME` | discover, onboard | Required. Everyday name or alias. |
| `--year YYYY` or `--year YYYY-YYYY` | discover, onboard | **Required.** Prevents unbounded onboard runs. |
| `--year YYYY` | populate | Required single year for `UniverseBuilder`. |
| `--form-type {s1f1,S-1,S-1/A,F-1,F-1/A}` | discover, onboard | Default: `s1f1` (the union). |
| `--exclude-amendments` | discover, onboard | Drop `S-1/A`/`F-1/A` from the form-type set. |
| `--limit N` | discover, onboard | Cap NEW rows shown or processed. |
| `--dry-run` | onboard | Print plan; no writes. |
| `--skip-txt` | onboard | Skip the TXT filing fetch (HTML only). |
| `--include-already-extracted` | onboard | Enters interactive re-extraction prompt. |
| `--yes` | onboard | Auto-confirm re-extraction prompt. Requires `--include-already-extracted`. |
| `--storage-root PATH` | onboard | Filing cache dir. Default: `data/filings`. |
| `--database-url URL` | all | Override `DATABASE_URL` from `.env`. |
| `--user-agent STR` | all | EDGAR user agent. Default: `SEC_USER_AGENT` env. |

## Verification

After a successful `onboard` run:

- `v2_documents` row added with `status='complete'` and non-zero `fact_count`.
- Filing renders in the review UI (`/v2/review`).
- No `ReviewedFilingError` in logs unless a `--force` path was engaged.

Spot-check against EDGAR's full-text search to confirm the discovered count
matches reality:
<https://efts.sec.gov/LATEST/search-index?q=&dateRange=custom&startdt=2015-01-01&enddt=2015-12-31&forms=S-1>
(filter to SIC 7372 for prepackaged software).

## Related scripts

- `scripts/build_universe_real.py` — full-year universe sweep (use when you
  want everything, not a subset).
- `scripts/batch_download_filings.py` — download any `processing_status='pending'`
  filings regardless of industry.
- `scripts/batch_v2_extraction.py` — V2 extraction for any `status='fetched'`
  filing; supports `--filing-id N` and `--force-reextract`.
- `scripts/run_v2_extraction.py` — single-filing runner with `--force-reextract`.

## 10-K onboarding semantics

`populate --year YYYY --form-type 10k` runs `UniverseBuilder` over all
10-K / 10-K/A filings in the daily-index for the year. These filings land
in the `filings` table with **`is_in_scope_phase1=FALSE`** — that is
correct, not a bug. Phase 1 = S-1/F-1 first-time issuers, and the existing
`is_in_scope_phase1(form_type, ...)` gate returns `False` for 10-K by
design (`src/universe/classifiers.py:832-834`). Preserving that semantic
keeps the Phase 1 calibration intact for the gold-standard validator.

Discovery is form-aware: `discover` / `onboard` with `--form-type 10k`
omit the `is_in_scope_phase1 = TRUE` filter in the SQL, so 10-K rows
surface correctly. With `--form-type s1f1` (default) the filter applies as
before. A mixed bundle (e.g. `S-1` + `10-K` explicitly) keeps the filter
conservatively — only requests that are exclusively non-S-1/F-1 drop it.

Practical notes:

- A year's worth of 10-Ks is ~5–10k filings (every public US company files
  one annually). `populate` has no `--limit`; plan for ~15 minutes at SEC's
  10 req/s rate limit for metadata + per-CIK SIC lookups.
- 10-K/A amendments **supersede** the same-fiscal-year 10-K. After
  `populate`, `UniverseBuilder` calls `mark_superseded_filings()`, which
  demotes (`is_in_scope_phase1 = FALSE`) any 10-K whose
  `(company_id, period_end_date)` pair has a later filing — so a FY2022
  10-K/A filed in 2024 demotes the FY2022 10-K but leaves FY2023's 10-K
  in scope. Cross-fiscal-year analytics is preserved; per-fiscal-year
  the latest filed wins (legacy-040). Rows with NULL `period_end_date`
  are conservatively skipped — the supersession step needs the fiscal
  period to pair an amendment with its original. `period_end_date` is
  populated for 10-K / 10-K/A from EDGAR submissions JSON
  (`SECClient.get_filing_period_of_report`); S-1/F-1 retain their
  existing per-company "latest filing wins" semantics.
- The IPO-era SGML SPAC re-check (which fetches `txt_url` to look for
  "BLANK CHECKS [6770]" in the SGML header) is skipped for non-S-1/F-1
  forms — it's a per-filing HTTP call that adds no signal for 10-Ks.
  Verified by `test_process_filing_10k_skips_sgml_recheck` in
  `tests/unit/universe/test_universe_builder.py`.

## Extending

- **New form type** (e.g. `8-K`): add to `FORM_TYPE_BUNDLES` in
  `scripts/onboard_tickers.py` (10-K is already shipped — use `--form-type 10k`).
  `build_universe(form_types=[...])` accepts arbitrary form-type lists;
  `SECClient.search_filings` filters daily-index files per-form. Check
  `sql/01_create_schema.sql` line 79 and `sql/16_add_8k_form_type.sql` for
  the `CHECK` constraint (S-1/F-1/10-K/10-K/A/8-K/earnings_call/
  investor_presentation are allowed). If the new form's Phase-1 semantics
  differ from S-1/F-1, update `S1F1_FORMS` in `scripts/onboard_tickers.py`
  and/or `is_in_scope_phase1` in `src/universe/classifiers.py` accordingly.
  **8-K note:** `scripts/ingest_presentations.py` owns 8-K investor
  presentations via a different code path; don't duplicate.
- **New industry**: append under `industries:` in the YAML.
- **Ticker → CIK fast path**: deferred. When the operator knows the CIK up
  front, add `build_universe_for_ciks` to `UniverseBuilder`.

## Known limitations

- **`populate` supports `--form-type s1f1` (default) and `--form-type 10k`.**
  8-K / earnings-call / investor-presentation ingestion is handled by
  `scripts/ingest_presentations.py` (different architecture — per-ticker
  EDGAR submissions lookup, not daily-index sweep). See "10-K onboarding
  semantics" below for the Phase 1 interaction.
- **Hardcoded column widths in the discover table.** Long company names get
  truncated at 30 characters; no terminal-size detection. Cosmetic only;
  does not affect correctness.
- **`companies.industry_code IS NULL` is silently excluded.** The discovery
  filter `c.industry_code = ANY(sic_codes)` drops NULL rows. If a company
  exists in `companies` without a SIC assignment, it will never appear under
  any `--industry` filter. Re-run `populate --year YYYY` to refresh via
  `get_company_info`.

## Web UI

The batch-ingest UI at `/ingest/` is an alternative to the CLI for operators
who prefer a browser workflow. It drives the same underlying pipeline.

### Workflow

1. **Criteria form** (`/ingest/`) — enter industry, year(s), form type, and
   (optionally) a candidate limit. Submit to preview.
2. **Preview** (`/ingest/preview`) — shows the three filing buckets (see below)
   and per-bucket counts. Opt-in checkboxes for ALREADY EXTRACTED filings.
   Large batches trigger warnings or hard blocks before you can proceed.
3. **Start** (`/ingest/start`) — enqueues a batch row in `v2_ingest_batches`
   (`status='queued'`). Redirects immediately to the live-progress page.
4. **Live progress** (`/ingest/batch/<id>`) — polls `/api/v2/ingest/batches/<id>/status`
   every 3 seconds and renders per-filing status in real time.

### Sizing controls (Phase 1, 2026-04-30)

Two complementary affordances for capping batch size when an "all-industry"
year sweep returns hundreds of candidates:

- **Candidate Limit** field on the criteria form — applies a SQL `LIMIT` to
  the discovery query. Range 1–5 000; blank = no cap. The volume banner on the
  preview page reflects the limited count, so a large universe can land in the
  OK band by setting `limit=25`.
- **"Check first N"** controls per section on the preview page — uncheck all
  rows in that section, then check the first N currently-rendered rows. Useful
  for slicing an already-discovered list of, say, 200 candidates into batches
  of 25 without re-querying.

Discovery is sorted **most-recent first** (`filing_date DESC, company_name ASC`),
so "first N" means the N most recent filings. The same sort applies to
`load_candidates_by_filing_ids` and the `/api/v2/ingest/batches/<id>/status`
filings list.

### Industry catalog

Named industries live in `config/industry_sic_codes.yaml`. The Phase 1
expansion (2026-04-30) added 20 non-tech sectors (biotech, pharmaceuticals,
medical_devices, commercial_banking, investment_management, apparel_retail,
home_improvement_retail, auto_dealers, restaurants, oil_gas_exploration,
oil_gas_refining, electric_utilities, semiconductors, computer_hardware,
telecom_equipment, aerospace_defense, media_publishing, gaming_entertainment,
it_services_consulting, homebuilding) plus aliases (`bio`, `pharma`,
`medtech`, `banks`, `chips`, `defense`, etc.). All SIC codes verified against
SEC's published list. To add a new industry, append to the YAML and run
`pytest tests/unit/universe/test_onboarding.py::test_load_industry_map_includes_new_industries`.

### Year ↔ industry ↔ form-type facet cascade (Phase 2b–2c, 2026-04-30)

The discovery form (the lower section under the Build-universe panel) is
**facet-driven across three axes**: Industries (multi-select listbox),
Year (multi-select listbox), and Form Types (checkbox row). All three
are populated from the actual contents of `filings`, with row counts
shown next to each option. Each axis count equals the number of filings
matching the OTHER two axes' selections (standard facet UX — each axis
ignores its own selection so the user always sees the full set of
choices for that axis):

- Selecting year(s) narrows industries + form-types.
- Selecting industries narrows years + form-types.
- Selecting form-type(s) narrows years + industries.
- Form-type checkboxes: multiple selections are OR-ed, so `IPO` + `10-K`
  shows year/industry counts for filings in either bundle.
- Selected options that drop to zero count stay visible (greyed `(0)`)
  so the user can deselect them. For Year and Industry listboxes,
  unselected zero-count options are hidden; for Form-type checkboxes,
  unselected zero-count options stay visible-but-disabled (the row only
  has 3 entries, hiding would be jarring).

Backed by `GET /api/v2/ingest/filter-options?year=...&industry=...&form_type=...`
→ `{years: [...], industries: [...], form_types: [...]}`. Helpers in
`src/universe/onboarding.py`: `query_universe_year_counts`,
`query_universe_industry_counts`, `query_universe_form_type_counts`.
Cascade JS: `src/web/static/js/ingest_form_facets.js`.

**Year multi-select edge case:** non-contiguous selections (e.g. 2016 +
2018 with 2017 omitted) silently expand to the inclusive (min, max) range
because the underlying discovery SQL uses `BETWEEN year_min AND year_max`.
For a true gap, submit two batches.

### Universe gap banner

If the criteria reference (year × form_type) combinations with zero rows in
the `filings` table, the preview surfaces a "Universe gaps detected" banner
with one-click populate buttons. Clicking submits a `kind='populate'` batch
inline; the preview re-fetches when populate completes. Gap detection works
for company-name-only criteria too (no industry / no SIC required).

### Build universe via UI (Phase 2a, 2026-04-30)

The criteria form at `/ingest/` also exposes a top-of-page **"Build universe
(populate from SEC)"** panel — the direct equivalent of running
`scripts/build_universe_real.py --start-date YYYY-01-01 --end-date YYYY-12-31`.
Submit a year + form-type bundle (`s1f1` or `10k`) + reviewer name to enqueue
a `kind='populate'` batch; the worker (`filings-onboarding-runner` in prod,
local subprocess in dev) drains it via `UniverseBuilder.build_universe`. The
existing `/ingest/batch/<id>` progress page and `/ingest/history` list both
render populate batches.

Notes:
- **Single year per submit.** The endpoint accepts one year (1990–2030); for
  multi-year campaigns submit multiple times. The worker processes one build
  at a time, so concurrent submissions queue safely.
- **Idempotent.** Re-running a year upserts rows in `companies` / `filings`
  and re-runs amendment supersession; no duplicates.
- **8-K not exposed in the dropdown.** `FORM_TYPE_BUNDLES` admits `8k` but
  `UniverseBuilder` does not classify SPAC / first-time-issuer / amendment
  supersession on 8-Ks (those gates are S-1/F-1 and 10-K-scoped by design),
  so populating 8-K via this UI yields a raw filing index that is not a
  CMASB universe. Use the CLI with `--form-types 8-K,8-K/A` if you need it.
- **Prereq:** `SEC_USER_AGENT` must be set on the runner service
  (`filings-onboarding-runner` env group) — the placeholder fallback in
  `onboarding_runner.py` violates SEC's contact-email requirement and will
  trigger 403/429 from EDGAR.

### Three filing buckets

| Bucket | Default | Override |
|--------|---------|----------|
| **NEW** — no existing `v2_documents` row | Process | (always included) |
| **ALREADY EXTRACTED, no review decisions** | Skip | Opt-in checkbox on preview page |
| **ALREADY EXTRACTED + reviewed** | Skip | Per-row checkbox + confirm dialog |

### Re-extraction semantics

Re-extracting a filing with existing review decisions CASCADEs via
`v2_review_decisions.fact_id ON DELETE CASCADE`, permanently purging those
decisions. There is no archive. The confirm dialog names the affected filing
and decision count before proceeding.

See `.claude/rules/v2-pipeline.md` — "Reviewed-Filing Guard" — for the
`ReviewedFilingError` that prevents silent purges if a consumer bypasses the
UI prompt.

### Volume thresholds

| Range | Behaviour |
|-------|-----------|
| < 50 | OK — proceed immediately |
| 50–199 | SOFT_WARN — info banner; proceed without extra step |
| 200–499 | HARD_WARN — checkbox "I understand this is a large batch" required |
| 500–999 | REFINE — batch rejected; refine filters before submitting |
| ≥ 1 000 | BLOCK — batch rejected unconditionally |

### Render deployment

In production, the web dyno sets `INGEST_SPAWN_SUBPROCESS=false` (via
`render.yaml`) so it never spawns a runner subprocess. Instead, the
`filings-onboarding-runner` worker service picks up queued batches within
~10 seconds:

```yaml
# render.yaml (excerpt)
- type: worker
  name: filings-onboarding-runner
  runtime: docker
  dockerCommand: python3 -m src.universe.onboarding_runner --watch --poll-interval 10
```

In local dev, `INGEST_SPAWN_SUBPROCESS` defaults to `true` (set in
`src/web/app.py::Config`), so `/ingest/start` spawns the runner inline as a
detached subprocess — no separate process needed.

### Troubleshooting stuck batches

If a batch is stuck in `status='running'` (e.g. after a web-dyno restart killed
the subprocess mid-run — Issue #47), recover it manually:

```sql
UPDATE v2_ingest_batches
SET status = 'failed', finished_at = NOW()
WHERE batch_id = '<id>' AND status = 'running';
```

After this, re-submit from the preview page. A `--cleanup-stuck` admin flag
(auto-resets timed-out running rows on worker startup) is a planned follow-up.

---

## Recovering a stuck batch (local dev)

On local dev there is no watcher process. If `onboarding_runner` dies mid-batch (kernel OOM, Flask server killed, `ctrl-c` at the wrong time), the row in `v2_ingest_batches` stays in `status='running'` forever and subsequent runs won't re-claim it.

To find stuck candidates:

```sql
SELECT batch_id, started_at, run_lock_until
FROM v2_ingest_batches
WHERE status = 'running'
  AND (run_lock_until IS NULL OR run_lock_until < NOW() - INTERVAL '1 hour');
```

To mark a batch failed manually:

```sql
UPDATE v2_ingest_batches
SET status = 'failed',
    finished_at = NOW(),
    run_lock_until = NULL
WHERE batch_id = '<uuid>';
```

Partially-processed `v2_ingest_batch_filings` rows with `processing_status='running'` should also be reset or deleted depending on whether the filings had side effects (image assets written, facts persisted). Inspect before cleaning.

Prod / Render: the `--watch` mode on the worker service automatically re-claims batches whose `run_lock_until` has expired — no manual step needed.

Prefer the scripted path below over hand-crafted UPDATEs.

### Cleaning up stuck batches with `--cleanup-stuck`

`onboarding_runner` ships an admin mode that finds running batches whose
`run_lock_until` is older than a tunable threshold and marks them
`status='failed'`. Always run dry-run first to inspect candidates before
writing.

**Dry-run (default — no writes):**

```bash
python3 -m src.universe.onboarding_runner --cleanup-stuck
```

Sample output:

```
INFO ... cleanup-stuck: 1 candidate batch(es) older than threshold='1 hour':
INFO ...   batch_id=4f3a... started_at=2026-04-28 09:14:22+00 run_lock_until=2026-04-28 09:29:22+00
INFO ... cleanup-stuck: matched=1 marked_failed=0 (dry-run)
```

**Apply (writes the UPDATE):**

```bash
python3 -m src.universe.onboarding_runner --cleanup-stuck --apply
```

Each matched row is set to `status='failed'`, `finished_at=NOW()`,
`run_lock_until=NULL`. Per-filing rows in `v2_ingest_batch_filings` are not
touched — partial-progress rows must still be inspected by hand if their
filings had side effects (image assets written, facts persisted).

**Tunable threshold:**

```bash
python3 -m src.universe.onboarding_runner --cleanup-stuck \
    --stuck-threshold '30 minutes'
```

`--stuck-threshold` accepts any Postgres interval string. Default is
`'1 hour'`.

**Production guard:** `--apply` against a `*.neon.tech` `DATABASE_URL` is
refused with exit code `2` unless `--allow-prod` is also passed. Dry-run
mode is always permitted (no writes). On Render this is unnecessary —
the worker service running `--watch` already re-claims any batch whose
lock has expired, so production normally needs no manual intervention.

```bash
# Required for prod writes (only if you really mean it):
python3 -m src.universe.onboarding_runner --cleanup-stuck --apply --allow-prod
```

`--cleanup-stuck` is the *abandon* path: it gives up on a stuck batch
rather than retrying it. If you instead want to retry, leave the row
alone and start `--watch`; the existing claim semantics
(`run_lock_until < NOW()`) will pick it back up automatically.

Tracked under [known issue #62](../known-issues/legacy-062-local-dev-stuck-batch-recovery-is-manual.md).
