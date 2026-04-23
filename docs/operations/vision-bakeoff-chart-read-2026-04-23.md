# Wave B5.x Vision Bake-off — Chart-READ Mode — 2026-04-23

**Status:** Companion to [`vision-bakeoff-2026-04-23.md`](./vision-bakeoff-2026-04-23.md).
That run measured chart DETECTION (`contains_chart` + `chart_hint`) and
saturated at F1=1.0 for every provider, which couldn't separate them on the
dimension that actually matters (per-point data fidelity). This run
exercises `VisionClient.analyze_image_targeted(task_type="chart_read")`
— the prod chart-extraction path — across the same 7-image corpus, scores
extracted values against `extracted_values.csv` rows where
`source_type="chart"`, and for the first time includes `two-stage`
(B4 routing) in the sweep.

**Scope of this run:** 6 provider configurations (`current`,
`openai-vnext`, `gemini-flash`, `gemini-pro`, `anthropic`, `two-stage`)
benchmarked via `scripts/benchmark_vision.py --bakeoff --mode chart-read`
against the same hand-picked 7-image corpus (3 Farfetch + 4 Slack).
Total real spend $0.34 under a $5 cap. Ran with
`LLM_CACHE_ENABLED=false` so every $ number reflects a real API call,
not a cache hit.

## TL;DR

Per-value data fidelity is a **tie** across the field in this corpus:
every provider scored P=0.111 / R=0.500 / F1=0.182 on the one image with
CSV-mapped ground truth. That's not a null result — it's a measurement
ceiling that the current 7-image corpus can't break through. Providers
DO separate on cost, latency, structural completeness, and reliability;
and the PR #142 default-provider decision (`gemini-flash`) no longer
has the cost margin it had on detection.

## Results

