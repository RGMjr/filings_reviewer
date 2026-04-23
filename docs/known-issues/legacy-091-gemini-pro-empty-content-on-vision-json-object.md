---
autonomy: n/a
discovered: '2026-04-23'
estimated: S
id: 91
severity: medium
slug: gemini-pro-empty-content-on-vision-json-object
source: legacy
status: open
title: gemini-pro Returns Empty Content on vision + response_format=json_object
touches:
  - src/llm/vision_client.py
  - scripts/benchmark_vision.py
updated: '2026-04-23'
---

### Problem

In the 2026-04-23 metric-classify bake-off
(`docs/operations/vision-bakeoff-metric-classify-2026-04-23.md`),
`gemini-pro` (`gemini-2.5-pro`) returned an empty `content` field
(`""`) for every one of the 7 images when called via
`VisionClient.analyze_image(image_bytes, prompt, response_format={"type":
"json_object"})`. This drove parse failure rate to 1.0, tag F1 to 0.0,
and auto-disposition to 0.0 for that provider. The same corpus + prompt
works cleanly on `gemini-2.5-flash-lite`, so the quirk is specific to
the Pro model path — likely the combination of vision input and the
JSON response-format hint.

Not reproducing on any other provider in `PROVIDER_CONFIGS`.

### Next Steps

- Reproduce with a minimal repro (one image, direct `google-genai`
  call) to confirm it's upstream behaviour and not something the
  vision adapter is stripping.
- If confirmed upstream: drop the JSON response-format hint for the
  Gemini Pro adapter path in `src/llm/vision_client.py` and parse
  free-text back into the four-field classify schema.
- Or route Pro through a non-JSON code path when the harness calls
  `analyze_image` so other downstream callers are unaffected.
- Until resolved, omit `gemini-pro` from the classify bake-off order
  (`BAKEOFF_PROVIDER_ORDER_METRIC_CLASSIFY`) — current ordering
  already excludes `two-stage` for a similar reason.
