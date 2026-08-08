# Parallel-session claims — design

**Date:** 2026-08-08 (rev 3 — closed ideas are archived, not deleted)
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

## The core move

Collisions 1 and 2 are both contention over **shared documents**. The strongest fix is not to police
access to a contested resource but to **stop the resource being contested**: give every in-flight idea
its own file, so a session records its work there instead of in a document another session is also
writing.

Collision 3 is physical — git cannot have one working tree on two branches — and needs worktrees, not
documents. Collision 4 is a rule about who may publish a branch.

So the design has three independent parts, in decreasing order of how much work they do.

## Non-goals

- Not a locking system. Two sessions claiming the same idea is surfaced, not prevented.
- Not a scheduler, queue, or CLI. No claim expiry, no timeouts, no daemon.
- Not a replacement for `feedback_scope_restriction` — a session still works one project at a time.
- **Not a second hypothesis tracker.** See "Boundary with the ledger" below.

## Design

### 1. Isolation — one worktree per session

Every session works in its own git worktree. **The bare checkout belongs to nobody:**
`C:\Users\gl450\trading_app` and `C:\Users\gl450\polymarket_app` stay on `main`, clean. No session
commits there. A session that finds itself in the bare checkout creates its worktree first.

This is required for collision #3 and no document can substitute for it: `git checkout` in a shared
directory rewrites files under a live session regardless of what any markdown file says.

Second payoff: the operator's restart path becomes unambiguous. The long-running confusion where
merged config knobs had no effect — because the backend ran from a checkout parked on an unrelated
feature branch — cannot recur if the bare checkout is always `main`. `polymarket_app`'s bare checkout
is currently on `feat/scan-loop-resilience`, so adopting this is a change there, not a formalisation.

**Identity is separate from isolation.** A session's handle is short and stable (`hta`, `it15`), and
defaults to the worktree's basename normalised — strip a leading `.`, a `<repo>-` prefix, a
`-worktree` suffix. A session may also be given a handle explicitly. `polymarket_app` already runs
nine worktrees under three naming conventions (`pattern-c`, `pnl-worktree`, `.wt-dbar`,
`maker-exit-leg`, several under `AppData\Local\Temp`); normalising the basename accommodates all of
them and **nothing needs renaming**. New worktrees should prefer `<repo>-<handle>`.

### 2. Claim — one file per idea

`docs/ideas/<ID>.md`. The file *is* the claim; the owner is a field in it.

```markdown
---
id: H18
owner: it15
branch: feat/hist-trail-gap
status: REJECTED          # exploring | probing | building | open | landed | REJECTED
claims:
  - file:scripts/trail_arm_gap_probe.py
  - file:backend/agents/historical_trends_agent.py
updated: 2026-08-08
---

# H18 — trail-arm gap is closable

Working notes, probe results, the verdict as it develops. This is where the owner
writes while the work is live — NOT the shared ledger.
```

**ID scheme:** ledger hypotheses use their H-number (`H18.md`); everything else uses a kebab slug
(`parallel-session-claims.md`, `env-hygiene.md`). One idea, one file, one owner at a time.

**`claims:` entries** are what the hook enforces:

| kind | example | enforced? |
|---|---|---|
| file / path | `file:backend/agents/historical_trends_agent.py` | **yes — blocks** |
| path prefix | `file:backend/agents/` | **yes — blocks** |
| doc section | `doc:CLAUDE.md#trading-policy-defaults` | warn only (see Limitations) |

**Why per-idea rather than per-session.** An earlier revision of this spec used one file per session
(`docs/claims/<handle>.md`), chosen so that no two sessions would ever write the same file. That
optimised for the wrong property. Per-idea files are better on every axis that matters:

| | per-session | per-idea |
|---|---|---|
| "who owns H19?" | grep every file | open `H19.md` |
| handoff to another session | move a row between two files | change one field |
| unit of growth | sessions — few, churn constantly | ideas — the thing actually tracked |
| working notes | nowhere, so pressure returns to the shared ledger | live in the idea file |
| collision #1 | flagged by a rule | **dissolved** — the contested doc is no longer touched while work is live |

Per-idea files do allow two sessions to open the same file. That is the one collision worth surfacing
loudly and early: it means two sessions are chasing the same hypothesis, and they should discover that
at claim time rather than at merge.

