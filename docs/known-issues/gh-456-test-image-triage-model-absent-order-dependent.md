---
id: 456
source: gh
slug: test-image-triage-model-absent-order-dependent
title: "test_image_triage: TestLearnedTriageGate::test_gate_on_but_model_absent_falls_back_to_heuristic order-dependent on data/image_model/ filesystem state"
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 456
note: passes in isolation, fails in full-suite — earlier test leaves model files under data/image_model/ that defeat the "absent" precondition
---

### Problem

`tests/unit/extraction_v2/test_image_triage.py::TestLearnedTriageGate::test_gate_on_but_model_absent_falls_back_to_heuristic` passes in isolation but fails when run as part of the full unit suite. An earlier test appears to create files under `data/image_model/` (or equivalent) that defeat the "model absent" precondition this test asserts on.

### Next Steps

- Identify the earlier test that seeds `data/image_model/` and tighten its cleanup, OR
- Pin model-loading via `tmp_path` / `monkeypatch` so this test does not rely on the shared `data/image_model/` directory
