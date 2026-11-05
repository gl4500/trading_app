# Task 4 old -> new

All of the edits below are in existing test files. Each is classified. At Task 4's end, every edited test except
the two BUNDLE-tuple tests (green) is in the Task 5 migration red list (t4_red_list.txt): its fixture now stops
before the edited assertion, at the RUN-ACK token refusal. The edited assertions are therefore first executed in
Task 5.

## research/s1/s1_tests/test_s1_t12_a3_a8.py (BUNDLE tuple)
Old: `... "s1_seal.py", "s1_snapshot.py")`
New: `... "s1_seal.py", "s1_snapshot.py", "s1_trial.py")`
Why: intended semantic change (A3.1 explicit file list gains the new module s1_trial.py, mirroring
s1_common.BUNDLE_CODE). RED on the stub (t4_red.txt), GREEN after (t4_full.txt).

## research/s1/s1_tests/test_s1_a3_journal.py
Added `assert "s1_trial.py" in c.BUNDLE_CODE` to test_bundle_pins_addendum3_and_lists_every_new_module. No existing
assertion changed.

## research/s1/s1_tests/test_s1_run.py
- L218 old: `... a["trial_id"] == "S1" and a["planned_start"] == START`
  new: `... a["trial_id"] == read(out / "plan.json")["trial_id"]` plus `assert a["planned_start"] == START`.
- L1012 old: `r.attest_start(...)["trial_id"] == "S1"`
  new: `== read(out / "plan.json")["trial_id"]`.
- L1505 old: `trial_id="".join(list(r.TRIAL_ID))`
  new: `trial_id="".join(list(plan["trial_id"]))`.
  r.TRIAL_ID is removed; the by-value comparison is kept.
Why: intended semantic change (F6.2, OQ-27). The trial id is the plan's uuid4, not the constant "S1".

## research/s1/s1_tests/test_s1_t12_a4.py
- L204 old: `assert pr["trial_id"] == "S1"`
  new: `== <plan.json>["trial_id"]`.
Why: intended semantic change (F6.2).

## research/s1/s1_tests/test_s1_t12_mutant_survivors.py
- L228 old: `r.do_prereg(...)["trial_id"] == "S1"`
  new: `== <plan.json>["trial_id"]`.
Why: intended semantic change (F6.2).

## research/s1/s1_tests/test_s1_task11.py
- L455 old: `... and "{attest}" in k.ACQUIRE_ACK`
  new: `... and "attest_stop_sha256" in s1_trial.ACK_FIELDS["S1-ACQUIRE-ACK"]`.
Why: intended semantic change (OQ-5). The ACQUIRE text is ACK_FIELDS, and k.ACQUIRE_ACK is removed.

## research/s1/s1_tests/test_s1_t12_fix8.py (fixture `template`, module scope)
- Old: `c.MAILBOX = root / "mailbox.sqlite3"` (file not yet created).
  New: `c.MAILBOX = s1_mailbox_init(root)` (and the import).
Why: fixture incompatibility. write_plan now reads the mailbox first (F9 / OQ-20, require_no_open_trial). This
module-scoped template runs outside the per-test autouse fixture that creates the tmp mailbox, so it refused
"mailbox unreadable" for all 189 parametrized cases.
- After the fix, those 189 cases fall into the Task 5 migration set (the RUN-ACK token refusal), the same single
  cause as every other red case.
- The mailbox is still a tmp file under tmp_path_factory, never the real one.

## Not edited (in the Task 5 migration set)
test_s1_connected.py:453 `k.ACQUIRE_ACK.format(...)` (the plan says this is classified in Task 5). It is in the red
list because its fixture fails earlier, at the RUN-ACK token. When Task 5 reaches that line, it would fail with
AttributeError, because k.ACQUIRE_ACK is removed as the plan requires.
