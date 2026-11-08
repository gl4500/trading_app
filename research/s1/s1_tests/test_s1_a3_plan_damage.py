"""A3 Task 14b (controller-added; review O-3 / Task 14 I-1; progress.md ruling "T14 I-1"): after any journal row, a
damaged plan.json is TRIAL-INVALID, never a refusal the trial can resume from.
- F4 table + F4.8: plan.json is a bound input of the CREATED audit stage; missing or changed means INVALIDATE.
- F6.2: plan.json never changes after the AUDIT-ACK. A plan naming ANOTHER trial_id is a foreign root: refused with
  no row, never judged (F10 Identity), so it never invalidates this trial.
- OQ-19: after any row the legacy detector never overrides the journal; its persistent INVALID may still decide
  first, but its A2 B3.2 "inconsistent pre-registration state" refusal never ends the gate (Task 7 concern-2 ruling).
- Task 7 I1 / Task 11 I1: confirm on re-read before any INVALID; a transient OSError or a re-read that differs
  refuses with no row.
- F6.6: s1_out is never recreated. Before any journal row nothing changes (control)."""
import json
import re
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
import s1_common as c
import s1_journal as j
import s1_seal as z
import s1_stage as sg
import s1_trial as t
from conftest import Ledger, S1_RECEIPT, Spies, _Clock, s1_ack, s1_first_invalid, s1_opening_checkpoint, \
    s1_plan_audit, s1_state

START = "2026-10-26T13:30:00+00:00"
OTHER = "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"
POINTS = ("after-audit", "after-opening", "after-start-attest")
DAMAGES = ("deleted", "unparseable", "no-trial-id")
FOREIGN_POINTS = ("after-audit", "after-opening")
INVALID_STOP = (r"INVALID \((stage-replaced|registration-artifact)\)|"                      # the gate / F4 table
                r"persistent ABORTED-INVALID \(reason registration artifact\)")             # the OQ-19 detector
STAGE_REPLACED_PLAN = (r"stage audit: bound input plan\.json missing or changed since the AUDIT-ACK \(.*after journal "
                       r"rows.*\): INVALID \(stage-replaced\)")
FOREIGN = rf"plan\.json trial_id '{OTHER}' differs from the AUDIT-ACK's [0-9a-f-]+ \(F6\.2\)"
NOT_CONFIRMED = r"plan\.json .*not confirmed.*refused with no row"
UNREADABLE = r"plan\.json unreadable \(PermissionError\).*refused with no row"


def _build(root, point):
    """The real lifecycle up to `point` (the damage matrix's own construction, test_s1_a3_matrix._build)."""
    if point in ("after-audit", "after-opening"):
        start, cal, oc, _ = s1_plan_audit(root, START)
        if point == "after-opening":
            s1_opening_checkpoint(root, Ledger(root / "ledger.sqlite3"), oc, cal, S1_RECEIPT)
        return {"now": z.close_of(oc, cal) + timedelta(hours=1)}
    st_ = s1_state(root, START, upto=point)
    return {"now": st_["now"]}


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory):
    """Each point built once (module scope), inside the same guards the autouse fixtures apply (ruling B4/C14): its
    own tmp mailbox and receipt HMAC key, and the network guard."""
    import socket
    import httpx
    import s1_receipt
    from conftest import s1_mailbox_init
    got = {}
    base = tmp_path_factory.mktemp("plan_damage")

    def refuse(*a, **kw):
        raise AssertionError("A3 network guard: a real network call was attempted")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx.HTTPTransport, "handle_request", refuse)
        mp.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
        mp.setattr(socket, "create_connection", refuse)
        # fix round 1 (I-1): two more trials, each with its own mailbox - another trial's genuine whole root
        for key, p in [(p, p) for p in POINTS] + [(f"foreign-{p}", p) for p in FOREIGN_POINTS]:
            root = base / key
            root.mkdir()
            mp.setattr(c, "MAILBOX", root / "mailbox.sqlite3")
            mp.setattr(s1_receipt, "HMAC_KEY", root / "s1_receipt_hmac.key")
            s1_mailbox_init(root)
            got[key] = dict(_build(root, p), root=root)
    return got


