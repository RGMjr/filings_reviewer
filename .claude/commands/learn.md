# Learn — Session Lesson Capture (project-local)

**Purpose:** Capture durable lessons from the current session into project memory, or audit existing memory for stale/redundant entries. Memory shapes how Claude works on this project — entries that are wrong, vague, or duplicative actively degrade future sessions, so this skill treats both *adding* and *pruning* as first-class operations.

**When to use:**
- "What did we learn this session?" — end-of-session reflection.
- "Capture that lesson before we forget." — mid-session, after a non-obvious correction or success.
- "Audit memory and clean it up." — periodic maintenance (`/learn cleanup`).

**Core question:** *What, if anything, did we learn this session that should change how we work on this project going forward?*

Three deliberate words: **"if anything"** (honest about empty sessions), **"should change"** (durability test — must affect future work), **"this project"** (scoped, not generic advice).

---

## Arguments

- **(no arg)** — reflect on the current session, propose memory additions / updates / known-issue follow-ups, get approval, write. Includes a quick cleanup pass on entries that are *touched* (merge-into-existing case) — full audit only happens in `cleanup` mode.
- **`cleanup`** — full audit of all memory files. Propose deletions, merges, simplifications. No session reflection.

Example invocations:
- `/learn` — reflect on this session.
- `/learn cleanup` — audit-only.

---

## Memory location

Project memory lives at:

```
/Users/rgmarkey/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/
```

- `MEMORY.md` — index, one line per entry, ~150 chars max, truncated after 200 lines.
- `<type>_<slug>.md` — one file per memory, frontmatter + body. Types: `user`, `feedback`, `project`, `reference`. Body for `feedback` / `project` types must include **Why:** and **How to apply:** sections.

The global system prompt's "How to save memories" / "What NOT to save" rules are authoritative — this skill follows them, it does not redefine them.

---

## Steps — default mode (`/learn`)

### 1. Read current memory state

Read `MEMORY.md` in full. Note current entry count and any obvious topical clusters (used in step 4 for conflict detection).

### 2. Reflect on the session

Walk back through this conversation and identify candidate lessons. Each candidate must have an **evidence anchor** — a specific moment in the session that prompted the lesson. No anchor, no candidate.

Look for:
- **Corrections received** — user said "no, not that" / "stop doing X".
- **Surprising successes** — non-obvious approach worked, user confirmed without pushback.
- **Wasted effort** — something that took longer than it should have, with a clear root cause that future-me could avoid.
- **Hypothesis-vs-reality gaps** — a fragment, plan, or assumption proved wrong; the corrective insight is the lesson.
- **Pointers to external systems** — user mentioned a dashboard, channel, or tool location not already in memory.

Filter out (per global "What NOT to save"):
- Code patterns, file paths, conventions — derivable from current state.
- Git history / who-changed-what — `git log` is authoritative.
- Debugging fix recipes — the commit message has the context.
- Anything already in `CLAUDE.md` files.
- Ephemeral task state.
- Generic engineering knowledge not tied to this project's specific code, conventions, infrastructure, or team. Route those via step 2b instead of writing to memory.

### 2a. Durability gate

Default expectation: zero candidates per session. Each candidate must pass **all three** checks to survive into routing — drop entirely on "no" or "maybe" on any one:

- **Q1.** Would future-me, without intervention, make this **exact mistake** at >85% odds? (Not "would benefit from a reminder" — would actively re-make the mistake.)
- **Q2.** Is the lesson **not derivable** from `CLAUDE.md` / project docs / `git log` / common engineering knowledge?
- **Q3. Specific wrong action.** Name the exact wrong action future-me would take *without* this memory — not a vague "they'd make an error", but a concrete behaviour: "I would call X", "I would try Y", "I would skip Z check". If you cannot name it in one sentence, the lesson is not sharp enough to store.

Show the Q1 / Q2 / Q3 answers for each candidate when presenting in step 5 — surfacing the reasoning lets the user catch overgenerous self-assessment.

### 2b. Surface routing

For each candidate that passes 2a, classify where it belongs. Memory is **only** the right home when the lesson is project-specific:

- **Memory** — knowledge about this codebase / team / initiative that future-me can't reconstruct from current state. Continue to step 3.
- **Hook or settings.json rule** — automated behavior that should fire on a tool call. Suggest the user run `/update-config`.
- **Skill or command** — multi-step process worth packaging. Suggest a new `.claude/commands/<name>.md`.
- **CLAUDE.md / docs edit** — invariant or convention the project should document. Suggest the target file.
- **No surface available** — lesson is real and durable but generic; no automation home fits. Flag in the session report so it's visible, but write nothing.

