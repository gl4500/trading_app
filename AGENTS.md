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

## 2. Who does what

- **Claude (author):** implements, writes the failing test first, requests review.
- **Codex (reviewer, `ta-codex`):** independent review of every PR before merge.
- **Operator:** clicks merge on GitHub; restarts the live app; approves anything irreversible.
- Mailbox: `C:\Users\gl450\.coordination\trading_app\mailbox.py` only. Never the polymarket session link.

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