def _copy(tmp_path, monkeypatch, snap, name="root", *, mailbox=True) -> Path:
    """A private copy of a snapshot root; `mailbox`: point s1_common.MAILBOX (the open trial) at the copy's."""
    root = tmp_path / name
    shutil.copytree(snap["root"], root)
    if mailbox:
        monkeypatch.setattr(c, "MAILBOX", root / "mailbox.sqlite3")
    return root


def _invalid_rows(root) -> int:
    trials = t.trials(t.scan(Path(root) / "mailbox.sqlite3"))
    return sum(1 for tid, x in trials.items() for row in j.read_trial(tid, x.genesis, Path(root) / "mailbox.sqlite3")
               if row.kind == "TRIAL-INVALID")


def _damage(out: Path, how: str) -> None:
    p = out / "plan.json"
    if how == "deleted":
        p.unlink()
    elif how == "unparseable":
        p.write_bytes(b"{not JSON")
    elif how == "no-trial-id":
        plan = json.loads(p.read_bytes())
        del plan["trial_id"]
        p.write_bytes(json.dumps(plan).encode("utf-8"))
    elif how == "changed":
        p.write_bytes(p.read_bytes() + b" ")
    else:
        raise ValueError(how)


def _no_stage_work(monkeypatch) -> None:
    """F0.6: the gate decides before any stage work - the stage table and stage engine must not run here."""
    def trip(*a, **kw):
        raise AssertionError("stage work ran on a plan.json damage path")
    for name in ("evaluate", "run", "recover"):
        monkeypatch.setattr(sg, name, trip)


def _restored_stays_invalid(root, now, keep: bytes, *extra) -> None:
    """Restoring plan.json (and removing every fabricated file and the local abort) never resumes the trial: the
    journal's TRIAL-INVALID decides (F1, OQ-19)."""
    out = root / "s1_out"
    (out / "plan.json").write_bytes(keep)
    for name in extra + ("aborted.json",):
        (out / name).unlink(missing_ok=True)
    with _Clock(now), pytest.raises(SystemExit, match=r"trial INVALID \(reason/"):
        t.gate(root, "after restoration")


@pytest.mark.parametrize("point", POINTS)
def test_control_the_undamaged_snapshot_passes_the_gate(tmp_path, monkeypatch, snapshots, point):
    root = _copy(tmp_path, monkeypatch, snapshots[point])
    with _Clock(snapshots[point]["now"]):
        assert t.gate(root, "control").state == "ACTIVE"


@pytest.mark.parametrize("how", DAMAGES)
@pytest.mark.parametrize("point", POINTS)
def test_a_damaged_plan_after_journal_rows_is_invalid_and_restoring_never_resumes(tmp_path, monkeypatch, snapshots,
                                                                                    point, how):
    snap = snapshots[point]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    keep = (out / "plan.json").read_bytes()
    before = _invalid_rows(root)
    _damage(out, how)
    sp = Spies(monkeypatch)
    _no_stage_work(monkeypatch)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=INVALID_STOP) as ei:
        t.gate(root, "plan damage")
    sp.assert_zero()
    assert _invalid_rows(root) == before + 1, str(ei.value)
    assert c.load_abort(out) is not None
    if point == "after-audit":                       # no registration exists: the gate's own audit bound-input INVALID
        assert s1_first_invalid(root) == "reason/stage-replaced"
        assert re.search(STAGE_REPLACED_PLAN, str(ei.value)), str(ei.value)
    _restored_stays_invalid(root, snap["now"], keep)


