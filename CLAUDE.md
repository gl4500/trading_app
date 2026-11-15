# CLAUDE.md — trading_app (Claude adapter)

@AGENTS.md

**If the `AGENTS.md` text is not in your context, read `AGENTS.md` in the repository root (the folder
that holds this `CLAUDE.md`) in full before doing anything else.** Claude Code skips the import above
when a session starts in a subdirectory (e.g. `backend/`): the root file then counts as an external
import that needs approval, and a non-interactive session never asks. Start sessions at the repository root.

`AGENTS.md` (imported above) is the shared project contract for Claude Code and Codex: scope, roles,
workflow, tests, security gate, architecture, key invariants, checklists and the mandatory references
in `docs/agents/`. This file adds only what applies to Claude. Where they disagree, stop and ask the operator.

---

## CLAUDE.md ↔ Memory Sync Rule

**The repo contract and memory must always be updated together, and memory must be updated after every code change.**

The repo contract (`AGENTS.md` for shared rules, this `CLAUDE.md` for Claude-only rules) and the persistent memory files at
`C:\Users\gl450\.claude\projects\C--Users-gl450\memory\` are the two halves of the same contract.

### After every code change — required steps
1. If the change affects architecture, agents, endpoints, or file structure → update `trading_app_architecture.md`.
2. If the change fixes a bug → append the bug + fix to `trading_app_bugs_fixed.md`.
3. If the change adds or modifies a rule → update the matching memory file AND the matching `AGENTS.md` section (or this `CLAUDE.md`, for a Claude-only rule) in the same response.
4. Never commit code without also committing any corresponding `AGENTS.md` / `CLAUDE.md` update in the same or immediately following commit.

### Contract ↔ memory sync
- When you add or change a rule in `AGENTS.md` or `CLAUDE.md` → update the corresponding memory file in the same response.
- When you update a memory file that covers trading_app rules or feedback → reflect the change in `AGENTS.md` (shared rule) or `CLAUDE.md` (Claude-only rule) in the same response.
- Never let a session end with the two out of sync.

Relevant memory files for this repo:
| Memory file | Mirrors |
|---|---|
| `feedback_tdd_workflow.md` | `AGENTS.md` TDD Workflow section |
| `feedback_scope_restriction.md` | `AGENTS.md` Scope section |
| `feedback_shell_cleanup.md` | `AGENTS.md` Shell cleanup section |
| `feedback_sync_rule.md` | This section (memory update after every change) |
| `feedback_performance_history_retention.md` | `AGENTS.md` Key invariant #9 (no date-based prune on performance table) |
| `trading_app_architecture.md` | `AGENTS.md` Architecture Quick Reference + Key invariants |
| `trading_app_bugs_fixed.md` | Known bugs and fixes (not in the repo contract — memory only) |
| `trading_app_thresholds.md` | Agent thresholds (not in the repo contract — memory only; env defaults are in `docs/agents/trading-policy-defaults.md`) |