| Provider | Model | Detect F1 (from #142) | Chart-read F1 | Parse fail % | Data-P | Data-R | Data-F1 | Cost/image | 7-img total | Mean latency |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `current` | `gpt-4o` | 1.000 | 1.000 | 0% | 0.111 | 0.500 | 0.182 | **$0.00575** | $0.0402 | 3347 ms |
| `openai-vnext` | `gpt-4o-2024-11-20` | 1.000 | 1.000 | 0% | 0.111 | 0.500 | 0.182 | $0.00673 | $0.0471 | 3862 ms |
| `gemini-flash` | `gemini-2.5-flash-lite` | 1.000 | 1.000 | 0% | 0.111 | 0.500 | 0.182 | $0.00759 | $0.0531 | **2755 ms** |
| `gemini-pro` | `gemini-2.5-pro` | 1.000 | 0.923 | 14% | 0.111 | 0.500 | 0.182 | **$0.00411** | **$0.0288** | 12641 ms |
| `anthropic` | `claude-sonnet-4-6` | 1.000 | 1.000 | 0% | 0.111 | 0.500 | 0.182 | $0.01158 | $0.0810 | 6355 ms |
| `two-stage` | gemini-flash OCR → sonnet-4-6 | — | 0.923 | 14% | 0.111 | 0.500 | 0.182 | $0.01268 | $0.0887 | 6280 ms |

Detection F1 dropped for gemini-pro and two-stage because each hit one
parse failure (gemini-pro returned unparseable JSON on one image;
two-stage got a transient Gemini 503 on `slack-mdaa3`'s OCR pass). The
rest held at 1.000.

### Structural fidelity (where providers actually separate)

Which image fields did each provider populate? (7 images total.)

| Provider | title | axes labels | legend | annotation points | parse fails |
|---|---:|---:|---:|---:|---:|
| `current` | 5/7 | 2/7 | 2/7 | 6 | 0 |
| `openai-vnext` | 5/7 | 2/7 | 2/7 | 6 | 0 |
| `gemini-flash` | 4/7 | 2/7 | **6/7** | **7** | 0 |
| `gemini-pro` | 3/7 | 1/7 | 4/7 | 6 | 1 |
| `anthropic` | 4/7 | 2/7 | 5/7 | 6 | 0 |
| `two-stage` | 4/7 | 2/7 | 4/7 | 4 | 1 |

Gemini-flash wins on legend + annotations coverage (catches series names
on 6 / 7 charts vs 2 / 7 for GPT-4o). OpenAI providers win on title
recognition but leave more series unnamed. Axis labels are a weak spot
across the board (2 / 7 at best).

## Decision

**Provisional default for chart-read stays with the PR #142 winner,
`gemini-flash`, but the rationale changes**:

- Cost is no longer the dominant reason. On chart-read, `gemini-flash`
  ($0.0076/image) is **32% more expensive than `current` GPT-4o
  ($0.0058)** — the inverse of the detection ranking where it was 34%
  cheaper. The chart-read prompt is longer (both input and output
  tokens) and Gemini-flash-lite's output-token pricing erodes its
  input-side advantage.
- Latency is the dominant reason. `gemini-flash` is still the fastest
  at 2.8 s vs GPT-4o's 3.3 s — and it's ~5× faster than `gemini-pro`
  (12.6 s) and ~2× faster than Claude Sonnet (6.4 s). Chart extraction
  is already the slowest hop in the per-filing pipeline; keeping this
  budget tight matters more than shaving a fraction of a cent.
- Structural completeness is a secondary reason. `gemini-flash` produced
  legend / annotation content on more images (6 / 7 legend, 7 / 7 images
  with at least one annotation point) than any other provider.

**`two-stage` does NOT justify its cost today.** At $0.0127/image it is
the most expensive config by a small margin over `anthropic` ($0.0116),
and on this corpus its chart-read data F1 is identical to every other
provider's. The second Gemini call (OCR grounding) adds latency + a new
failure mode (503s) without visibly improving the premium reader's
output. Revisit this after corpus expansion — two-stage's thesis
(ground the premium model with fast OCR text) can't fail gracefully or
succeed meaningfully until there's enough value-level ground truth to
score it.

**`gemini-pro` is not a sensible default.** 7× slower than
`gemini-flash` on chart-read with no fidelity gain and one transient
parse failure.

## Caveats — why this decision is still provisional

1. **Ground-truth scarcity is the blocker.** Of 7 corpus images, only
   one (`Farfetch_Limited/g607688g09d00.jpg`) has value-level ground
   truth in `data/gold_standard/*/extracted_values.csv` — the two
   `cm_revenue_by_cohort` annotation rows (44.4, 55.6). The other 3
   Farfetch images have 0 chart rows in the CSV; Slack has 0 chart
   rows across the entire file. Every provider's data-value F1 of
   0.182 is the result of every provider correctly reading the 44%
   series label (matched to 44.4 within 2% tolerance) and missing the
   55.6 annotation — a near-identical output pattern. **With n = 2
   reference values scored on n = 1 image, data-value F1 cannot
   separate providers here.** That's a corpus problem, not a provider
   problem; the harness does score correctly once real signal arrives.

2. **Structural saturation too.** Title / axes / legend scoring is
   limited because the manifest tracks `reviewer_notes` (free-text
   reviewer comments) rather than per-image ground-truth titles and
   labels. The "is the title populated?" tally in the table above is
   the best we can do today; a proper title-match score needs
   hand-annotated per-image references.

3. **One transient 503 biased two-stage.** Gemini's Flash-Lite OCR pass
   hit a `503 UNAVAILABLE` on one image and propagated through as a
   parse failure. That's a real operational concern for two-stage in
   production (two upstream providers = union of their failure modes)
   but it's a single data point here — don't read too much into
   the 14% parse-failure rate.

4. **Order `BAKEOFF_PROVIDER_ORDER` vs `_ORDER_CHART_READ`.** This
   run uses the new `BAKEOFF_PROVIDER_ORDER_CHART_READ` constant which
   includes `two-stage`. The older detect-mode order (the one PR #142
   bakeoffs use) deliberately still excludes `two-stage` — running
   two-stage under `analyze_image_for_text` would burn spend without
   exercising B4 routing, since that method ignores
   `VISION_ROUTING_MODE`. The split is by design and the memo's
   comparison table handles it: `two-stage` has no detect-F1 number.

## Next steps

1. **Corpus expansion is the highest-leverage follow-up.** `data/gold_standard/`
   has 65 chart-source rows across 5 companies
   (Farfetch + Maplebear, Robinhood, Samsara, Torrid) but JPGs only for
   Farfetch + Slack. Populating the JPG fixtures from the corresponding
   filings' images, plus adding `ground_truth_value_ids` mappings on
   the manifest entries, would turn data-value F1 into a real signal
   overnight.

2. **`v2_image_review_decisions` hydration.** Once the test DB has
   review rows, re-run `scripts/benchmark_vision.py --build-corpus`
   to get the stratified multi-hundred-image manifest. The
   `_load_chart_ground_truth` helper already derives CSV lookups from
   `storage_key`; every reviewed image mapped to a filing with
   gold-standard chart rows becomes scorable.

3. **Per-image title / axis-label ground truth in the manifest.**
   A modest hand-curation pass on 7 images (pull the title, x-axis
   label, y-axis label, legend list into each manifest entry) would
   let us replace the "reviewer_notes-proxy" scoring in `image_eval.py`
   with real string-accuracy numbers.

4. **Defer `B5.4 shadow + canary`** until data-value separation
   actually exists. Shadowing a chart-read provider on 50 reviewed
   filings is meaningful only if we can measure whether its output
   differs from prod on the dimensions users care about.

## Reproducing this bake-off

```bash
# Prerequisites:
#   .env has OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY
#   pip install google-genai
#
# From the repo root (or any worktree):
LLM_CACHE_ENABLED=false MAX_BAKEOFF_USD=5.0 \
    python3 scripts/benchmark_vision.py --bakeoff --mode chart-read

# Per-provider JSONs land in data/image_benchmarks/bakeoff_chart_read_<date>/<provider>.json
# Summary lands in                      data/image_benchmarks/bakeoff_chart_read_<date>/summary.json
# (both gitignored — regenerate on demand)

# Single-provider smoke (cheap):
LLM_CACHE_ENABLED=false python3 scripts/benchmark_vision.py \
    --provider gemini-flash --mode chart-read --limit 1

# Two-stage end-to-end (exercises B4 routing):
LLM_CACHE_ENABLED=false python3 scripts/benchmark_vision.py \
    --provider two-stage --mode chart-read --limit 1
```

Total cost: $0.34 per full 6-provider sweep. Cap is $5 so margin is
roughly 15×.

## Appendix — raw cost + latency (chart-read mode)

7 real API calls per single-provider config (2× that for `two-stage`,
which makes both an OCR grounding call and a chart-read call per image).

| Provider | $ / image | 7-img total | Latency (ms) |
|---|---:|---:|---:|
| current | 0.00575 | 0.04023 | 3347 |
| openai-vnext | 0.00673 | 0.04713 | 3862 |
| gemini-flash | 0.00759 | 0.05313 | 2755 |
| gemini-pro | 0.00411 | 0.02880 | 12641 |
| anthropic | 0.01158 | 0.08104 | 6355 |
| two-stage | 0.01268 | 0.08873 | 6280 |
| **Total** | — | **$0.33907** | — |

## Detection vs chart-read cost inflation

| Provider | Detect $/img | Chart-read $/img | Ratio |
|---|---:|---:|---:|
| current | 0.00330 | 0.00575 | 1.74× |
| openai-vnext | 0.00341 | 0.00673 | 1.97× |
| gemini-flash | 0.00218 | 0.00759 | 3.48× |
| gemini-pro | 0.00200 | 0.00411 | 2.06× |
| anthropic | 0.00572 | 0.01158 | 2.03× |

`gemini-flash` takes the biggest cost hit going from detection to
chart-read (3.48× vs ~2× for everyone else). This is what flipped the
PR #142 winner ranking and is worth re-checking if Google changes
Flash-Lite pricing.