@pytest.mark.parametrize("how", ("deleted", "unparseable", "no-trial-id", "changed"))
@pytest.mark.parametrize("fab", ("attest_start.json", "prereg.json", "stop.json"))
def test_a_damaged_plan_with_a_fabricated_registration_file_is_invalid_never_the_b32_refusal(
        tmp_path, monkeypatch, snapshots, fab, how):
    snap = snapshots["after-audit"]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    keep = (out / "plan.json").read_bytes()
    before = _invalid_rows(root)
    _damage(out, how)
    (out / fab).write_bytes(b"{} ")
    sp = Spies(monkeypatch)
    _no_stage_work(monkeypatch)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=INVALID_STOP) as ei:
        t.gate(root, "plan damage + fabricated")
    assert "inconsistent pre-registration state" not in str(ei.value)
    sp.assert_zero()
    assert _invalid_rows(root) == before + 1
    _restored_stays_invalid(root, snap["now"], keep, fab)


@pytest.mark.parametrize("fab", (None, "attest_start.json"))
@pytest.mark.parametrize("point", ("after-audit", "after-opening"))
def test_a_plan_naming_another_trial_id_in_this_trials_own_root_is_invalid(tmp_path, monkeypatch, snapshots, point,
                                                                           fab):
    """Fix round 1 (ruling "T14b I-1" amends brief item 2; old->new: this test asserted the F6.2 refusal before):
    this root holds this trial's journal-bound audit artifacts, so a plan.json naming another trial_id here (an edited
    plan, with or without a fabricated attest_start.json) is this trial's plan changed - INVALID, never resumable.
    Another trial's genuine root keeps the F6.2 refusal (test_fx1_another_trials_genuine_root_...)."""
    snap = snapshots[point]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    keep = (out / "plan.json").read_bytes()
    before = _invalid_rows(root)
    (out / "plan.json").write_bytes(json.dumps(dict(json.loads(keep), trial_id=OTHER)).encode("utf-8"))
    if fab:
        (out / fab).write_bytes(b"{} ")
    sp = Spies(monkeypatch)
    _no_stage_work(monkeypatch)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=INVALID_STOP) as ei:
        t.gate(root, "another trial_id here")
    assert not re.search(FOREIGN, str(ei.value)) and "inconsistent pre-registration state" not in str(ei.value)
    sp.assert_zero()
    assert _invalid_rows(root) == before + 1 and c.load_abort(out) is not None
    _restored_stays_invalid(root, snap["now"], keep, *((fab,) if fab else ()))


def _plan_reads(monkeypatch, plan: Path, results: list) -> None:
    """Every read of `plan` (read_bytes / read_text) returns the next item of `results` (bytes, or an exception
    instance to raise); the last item repeats. Returns the function that restores the real methods."""
    real_b, real_t = Path.read_bytes, Path.read_text
    seq = list(results)

    def nxt(self):
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, BaseException):
            raise item
        return item

    def rb(self):
        return nxt(self) if Path(self) == plan else real_b(self)

    def rt(self, *a, **kw):
        return nxt(self).decode("utf-8") if Path(self) == plan else real_t(self, *a, **kw)
    monkeypatch.setattr(Path, "read_bytes", rb)
    monkeypatch.setattr(Path, "read_text", rt)

    def restore():
        monkeypatch.setattr(Path, "read_bytes", real_b)
        monkeypatch.setattr(Path, "read_text", real_t)
    return restore


@pytest.mark.parametrize("point", ("after-audit", "after-opening"))
def test_a_transient_os_error_on_the_plan_read_refuses_with_no_row(tmp_path, monkeypatch, snapshots, point):
    snap = snapshots[point]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    before = _invalid_rows(root)
    restore = _plan_reads(monkeypatch, out / "plan.json", [PermissionError(13, "sharing violation")])
    sp = Spies(monkeypatch)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=UNREADABLE):
        t.gate(root, "transient")
    sp.assert_zero()
    restore()
    assert _invalid_rows(root) == before and c.load_abort(out) is None
    with _Clock(snap["now"]):
        assert t.gate(root, "after the error cleared").state == "ACTIVE"