### 3. Closing — archive, never delete

An idea closes by **moving** its file from `docs/ideas/` to `docs/ideas/_archive/`. The move is the
whole ceremony:

```
docs/ideas/H18.md   ->   docs/ideas/_archive/H18.md
```

**The directory is the state.** A file under `docs/ideas/` is live and its `claims:` are enforced; a
file under `_archive/` is history and enforces nothing. The hook globs `docs/ideas/*.md` only, so an
archived file's stale `claims:` list can never block anyone. Nothing else has to be updated, and there
is no release step to forget. (`_archive/` matches the naming already used by the operator's memory
store, so the convention reads the same in both places.)

On archiving, the owner adds the closing fields:

```markdown
status:   closed
outcome:  REJECTED          # or LANDED / SUPERSEDED / ABANDONED
closed:   2026-08-08
ledger:   Iteration 16      # where the settled verdict lives
```

**Why keep it.** The ledger records the verdict; the idea file records the *work* — the thresholds
tried and discarded, the probe that had a bug, the reasoning that was reframed halfway. A future
session picking up an adjacent hypothesis needs that far more than it needs the summary, and it is
exactly what is lost when the working document is thrown away at the end.

**Archived files are read-only in practice.** Once closed, an idea file is not edited again except to
fix a broken link. It is a point-in-time record, and its conclusions may have been overtaken.

### 3a. Boundary with the ledger — no second tracker

`docs/model_improvement_ledger.md` already has a hypothesis backlog table and per-iteration verdicts.
The idea files must not duplicate it. The split:

| | idea file | ledger |
|---|---|---|
| holds | the **working record**: owner, branch, status, notes, dead ends, partial results | the **settled** verdict and its reasoning |
| lifetime | `docs/ideas/` while live → `docs/ideas/_archive/` once closed. Never deleted. | permanent |
| written by | the owner, continuously, while the work is live | the owner, once, as part of the landing PR |
| authority | context only | **authoritative** |

Closing is a single act in one PR: the owner writes the ledger entry **and** moves the idea file to
`_archive/`. If the two ever disagree, **the ledger wins**.

Every archived file therefore opens with this line, so a future session cannot mistake a working note
for a current conclusion:

> *Archived working record. The settled verdict is in `docs/model_improvement_ledger.md` — see the
> `ledger:` field above. Anything here may have been superseded.*

### 4. Contract — five rules

- **R1 — Claim before you work.** Create `docs/ideas/<ID>.md`, commit, push. Pushing *is* the
  announcement.
- **R2 — Never write another owner's claimed paths,** and never write their idea file or their ledger
  entry. Do not open, merge, or retarget their PR. Do not cherry-pick from their branch.
- **R3 — Your branch is yours alone to publish.** Nobody incorporates anyone else's branch into `main`
  but its owner. This is what makes collision #4 impossible: a stale remote head is never anyone
  else's problem, because nobody else ever reads it.
  *Exception — abandoned work.* A branch with no live idea file and no active session behind it is
  unowned, and anyone may land it. `trading_app` has ~60 such branches from finished sessions. The
  test is the idea file, not the branch's age.
- **R4 — Commit with an explicit pathspec:** `git commit -m "…" -- <paths>`. Never bare `git add -A`
  followed by a bare commit. Carried over from `feedback_parallel_agent_coordination`.
- **R5 — Shared docs are claimed by section, not whole-file.** Claiming all of CLAUDE.md or the whole
  ledger blocks the other session from unrelated work and will be refused in review.

### 5. Enforcement — pre-commit hook, step 0

A new first step in each repo's `.git/hooks/pre-commit`, ahead of the existing secret scan:

```
=== pre-commit gate ===
BLOCKED: scripts/trail_arm_gap_probe.py
  claimed by 'it15' in docs/ideas/H18.md (probing)
  you are 'hta'

  ask it15 to land it, or take ownership in docs/ideas/H18.md
```

Behaviour:

1. Derive own handle from the worktree basename (normalised), or an explicit override.
2. Read `docs/ideas/*.md` **from `HEAD`, not the worktree** — a half-edited idea file must never wedge
   a commit. The glob is deliberately non-recursive: `docs/ideas/_archive/**` is never read, so a
   closed idea's stale `claims:` list can never block anyone.
