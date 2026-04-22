#!/usr/bin/env bash
# run_nightly_sweep.sh — orchestrator for the nightly KNOWN_ISSUES sweeper.
#
# Flow:
#   1. Honor .claude/sweep.pause kill switch.
#   2. Fetch latest main, check out.
#   3. Call scripts/known_issues_selector.py for up to N picks.
#   4. For each pick: create a worktree, invoke `claude -p` with an issue-scoped
#      prompt that runs /commit, capture outcome, classify.
#   5. Emit run-outcomes JSON, invoke scripts/write_sweep_digest.py.
#   6. Open a PR for the digest (docs-only, not via /commit).
#   7. Clean up worktrees that produced no commits; delete stale branches.
#
# Environment:
#   SWEEP_MAX            max picks per run (default: 3)
#   SWEEP_INCLUDE_REVIEW if set to 1, include Autonomy=review (default: 0)
#   SWEEP_WALL_BUDGET    total wall-clock budget in seconds (default: 2700 = 45m)
#   SWEEP_PER_ISSUE      per-issue budget in seconds (default: 900 = 15m)
#   ANTHROPIC_API_KEY    required by `claude`
#   GH_TOKEN             required by `gh` (or prior `gh auth login`)
#
# Exits:
#   0 — ran to completion (including empty picks / paused)
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

PAUSE_FILE="$REPO_ROOT/.claude/sweep.pause"
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
if [[ -f "$PAUSE_FILE" ]]; then
  if [[ "${SWEEP_FORCE:-0}" == "1" ]]; then
    log "Kill switch active but SWEEP_FORCE=1 — proceeding anyway."
  else
    log "Kill switch active ($PAUSE_FILE exists). Exiting."
    exit 0
  fi
fi

# --- 2. Prereqs + fresh main ---
require git
require python3
require claude
require gh

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
You are the nightly autonomous sweeper working issue #${issue} from docs/KNOWN_ISSUES.md.

Classification: Autonomy=${autonomy}. Note: "${note}".

Rules (STRICT):
1. Read the full issue body for #${issue} in docs/KNOWN_ISSUES.md. Do exactly what its "Next Steps" section asks, no more.
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
  (
    cd "$worktree"
    timeout "$PER_ISSUE_BUDGET" claude -p "$prompt" > "$log_file" 2>&1
  ) || exit_code=$?

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
    outcome_json=$(python3 -c "import json; print(json.dumps({'issue': $issue, 'autonomy': '$autonomy', 'outcome': 'merged', 'pr_number': int('$pr_number' or 0), 'pr_url': '$pr_url', 'branch': '$branch', 'started_at': '$started', 'finished_at': '$finished'}))")
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
      gh pr create --fill >/dev/null || log "digest PR create failed (may already exist)"
      gh pr merge --auto --squash >/dev/null || log "digest auto-merge enable failed"
    else
      log "digest push failed — leaving branch local"
    fi
  else
    log "digest branch $DIGEST_BRANCH already exists — skipping PR"
  fi
fi

log "Sweep complete. Outcomes: $(python3 -c 'import json, sys; d=json.load(open(sys.argv[1])); print(len([o for o in d if o["outcome"]=="merged"])) , " merged,", len([o for o in d if o["outcome"]=="awaiting_review"]), "awaiting,", len([o for o in d if o["outcome"]=="abandoned"]), "abandoned"' "$OUTCOMES_FILE")"
