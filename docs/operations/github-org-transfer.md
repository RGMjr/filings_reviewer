# GitHub Organization Transfer — When & How

**Status:** decision record + migration runbook
**Last Updated:** 2026-04-21

Today `RGMjr/filings_reviewer` is a user-owned public repo. Several GitHub features are gated to organization-owned repos; this doc captures what we'd unlock by transferring, when it becomes worth the cost, and how to do it safely without breaking clones/CI/Render.

Start here when:
- You're tempted to re-propose GitHub merge queue (you can't, the repo is user-owned — verified 2026-04-21).
- Someone asks about required reviewers, teams, or org-level rulesets.
- Another human is joining the project and permissions need more than "collaborator."

---

## What you'd unlock

Listed in rough order of current usefulness:

1. **GitHub Merge Queue.** Batches and serializes merges atop a synthetic `merge_group` ref, removing the stale-base rebase treadmill entirely. We have the CI concurrency block already (`.github/workflows/ci.yml`), but `strict: false` is our current mitigation instead of a queue. Org migration makes the queue reachable.
2. **Organization rulesets** (apply to all repos in the org, not just one). Useful if we ever spin off `filings-reviewer-core`, `filings-reviewer-ui`, etc.
3. **Required reviewers / CODEOWNERS with teams.** Personal repos can require reviews, but team-based assignment is org-only.
4. **Secrets + variables at org level.** Shared `FILINGS_API_KEY`, Render deploy hooks, etc. can be org-scoped instead of per-repo.
5. **Fine-grained permissions.** Collaborators on a user repo get push or no-push. Orgs allow triage, maintain, admin separation.
6. **GitHub Projects (v2) at org level** for cross-repo tracking, if the initiative outgrows one repo.

What you don't unlock (worth checking): private-repo merge queue needs GitHub Team plan (paid); a free org is sufficient for public-repo merge queue.

---

## Trigger conditions

Migrate when **any** of these become true — not just "it would be nice to have":

- Concurrent-PR logjam returns despite `strict: false`. If CI wall-time grows (e.g., integration tests double) or session count climbs and we start seeing semantic conflicts land that a queue would have caught, the queue is worth the transfer.
- A second human joins as a regular contributor. Team permissions + required reviews start mattering.
- We spin off a second repo (core vs. UI vs. ingestion) and want shared org-level secrets/rulesets.
- Any paid plan is already on the user account for another reason — org plans are orthogonal but may simplify billing.

Do **not** migrate just for: aesthetics, "orgs look more professional," future optionality with no concrete trigger. GitHub auto-redirects keep old URLs working, but re-configuring secrets + Render + CI + remotes is non-zero work.

---

## Migration steps

GitHub's own runbook: <https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository>

High-level sequence:

1. **Create the target organization** on GitHub (free tier is fine for public repos). Choose a slug — `cmasb`, `customer-metrics`, etc. Irreversible-ish (orgs can be renamed but it's a paper cut).
2. **Inventory repo-level configuration** before transfer:
   - Branch protection on `main` (current: `strict: false`, 5 required contexts, `enforce_admins: true`). Capture via `gh api /repos/RGMjr/filings_reviewer/branches/main/protection > /tmp/protection-backup.json`.
   - Rulesets (current: "Base rules" with `deletion` + `non_fast_forward`). Capture via `gh api /repos/RGMjr/filings_reviewer/rulesets`.
   - Secrets. List with `gh secret list --repo RGMjr/filings_reviewer`. Values are not extractable — you'll re-add them by hand post-transfer.
   - Webhooks. `gh api /repos/RGMjr/filings_reviewer/hooks`. Render deploy hook is the important one.
   - Deploy keys, if any.
3. **Transfer the repo** via GitHub UI (Settings → General → Transfer ownership) or `gh api --method POST /repos/RGMjr/filings_reviewer/transfer -f new_owner=<org-slug>`. GitHub auto-creates a permanent redirect from `RGMjr/filings_reviewer/*` to `<org>/filings_reviewer/*` — clones, PR URLs, and API calls keep working without change.
4. **Re-apply repo config** (branch protection does NOT auto-transfer in all cases; Rulesets usually do but verify):
   - PUT the `/branches/main/protection` payload from step 2 to the new URL.
   - Recreate secrets from `.env` or password manager (values are not exportable).
   - Re-add the Render deploy webhook (from step 2 inventory).
5. **Update local clones** — `git remote set-url origin git@github.com:<org>/filings_reviewer.git` on every worktree. GitHub also keeps the old URL working via redirect, but updating is clean.
6. **Update Render** — the Render service has a `repo` field pointing at `RGMjr/filings_reviewer`. Change it to the org URL in the Render dashboard. The `render.yaml` doesn't hardcode it but dashboard config does. Re-verify the deploy webhook fires.
7. **Run a smoke PR** — small docs-only PR through `/commit`. Confirms CI still runs, auto-merge still works, Render deploy webhook still fires.

---

## Post-transfer: re-enable merge queue

Once transferred, flip the items this repo deliberately backed out of:

1. **Re-add `merge_group:` trigger to `.github/workflows/ci.yml`:**
   ```yaml
   on:
     push:
       branches: [main]
     pull_request:
     merge_group:
   ```
2. **Create the merge queue ruleset** (via UI: Rules → Rulesets → New → add Merge queue rule; or via API — the Rulesets API accepts `merge_queue` rules for org-owned repos). Starter tunables per earlier plan: Squash method, min group 1, max group 5, min wait 0 min, max wait 5 min, grace period 5 min.
3. **Flip `strict` back on or leave off** — either works with a queue. `strict: true` becomes redundant (queue owns up-to-date-with-main); leaving `strict: false` saves one API round-trip on merge.
4. **Update `docs/operations/ci-branch-protection.md`** — the "Why not a merge queue?" section is now obsolete; replace with a merge-queue runbook.
5. **Update this file** to mark the migration complete, leave the historical context.

Memory entry to update after migration: `~/.claude/projects/.../memory/feedback_merge_queue_personal.md` — change "don't propose merge queue on this repo" to "queue is live; re-propose when stale-branch issues surface."

---

## Rollback / don't-do-this

- Transferring **back** to a personal account works (same `gh api transfer` call in reverse) but loses any org-only configuration you added. Expect to re-do step 4 of the migration in the reverse direction.
- Don't delete the user repo before transfer — use GitHub's transfer flow, which preserves history + redirects.
- Don't transfer without verifying Render integration after. A broken deploy webhook is silent until the next push doesn't deploy.

---

## References

- GitHub's transfer docs: <https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository>
- Merge queue availability matrix: [docs.github.com merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
- Current branch protection verification: `gh api /repos/RGMjr/filings_reviewer/branches/main/protection --jq '{strict: .required_status_checks.strict, enforce_admins: .enforce_admins.enabled}'`
- Memory context: `~/.claude/projects/.../memory/feedback_merge_queue_personal.md`
- Related: `docs/operations/ci-branch-protection.md` § "Why not a merge queue?"