3. Collect `file:` claims from each live idea, with their `owner`. Block a staged path if a
   **different** handle claims it.
4. `doc:` claims print a warning and do not block.
5. Own claims never block. `--no-verify` remains the documented escape hatch.

`trading_app`'s hook currently runs a secret scan plus Bandit (<10s). `polymarket_app`'s runs the full
pytest suite (~7 min). Step 0 must run **first** in both, so a claim violation fails in milliseconds
rather than after a seven-minute test run.

### 6. Rollout

1. `docs/ideas/` + `docs/ideas/_archive/` + `README.md` (frontmatter schema, the five rules, the
   archive-on-close step) in both repos.
2. Hook step 0 in both repos.
3. Replace the stale "Two-Agent Setup" section in `trading_app/CLAUDE.md`; add the equivalent to
   `polymarket_app/CLAUDE.md`.
4. Update `feedback_parallel_agent_coordination` in memory, and add a cross-project memory entry —
   memory is the only genuinely cross-repo store, so it holds the canonical statement while each repo
   holds its own `docs/ideas/README.md`.
5. Backfill only what is **live**: `H18`/`H19`/`H20` owned by `it15`; the term-structure work owned by
   its session; this spec owned by `hta`. Settled hypotheses stay in the ledger and get no file.

**Applying R3 to the work already in flight.** `hta` currently holds a local staging branch with two
cherry-picks: ledger Iteration 14, and `it15`'s Iteration 16 probe script. Under R3 these split —

- *Iteration 14* sits on `docs/ledger-iter14-v1.0.1`, authored by a session that ended weeks ago and
  claimed by nobody. Unowned, so `hta` may land it.
- *The Iteration 16 probe, and the ledger entry describing it*, belong to `it15`, who is still
  actively working that hypothesis. `hta` drops the cherry-pick; `it15` publishes when ready.

## Limitations — stated plainly

- **`doc:…#section` cannot block.** Mapping a section anchor to a diff hunk is not reliable enough to
  refuse a commit on, so section claims warn only. Collision #2 is therefore *reduced* — most writing
  moves into idea files and never reaches the shared doc — but not prevented. R4's pathspec discipline
  is the actual guard.
- **Hooks are untracked.** `.git/hooks/` does not survive a fresh clone, and neither repo's setup
  script installs hooks. On a new machine the idea files still exist and remain readable, but
  enforcement silently degrades to advisory. Wiring hook installation into `scripts/setup_fresh.*` is
  a follow-up, not part of this design.
- **Nothing forces a session into a worktree.** A session that ignores R1 and commits from the bare
  checkout is not stopped by anything here. The hook can detect the bare checkout and warn.
- **Claims are only as fresh as the last push.** A session that claims locally and does not push is
  invisible to everyone else.
- **Two sessions can edit one idea file.** By design — that is the conflict worth surfacing. But it is
  a real merge conflict, not a clean error message.
- **Idea files can rot.** An abandoned session leaves a *live* file claiming paths forever. Mitigation
  is social — the `updated` field makes staleness visible, and anyone may move a clearly-dead idea to
  `_archive/` with `outcome: ABANDONED`. No expiry mechanism is proposed, because an automatic one
  would release claims on work that is merely paused.
- **The archive can mislead.** A closed idea file is a point-in-time record whose conclusions may have
  been overtaken — a real instance of this happened while drafting: a note reading "these two knobs
  remain unvalidated" was already stale when written, because another session had begun validating
  them that hour. The `ledger:` field and the archived-record banner are the mitigation; a future
  session must treat an archived file as context, never as current fact.

## Alternatives considered

- **One file per session** (`docs/claims/<handle>.md`). Guarantees the claim mechanism itself cannot
  collide, but scatters ownership across files, makes handoff a two-file edit, and — decisively —
  gives working notes no home, so verdicts get written into the shared ledger while work is live,
  which is collision #1. This was rev 1 of this spec; superseded.
- **Owner column in the ledger's hypothesis table.** No new file and it sits where `Hxx` already
  lives, but the ledger is the highest-collision document in the repo, and non-hypothesis work has
  nowhere to live. Rejected.
- **GitHub assignees and labels only.** Uses existing tooling and needs no new file, but an idea
  cannot be claimed before a PR exists — precisely when three of the four collisions occurred.
  Rejected.
