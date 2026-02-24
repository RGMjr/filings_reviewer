# 11 - Parallel Execution and Dependencies

## Objective
Maximize parallel execution while preserving correctness, merge stability, and release gating discipline.

## Workstream Dependency Summary
1. WS-01 blocks production cutover and test migration contract.
2. WS-02, WS-03, WS-04 can run in parallel; coordinate shared route touchpoints.
3. WS-08 is independent and should ship early.
4. WS-05 depends on WS-01 migration contract and coordinates with WS-06 persistence semantics.
5. WS-06 can start early but final validation aligns with WS-05 runner behavior.
6. WS-07 starts scaffolding early; final gate validation depends on outputs from WS-02/03/04/05/06/08.
7. WS-09 begins after interfaces stabilize from WS-01 through WS-08.
8. WS-10 can begin analysis early; final parity gate depends on stable WS-06 and WS-07 validation rails.

## Wave Plan
1. Wave 1 (parallel): WS-01, WS-02, WS-03, WS-04, WS-08, WS-10 (analysis phase only).
2. Wave 2 (parallel): WS-05, WS-06, WS-07 (foundational test updates), WS-10 (tuning phase).
3. Wave 3: WS-07 final CI gates, WS-10 final parity sign-off, WS-09 phased modularization.

## Merge Sequencing
1. Merge WS-08 as soon as tests pass.
2. Merge WS-01 before any migration-dependent docs/scripts are finalized.
3. Merge WS-02/03/04 with interface coordination checkpoints.
4. Merge WS-05 and WS-06 once staging dry-runs and throughput checks pass.
5. Merge WS-07 only after flaky/failing reliability tests are stabilized.
6. Merge WS-10 only with quality metrics evidence attached.
7. Merge WS-09 in smaller phased PRs after core readiness gates are stable.

## Required Coordination Cadence
1. Daily cross-workstream sync for shared modules (`src/web/routes/*`, `src/infra/db.py`, orchestration scripts).
2. Dependency blocker escalation within one business day.
3. Rebase against `main` during active overlap windows.

## Staffing Suggestion
1. Engineer A: WS-01.
2. Engineer B: WS-02.
3. Engineer C: WS-03.
4. Engineer D: WS-04.
5. Engineer E: WS-05.
6. Engineer F: WS-06.
7. Engineer G: WS-08 then WS-07.
8. Engineer H: WS-10 then WS-09.

## Completion Rule
No wave is considered complete until all wave-level acceptance checks pass and evidence artifacts are published.
