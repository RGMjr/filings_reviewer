#!/usr/bin/env bash
# run_nightly_sweep.sh — orchestrator for the nightly KNOWN_ISSUES sweeper.
#
# Flow:
#   1. Honor SWEEP_FORCE env-var gate (must be "1" to proceed).
#   2. Fetch latest main, check out.
#   3. Call scripts/known_issues_selector.py for up to N picks.
#   4. For each pick: create a worktree, invoke `claude -p` with an issue-scoped
#      prompt that runs /commit, capture outcome, classify.
#   5. Emit run-outcomes JSON, invoke scripts/write_sweep_digest.py.
#   6. Open a PR for the digest (docs-only, not via /commit).
#   7. Clean up worktrees that produced no commits; delete stale branches.
#
# Environment:
#   SWEEP_FORCE          REQUIRED: must be "1" or the script exits 0 immediately.
#                        Set on Render `filings-nightly-sweep` via env group
#                        `filings-claude-secrets`. Local manual /sweep runs
#                        must invoke as `SWEEP_FORCE=1 bash scripts/...`.
#   SWEEP_MAX            max picks per run (default: 3)
#   SWEEP_INCLUDE_REVIEW if set to 1, include Autonomy=review (default: 0)
#   SWEEP_WALL_BUDGET    total wall-clock budget in seconds (default: 2700 = 45m)
#   SWEEP_PER_ISSUE      per-issue budget in seconds (default: 900 = 15m)
#   ANTHROPIC_API_KEY    required by `claude`
#   GH_TOKEN             required by `gh` (or prior `gh auth login`)
#
# Exits:
#   0 — ran to completion (including empty picks / SWEEP_FORCE not set)
#   1 — fatal prerequisite missing (git, claude, gh, or selector failure)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MAX_PICKS="${SWEEP_MAX:-3}"
INCLUDE_REVIEW="${SWEEP_INCLUDE_REVIEW:-0}"
WALL_BUDGET="${SWEEP_WALL_BUDGET:-2700}"
PER_ISSUE_BUDGET="${SWEEP_PER_ISSUE:-900}"
DATE="$(date +%Y-%m-%d)"
RUN_START_EPOCH="$(date +%s)"
RUN_START_HHMM="$(date +%H:%M)"

WORKTREE_ROOT="$REPO_ROOT/.claude/worktrees"
DIGEST_DIR="$REPO_ROOT/.claude/sweep-digests"
OUTCOMES_FILE="$(mktemp -t sweep-outcomes.XXXXXX.json)"
echo "[]" > "$OUTCOMES_FILE"

