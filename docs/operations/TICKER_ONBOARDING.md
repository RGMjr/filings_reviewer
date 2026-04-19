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
      - "7370"  # Services-Computer Services
      - "7371"  # Services-Computer Programming, Data Processing
      - "7372"  # Services-Prepackaged Software
      - "7373"  # Services-Computer Integrated Systems Design
      - "7374"  # Services-Computer Processing & Data Preparation
      - "7377"  # Services-Computer Rental and Leasing
      - "7379"  # Services-Computer Services, NEC
aliases:
  saas: software
  "computer services": software
```

The CLI prints the resolved codes on every run. To add an industry, edit the
YAML; codes must be 4-digit numeric strings (validated at load).

SIC reference: <https://www.sec.gov/info/edgar/siccodes.htm>.

### Null `industry_code` caveat

The discovery query filters with `c.industry_code = ANY(sic_codes)` which
excludes rows where `industry_code IS NULL`. Companies upserted before SIC
resolution landed — or whose EDGAR submissions record returned no SIC —
will NOT appear under any `--industry` filter.

If you suspect this is hiding valid rows, re-run `populate --year YYYY` to
refresh `industry_code` via `UniverseBuilder._process_filing → get_company_info`.
Future: explicit `--refresh-sic` flag (deferred; see plan).

## Flag reference

| Flag | Subcommands | Purpose |
|---|---|---|
| `--industry NAME` | discover, onboard | Required. Everyday name or alias. |
| `--year YYYY` or `--year YYYY-YYYY` | discover, onboard | Filter. Range supported for discover/onboard only. |
| `--year YYYY` | populate | Required single year for `UniverseBuilder`. |
| `--form-type {s1f1,S-1,S-1/A,F-1,F-1/A}` | discover, onboard | Default: `s1f1` (the union). |
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

## Extending

- **New form type** (e.g. `10-K`): add to `FORM_TYPE_BUNDLES` in
  `scripts/onboard_tickers.py`. The discovery SQL already parameterizes
  `form_type`. Check `sql/01_create_schema.sql` line 79 for the `CHECK`
  constraint (10-K is already allowed). Note that `UniverseBuilder.build_universe`
  currently hardcodes S-1/F-1; extending to 10-K requires a separate path.
- **New industry**: append under `industries:` in the YAML.
- **Ticker → CIK fast path**: deferred. When the operator knows the CIK up
  front, add `build_universe_for_ciks` to `UniverseBuilder`.
