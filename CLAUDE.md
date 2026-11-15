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

## Memory ↔ repo rule (pointers, not copies)

**A rule's text lives once, in this repo:** shared rules in `AGENTS.md` and its mandatory references,
Claude-only rules in this `CLAUDE.md`. The memory folder `C:\Users\gl450\.claude\projects\C--Users-gl450\memory\`
holds what the repo does not: why a rule exists, incident history, operator quotes, rules that apply
across projects, and project state (architecture, bugs, thresholds, sprint log). Where memory covers a
repo rule it holds a pointer to the section, a one-line summary and the why, never a second full copy.
If a memory pointer's one-line summary disagrees with the repo section it points to, that section (in
the task's own checkout) wins: follow it and fix the summary in the same session. Any other conflict (a
general or cross-project rule kept in memory, an operator instruction, or a pointer whose target is
missing or stale) is not settled by this precedence: stop the affected action and ask the operator.

### After every code change — required steps
1. If the change affects architecture, agents, endpoints, or file structure → update `trading_app_architecture.md`.
2. If the change fixes a bug → append the bug + fix to `trading_app_bugs_fixed.md`.
3. If the change adds or modifies a rule → change it in the matching `AGENTS.md` section or mandatory reference (or this `CLAUDE.md`, for a Claude-only rule). In the same response, update the memory pointer, summary line and why/history; don't copy the rule text into memory.
4. Never commit code without also committing any corresponding `AGENTS.md` / `CLAUDE.md` update in the same or immediately following commit.

Memory files that point into this repo:
| Memory file | Points to (memory keeps why/history) |
|---|---|
| `feedback_performance_history_retention.md` | `AGENTS.md` Key invariant #9 |
| `feedback_trading_app_auto_merge_after_codex.md` | Superseded history; current rule is `AGENTS.md` Roles + Before merge |
| `feedback_loose_coupling.md` | General rule in memory; this repo's boundary is `AGENTS.md` Key invariant #10 |
| `feedback_tdd_workflow.md`, `feedback_scope_restriction.md`, `feedback_shell_cleanup.md` | General rules in memory; this repo's procedure in the matching `AGENTS.md` section |
| `feedback_sync_rule.md` | This section |
| `trading_app_architecture.md` | Project state; normative invariants are in `AGENTS.md` Key invariants |
| `trading_app_bugs_fixed.md` | Known bugs and fixes (project history — memory only) |
| `trading_app_thresholds.md` | Agent thresholds (project state — memory only; normative env defaults are in `docs/agents/trading-policy-defaults.md`) |
