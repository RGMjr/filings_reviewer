---
autonomy: n/a
discovered: '2026-04-23'
estimated: S
id: 92
severity: low
slug: classify-prompt-lives-in-harness-not-vision-client
source: legacy
status: open
title: CLASSIFY_PROMPT Lives in Bake-off Harness — Move to VisionClient When Classify Lands in Prod
touches:
  - scripts/benchmark_vision.py
  - src/llm/vision_client.py
  - src/extraction_v2/stages/image_triage.py
updated: '2026-04-23'
---

### Problem

`CLASSIFY_PROMPT` (the per-image metric-disclosure classification
prompt) is defined inline in `scripts/benchmark_vision.py` rather than
in `src/llm/vision_client.py`. This was intentional for the 2026-04-23
bake-off (PR B5.x.1) — validating the approach before touching prod
routing. But if / when classify is adopted as a prod extraction gate,
two prompt copies will exist and will drift. The harness has a `TODO`
comment flagging the eventual home (next to the constant).

### Next Steps

- Promote `CLASSIFY_PROMPT` + `_build_classify_prompt` +
  `_parse_classify_response` into a new
  `VisionClient.analyze_image_for_metric_classification` helper
  (alongside the existing `analyze_image_for_text` / `_targeted`
  helpers).
- Update `scripts/benchmark_vision.py::_run_provider_metric_classify`
  to call the new helper instead of re-implementing the API wrapping +
  parsing.
- Coordinate with the full-page-OCR work (PRs #110 / #114 / #139)
  which owns `analyze_image_for_text` — the two helpers should share
  the `VisionClient` lifecycle and cache key style.
- Expected to land alongside the `v2_image_classifications`
  table/surface PR (tracked separately in
  `project_image_extraction_program.md` follow-up #2).