Candidates not routed to **Memory** skip steps 3 and 4 and go straight to step 5's PROPOSED ROUTING section.

### 3. Classify each candidate

For each candidate routed to **Memory** in step 2b, assign exactly one type per the global memory schema:
- **user** — about the user's role, knowledge, preferences.
- **feedback** — guidance about how to approach work (rules + Why + How to apply).
- **project** — facts about ongoing work / decisions / deadlines (with absolute dates).
- **reference** — pointers to external systems.

Or route to **known-issue** instead if the lesson is "this thing is broken and needs work later" — that's a fragment under `docs/known-issues/`, not a memory. Memory and known-issues are mutually exclusive per item; pick one.

### 4. Conflict-check against existing memory

For each candidate, grep `MEMORY.md` for overlap on slug keywords and topic. For each match, decide:
- **SKIP** — already covered, no new information.
- **MERGE** — extend / clarify the existing entry (touched-entry simplification happens here).
- **ADD** — genuinely new, no meaningful overlap.

When MERGE is chosen, also check: can the existing entry be *simplified* while you're touching it? If the existing body is verbose or its **Why:** has gone stale, draft a tightened version. The continuous-improvement promise applies only to entries actually being modified — do not opportunistically rewrite untouched entries.

### 4a. Counterfactual double-check

For each candidate that survived steps 2a–4, re-read the specific wrong action named in Q3 and ask: **"Is that action actually what future-me would do, or is it what I feared they'd do?"**

If the action is speculative or hedged ("might", "could", "probably") → drop the candidate. It must be what future-me *would* do — not a possibility. If the wrong action has since become obvious from context (e.g. the conflict message itself diagnoses the fix) → also drop.

This is the final filter before presentation. Show the Q3 wrong action and this confirmation in step 5.

### 5. Present recommendations

Default action is to write nothing until the user approves. Output:

```
Session lesson review

PROPOSED ADDITIONS:
1. [feedback] <one-line title>
   Anchor: <session moment>
   Q1 (would re-make at >85%?): <yes — reasoning>
   Q2 (not derivable?): <yes — reasoning>
   Q3 (specific wrong action): <exact sentence — "I would call X" / "I would try Y" / "I would skip Z">
   4a (wrong action confirmed, not speculative?): <yes — reasoning>
   Why: <reason>
   How to apply: <when this kicks in>
   Conflicts: <none | feedback_<slug> (recommend MERGE / recommend ADD because <reason>)>

PROPOSED UPDATES (merges into existing entries):
2. MERGE into feedback_<slug>:
   Anchor: <session moment>
   Q1/Q2/Q3/4a: <as above>
   Change: <what gets added or simplified>
   Diff preview: <±2 lines showing the touched parts>

PROPOSED ROUTING (passes durability, but not project-specific memory):
3. [hook | skill | CLAUDE.md edit | no surface] <title>
   Anchor: <session moment>
   Q1/Q2/Q3/4a: <as above>
   Why memory is wrong fit: <reason>
   Suggested action: <concrete next step — e.g. "run /update-config to add a PreToolUse hook on X", "edit CLAUDE.md section Y", or "no automation home — flagged for awareness only">

PROPOSED KNOWN-ISSUE FRAGMENTS:
4. [<severity>] <title>
   Anchor: <session moment>
   Why memory is wrong fit: <reason>

Reply: "approve" / "all" to accept everything, "none" to skip all,
or list specific items to keep (e.g. "1,3" or "skip 2").
```

If no candidates surfaced: print `Nothing durable to capture this session.` and stop. Do not invent lessons to fill space. Default expectation is zero — most sessions will print this.

### 6. Act on approval

- "approve" / "all" / silent → write everything proposed.
- "none" / "skip" → write nothing, exit.
- Anything else → apply user edits, show revised list, get one more confirmation.

For each accepted item:
- **ADD** — write `<type>_<slug>.md` with frontmatter (`name`, `description`, `type`, `originSessionId`) and body (rule + **Why:** + **How to apply:** for feedback / project types). Append a `MEMORY.md` index line: `- [Title](file.md) — one-line hook` under ~150 chars.
- **MERGE** — edit the existing memory file in place. Update the `MEMORY.md` index line if the hook changed.
- **ROUTING** — do not write to memory. Carry out the suggested action:
  - **hook / settings.json rule** → invoke the `update-config` skill with the proposed change.
  - **skill or command** → draft `.claude/commands/<name>.md` and write it (treat as a normal file edit, not a memory write).
  - **CLAUDE.md / docs edit** → propose the diff inline and apply on user confirmation.
  - **No surface available** → print the lesson in the final summary so it's logged in the transcript, then stop. No file writes.