@pytest.mark.parametrize("reads", ("bad-then-other-bad", "absent-then-intact", "bad-then-intact"))
def test_a_re_read_that_differs_refuses_with_no_row(tmp_path, monkeypatch, snapshots, reads):
    snap = snapshots["after-audit"]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    keep = (out / "plan.json").read_bytes()
    before = _invalid_rows(root)
    first = FileNotFoundError(2, "no such file") if reads.startswith("absent") else b"{not JSON"
    second = b"{also not JSON" if reads == "bad-then-other-bad" else keep
    restore = _plan_reads(monkeypatch, out / "plan.json", [first, second])
    sp = Spies(monkeypatch)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=NOT_CONFIRMED):
        t.gate(root, "re-read")
    sp.assert_zero()
    restore()
    assert _invalid_rows(root) == before and c.load_abort(out) is None
    with _Clock(snap["now"]):
        assert t.gate(root, "settled").state == "ACTIVE"


def test_the_invalidation_never_recreates_a_vanished_s1_out(tmp_path, monkeypatch, snapshots):
    """F6.6: if s1_out vanishes after the TRIAL-INVALID commits, the gate's local abort is skipped, never written into
    a recreated tree."""
    snap = snapshots["after-audit"]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    before = _invalid_rows(root)
    _damage(out, "deleted")
    real = t.invalidate

    def then_vanish(*a, **kw):
        res = real(*a, **kw)
        shutil.rmtree(out)
        return res
    monkeypatch.setattr(t, "invalidate", then_vanish)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=STAGE_REPLACED_PLAN):
        t.gate(root, "vanishing tree")
    assert not out.exists() and _invalid_rows(root) == before + 1


@pytest.mark.parametrize("how", DAMAGES)
def test_control_before_any_journal_row_a_damaged_plan_is_still_a_plain_refusal(tmp_path, monkeypatch, how):
    """Pre-audit (the plan and its AUDIT-ACK, no journal row, F6.4): unchanged - the F6.2 refusal with no row;
    restoring resumes."""
    import a3_helpers as h
    h.plan_only(tmp_path, c.aware(START))
    out = tmp_path / "s1_out"
    keep = (out / "plan.json").read_bytes()
    _damage(out, how)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"plan\.json trial_id None differs from the AUDIT-ACK's .* \(F6\.2\)"):
        t.gate(tmp_path, "pre-audit")
    sp.assert_zero()
    assert _invalid_rows(tmp_path) == 0 and c.load_abort(out) is None
    (out / "plan.json").write_bytes(keep)
    assert t.gate(tmp_path, "restored").state == "ACTIVE"


def test_control_before_any_journal_row_a_changed_plan_passes_the_gate(tmp_path):
    """Pre-audit control: a re-formatted plan with the same trial_id is not judged by the gate before any row (the
    audit's own A8.1 plan binding refuses later); unchanged by Task 14b."""
    import a3_helpers as h
    h.plan_only(tmp_path, c.aware(START))
    _damage(tmp_path / "s1_out", "changed")
    assert t.gate(tmp_path, "pre-audit").state == "ACTIVE"
    assert _invalid_rows(tmp_path) == 0


# ------------------------------------------------------------------------------------------------ fix round 1
# task-14b-review-verdict.md I-1, I-2, M-1..M-3; progress.md rulings "T14b I-1" (amends brief item 2), "T14b I-2".
ANY_FOREIGN = r"plan\.json trial_id '[0-9a-f-]+' differs from the AUDIT-ACK's [0-9a-f-]+ \(F6\.2\)"


def _plan_of(snapshots, key) -> bytes:
    return (snapshots[key]["root"] / "s1_out" / "plan.json").read_bytes()


