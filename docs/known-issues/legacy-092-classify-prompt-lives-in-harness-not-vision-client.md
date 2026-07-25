---
autonomy: n/a
discovered: '2026-04-23'
estimated: S
id: 92
severity: low
slug: classify-prompt-lives-in-harness-not-vision-client
source: legacy
status: archived
title: CLASSIFY_PROMPT Lives in Bake-off Harness — Move to VisionClient When Classify Lands in Prod
touches:
  - scripts/benchmark_vision.py
  - src/llm/vision_client.py
  - src/extraction_v2/stages/image_classify.py
updated: '2026-04-23'
---

**Resolved**: 2026-04-23 — see below.

### Resolution (2026-04-23)

Leg A of the tripod plan (PR #157) ported `CLASSIFY_PROMPT`,
`CLASSIFY_REJECTION_REASONS`, `_build_classify_prompt`, and
`_parse_classify_response` into `src/llm/vision_client.py`, exposed as
`VisionClient.analyze_image_for_metric_classification`. Leg B (this PR)
wires the new `ImageClassifyStage` to call that helper when
`ENABLE_METRIC_CLASSIFY=true`.

`scripts/benchmark_vision.py` still has its own copy of the prompt. The
harness branch will rebase onto main and import from vision_client as a
follow-up — tracked in the plan doc at `~/.claude/plans/let-s-tackle-known-issues-md-92-tidy-cake.md`,
not as a new KI (it's a branch-only cleanup).

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
