# 12 - RWLO Execution Instructions (Mandatory)

## Purpose
Define one execution protocol for all contributors to guarantee engineering rigor and consistent handoff quality.

## Loop Definitions
1. Loop R (Recon): confirm current behavior, interfaces, dependencies, and risk boundaries.
2. Loop W (Write): implement the smallest safe vertical slice.
3. Loop L (Lock): add tests, assertions, and acceptance evidence.
4. Loop O (Operate): validate rollout, observability, and rollback readiness.

## Required Workflow
1. Read assigned workstream spec and this protocol.
2. Open a branch named `codex/<ws-id>-<short-desc>`.
3. Produce a short design note before coding.
4. Execute RWLO loops in order.
5. Submit PR with required sections and evidence links.

## Loop R Checklist
1. Confirm in-scope and out-of-scope boundaries.
2. Confirm touched contracts and backward compatibility expectations.
3. Confirm dependencies with other workstreams.
4. Confirm acceptance criteria are directly testable.

## Loop W Checklist
1. Implement minimal working path first.
2. Prefer additive changes before removals.
3. Keep error messages and logs actionable.
4. Avoid hidden behavior changes outside the workstream scope.

## Loop L Checklist
1. Add or update unit tests.
2. Add or update integration tests where required.
3. Add performance/reliability tests when the workstream calls for it.
4. Verify each acceptance criterion with a specific artifact.

## Loop O Checklist
1. Add feature flags for medium/high-risk behavior changes.
2. Add operational metrics/logging for changed runtime paths.
3. Document rollout steps and rollback steps.
4. Provide post-deploy verification commands.

## Required PR Sections
1. Workstream ID and objective.
2. Scope implemented and explicit out-of-scope list.
3. Acceptance criteria checklist with evidence links.
4. Test commands and summarized results.
5. Risk analysis and rollback instructions.
6. Follow-up tasks and deferred items.

## Parallel Development Rules
1. Do not modify another engineer's assigned core files without coordination.
2. Use interface-first agreements for shared modules.
3. Escalate blockers quickly; do not silently work around contract conflicts.

## Stop-Ship Conditions
1. Missing acceptance evidence.
2. Required tests skipped or failing without approved waiver.
3. Missing rollback plan for medium/high-risk change.
4. Security regression (for example query-key auth leakage, missing CSRF on browser paths).