- **Known-issue** — defer to the project-local `/commit-proj` skill's step 9 flow (`gh issue create` first, then `gh-N-<slug>.md` fragment). Do not file directly from this skill — the commit skill is the single source of truth for fragment creation. Print the proposed title and ask the user to run `/commit-proj` to file it, or stage it for them to file at the next commit.

### 7. Final summary

One line per outcome category:

```
Wrote N additions, M merges. Routed R items (hook/skill/docs/no-surface). Filed K known-issue proposals (run /commit-proj to log). MEMORY.md now at <count> entries.
```

If nothing changed: `No memory changes this session.`

---

## Steps — cleanup mode (`/learn cleanup`)

### 1. Inventory

Read `MEMORY.md` and every memory file it references. Flag any orphan files (referenced files that don't exist; existing files not in the index).

### 2. Identify cleanup candidates

Three priority categories — surface the obvious wins, do not try to re-organize the whole index:

**STALE** — entry references a file path, function, flag, PR #, or migration that no longer exists or has been renamed/superseded. Verify with `Read` / `grep` / `git log`. Per the global "Before recommending from memory" rule, a memory is a claim that something existed *when written*; stale memories actively mislead.

**DUPLICATE / MERGE** — two or more entries on the same topic that could fold into one without losing the distinct **Why:** of either. Common pattern in this project: multiple entries about a single tool's quirks (e.g. `/commit` skill behaviors).

**VERBOSE** — entry body is long enough to compress without losing the rule, **Why:**, or **How to apply:**. Rough threshold: bodies > ~200 words or `MEMORY.md` index lines > 150 chars.

Do **not** flag:
- Entries that are simply old but still accurate.
- Entries the user has explicitly endorsed in a recent session.
- The handful of "load-bearing" entries the project actively relies on (e.g. those referenced in worker prompts).

### 3. Present recommendations

```
Memory audit — <count> entries reviewed

PROPOSED DELETIONS (stale):
1. feedback_<slug>: <reason it's stale, with verification command output>

PROPOSED MERGES:
2. Merge feedback_<slug_a> + feedback_<slug_b> → feedback_<new_slug>
   Combined rule: <draft>
   Why merge: <distinct Why's preserved | one is a special case of the other | overlap is total>

PROPOSED SIMPLIFICATIONS:
3. Tighten feedback_<slug>: <current word count> → <draft word count>
   Diff preview: <±3 lines>

Reply: "approve" / "all" / "none" / list specific items.
```

If no candidates: print `Memory looks clean — N entries, no stale / duplicate / verbose flags.` and stop.

### 4. Act on approval

- **DELETE** — `rm <type>_<slug>.md`, remove the `MEMORY.md` index line.
- **MERGE** — write the new combined file, delete the constituents, update the index.
- **SIMPLIFY** — edit in place, update the index line if the hook changed.

### 5. Final summary

```
Audit complete: <D> deletions, <M> merges, <S> simplifications. MEMORY.md now at <count> entries (was <prev>).
```

---

## Rules

- **Never write to memory without explicit user approval.** Auto-writing is the failure mode this skill exists to prevent.
- **Every addition needs an evidence anchor** — a concrete session moment. No anchor → not a lesson, just a guess.
- **Memory and known-issues are mutually exclusive per item.** Memory is a durable rule for future-me; known-issue is work that needs doing. Pick one explicitly per candidate.
- **Default expectation per session is zero candidates.** Most sessions don't yield durable lessons; "Nothing learned" is the expected output, not a fallback. Don't fabricate to fill space, and don't lower the durability bar (steps 2a + 4a) to surface marginal candidates.
- **Touched-entry simplification only.** In default mode, only entries being merged into get tightened. Full-audit cleanup is `/learn cleanup` — keep the modes separate.
- **Honor the global memory schema.** Frontmatter must include `name`, `description`, `type`, `originSessionId`. Feedback and project bodies need **Why:** and **How to apply:** sections. Project memories convert relative dates ("yesterday", "Thursday") to absolute YYYY-MM-DD.
- **MEMORY.md index discipline.** One line per entry, ~150 chars max. The index is loaded into every conversation; bloat truncates real memory at line 200.
- **Defer fragment filing to `/commit`.** This skill proposes known-issue candidates; `/commit` step 9 is the only place fragments are actually filed (server-allocated `gh-N` IDs, no local collisions).
- **Do not edit untouched memory entries** in default mode. Continuous improvement applies to entries this skill is already modifying — opportunistic rewrites belong in `cleanup` mode.
- **Verify before flagging stale.** A memory referencing a file that "doesn't exist" might just have been moved. Run the verification command before recommending deletion.