@pytest.mark.parametrize("point", POINTS)
def test_fx1_another_trials_plan_swapped_into_this_root_is_invalid_and_never_resumes(tmp_path, monkeypatch,
                                                                                     snapshots, point):
    """I-1 (ruling "T14b I-1"): this root still holds this trial's journal-bound audit artifacts (its staging
    intent.json / committed audit members), so another trial's plan.json here is THIS trial's plan changed - INVALID,
    not the foreign-root refusal; restoring the plan never resumes."""
    snap = snapshots[point]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    keep = (out / "plan.json").read_bytes()
    other = _plan_of(snapshots, "foreign-after-audit")
    assert json.loads(other)["trial_id"] != json.loads(keep)["trial_id"]
    before = _invalid_rows(root)
    (out / "plan.json").write_bytes(other)
    sp = Spies(monkeypatch)
    _no_stage_work(monkeypatch)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=INVALID_STOP) as ei:
        t.gate(root, "swapped plan")
    sp.assert_zero()
    assert _invalid_rows(root) == before + 1 and c.load_abort(out) is not None
    if point == "after-audit":
        assert s1_first_invalid(root) == "reason/stage-replaced"
        assert re.search(STAGE_REPLACED_PLAN, str(ei.value)) and "names another trial_id" in str(ei.value)
    _restored_stays_invalid(root, snap["now"], keep)


@pytest.mark.parametrize("point", FOREIGN_POINTS)
def test_fx1_another_trials_genuine_root_is_refused_and_never_invalidates_the_open_trial(tmp_path, monkeypatch,
                                                                                        snapshots, point):
    """I-1 regression guard: gating another trial's whole root (no staging or committed audit member of the open
    trial) under the open trial's mailbox is the F6.2 refusal with no row - also after the opening, where 56f8cb2's
    legacy detector INVALIDATED the open trial (registration-artifact)."""
    snap = snapshots[point]
    mine = _copy(tmp_path, monkeypatch, snap, "mine")                       # the open trial (its mailbox)
    theirs = _copy(tmp_path, monkeypatch, snapshots[f"foreign-{point}"], "theirs", mailbox=False)
    before = _invalid_rows(mine)
    sp = Spies(monkeypatch)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=ANY_FOREIGN):
        t.gate(theirs, "another trial's root")
    sp.assert_zero()
    assert _invalid_rows(mine) == before
    assert c.load_abort(theirs / "s1_out") is None and c.load_abort(mine / "s1_out") is None
    with _Clock(snap["now"]):
        assert t.gate(mine, "the open trial").state == "ACTIVE"


def test_fx1_an_os_error_reading_this_trials_audit_commitment_refuses_with_no_row(tmp_path, monkeypatch, snapshots):
    """I-1: the swap decider reads s1_staging/<trial>/audit/intent.json; any OSError other than absence there refuses
    with no row (never INVALID, never the foreign verdict)."""
    snap = snapshots["after-audit"]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    keep = (out / "plan.json").read_bytes()
    before = _invalid_rows(root)
    intent = sg.staging_dir(root, json.loads(keep)["trial_id"], "audit") / "intent.json"
    assert intent.is_file()
    (out / "plan.json").write_bytes(_plan_of(snapshots, "foreign-after-audit"))
    real = Path.read_bytes

    def rb(self):
        if Path(self) == intent:
            raise PermissionError(13, "sharing violation")
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", rb)
    sp = Spies(monkeypatch)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=r"audit commitment unreadable \(PermissionError\).*"
                                                              r"refused with no row"):
        t.gate(root, "decider error")
    sp.assert_zero()
    monkeypatch.setattr(Path, "read_bytes", real)
    assert _invalid_rows(root) == before and c.load_abort(out) is None
    (out / "plan.json").write_bytes(keep)
    with _Clock(snap["now"]):
        assert t.gate(root, "after the error cleared").state == "ACTIVE"


