# Filing Gold Standard Review Checklist (S-1/F-1/10-K HTML filings)

This directory covers S-1/F-1/10-K HTML filings ONLY. For 8-K investor presentations see `data/presentation_gold_standard/REVIEW_CHECKLIST.md`.

Last updated: 2026-04-07 (all pending filings reviewed and merged)

## Legend
- Text review: `python3 scripts/review_presentation_annotations.py --form-type S-1 data/filing_gold_standard/<key>_preannotated.csv`
- Image review: start Flask (`python3 src/web/app.py`) → http://127.0.0.1:5002/review/pres-images/
- Merge: `python3 scripts/merge_presentation_annotations.py --form-type S-1`

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
| `SI_S-1_2025-07-25` | Shoulder Innovations (orthopedics), not Silvergate. 0 text candidates, 15 images all `not_relevant`. Do not merge. |

---

## Reviewed but not yet merged into gold standard

These have `_reviewed.csv` files but their ticker does not appear in `filing_gold_standard.csv`. Run merge after confirming.

*None pending.*

---

## Complete (in gold standard) — S-1/F-1/10-K entries only

8-K investor presentation entries are in `data/presentation_gold_standard/REVIEW_CHECKLIST.md`.

| Key | Text reviewed | Image decisions | Split |
| --- | --- | --- | --- |
| `ABNB_S-1_2020-12-07` | — | — | tuning |
| `BRZE_S-1_2021-11-08` | — | — | tuning |
| `CART_S-1_2023-09-15` | 50/55 | 83/83 | test |
| `CHWY_S-1_2019-06-12` | 38/38 | 34/34 | tuning |
| `CURV_S-1_2021-06-30` | 76/76 | 23/23 | tuning |
| `DASH_S-1_2020-12-07` | — | — | tuning |
| `DDOG_S-1_2019-09-17` | 23/23 | 19/19 | tuning |
| `DUOL_S-1_2021-07-26` | — | — | tuning |
| `FLYW_10-K_2026-02-24` | 5/5 | 9/9 | test |
| `GTLB_S-1_2021-10-12` | 48/48 | 9/9 | test |
| `HOOD_S-1_2021-10-08` | 60/61 | 22/22 | test |
| `IOT_S-1_2021-12-06` | 73/73 | 25/25 | tuning |
| `KC_F-1_2020-09-23` | 24/24 | 15/15 | tuning |
| `NETS_F-1_2017-03-21` | 61/61 | 16/16 | tuning |
| `SI_S-1_2018-11-07` | 12/12 | 24/24 | tuning |
| `SNOW_S-1_2020-09-14` | — | — | tuning |
| `TENB_S-1_2018-07-24` | 20/20 | 9/9 | tuning |
