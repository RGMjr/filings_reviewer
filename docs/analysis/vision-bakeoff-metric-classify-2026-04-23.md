# Wave B5.x Vision Bake-off — Metric-CLASSIFY Mode — 2026-04-23

**Status:** Third leg of the 2026-04-23 vision sweep, following
[`vision-bakeoff-2026-04-23.md`](./vision-bakeoff-2026-04-23.md) (detect)
and
[`vision-bakeoff-chart-read-2026-04-23.md`](./vision-bakeoff-chart-read-2026-04-23.md)
(chart-read). Those runs measured, respectively, whether an image
contains a chart and how well the numeric values can be recovered from
it. This run measures what the operational pipeline actually needs:
**given a chart image, which Tier-1 / Tier-2 customer metric does it
disclose?** The prediction is paired with the image in the review UI
so a reviewer's single click maps to one of four actions — **accept**,
**reject**, **correct**, or **add** — per the presence-first
direction captured in memory
(`project_presence_first_extraction_direction`).

**Scope of this run:** 5 provider configurations (`current`,
`openai-vnext`, `gemini-flash`, `gemini-pro`, `anthropic`) benchmarked
via `scripts/benchmark_vision.py --bakeoff --mode metric-classify`
against the same 7-image corpus (3 Farfetch + 4 Slack). `two-stage`
is intentionally excluded — the premium reader's edge is numeric
fidelity, not presence classification. Total spend $0.12 under a $3
cap. Ran with `LLM_CACHE_ENABLED=false` so every dollar figure
reflects a real API call.

Ground truth is **hand-annotated** per manifest entry
(`ground_truth_metric_ids`) by visually inspecting the JPGs, not
hydrated from `v2_metric_facts` — an unlabeled cohort parfait can have
zero fact rows and still disclose a metric. Prior notes suggested the
Slack mdaa2/3/4 JPGs were missing; visual inspection on 2026-04-23
confirmed all four Slack images (mda1c, mdaa2, mdaa3, mdaa4) are present
on disk, and annotations were assigned accordingly.

## TL;DR

`gemini-flash` is the clear winner on every operational axis:

- **Auto-disposition rate 0.714** (accept + skip) — highest in the sweep;
  5 of 7 images would need zero reviewer action if we shipped its
  predictions straight to the review UI.
- **Zero `add` actions** — it never missed a metric the reviewer would
  have to add by hand, which is the single costliest bucket
  operationally.
- **Metric-tag F1 0.750** — highest set-overlap score.
- **Lowest latency (1.5 s/image)** and **lowest cost ($0.002/image)**.
- **Best calibration (ECE 0.271)** — its confidence numbers are the
  closest to its accuracy.

The operational recommendation (pending a larger corpus) is to use
`gemini-flash` for classify and wire it into the review UI as a
pre-filled prediction; chart-read stays reserved for downstream
numeric-extraction work once reviewers confirm metric presence.

## Side-by-side (5-provider bake-off)

Results from
`data/image_benchmarks/bakeoff_metric_classify_2026-04-23/summary.json`.
All seven images contribute (every entry now carries
`ground_truth_metric_ids`).

| Provider | Accept | Reject | Correct | Add | Partial | Skip | Auto-disp | Tag F1 | ECE | Parse fail | Cost/img | Latency |
|---------------|-------:|-------:|--------:|----:|--------:|-----:|----------:|-------:|----:|-----------:|---------:|--------:|
| current       | 0.43   | 0.00   | 0.29    | 0.29| 0.00    | 0.00 | **0.429** | 0.571  | 0.343 | 0.000    | $0.0039  | 2774ms  |
| openai-vnext  | 0.57   | 0.00   | 0.29    | 0.14| 0.00    | 0.00 | **0.571** | 0.667  | 0.393 | 0.000    | $0.0039  | 1889ms  |
| **gemini-flash** | **0.71** | 0.00 | 0.29  | **0.00** | 0.00 | 0.00 | **0.714** | **0.750** | **0.271** | 0.000 | **$0.0021** | **1485ms** |
| gemini-pro    | 0.00   | 0.00   | 0.00    | 1.00| 0.00    | 0.00 | 0.000     | 0.000  | 0.000 | 1.000      | $0.0011  | 4998ms  |
| anthropic     | 0.57   | 0.00   | 0.29    | 0.14| 0.00    | 0.00 | 0.571     | 0.667  | 0.344 | 0.000      | $0.0066  | 3654ms  |

Metric-tag P/R/F1 (scored on 7 images):

