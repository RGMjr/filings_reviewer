---
id: 477
source: gh
slug: image-triage-env-vars-module-scope
title: image_triage.py reads USE_LEARNED_TRIAGE at module scope — env-var changes silently require worker restart
status: archived
severity: high
autonomy: review
estimated: S
touches:
  - src/extraction_v2/stages/image_triage.py
  - tests/unit/extraction_v2/test_image_triage.py
discovered: '2026-05-04'
updated: '2026-05-04'
gh_issue: 477
note: Refactored to per-call helpers `_use_learned_triage()` / `_learned_triage_min()`; env-var flips on long-running workers now take effect on the next request, no restart needed. Added regression test that constructs the stage with the env unset, flips `USE_LEARNED_TRIAGE=true`, and asserts the next triage call uses the learned gate.
---

### Problem

`src/extraction_v2/stages/image_triage.py:46` reads:

```python
_USE_LEARNED_TRIAGE = os.environ.get("USE_LEARNED_TRIAGE", "false").lower() == "true"
_LEARNED_TRIAGE_MIN = float(os.environ.get("LEARNED_TRIAGE_MIN", "0.4"))
```

Both are **module-level** assignments. They evaluate exactly once, at first import of the module. After that the values are baked into the worker process for its entire lifetime — env-var changes have no effect until the process restarts.

This created a hidden landmine when gh-469 (PR #471) added `USE_LEARNED_TRIAGE=true` to `filings-onboarding-runner` in `render.yaml`. Render *should* restart the worker on YAML changes, but a long-running worker process never re-imports the module, so the gate stays off silently.

Invisible to PR review (the YAML looks correct), invisible to operators (no log signal that the gate is off), invisible to monitoring (`v2_image_assets.predicted_relevance` is legitimately allowed to be NULL when the gate is intentionally off, so the absence isn't an alert).

Compare to `src/extraction_v2/pipeline.py:502`: `_env_truthy("ENABLE_METRIC_CLASSIFY")` is read inside `_setup_stages()`, which runs per-pipeline-instance per filing — restart-immune. The image_triage path needs the same pattern.

### Repro

2026-05-04 22:25 UTC: filing 1529 was re-extracted on the `filings-onboarding-runner` worker after gh-469 merged and `GOOGLE_API_KEY` was set. Text extraction produced 349 new `v2_segments` rows. The image stage upserted the existing `v2_image_assets` row but did NOT populate `predicted_relevance` — confirming the module-level gate was still `False` from the worker's original import.

### Next Steps

Two layered fixes:

1. **Refactor `image_triage.py` to read env vars per-call.** Move the `_USE_LEARNED_TRIAGE` / `_LEARNED_TRIAGE_MIN` reads into the gate site (around lines 600-640 where the gate fires). Match the `_env_truthy("ENABLE_METRIC_CLASSIFY")` pattern in `pipeline.py:502`. After this, env-var changes take effect on the next request, no restart needed.
2. **Document the trap** in `.claude/rules/infrastructure.md` env-vars table — until the refactor lands, operators must manually restart workers after any env-var change. The "Render auto-applies env vars" assumption is half-true.

### Test coverage

A new unit test should verify: monkeypatch `os.environ["USE_LEARNED_TRIAGE"] = "true"` AFTER import, then call the gate function, expect the gate to be active. Today's module-level pattern would fail this test (the value was already read at import); the refactor makes it pass.

### Same-shaped trap to scan for

Audit other module-level `os.environ.get(...)` reads in `src/extraction_v2/stages/` and `src/extraction_v2/pipeline.py`. Any that gate behavior should move to per-call. Quick pass:

```bash
grep -rn '^_[A-Z_]* = os\.environ' src/extraction_v2/
```

Out of scope here unless the audit finds something equally consequential — file separately if so.

### Verification

- Apply the refactor; in a worker shell, set `USE_LEARNED_TRIAGE=true`, trigger a filing through the pipeline, confirm `predicted_relevance IS NOT NULL`. Then set `=false`, trigger again, confirm new images get NULL. Both transitions should work without restarting the worker.
- After fix lands and worker redeploys: re-extract filing 1529 (`POST /ingest/batch/c0f070ce-e062-4724-8916-c31e05050087/reextract`), confirm the upserted `v2_image_assets` row gets `predicted_relevance` populated and a `v2_image_classifications` row appears.
