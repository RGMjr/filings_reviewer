# Wave B5 Vision Bake-off — 2026-04-23

**Status:** First iteration complete. Winner provisionally named. Deeper
evaluation deferred pending a larger corpus + a chart-data-extraction harness.

**Scope of this run:** Five vision provider configurations benchmarked via
`scripts/benchmark_vision.py --bakeoff` against a hand-picked 7-image corpus
(3 Farfetch S-1 charts + 4 Slack S-1 MD&A charts in `data/gold_standard/`).
Total spend $0.12 under a $15 cap. Numbers below are from a clean re-run with
`LLM_CACHE_ENABLED=false` so costs reflect real API calls, not cache hits.

## Results

| Provider | Model | Chart-detection F1 | Cost / image | 7-image total | Mean latency |
|---|---|---:|---:|---:|---:|
| `current` (baseline) | `gpt-4o` | 1.000 | $0.00330 | $0.0231 | 2907 ms |
| `openai-vnext` | `gpt-4o-2024-11-20` | 1.000 | $0.00341 | $0.0238 | 2111 ms |
| `gemini-flash` | `gemini-2.5-flash-lite` | 1.000 | **$0.00218** | **$0.0152** | **1590 ms** |
| `gemini-pro` | `gemini-2.5-pro` | 1.000 | $0.00200 | $0.0140 | 10897 ms |
| `anthropic` | `claude-sonnet-4-6` | 1.000 | $0.00572 | $0.0401 | 4115 ms |

All five providers achieve **P=R=F1=1.0** on chart detection. `parse_failure_rate`
is 0 across the board after the initial `google-genai` SDK install. No provider
was vetoed (cap untouched at $0.12 / $15).

## Decision

**Winner: `gemini-flash` (`gemini-2.5-flash-lite`).**

Rubric from the Wave B5 plan:

1. **Must-preserve** chart-fact F1 ≥ current prod → satisfied (1.000 vs 1.000).
2. **Maximize** cost reduction → gemini-flash is **34% cheaper** than current
   prod per image ($0.00218 vs $0.00330).
3. **Tiebreaker: latency** → gemini-flash is **45% faster** than current prod
   per image (1590 ms vs 2907 ms).
4. **Veto** any provider with `parse_failure_rate > 10%` → none vetoed.

Why not gemini-pro (slightly cheaper per image)? **7× slower** (10.9 s vs 1.6 s)
with no quality gain on this task. That latency bump materially hurts batch
throughput and user-facing extraction.

Why not anthropic? **2.6× more expensive** per image with no quality gain on
this task. Claude Sonnet 4.6 will still earn its keep as the premium
chart-reader in B4 two-stage mode (where reading accuracy matters more than
detection), but not as the default single-call provider.

Why not openai-vnext? Effectively the same cost + quality as current GPT-4o
on this task. No reason to migrate away from the stable prod model.

## Caveats — why this decision is provisional

1. **Task saturation.** All five providers score 1.0 on chart detection. The
   corpus is seven visually-unambiguous chart images where any modern vision
   model returns `contains_chart=true` trivially. This bake-off measured
   **detection + cost + latency**, not **extraction fidelity** (axis labels,
   title match, data values). Saturated metrics can't separate models on the
   dimension that actually matters for Tier-1 recall.

2. **Harness limitation: two-stage path not exercised.** The harness invokes
   `VisionClient.analyze_image_for_text()`, which does not route through
   `VisionClient.analyze_image_targeted()` — the only call site where
   `VISION_ROUTING_MODE=two_stage` fires. The `two-stage` provider config is
   therefore excluded from the default bake-off (`BAKEOFF_PROVIDER_ORDER` in
   `scripts/benchmark_vision.py`). Benchmarking B4's hybrid path is a follow-up
   that needs a harness mode exercising `analyze_image_targeted(task_type=
   "chart_read")`. The config is still registered in `PROVIDER_CONFIGS` so
   the follow-up harness can reuse it unchanged.

3. **Tiny corpus (n = 7).** Per-provider differences within a few images of
   each other are not statistically meaningful. Once the test DB has
   `v2_image_review_decisions` rows, re-run `--build-corpus` to get the
   stratified multi-hundred-image manifest `_stratify_corpus` was built for.

4. **`tier1_fact_recall` is zero everywhere.** `analyze_image_for_text`
   returns `contains_chart` + `chart_hint` + raw OCR text; it doesn't
   construct Tier-1 metric facts, so the eval module can't score
   `tier1_fact_recall`. Not a provider difference; a measurement gap.

## Next steps (not in this PR)

1. **B5.x: exercise `analyze_image_targeted`.** Add an alternate harness mode
   (e.g. `--mode chart-read`) that calls `analyze_image_targeted(task_type=
   "chart_read")` with a JSON-schema prompt, then scores per-point data
   fidelity against `extracted_values.csv` rows. This is where providers
   should actually differentiate.

2. **B5.x: expand the corpus.** Populate `v2_image_review_decisions` in the
   test DB (either via a replay script or by running the review UI locally
   against the gold-standard fixtures), then re-run
   `--build-corpus` to get a stratified corpus of tens-to-hundreds of images
   covering hard-OCR and non-chart decoys.

3. **B5.4: shadow + canary.** Once extraction-fidelity numbers separate
   providers, stand up shadow mode on ~50 reviewed filings (scratch-DB to
   respect the reviewed-filing guard), then canary 10% → 100% via the
   `VISION_PROVIDER` env var rolled out on Render.

## Reproducing this bake-off

```bash
# Prerequisites:
#   .env has OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY
#   pip install google-genai
#
# From the repo root (or any worktree):
LLM_CACHE_ENABLED=false MAX_BAKEOFF_USD=15.0 \
    python3 scripts/benchmark_vision.py --bakeoff

# Per-provider JSONs land in data/image_benchmarks/bakeoff_<date>/<provider>.json
# Summary lands in                      data/image_benchmarks/bakeoff_<date>/summary.json
# (both gitignored — regenerate on demand)
```

Total cost: under $0.15 per full-sweep run. Cap is $15 so margin is huge.

## Appendix — raw cost + latency numbers

7 real API calls per provider, no cache.

| Provider | $ / image | 7-img total | Latency (ms) |
|---|---:|---:|---:|
| current | 0.003296 | 0.023071 | 2907 |
| openai-vnext | 0.003405 | 0.023834 | 2111 |
| gemini-flash | 0.002183 | 0.015283 | 1590 |
| gemini-pro | 0.001997 | 0.013976 | 10897 |
| anthropic | 0.005716 | 0.040011 | 4115 |
| **Total** | — | **$0.116175** | — |