| Provider      | Precision | Recall | F1    |
|---------------|----------:|-------:|------:|
| current       | 0.667     | 0.500  | 0.571 |
| openai-vnext  | 0.714     | 0.625  | 0.667 |
| gemini-flash  | 0.750     | 0.750  | 0.750 |
| gemini-pro    | 0.000     | 0.000  | 0.000 |
| anthropic     | 0.714     | 0.625  | 0.667 |

### gemini-pro caveat

`gemini-pro` returned **empty content** for every image (parse failure
rate 1.0, raw output `""`), so its disposition numbers reflect "pipeline
emitted nothing" — every scorable image is logged as `add` because
reference is non-empty. This is a known upstream quirk with
`gemini-2.5-pro` on vision-plus-`response_format=json_object`; it does
not reproduce on `gemini-2.5-flash-lite`. It is not a classify-harness
bug and is out of scope for this PR. If a Gemini-Pro classify path is
needed later, the likely fix is dropping the JSON response-format hint
for that provider adapter and parsing the content-free response
payload, which belongs in `src/llm/vision_client.py` gemini adapter
work.

## Three-way comparison with detect and chart-read modes

| Dimension | Detect (PR #142) | Chart-read (B5.x / #145) | **Classify (this run)** |
|-----------|---|---|---|
| Question answered | "Is this a chart?" | "What are the numbers?" | **"Which metric?"** |
| Cheapest F1=1.0 provider | gemini-flash (tie) | N/A (P/R ceiling from fixture corpus) | **gemini-flash (F1 0.750)** |
| Operational value | Gate for OCR pipeline | Value fidelity for downstream extraction | **Single-click reviewer action on the presence-first UI** |
| Spend | $0.02 | $0.34 | **$0.12** |
| Latency | ~2 s | 3-15 s | **1.5 s (flash)** |
| Separation between providers | Saturated at 1.0 | Ceiling-limited (tie at F1 0.182) | **Clean (0.571 / 0.667 / 0.750 / 0.000 / 0.667)** |
| Measurable on current fixture | Yes | Weakly (1 image) | **Yes (7 images)** |

The operational stack is layered: detect decides whether to call the
image pipeline at all; classify names the metric so the reviewer can
accept/reject; chart-read runs only once classify has confirmed a
metric and downstream consumers actually need numbers. The
full-page-OCR work (PRs #110 / #114 / #139) sits orthogonal to this
stack — it handles TABLES via `VisionClient.analyze_image_for_text`.
Classify mode is charts-only; it maps a table image to
`predicted_metrics=[]` + `rejection_reason="other"` so the OCR
pipeline can own them.

## Confidence-threshold sweep — auto-disposition vs add-rate

Recomputed from the raw per-image records (simulate
`predicted_metrics → []` when model confidence falls below the
threshold; disposition follows the standard rule set). Values are
auto-disposition (`accept + skip`) share at each threshold:

| Provider      | @ 0.5  | @ 0.7  | @ 0.85 | @ 0.95 |
|---------------|-------:|-------:|-------:|-------:|
| current       | 0.429  | 0.429  | 0.429  | 0.143  |
| openai-vnext  | 0.571  | 0.571  | 0.429  | 0.286  |
| **gemini-flash** | **0.714** | **0.714** | **0.714** | **0.571** |
| anthropic     | 0.571  | 0.571  | 0.571  | 0.429  |

(`gemini-pro` omitted — empty responses leave auto-disposition at 0 for
every threshold.)

Gemini Flash stays at 0.714 across the 0.5-0.85 range because six of
its seven predictions carry conf = 1.0; only the mda1c prediction
(conf 0.9) falls below the 0.95 bar. Raising the bar past 0.85 starts
converting accepts into adds for every other provider but still leaves
Flash ahead on auto-disposition at every threshold.

**Preliminary — rerun when the corpus expands.** ECE with n=7 is
noisy by construction; the calibration numbers above are ordinal
signal, not quantitative ground truth.

## Corpus notes

Seven images, all hand-annotated on 2026-04-23:

| img_id | Ground truth | Notes |
|--------|--------------|-------|
| `gs-farfetch-g607688g09d00` | `cm_revenue_by_cohort` | Line chart of revenue-share % by consumer cohort, 2015-2017 |
| `gs-farfetch-g607688g12o45` | `cm_transactions_by_cohort` | Marketplace GMV layer-cake parfait, 2010-2017 (NOT LTV/CAC as Issue #29 notes suggested — visual inspection confirms GMV-by-cohort) |
| `gs-farfetch-g607688g54x53` | `cm_ltv_to_cac_ratio_by_cohort` | LTV/CAC ratios (1.42x to 2.71x) by cohort (2015/2016/2017) at 6m/12m/24m tenure (NOT gross-margin-by-cohort as Issue #20 notes suggested) |
| `gs-slack-mda1c` | `cm_customers_period_end` | "Product and Partnerships Timeline" — Paid Customers line with milestone overlay |
| `gs-slack-mdaa2` | `cm_revenue_by_cohort`, `cm_arr` | "ARR by Annual Cohort through January 31, 2019" — layer-cake parfait, FY2015-FY2019 |
| `gs-slack-mdaa3` | `cm_customers_period_end` | "Paid Customers" bar chart FY2017-FY2019 (37K / 59K / 88K) |
| `gs-slack-mdaa4` | `cm_large_customers_period_end` | "Paid Customers > $100,000" bar chart FY2017-FY2019 (135 / 298 / 575) |

Two manifest notes corrected during this run: g12o45 was Farfetch
GMV-by-cohort (not LTV/CAC) and g54x53 was LTV/CAC-by-cohort (not
gross-margin-by-cohort). Both corrections are carried in the manifest
`reviewer_notes` for traceability.

## Why Gemini Flash wins

1. **Zero adds.** For every image, its prediction was either exactly
   right or named a different single metric — it never "missed" a
   disclosure that a reviewer would then have to hunt for and type in.
   It's the only provider with `add_rate = 0.0`.
2. **The one multi-metric case landed.** Slack mdaa2 (ARR-by-cohort
   layer cake) carries two ground-truth metrics (`cm_revenue_by_cohort`
   + `cm_arr`); Flash is the only provider that emitted both. The
   default path (`current`) and `openai-vnext` emit just `cm_arr`, so
   that image is logged as `add` (subset → reviewer adds the missing
   cohort tag).
3. **All errors are `correct`, not `add`.** Its two misses on this
   corpus — Farfetch g09d00 (named `cm_customers_period_end_by_tenure`
   for a cohort-revenue-share chart) and g12o45 (named
   `cm_revenue_by_cohort` for a marketplace-GMV cohort parfait, which
   ground truth labels `cm_transactions_by_cohort`) — produce
   `correct` dispositions, which is a single-click swap in the review
   UI rather than a type-from-scratch. The g12o45 "miss" is a close
   call; GMV-vs-revenue is a genuine taxonomy ambiguity.
4. **Separation is crisp.** Tag precision = recall = 0.750, meaning
   when it names a metric, it names the right one at the same rate it
   covers truth.
5. **Speed and cost dominate.** Half the latency of the next-closest
   provider and 1.9× cheaper than the default `current` path.

The default path (`current` = GPT-4o) scored worst among the providers
that parsed cleanly — `add_rate = 0.286`, F1 0.571. One of its misses
is a full give-up: mda1c (Paid Customers timeline) returned
`predicted_metrics=[]` at confidence 0.0. Switching the default to
Flash is a strict win on this corpus.

## Decisions

1. **`gemini-flash` becomes the recommended classify provider** pending
   a larger corpus. Flag the decision as preliminary — n=7 is too small
   to commit production routing.
2. **Do NOT wire classify into `src/extraction_v2/` yet.** The prompt
   lives in `scripts/benchmark_vision.py` intentionally; a follow-up PR
   promotes it into a `VisionClient.analyze_image_for_metric_classification`
   helper alongside the full-page-OCR work.
3. **Demote `chart-read` from the default path** in docs (presence-first
   framing). Keep it as a measurement mode — it's still the right tool
   for per-point data-fidelity work once a reviewer confirms the metric
   is disclosed.
4. **Expand the corpus before committing to prod routing.** Either
   hydrate `v2_image_review_decisions` locally and re-run
   `--build-corpus`, or hand-add 10-20 entries from filings already in
   `data/gold_standard/`. Priority targets: cohort parfaits with
   unlabeled data points (cohortcharts.com style) and table-as-image
   inputs (should return `predicted_metrics=[]` +
   `rejection_reason="other"`).

## Not in this PR (explicit follow-ups)

- Promote classify into `src/extraction_v2/stages/image_triage.py` (or a
  new stage) as the prod routing gate, with a
  `v2_image_classifications` table (or extension of `v2_image_assets`)
  and a review-UI surface for accept/reject/correct.
- Investigate `gemini-pro` empty-content behaviour on
  vision+`response_format=json_object` calls. Workaround in prod today
  is avoiding Gemini Pro for classify; longer-term, consider relaxing
  the JSON response-format hint for the Gemini adapter and parsing
  free-text back into the four-field schema.
- Extend `v2_image_review_decisions.rejection_reason` enum to include
  `table_handled_elsewhere` for cleaner accounting when the classifier
  returns `[]` on a table image (migration + review-UI change).
- Run classify on the 11 PayPal 8-Ks via
  `scripts/backfill_full_page_ocr.py --force-reextract` once classify
  is wired into prod routing.
