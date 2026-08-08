# Parallel-session claims — design

**Date:** 2026-08-08
**Applies to:** `trading_app` **and** `polymarket_app`
**Status:** design, pending operator review

## Problem

More than one Claude Code session works these repos at once. Nothing records who owns what, so
sessions collide. Four distinct collisions happened in a single afternoon on 2026-08-02/08:

| # | Collision | What actually happened |
|---|---|---|
| 1 | Authoring another session's write-up | Session `hta` was seconds from writing the Iteration 16 ledger entry — the verdict, in its own words — for a probe that session `it15` had designed, run and interpreted. `it15` had deliberately deferred that entry to avoid two writers in one doc. |
| 2 | Shared-doc commit bleed | `hta` edited a CLAUDE.md section; `it15`'s `git add` swept it into their commit, which shipped under a title describing only their own work. |
| 3 | Working tree yanked underneath | `hta` switched branches three times in the shared checkout while `it15` was mid-session in the same directory. |
| 4 | Stale branch vs local divergence | `it15`'s pushed branch was one rebase behind their local commit. `hta` nearly incorporated the stale version into `main`. |

The repos are not short of process. `trading_app/CLAUDE.md` has a "Two-Agent Setup" section with a
file-ownership table, and `feedback_parallel_agent_coordination` in memory covers pathspec commits and
checking `git status` before dispatch. Neither prevented any of the four. Two reasons:

- The CLAUDE.md model is **stale**. It describes one implementation agent plus one testing sub-agent,
  split by file type. Today's reality is two or more **peer** sessions each running the full
  design → probe → build → PR loop, both writing production code, tests and docs.
- Both are **advisory**. Nothing reads them at commit time.

## Non-goals

- Not a locking system. Simultaneous claims on the same item resolve first-to-push-wins; the loser
  finds out on `git pull`.
- Not a scheduler, queue, or CLI. No claim expiry, no timeouts, no daemon.
- Not a replacement for `feedback_scope_restriction` — a session still works one project at a time.

## Design

### 1. Identity — the worktree is the handle

Every session works in its own git worktree. The **handle** is the worktree directory's basename,
normalised:

```
strip a leading "."      .wt-dbar          -> wt-dbar
strip "<repo>-" prefix   trading_app-it15  -> it15
strip "-worktree" suffix pnl-worktree      -> pnl
```

New worktrees should be named `<repo>-<handle>` (`trading_app-hta`). Existing ones need no rename —
`polymarket_app` already has nine worktrees under three different conventions, and normalising the
basename accommodates all of them. The basename is already unique per worktree, which is the only
property the mechanism needs.

**The bare checkout belongs to nobody.** `C:\Users\gl450\trading_app` and
`C:\Users\gl450\polymarket_app` stay on `main`, clean. No session commits there. A session that finds
itself in the bare checkout creates its worktree before doing anything else.

This rule alone eliminates collision #3, and it has a second payoff: the operator's restart path
becomes unambiguous. The long-running confusion where merged config knobs had no effect — because the
backend ran from a checkout parked on an unrelated feature branch — cannot recur if the bare checkout
is always `main`. Note `polymarket_app`'s bare checkout is currently on `feat/scan-loop-resilience`,
so adopting this is a change there, not a formalisation of existing practice.

### 2. The claim — `docs/claims/<handle>.md`

One file per session. **A session writes only its own file.** No two sessions ever touch the same path,
so the claims mechanism cannot itself suffer collision #2. Reading everyone's claims is `ls docs/claims/`.

```markdown
# Claims — it15

| claim                                          | branch               | state    | updated    |
|------------------------------------------------|----------------------|----------|------------|
| H18                                            | feat/hist-trail-gap  | REJECTED | 2026-08-08 |
| H19, H20                                       | feat/hist-trail-gap  | probing  | 2026-08-08 |
| doc:model_improvement_ledger.md#iteration-16   | feat/hist-trail-gap  | drafting | 2026-08-08 |
| file:backend/agents/historical_trends_agent.py | feat/hist-trail-gap  | building | 2026-08-08 |
```

**Claim kinds**

| kind | example | enforced? |
|---|---|---|
| hypothesis | `H18` | no — advisory, for humans and for other sessions reading |
| pull request | `PR#93` | no — advisory |
| file / path | `file:backend/agents/historical_trends_agent.py` | **yes — blocks** |
| doc section | `doc:CLAUDE.md#trading-policy-defaults` | warn only (see Limitations) |

`file:` accepts a directory prefix (`file:backend/agents/`) to claim a subtree.

**States:** `probing` · `building` · `open` (PR raised) · `landed` · `REJECTED` · `released`.
A claim is released by deleting its row or setting `released`; either way the hook stops enforcing it.

### 3. The contract — five rules

- **R1 — Claim before you work.** Write the row, commit it, push it. Pushing *is* the announcement.
- **R2 — Never write another handle's claimed paths.** Do not author their ledger entry. Do not open,
  merge, or retarget their PR. Do not cherry-pick from their branch.
