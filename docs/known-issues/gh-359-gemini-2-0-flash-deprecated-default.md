---
id: 359
source: gh
slug: gemini-2-0-flash-deprecated-default
title: Default gemini-2.0-flash model deprecated for new Gemini API accounts
status: open
severity: medium
autonomy: skip
estimated: —
touches:
  - src/extraction_v2/pipeline.py
  - .env.template
discovered: 2026-04-29
updated: 2026-04-29
gh_issue: 359
note: change vision_full_page_ocr_model and vision_prescan_model defaults to a non-deprecated Gemini model
---

### Problem

The PR 2 triage-OCR defaults (`vision_full_page_ocr_model`, `vision_prescan_model`) are set to `gemini-2.0-flash`. During unit testing, this model returned `404 NOT_FOUND: "no longer available to new users"` when a newer Gemini API account was used. Production appears unaffected (legacy account key), but any contributor onboarding with a new API key will see silent extraction failures on the full-page-scan and prescan sites.

### Next Steps

- Evaluate `gemini-2.0-flash-lite` or `gemini-2.5-flash-lite` as replacement defaults
- Update `PipelineConfig` defaults and `.env.template` once a stable model is confirmed
- Consider a startup-time model availability check or graceful fallback in `_build_cheap_ocr_client`
