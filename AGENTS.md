# AGENTS.md — trading_app (AI Trading Competition)

Codex loads this file automatically. Claude Code loads it through the `@AGENTS.md` import in `CLAUDE.md`.

## 1. Read the full contract first

`CLAUDE.md` in this directory is the project contract: scope and the runtime Python, roles, TDD,
test conventions and commands, shell cleanup, commit standards, the security pre-commit hook, the
active trading roster, the code invariants and the trading-policy defaults. **Codex: read all of
`CLAUDE.md` before your first task in this repository and follow it.** This file does not repeat it.
Sections that apply to Claude only: "CLAUDE.md ↔ Memory Sync Rule" (Codex never edits Claude's memory
folder). Where this file and `CLAUDE.md` disagree, stop and ask the operator.

Reviews follow `C:\Users\gl450\.coordination\trading_app\PEER_REVIEW.md` (shared findings ledger,
requirements and testing standard). Multi-agent work also follows
`C:\Users\gl450\.agent-forum\AGENT_FORUM_FRAMEWORK.md`.

## 2. Roles (assigned per task, not per agent)

Either agent can be author or reviewer. Roles are fixed here; who fills them is set per task.

| Role | Must | Must not |
|---|---|---|
| **Author** | Claim the task; work on its own branch or worktree; write the failing test first; request review with the head SHA, what changed and the evidence (PEER_REVIEW.md record) | Approve its own work; confirm its own finding; merge |
| **Reviewer** | Inspect the exact head SHA; check each decision-critical claim itself; give the strongest objection; reply APPROVE naming the SHA, or numbered defects, plus a forum status | Push to the author's branch (it proposes fixes instead); approve a SHA it did not inspect |
| **Operator** | Clicks merge; restarts the live app; approves test windows and anything irreversible; decides disputes, NO_CONSENSUS and role swaps | — |

**Assignment.** Each task has one record, set when it starts, at
`C:\Users\gl450\.coordination\trading_app\tasks\<task-id>.yaml` (next to the shared findings ledger):

```yaml
task: <id>          # also named in every review request and verdict
author: claude      # or codex
reviewer: codex     # always the other agent
operator: gl4500
scope: [paths]
branch: <branch>
```

- Default: whoever claims the task is the author. Swaps only by the operator or an explicit handoff message.
- **Codex as author:** Codex never edits Claude's memory folder. It records each change in the PR description
  and the findings ledger; the Claude reviewer updates memory after merge.
- Mailbox: `C:\Users\gl450\.coordination\trading_app\mailbox.py` only. Never the polymarket session link.
  Agents: Claude in the trading_app workspace, `ta-codex` (Herdr names).

## 3. Checklists by pause point

**Session start (both)**
1. Read the trading_app mailbox inbox; ack what you read.
2. `git status` and `git stash list`: unfamiliar changes are another agent's work. Don't touch them.
3. Confirm the task stays inside this repo (CLAUDE.md, Scope).

**Before running anything that uses this machine (both)**
1. Use only `C:\Users\gl450\trading_app\runtime\python\python.exe`; run `backend\run_tests.py` from the
   checkout that holds the code under test, which needs a `site-packages` link if it is a worktree
   (CLAUDE.md, Running tests).
2. Never test against the live `trading.db` or the broker; use temp DBs and mocks (CLAUDE.md, Test Conventions).
3. Clean up only processes you can name as your own, by command line (CLAUDE.md, Shell cleanup).

**Live-backend guard**
`tools/agent_guard/live_guard.py` is a PreToolUse hook for both agents (`.claude/settings.json`,
`.codex/hooks.json`). While port 8000 is listening (or its state can't be determined) it blocks test runs and
process kills. Test runs pass only during an operator test window: a gitignored `.agent-test-window` file at the
repo root holding an ISO-8601 expiry with timezone (e.g. `2026-11-14T22:00:00-05:00`). Kills always need the
operator.

- **Claude:** active whenever this checkout's `.claude/settings.json` loads; a failing hook blocks the command.
- **Codex:** active only after the operator trusts the project hooks (`/hooks`), in a project Codex trusts.
- **If the hook itself breaks** and blocks everything, only the operator restores it, for example by
  temporarily renaming `.claude/settings.json` locally (never committed). Agents never weaken the guard.
- It is a guardrail against mistakes, not a security boundary. Tests: `tools/agent_guard/test_live_guard.py`.

**Author: before requesting review**
1. Fresh branch off `main`; commit with `git commit -m "<msg>" -- <paths>`; check `git log -1 --stat`.
2. Evidence per PEER_REVIEW.md: requirement IDs, old-fail/new-pass, commands and outputs.
3. Send: PR link, head SHA, what changed, how it was verified, specific questions.

**Reviewer: each review**
1. Review the exact head SHA named in the request; read the diff against its merge base.
2. Check each decision-critical claim yourself; never confirm your own finding.
3. Give the strongest consequential objection before agreeing.
4. Reply APPROVE naming the SHA, or a numbered defect list. An acknowledgement is not approval.
5. End with a forum status: CONSENSUS, CONDITIONAL_CONSENSUS, NO_CONSENSUS or INSUFFICIENT_EVIDENCE.

**Before merge**
1. Every new commit or rebase goes back to the reviewer with the new SHA and delta.
2. Required checks green; findings fixed or explicitly waived by the operator.
3. Hand the operator the PR link and approved SHA; the operator clicks merge and restarts.