@pytest.mark.parametrize("how", ("deleted", "unparseable"))
@pytest.mark.parametrize("point", FOREIGN_POINTS)
def test_fx1_a_legacy_stage_lock_next_to_a_damaged_plan_never_pre_empts_the_invalid(tmp_path, monkeypatch,
                                                                                   snapshots, point, how):
    """I-2 (ruling "T14b I-2"): s1_out/stage.lock (fabricated, or left by a crashed legacy publication) makes the
    legacy detector refuse; with the plan damage confirmed, that refusal must not end the gate (it committed no
    TRIAL-INVALID), so the stage-replaced INVALID follows; removing the lock and restoring the plan never resumes."""
    snap = snapshots[point]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    keep = (out / "plan.json").read_bytes()
    before = _invalid_rows(root)
    _damage(out, how)
    (out / "stage.lock").write_text(json.dumps({"pid": 4242, "utc": "2026-10-20T00:00:00+00:00"}), encoding="utf-8")
    sp = Spies(monkeypatch)
    _no_stage_work(monkeypatch)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=STAGE_REPLACED_PLAN):
        t.gate(root, "stage.lock + plan damage")
    sp.assert_zero()
    assert _invalid_rows(root) == before + 1 and s1_first_invalid(root) == "reason/stage-replaced"
    _restored_stays_invalid(root, snap["now"], keep, "stage.lock")


@pytest.mark.parametrize("plan", ("intact", "unparseable"))
def test_fx1_a_live_audit_owner_at_intent_pending_for_an_intact_plan_invalid_for_a_damaged_one(tmp_path, monkeypatch,
                                                                                               plan):
    """M-2 (concern 3) + M-1: a live owner (a real child process) holds the audit stage lock after its INTENT. An
    intact plan: the F4 table's "pending" (no row). A damaged plan: INVALID (stage-replaced) - F4.1 (the INTENT
    commits plan.json's sha256), F6.2, F9 - and the message names the audit stage's journal state (INTENT), never
    "CREATED"."""
    import subprocess
    import sys
    import a3_helpers as h
    h.plan_only(tmp_path, c.aware(START))
    at = c.aware(START) - timedelta(days=12, hours=3)
    p = subprocess.Popen([sys.executable, "-I", str(Path(h.__file__).resolve()), str(tmp_path), "audit",
                          "hold-after-intent", at.isoformat()],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "held", p.stderr.read()
        if plan == "unparseable":
            _damage(tmp_path / "s1_out", "unparseable")
        sp = Spies(monkeypatch)
        if plan == "intact":
            with pytest.raises(SystemExit, match=r"stage audit: pending"):
                t.gate(tmp_path, "while the audit runs")
            assert _invalid_rows(tmp_path) == 0
        else:
            with pytest.raises(SystemExit, match=STAGE_REPLACED_PLAN) as ei:
                t.gate(tmp_path, "while the audit runs")
            assert "the audit stage is at INTENT" in str(ei.value) and "CREATED" not in str(ei.value)
            assert _invalid_rows(tmp_path) == 1 and s1_first_invalid(tmp_path) == "reason/stage-replaced"
        sp.assert_zero()
    finally:
        p.stdin.close()
        p.communicate(timeout=60)


def test_fx1_s1_out_vanishing_between_the_plan_reads_is_lost_not_stage_replaced(tmp_path, monkeypatch, snapshots):
    """M-3 (F6.6 precedence): the tree disappears after the gate's LOST check, during the plan reads - INVALID
    (LOST), and s1_out is never recreated."""
    snap = snapshots["after-audit"]
    root = _copy(tmp_path, monkeypatch, snap)
    out = root / "s1_out"
    plan = out / "plan.json"
    before = _invalid_rows(root)
    real = Path.read_bytes
    gone = []

    def rb(self):
        if Path(self) == plan and not gone:
            gone.append(True)
            shutil.rmtree(out)                           # the whole tree vanishes during the first plan read
            raise FileNotFoundError(2, "no such file")
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", rb)
    with _Clock(snap["now"]), pytest.raises(SystemExit, match=r"s1_out is gone .*INVALID \(LOST\)"):
        t.gate(root, "vanishing during the reads")
    assert gone and not out.exists()
    assert _invalid_rows(root) == before + 1 and s1_first_invalid(root) == "reason/LOST"