log() { printf '[sweep %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

require() {
  command -v "$1" >/dev/null 2>&1 || { log "FATAL: $1 not installed"; exit 1; }
}

cleanup() {
  rm -f "$OUTCOMES_FILE"
}
trap cleanup EXIT

# --- 1. Kill switch ---
# SWEEP_FORCE is the authoritative gate. On Render, it lives in env group
# `filings-claude-secrets`; unset (or set to anything other than "1") to pause.
# Local manual /sweep runs must invoke as `SWEEP_FORCE=1 bash scripts/...`.
if [[ "${SWEEP_FORCE:-0}" != "1" ]]; then
  log "SWEEP_FORCE not set to 1 — sweeper disabled. Exiting."
  exit 0
fi

# --- 2. Prereqs + fresh main ---
require git
require python3
require claude
require gh

# Detect timeout command. GNU coreutils `timeout` is standard on Linux; macOS
# ships without it. Install via `brew install coreutils` to get `gtimeout`.
if command -v timeout >/dev/null 2>&1; then
  _TIMEOUT_CMD="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  _TIMEOUT_CMD="gtimeout"
else
  _TIMEOUT_CMD=""
  log "WARNING: neither 'timeout' nor 'gtimeout' found — per-issue budget enforcement disabled (macOS: run 'brew install coreutils' to enable)"
fi

# Container images built from this repo strip .git via .dockerignore to keep
# the web/extraction images lean. The sweeper orchestrator needs real git
# history (fetch, checkout, worktree add, push), so bootstrap a minimal repo
# from origin when running inside a stripped image. Local /sweep invocations
# already have .git and skip this branch.
_BOOTSTRAPPED=0
if [[ ! -d .git ]]; then
  if [[ -z "${GH_TOKEN:-}" ]]; then
    log "FATAL: GH_TOKEN required to bootstrap .git from origin"
    exit 1
  fi
  log "No .git found — initializing repo from origin..."
  git init --quiet
  git remote add origin "https://github.com/RGMjr/filings_reviewer.git"
  _BOOTSTRAPPED=1
fi

# Let gh front github.com auth for git so tokens stay out of .git/config.
# Idempotent; safe to run on every invocation.
gh auth setup-git 2>/dev/null || { log "FATAL: gh auth setup-git failed (GH_TOKEN invalid?)"; exit 1; }

# Commit author identity is required downstream — the per-issue Claude session
# runs /commit, which calls `git commit`, which aborts without user.email/name.
git config --global user.email "${GIT_AUTHOR_EMAIL:-sweeper@users.noreply.github.com}"
git config --global user.name  "${GIT_AUTHOR_NAME:-Nightly Sweeper}"

log "Fetching origin/main..."
git fetch origin main --quiet

if [[ "$_BOOTSTRAPPED" == "1" ]]; then
  # After a fresh `git init`, every file in /app (populated by the Dockerfile's
  # `COPY . .`) is untracked. `git checkout main` would refuse to overwrite
  # those paths. Wipe the untracked tree first, then materialize origin/main.
  # The running bash process keeps executing from its in-memory script copy
  # even after `scripts/run_nightly_sweep.sh` is removed and recreated.
  log "Reconciling COPY'd tree with origin/main..."
  git clean -fdx --quiet
  git checkout -B main origin/main --quiet
else
  git checkout main --quiet 2>/dev/null || git checkout -B main origin/main --quiet
  git reset --hard origin/main --quiet
fi

# --- 2b. Sync fragment status from merged PRs ---
log "Syncing fragment status from merged pr_refs..."
python3 scripts/sync_known_issue_status.py --verbose \
  || log "WARNING: sync_known_issue_status.py failed (exit $?) — continuing anyway"

# --- 3. Selector ---
INCLUDE_REVIEW_FLAG=""
[[ "$INCLUDE_REVIEW" == "1" ]] && INCLUDE_REVIEW_FLAG="--include-review"

log "Running selector (max=$MAX_PICKS, include_review=$INCLUDE_REVIEW)..."
PICKS_JSON="$(python3 scripts/known_issues_selector.py \
    --max "$MAX_PICKS" $INCLUDE_REVIEW_FLAG)"
NUM_PICKS="$(echo "$PICKS_JSON" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
log "Selector returned $NUM_PICKS picks."

if [[ "$NUM_PICKS" == "0" ]]; then
  log "Nothing to sweep tonight."
  echo "[]" > "$OUTCOMES_FILE"
fi

# --- 4. Per-issue sweep loop ---
append_outcome() {
  # $1: JSON object for one outcome
  python3 - "$OUTCOMES_FILE" "$1" <<'PY'
import json, sys
path, new = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
data.append(json.loads(new))
with open(path, "w") as f:
    json.dump(data, f)
PY
}

sweep_issue() {
  local issue="$1" autonomy="$2" note="$3"
  local branch="claude/sweep/issue-${issue}-${DATE}"
  local worktree="$WORKTREE_ROOT/sweep-${DATE}-issue-${issue}"
  local started="$(date +%H:%M)"

  log "Issue #$issue [$autonomy] — creating worktree $worktree"

  if ! git worktree add -b "$branch" "$worktree" origin/main --quiet 2>/dev/null; then
    append_outcome "$(python3 -c "import json; print(json.dumps({'issue': $issue, 'autonomy': '$autonomy', 'outcome': 'abandoned', 'reason': 'worktree create failed (branch may already exist)'}))")"
    return
  fi

  # Prompt briefs Claude on the issue, restricts scope, calls /commit.
  local prompt
  prompt=$(cat <<EOF
You are the nightly autonomous sweeper working issue #${issue}.

Classification: Autonomy=${autonomy}. Note: "${note}".

Rules (STRICT):
1. Find the fragment file for issue #${issue} under docs/known-issues/ (filename prefix is either legacy- or gh-, e.g. legacy-${issue}-*.md or gh-${issue}-*.md) and read it in full. Do exactly what its "Next Steps" section asks, no more.
2. If the issue requires schema migrations, infra edits, credential changes, or anything outside the "Touches" globs declared in the classification table: ABORT and explain.
3. After implementing, invoke the /commit skill. The skill handles branch/tests/PR/auto-merge.
4. If tests fail or you cannot complete the work cleanly, abort. Do NOT update baselines, do NOT skip tests, do NOT use --no-verify.
5. On successful /commit, report the PR URL on stdout as: "PR_URL=<url>".
6. On abort, report the reason on stdout as: "ABORT_REASON=<short reason>".

Begin.
EOF
)

  local log_file="$worktree/.sweep.log"
  local exit_code=0
  # </dev/null is load-bearing: this function is called from inside a
  # `picks | while read` pipeline, so the subshell inherits the pick stream
  # on stdin. Without the redirect, `claude -p` (or `timeout` forwarding to
  # it) reads the remaining pick lines from the pipe on its first call,
  # which drains the iterator and makes the while-loop exit after pick 1
  # of N. Reproduced locally with `(cat)` in place of claude.
  # --dangerously-skip-permissions: the sweeper runs unattended (no human to
  # answer permission prompts), and the session is already scoped by the issue
  # prompt's STRICT rules and by the Nightly Sweeper Classification "Touches"
  # globs. Without this, `gh pr create` / `git push` get blocked by
  # .claude/settings.json's default allow list and the session ends with a
  # committed-but-unpushed branch (or pushed-but-no-PR), as observed on the
  # 2026-04-22 17:50 UTC run where issues #68 and #71 were fixed correctly
  # but their PRs had to be opened manually. The kill switch + classification
  # table + prompt rules + CI checks remain the primary guardrails.
  (
    cd "$worktree"
    if [[ -n "$_TIMEOUT_CMD" ]]; then
      "$_TIMEOUT_CMD" "$PER_ISSUE_BUDGET" claude -p --dangerously-skip-permissions "$prompt" > "$log_file" 2>&1
    else
      claude -p --dangerously-skip-permissions "$prompt" > "$log_file" 2>&1
    fi
  ) </dev/null || exit_code=$?

  local finished="$(date +%H:%M)"
  local pr_url="" pr_number="" abort_reason=""
  if grep -qE '^PR_URL=' "$log_file" 2>/dev/null; then
    pr_url="$(grep -E '^PR_URL=' "$log_file" | tail -1 | sed 's/^PR_URL=//')"
    pr_number="$(echo "$pr_url" | grep -oE '[0-9]+$' || true)"
  fi
  if grep -qE '^ABORT_REASON=' "$log_file" 2>/dev/null; then
    abort_reason="$(grep -E '^ABORT_REASON=' "$log_file" | tail -1 | sed 's/^ABORT_REASON=//')"
  fi

  local outcome_json
  if [[ -n "$pr_url" && "$autonomy" == "safe" ]]; then
    outcome_json=$(python3 -c "import json; print(json.dumps({'issue': $issue, 'autonomy': '$autonomy', 'outcome': 'opened', 'pr_number': int('$pr_number' or 0), 'pr_url': '$pr_url', 'branch': '$branch', 'started_at': '$started', 'finished_at': '$finished'}))")
  elif [[ -n "$pr_url" && "$autonomy" == "review" ]]; then
    outcome_json=$(python3 -c "import json; print(json.dumps({'issue': $issue, 'autonomy': '$autonomy', 'outcome': 'awaiting_review', 'pr_number': int('$pr_number' or 0), 'pr_url': '$pr_url', 'branch': '$branch', 'started_at': '$started', 'finished_at': '$finished', 'reason': 'Autonomy=review — manual approval required'}))")
  else
    local reason="${abort_reason:-claude session exited $exit_code without a PR}"
    outcome_json=$(python3 -c "import json; print(json.dumps({'issue': $issue, 'autonomy': '$autonomy', 'outcome': 'abandoned', 'reason': '$reason', 'started_at': '$started', 'finished_at': '$finished'}))")
  fi
  append_outcome "$outcome_json"

  # Cleanup worktree + branch if no PR was opened.
  if [[ -z "$pr_url" ]]; then
    log "Issue #$issue produced no PR — cleaning up worktree and branch."
    git worktree remove --force "$worktree" >/dev/null 2>&1 || true
    git branch -D "$branch" >/dev/null 2>&1 || true
  else
    # Worktree served its purpose; branch is on origin now. Remove worktree dir,
    # keep the local branch reference (PR is the source of truth).
    git worktree remove --force "$worktree" >/dev/null 2>&1 || true
  fi
}

if [[ "$NUM_PICKS" != "0" ]]; then
  echo "$PICKS_JSON" | python3 -c '
import json, sys
picks = json.load(sys.stdin)
for p in picks:
    issue = p["issue"]
    autonomy = p["autonomy"]
    note = (p.get("note") or "").replace("\x27", " ")
    print(f"{issue}\t{autonomy}\t{note}")
' | while IFS=$'\t' read -r issue autonomy note; do
    elapsed=$(($(date +%s) - RUN_START_EPOCH))
    if [[ $elapsed -gt $WALL_BUDGET ]]; then
      log "Wall budget ($WALL_BUDGET s) exceeded — stopping before issue #$issue."
      append_outcome "$(python3 -c "import json; print(json.dumps({'issue': $issue, 'autonomy': '$autonomy', 'outcome': 'abandoned', 'reason': 'wall budget exceeded before start'}))")"
      continue
    fi
    sweep_issue "$issue" "$autonomy" "$note"
  done
fi

# --- 5. Digest ---
FINISHED_EPOCH="$(date +%s)"
DURATION_SEC=$((FINISHED_EPOCH - RUN_START_EPOCH))
DURATION_MIN=$((DURATION_SEC / 60))
log "Writing digest for $DATE ($DURATION_MIN m)."

python3 scripts/write_sweep_digest.py \
  --date "$DATE" \
  --input "$OUTCOMES_FILE" \
  --run-start "$RUN_START_HHMM" \
  --run-duration "${DURATION_MIN}m"

# --- 6. PR the digest (docs-only, minimal flow) ---
DIGEST_PATH="$DIGEST_DIR/$DATE.md"
if [[ -f "$DIGEST_PATH" ]]; then
  DIGEST_BRANCH="claude/sweep-digest/$DATE"
  if git checkout -b "$DIGEST_BRANCH" --quiet 2>/dev/null; then
    git add "$DIGEST_PATH"
    git commit -m "docs(sweep-digest): nightly digest for $DATE" --quiet || true
    if git push -u origin "$DIGEST_BRANCH" --quiet; then
      # Put the full digest in the PR body so GitHub's "PR opened" notification
      # email carries the merged / awaiting / abandoned summary directly.
      # Requires repo notification setting "All Activity" (not @mentions only).
      gh pr create \
        --title "docs(sweep-digest): nightly digest for $DATE" \
        --body-file "$DIGEST_PATH" >/dev/null \
        || log "digest PR create failed (may already exist)"
      gh pr merge --auto --squash >/dev/null || log "digest auto-merge enable failed"
      # If main advanced while the sweep was running, the digest branch may be
      # DIRTY before CI even starts. Poll once and merge main in to unblock.
      sleep 5
      _DIGEST_PR_NUM="$(gh pr view --head "$DIGEST_BRANCH" --json number --jq '.number' 2>/dev/null || echo "")"
      if [[ -n "$_DIGEST_PR_NUM" ]]; then
        _DIGEST_MERGE_STATUS="$(gh pr view "$_DIGEST_PR_NUM" --json mergeStateStatus --jq '.mergeStateStatus' 2>/dev/null || echo "UNKNOWN")"
        if [[ "$_DIGEST_MERGE_STATUS" == "DIRTY" ]]; then
          log "Digest PR #$_DIGEST_PR_NUM is DIRTY — merging main in via update-branch."
          gh pr update-branch "$_DIGEST_PR_NUM" >/dev/null 2>&1 \
            || log "digest PR update-branch failed — manual resolution required"
        fi
      fi
    else
      log "digest push failed — leaving branch local"
    fi
  else
    log "digest branch $DIGEST_BRANCH already exists — skipping PR"
  fi
fi

log "Sweep complete. Outcomes: $(python3 -c 'import json, sys; d=json.load(open(sys.argv[1])); print(len([o for o in d if o["outcome"]=="opened"]), "opened,", len([o for o in d if o["outcome"]=="awaiting_review"]), "awaiting,", len([o for o in d if o["outcome"]=="abandoned"]), "abandoned")' "$OUTCOMES_FILE")"