- **R3 — Your branch is yours alone to publish.** Nobody incorporates anyone else's branch into `main`
  but its owner. This is what makes collision #4 impossible: a stale remote head is never anyone
  else's problem, because nobody else ever reads it.
  *Exception — abandoned branches.* A branch with no live claim in any `docs/claims/*.md` and no
  active session behind it is unowned, and anyone may land it. `trading_app` has ~60 such branches
  from finished sessions. The test is the claim file, not the branch's age: if a handle still claims
  it, it is theirs regardless of how long it has sat.
- **R4 — Commit with an explicit pathspec:** `git commit -m "…" -- <paths>`. Never bare `git add -A`
  followed by a bare commit. Carried over from `feedback_parallel_agent_coordination`.
- **R5 — Shared docs are claimed by section, not whole-file.** Claiming all of CLAUDE.md or the whole
  ledger blocks the other session from unrelated work and will be refused in review.

### 4. Enforcement — pre-commit hook, step 0

A new first step in each repo's `.git/hooks/pre-commit`, ahead of the existing secret scan:

```
=== pre-commit gate ===
BLOCKED: docs/model_improvement_ledger.md
  claimed by 'it15' (H18, probing)
  you are 'hta'

  ask it15 to land it, or claim it in docs/claims/hta.md
```

Behaviour:

1. Derive own handle from the worktree basename (normalised as above).
2. Read `docs/claims/*.md` **from `HEAD`, not the worktree** — a half-edited claim file must never
   wedge a commit.
3. For each staged path, block if a **different** handle holds a matching `file:` claim in a
   non-`released` state.
4. `doc:` claims print a warning and do not block.
5. Own claims never block. `--no-verify` remains the documented escape hatch.

`trading_app`'s hook currently runs a secret scan plus Bandit (<10s). `polymarket_app`'s runs the full
pytest suite (~7 min). Step 0 must run **first** in both, so a claim violation fails in milliseconds
rather than after a seven-minute test run.

### 5. Rollout

1. `docs/claims/` + `README.md` (the format, the five rules) in both repos.
2. Hook step 0 in both repos.
3. Replace the stale "Two-Agent Setup" section in `trading_app/CLAUDE.md`; add the equivalent to
   `polymarket_app/CLAUDE.md`.
4. Update `feedback_parallel_agent_coordination` in memory, and add a cross-project memory entry —
   memory is the only genuinely cross-repo store, so it holds the canonical statement while each repo
   holds its own `docs/claims/README.md`.
5. Backfill today's live state: `it15` claims H18/H19/H20 and `feat/hist-trail-arm-gap`; the
   term-structure session claims PR#92 and its files; `hta` claims this spec.

**Applying R3 to the work already in flight.** `hta` currently holds a local staging branch with two
cherry-picks: ledger Iteration 14, and `it15`'s Iteration 16 probe script. Under R3 these split —

- *Iteration 14* sits on `docs/ledger-iter14-v1.0.1`, authored by a session that ended weeks ago and
  claimed by nobody. Unowned, so `hta` may land it.
- *The Iteration 16 probe, and the ledger entry describing it*, belong to `it15`, who is still
  actively working that hypothesis. `hta` drops the cherry-pick; `it15` publishes when ready.

This is the concrete case the design exists to settle, so it is recorded here rather than left to
judgement.

## Limitations — stated plainly

- **`doc:…#section` cannot block.** Mapping a section anchor to a diff hunk is not reliable enough to
  refuse a commit on, so section claims warn only. Collision #2 is therefore *discouraged*, not
  prevented; R4's pathspec discipline is what actually prevents it.
- **Hooks are untracked.** `.git/hooks/` does not survive a fresh clone, and neither repo's setup
  script installs hooks. On a new machine the claims files still exist and remain readable, but
  enforcement silently degrades to advisory. Wiring hook installation into `scripts/setup_fresh.*` is
  a follow-up, not part of this design.
- **Nothing forces a session into a worktree.** A session that ignores R1 and commits from the bare
  checkout is not stopped by anything here. The hook can see it is in the bare checkout and warn.
- **Claims are only as fresh as the last push.** A session that claims locally and does not push is
  invisible to everyone else.
- **Same-handle collisions are not addressed.** Two sessions in the same worktree would share a
  handle. Out of scope: that is the one-worktree-per-session rule's job.

## Alternatives considered

- **Single shared `AGENT_CLAIMS.md`.** One place to look, but it is itself a shared document — the
  exact collision class being fixed. Rejected.
- **Owner column in the ledger's hypothesis table.** No new file and it sits where `Hxx` already
  lives, but the ledger is the highest-collision document in the repo, and PRs and CLAUDE.md sections
  have nowhere to live. Rejected as the primary store; an owner column may still be added later as a
  convenience.
- **GitHub assignees and labels only.** Uses existing tooling and needs no new file, but a hypothesis
  cannot be claimed before a PR exists — which is precisely when three of the four collisions
  occurred. Rejected.
