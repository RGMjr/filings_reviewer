You are working gh-441: enable the Vision-API metric classifier in prod by flipping `ENABLE_METRIC_CLASSIFY=true` in `render.yaml`. The stage is fully wired (`src/extraction_v2/stages/image_classify.py`), the bake-off model (`gemini-2.5-flash-lite`) is the confirmed default, and the gate has been held at `false` with a "Flip after smoke-test" comment that has outlasted its premise. Flip it after a brief local smoke test.

## Source of truth

- Fragment: `docs/known-issues/gh-441-enable-metric-classify-in-prod.md` (read fully from `origin/main` before planning).
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**.
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules".
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply.
- Related context (read for shape, do not modify):
  - `render.yaml` (lines around the `filings-extraction` cron service — the env var to flip)
  - `src/extraction_v2/stages/image_classify.py` (the wired stage)
  - `src/llm/vision_client.py::analyze_image_for_metric_classification` (the call site)
  - `src/extraction_v2/pipeline.py` (look around line 200 for the threshold and model defaults)
  - `.claude/rules/infrastructure.md` "Environment Variables" table for `ENABLE_METRIC_CLASSIFY` / `VISION_CLASSIFY_*` semantics
  - `tests/integration/extraction/test_image_classify*.py` if any exist (sibling pattern)

## Workflow

1. **Verify the gate is still off.** `grep -n "ENABLE_METRIC_CLASSIFY" render.yaml` — expect a single line with `value: "false"` and the "Flip to 'true' after smoke-test" comment. If it's already `"true"`, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

2. **Plan mode.** Use plan mode — touches infra (`render.yaml`) and is a deliberate behavior change in prod. Run `/plan-review` before exiting. The plan must include the **Documentation** step: the comment on line 63 should be updated post-flip to record the date and what was verified, and `.claude/rules/infrastructure.md` may need a one-line update if it currently describes the gate as off-by-default in prod.

3. **Worktree-first.** First step of implementation: `EnterWorktree gh-441-enable-metric-classify` (or `ccw gh-441-enable-metric-classify` from the shell).

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT:** confirm the bake-off winner (`gemini-2.5-flash-lite`) is still the default in `src/extraction_v2/pipeline.py` (look for `_VISION_CLASSIFY_MODEL_DEFAULT` or equivalent). Confirm `VisionClient.analyze_image_for_metric_classification` is reachable from the wired stage (the docstring may have a stale "no prod pipeline stage wires this yet" note — ignore it; verify the actual call graph).
   - **SCOPE CHECK:** the only render.yaml change is flipping the value of `ENABLE_METRIC_CLASSIFY` from `"false"` to `"true"` on the `filings-extraction` cron service. Do NOT also tune `VISION_CLASSIFY_THRESHOLD` (default 0.5 is fine for first flip; per `.claude/rules/infrastructure.md` it only affects the downstream `predicted_relevant` projection, not row writes). Do NOT touch other `VISION_*` env vars. Do NOT change the comment to remove the `(#92)` historical pointer — append to it instead.
   - **RULES COMPLIANCE:** `project_render_env_invisible_to_git_audit` — be aware that any env-group overrides on the Render dashboard could shadow what's in `render.yaml`. Confirm the value really takes effect by checking the Render dashboard env tab post-deploy, not just the YAML.
   - **RISK ASSESSMENT:** what could break:
     - Per-image cost: one Gemini Flash Lite call per chart/table_image. The default 50-filing-per-day batch with ~10 charts/tables each is bounded.
     - Latency: first-time call adds a small per-image overhead (typically sub-second). The cron-side runtime increase is bounded.
     - API quota: confirm `GEMINI_API_KEY` rate limits aren't a blocker for the expected per-batch volume.
     - Row volume: `v2_image_classifications` will go from empty to ~500 rows per nightly batch. Verify the table doesn't have any size constraints.
   - **MINIMAL PATH:** one YAML value change + a doc note + a smoke-test rehearsal. No code changes.

5. **Implementation:**

   **5a. Smoke test (do this first, before touching `render.yaml`).** From a worktree (so the test doesn't pollute the primary tree):
   ```bash
   docker compose up -d  # local Postgres on TEST_DATABASE_URL
   ENABLE_METRIC_CLASSIFY=true \
     VISION_CLASSIFY_PROVIDER=gemini \
     VISION_CLASSIFY_MODEL=gemini-2.5-flash-lite \
     GEMINI_API_KEY=<your-key> \
     DATABASE_URL="$TEST_DATABASE_URL" \
     python3 scripts/batch_v2_extraction.py --status fetched --limit 3
   ```
   Then query: `psql "$TEST_DATABASE_URL" -c "SELECT classification_id, predicted_metrics, confidence FROM v2_image_classifications ORDER BY created_at DESC LIMIT 10;"` — expect non-empty rows with valid metric IDs and 0.0 < confidence < 1.0 distribution.

   **5b. `render.yaml`** — flip the value, append to the comment:
   ```yaml
   - key: ENABLE_METRIC_CLASSIFY
     value: "true"  # Tripod Leg B (#92): Vision-API metric classify. Flipped 2026-MM-DD per gh-441 (smoke-tested).
   ```

   **5c. `.claude/rules/infrastructure.md`** — find the `ENABLE_METRIC_CLASSIFY` row in the env-vars table; update the description if it currently says "Default off" or similar. Just clarify that prod is now on; the dev default remains off.

6. **Verification** (post-merge, post-Render-deploy):
   - Wait for the next `filings-extraction` cron run (daily 6am UTC) OR trigger a manual extraction batch on Render.
   - Verify row count growth in `v2_image_classifications`:
     ```sql
     SELECT DATE(created_at), COUNT(*) FROM v2_image_classifications
       WHERE created_at > NOW() - INTERVAL '7 days' GROUP BY 1 ORDER BY 1;
     ```
   - Confirm no error spike in Render logs for `filings-extraction`.
   - Spot-check one filing: assets with `classification IN ('chart', 'table_image')` should now have a corresponding `v2_image_classifications` row.

7. **Commit + PR** via `/commit-proj`. The skill auto-branches, runs pre-commit framework, opens a PR, queues auto-merge. PR description should reference gh-441 and note the smoke-test result (rows/per-image cost). After merge: update the gh-441 fragment to `status: resolved` with `pr_refs: [<PR#>]` (per memory: list of ints, no `#` prefix).

## Notes for the implementer

- The bake-off note in `.claude/rules/infrastructure.md` says `gemini-2.5-flash-lite` is the 2026-04-23 winner. Don't second-guess the model selection in this PR — that's a future bake-off decision tracked separately.
- `VISION_CLASSIFY_THRESHOLD=0.5` is **not** a write filter; it's only used downstream when computing `predicted_relevant`. Don't change it as part of this PR; tune it later if the data warrants.
- Do not flip `USE_LEARNED_TRIAGE` in this PR — that's gh-442, blocked on gh-419, separate concern.
