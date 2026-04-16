# Presentation Gold Standard Review Checklist (8-K investor presentations)

This directory covers 8-K investor presentations ONLY. For S-1/F-1/10-K HTML filings see `data/filing_gold_standard/REVIEW_CHECKLIST.md`.

Last updated: 2026-04-07 (all pending filings reviewed and merged)

## Legend
- Text review: `python3 scripts/review_presentation_annotations.py --form-type 8-K data/presentation_gold_standard/<key>_preannotated.csv`
- Image review: start Flask (`python3 src/web/app.py`) → http://127.0.0.1:5002/review/pres-images/
- Merge: `python3 scripts/merge_presentation_annotations.py --form-type 8-K`

---

## Needs text review

These have preannotated CSVs but no reviewed file. The 0-candidate filings go straight to the "add missed metrics" prompt.

*None pending.*

---

## Needs image review

These have image candidate files but no (or zero) review decisions in `_image_decisions.json`.

*None pending.*

---

## Out of scope / excluded

| Key | Notes |
| --- | --- |
| (S-1/F-1/10-K entries) | Moved to `data/filing_gold_standard/` — use `--form-type S-1` scripts for those. |

---

## Reviewed but not yet merged into gold standard

These have `_reviewed.csv` files but their ticker does not appear in `presentation_gold_standard.csv`. Run merge after confirming.

*None pending.*

---

## Complete (in gold standard) — 8-K entries only

S-1/F-1/10-K entries have moved to `data/filing_gold_standard/REVIEW_CHECKLIST.md`.

| Key | Text reviewed | Image decisions | Split |
| --- | --- | --- | --- |
| `ADBE_2019-01-24` | 0 confirmed | — | tuning |
| `BRZE_2025-03-27` | — | — | tuning |
| `CRM_2025-12-03` | 1/1 | — | tuning |
| `CRM_2026-02-25` | 4/4 | — | tuning |
| `DASH_2023-11-01` | — | — | tuning |
| `GOOGL_2025-10-29` | 1/1 | — | tuning |
| `GOOGL_2026-02-04` | 2/2 | — | tuning |
| `INTU_2025-11-20` | 1/1 | — | tuning |
| `INTU_2026-02-26` | 0 confirmed | — | tuning |
| `META_2025-12-12` | 0 confirmed | — | tuning |
| `META_2026-01-28` | 1/1 | — | tuning |
| `NOW_2013-07-31` | 0 confirmed | — | tuning |
| `PYPL_2025-10-28` | 7/2* | — | tuning |
| `PYPL_2026-02-03` | 7/2* | — | tuning |
| `SNOW_2026-02-25` | — | — | tuning |
| `TRUP_2018-02-13` | 2 added | — | test |
| `TRUP_2018-05-01` | 2 added | — | test |
| `TRUP_2018-08-02` | 2 added | — | test |

*PYPL reviewed file has more rows than preannotated — likely manually added entries.
