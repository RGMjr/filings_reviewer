---
id: 445
source: gh
slug: image-triage-test-pollution-from-cache-dir
title: test_gate_on_but_model_absent_falls_back_to_heuristic fails under full pytest run due to data/image_model/_cache/ pollution
status: archived
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 445
pr_refs:
- 491
note: image-triage model-absent test passes in isolation but fails under full pytest -x -q because a sibling test leaves data/image_model/_cache/ populated; masks regression coverage on the model-absent fallback path
---

### Problem

`tests/unit/extraction_v2/test_image_triage.py::TestLearnedTriageGate::test_gate_on_but_model_absent_falls_back_to_heuristic` passes in isolation but fails as part of `pytest -x -q` with `assert 0.9157916871700323 is None`. After a full run, `data/image_model/_cache/` exists in the worktree as an untracked artifact, indicating an earlier test in the suite produces a cached model that the loader subsequently finds when this test expects "model absent."

Pre-existing on clean main (verified via `git stash` + rerun on `worktree-gh-426-export-retrain-sync`, no script changes applied). Surfaced during gh-426 implementation while running the full suite for `/commit-proj` step 7.

### Next Steps

- Identify which test in the suite creates / leaves behind `data/image_model/_cache/` (likely a retrain or score test).
- Either isolate that test's writes to `tmp_path` or have `test_gate_on_but_model_absent_falls_back_to_heuristic` monkeypatch the model-loader path to a guaranteed-empty location.
- Add a session-level fixture / autouse cleanup if the cache dir is intended to be writable in tests.

### Resolution

The root cause was `_MODEL_CACHE` — a module-scope dict in `src/shared/image_features.py` — persisting across test instances. An earlier test that loaded a real model artifact would populate this cache, defeating the "model absent" precondition. The fix (see also gh-456) adds a class-level `autouse=True` fixture (`reset_model_cache`) to `TestLearnedTriageGate` in `tests/unit/extraction_v2/test_image_triage.py` that calls `image_features._MODEL_CACHE.clear()` both before and after every test in the class — mirroring the pattern already in place on `TestTriageGateEagerLoadStatusLog` (commit `b165ae31`). No production code was modified.
