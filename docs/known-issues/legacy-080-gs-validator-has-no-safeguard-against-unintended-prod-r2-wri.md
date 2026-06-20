---
autonomy: review
discovered: '2026-04-22'
estimated: S
id: 80
note: Add env-scoped guard against unintended prod R2 writes from CLI tools; design
  call (storage-layer vs validator-layer) needed
pr_refs:
- 200
severity: medium
slug: gs-validator-has-no-safeguard-against-unintended-prod-r2-wri
source: legacy
status: archived
title: GS Validator Has No Safeguard Against Unintended Prod R2 Writes
touches:
- src/infra/image_storage.py
- src/gold_standard/v2_validator.py
- .claude/rules/infrastructure.md
- render.yaml
updated: '2026-04-25'
---

### Problem

`python3 -m src.gold_standard.v2_validator` reads its environment uncritically. If `R2_BUCKET` (and the rest of the R2 creds) are set when the validator runs, the chart pipeline's `OCRExtractionStage._download_missing_images` will issue `storage.put_bytes` calls against the live R2 backend — a production write — for every chart-classified image whose asset row lacks a `file_path`. There is no warning, no dry-run mode, no env-scoped guardrail. A contributor who sources prod `.env` to make `psql` / `boto3` work for one CLI step (e.g. probing a key with `HeadObject`) and then runs the validator gets a silent prod state mutation.

The same risk applies to any code path that calls `storage.put_bytes` without an env-scoped sanity check (currently `OCRExtractionStage._download_missing_images` and `IngestionStage._extract_image_assets` both qualify).

### Next Steps

- Add an env-scoped safeguard to `get_image_storage()` (or wrap `put_bytes` itself): when the active backend is `R2Storage` AND the process was started without an explicit "I intend prod writes" opt-in (e.g., a `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` env var), refuse `put_bytes` and surface a clear error pointing at the cause. Reads (`get_bytes`, `exists`) stay open so diagnostics remain possible.
- Alternative: add a startup check in `v2_validator.py __main__` that warns (or aborts) when `R2_BUCKET` matches the prod bucket name unless `--allow-prod-writes` is passed. Narrower scope than the storage-layer guard but catches the validator-specific foot-gun.
- Document the foot-gun in `.claude/rules/infrastructure.md` under image-storage so future contributors are aware before the safeguard lands.

Cross-references: #77 (the bug whose fix surfaced this), #34 (R2 backend introduction).
