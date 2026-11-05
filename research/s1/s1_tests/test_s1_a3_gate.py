"""Addendum 3 rev 5 F0.6 (gates read the open trial, its state and the bundle before any callback, capture, provider
request or pricing), F6.4 (bundle), F6.6 (total loss), F7.5 (closure), F10 Identity and Other/pre-audit. Behavioural
RED against the Task 5 gate stub (s1_evidence/a3/t5_red.txt). Synthetic only; spies on every refusal path."""
import json
import re
import shutil
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_trial as t
from conftest import (S1_RECEIPT, Spies, _Clock, s1_ack, s1_jappend, s1_mailbox, s1_plan_audit, s1_register,
                      s1_state)

START = "2026-10-26T13:30:00+00:00"
KEYS = ("KEYID-dummy-123", "SECRET-dummy-456")
OTHER = "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def journal(root):
    tr = t.trials(t.scan(mb(root)))
    return {tid: j.read_trial(tid, x.genesis, mb(root)) for tid, x in tr.items()}


def kinds(root):
    return [(r_.kind, r_.subject) for rows in journal(root).values() for r_ in rows]


def raw_kinds(root):
    """Every journal row's kind, read without chain verification (the damaged-chain cases cannot be verified)."""
    return [r_.kind for r_ in j.read_all(mb(root))]


def commands(root, sp, sch):
    lg = Path(root) / "ledger.sqlite3"
    after = lambda: sch + timedelta(seconds=30)                                 # noqa: E731
    return {
        "do_audit": lambda: k.do_audit(root, "audit-ack", sp.client(), KEYS),
        "opening": lambda: ck.run_opening_checkpoint(root, lg, sch, sp.receipt(), sp.process(), Path(root) / "c.log",
                                                     now=after),
        "attest_start": lambda: r.attest_start(root, r.START_STATEMENT, S1_RECEIPT),
        "prereg": lambda: r.do_prereg(root, "run-ack", S1_RECEIPT),
        "checkpoint": lambda: ck.run_checkpoint(root, lg, sch, sp.receipt(), sp.process(), Path(root) / "c.log",
                                                now=after),
        "attest_stop": lambda: r.attest_stop(root, r.STOP_STATEMENT),
        "final_plan": lambda: k.write_final_plan(root),
        "final": lambda: k.do_final(root, "acq-ack", sp.client(), KEYS),
        "final_snapshot": lambda: ck.run_final_snapshot(root, lg, now=after),
        "score": lambda: r.score(root, "score-ack"),
    }


@pytest.mark.parametrize("name", ["do_audit", "opening", "attest_start", "prereg", "checkpoint", "attest_stop",
                                  "final_plan", "final", "final_snapshot", "score"])
def test_every_command_reads_trial_state_and_bundle_before_any_callback(tmp_path, monkeypatch, name):
    s1_plan_audit(tmp_path, START, journal=False)
    con = sqlite3.connect(mb(tmp_path))
    con.execute("DELETE FROM messages")                     # the test removes the AUDIT-ACK: zero open trials
    con.commit()
    con.close()
    sp = Spies(monkeypatch)
    sch = c.aware(START) + timedelta(hours=7, minutes=15)
    with pytest.raises(t.Refusal, match="zero open trials"):
        commands(tmp_path, sp, sch)[name]()
    sp.assert_zero()


def test_one_valid_open_trial_authorizes_a_stage(tmp_path):
    s1_state(tmp_path, START)
    gv = t.gate(tmp_path, "positive control")
    assert gv.state == "ACTIVE" and gv.rows and gv.trial.trial_id == c.load_json(gv.out / "plan.json")["trial_id"]


def test_wrong_role_close_is_ignored_and_the_trial_stays_open(tmp_path):              # rows 238, 330 (E4.4)
    s1_state(tmp_path, START)
    m = mb(tmp_path)
    ln = t.token("S1-CLOSE-ACK", tmp_path, mailbox=m, reason="WITHDRAWN", evidence_sha256="e" * 64)
    con = sqlite3.connect(m)
    con.execute("INSERT INTO messages VALUES ('c-claude','claude','codex','experiments-prereg',?,?,NULL)",
                (ln, c.aware("2026-10-25T23:00:00+00:00").timestamp()))
    con.commit()
    con.close()
    gv = t.gate(tmp_path, "wrong-role close is no candidate")
    assert gv.state == "ACTIVE" and gv.trial.closed is None


def test_gate_invalid_rows_use_a_fresh_operation_identity(tmp_path):                   # row 313 (OQ-2)
    s1_state(tmp_path, START)
    shutil.rmtree(tmp_path / "s1_out")                                  # the TEST removes its tmp tree: INVALID (LOST)
    with pytest.raises(t.Refusal, match="LOST"):
        t.gate(tmp_path, "tree lost")
    tr = t.trials(t.scan(mb(tmp_path)))
    (only,) = tr.values()
    rows = j.read_trial(only.trial_id, only.genesis, mb(tmp_path))
    inv = [x for x in rows if x.kind == "TRIAL-INVALID"]
    assert len(inv) == 1
    earlier = [y for y in rows if y.seq < inv[0].seq]
    assert earlier and all(inv[0].op != y.op and inv[0].actor != y.actor for y in earlier)


def _damage(root, case):
    """Mutate the tmp mailbox / journal / plan for one F10 Identity refusal case (test data only)."""
    m = mb(root)
    tr = t.open_trial(m)
    rows = j.read_trial(tr.trial_id, tr.genesis, m)
    at = c.aware("2026-10-25T23:00:00+00:00")
    if case == "zero-open":
        s1_ack(root, "close", "S1-CLOSE-ACK", at, reason="WITHDRAWN", evidence_sha256="e" * 64)
    elif case == "two-open":
        other = tr.audit.line.replace(tr.trial_id, OTHER)
        s1_mailbox(root, "audit-2", other, at)
    elif case == "duplicate-trial-id":
        s1_mailbox(root, "audit-dup", tr.audit.line, at)
    elif case == "wrong-bundle-close":
        s1_ack(root, "close", "S1-CLOSE-ACK", at, reason="WITHDRAWN", evidence_sha256="e" * 64,
               bundle_sha256="f" * 64)
    elif case == "close-before-audit":
        s1_ack(root, "close", "S1-CLOSE-ACK", c.aware("2026-01-01T00:00:00+00:00"), reason="WITHDRAWN",
               evidence_sha256="e" * 64)
    elif case == "two-opening-acks":
        em = tr.acks["S1-OPENING-ACK"].fields["evidence_manifest_sha256"]          # (revision 1: derived value)
        s1_mailbox(root, "opening-2", tr.acks["S1-OPENING-ACK"].line.replace("evidence_manifest_sha256=" + em,
                                                                             "evidence_manifest_sha256=" + "d" * 64),
                   at)
    elif case == "identical-duplicate-ack":
        s1_mailbox(root, "run-ack-2", tr.acks["S1-RUN-ACK"].line, at)
    elif case == "broken-prev":
        con = sqlite3.connect(m)
        bad = tr.acks["S1-RUN-ACK"].line.replace(f"prev={tr.acks['S1-OPENING-ACK'].mailbox_id}",
                                                 f"prev={tr.audit.mailbox_id}")
        con.execute("UPDATE messages SET body=? WHERE id='run-ack'", (bad,))   # the TEST edits its tmp mailbox
        con.commit()
        con.close()
    elif case == "closed-trial-same-bundle-ack":                # another (closed) trial's same-bundle RUN-ACK id
        s1_mailbox(root, "other-audit", tr.audit.line.replace(tr.trial_id, OTHER), at - timedelta(days=30))
        s1_mailbox(root, "not-this-trials-run-ack", tr.acks["S1-RUN-ACK"].line.replace(tr.trial_id, OTHER),
                   at - timedelta(days=29))
        s1_mailbox(root, "other-close", " ".join(["S1-CLOSE-ACK", f"trial_id={OTHER}", f"bundle_sha256={tr.bundle}",
                                                  "prev=not-this-trials-run-ack", "reason=WITHDRAWN",
                                                  "evidence_sha256=" + "e" * 64]), at - timedelta(days=28))
    elif case in ("journal-fork", "journal-gap", "duplicate-seq"):
        con = sqlite3.connect(m)
        r0 = rows[-1]
        if case == "journal-gap":
            con.execute("DELETE FROM messages WHERE id=?", (rows[1].mailbox_id,))
        else:
            dup = r0.line if case == "duplicate-seq" else r0.line.replace(f"op={r0.op}", f"op={'7' * 32}")
            con.execute("INSERT INTO messages VALUES ('jdup','s1','codex','experiments-s1-journal',?,?,NULL)",
                        (dup, r0.created + 1))
        con.commit()
        con.close()


IDENTITY = {"zero-open": "zero open trials",
            "two-open": "2 open trials",
            "duplicate-trial-id": "is on 2 AUDIT-ACKs",
            "wrong-bundle-close": "refused (bundle differs): the trial stays open",
            "close-before-audit": "refused (before the AUDIT-ACK",
            "two-opening-acks": "2 S1-OPENING-ACK for trial",
            "identical-duplicate-ack": "2 S1-RUN-ACK for trial",
            "broken-prev": "is not the S1-OPENING-ACK",
            "closed-trial-same-bundle-ack": "'not-this-trials-run-ack' is not the trial's S1-RUN-ACK",
            "journal-fork": "duplicate seq (a fork)",
            "journal-gap": "seq gap",
            "duplicate-seq": "duplicate seq (a fork)",
            "plan-trial-id-differs": f"plan.json trial_id '{OTHER}' differs from the AUDIT-ACK's"}


@pytest.mark.parametrize("case", sorted(IDENTITY))
def test_identity_refusals_have_zero_callbacks(tmp_path, monkeypatch, case):
    if case == "plan-trial-id-differs":
        s1_plan_audit(tmp_path, START, journal=False)
        p = tmp_path / "s1_out" / "plan.json"
        plan = json.loads(p.read_text(encoding="utf-8"))
        plan["trial_id"] = OTHER
        p.write_text(json.dumps(plan), encoding="utf-8")     # the TEST edits its tmp plan
    else:
        s1_state(tmp_path, START)
        _damage(tmp_path, case)
    before = raw_kinds(tmp_path)          # A3 Task 6: the fixture's opening slot has its SLOT-INTENT/QUALIFIED rows
    sp = Spies(monkeypatch)
    sch = c.aware(START) + timedelta(hours=7, minutes=15)
    with pytest.raises(t.Refusal, match=re.escape(IDENTITY[case])):
        if case == "closed-trial-same-bundle-ack":
            with _Clock(c.aware(START) - timedelta(hours=20)):
                r.do_prereg(tmp_path, "not-this-trials-run-ack", S1_RECEIPT)
        else:
            commands(tmp_path, sp, sch)["checkpoint"]()
    sp.assert_zero()
    assert raw_kinds(tmp_path) == before                      # the refused command appended no row (no SLOT-INTENT)


def test_bundle_mismatch_before_any_journal_row_is_a_refusal(tmp_path, monkeypatch):
    s1_plan_audit(tmp_path, START, journal=False)
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    with pytest.raises(t.Refusal, match="no journal row yet"):
        t.gate(tmp_path, "probe")
    assert kinds(tmp_path) == [] and c.load_abort(tmp_path / "s1_out") is None


def test_bundle_mismatch_after_any_journal_row_is_invalid_bundle(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    with pytest.raises(t.Refusal, match=r"INVALID \(bundle\)"):
        t.gate(tmp_path, "probe")
    assert kinds(tmp_path)[-1] == ("TRIAL-INVALID", "reason/bundle")
    assert c.load_abort(tmp_path / "s1_out")["reason"] == "bundle"


def test_total_loss_is_invalid_lost_and_restoring_stays_invalid(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    shutil.copytree(out, tmp_path / "backup")
    shutil.rmtree(out)                                          # the TEST deletes its tmp s1_out
    with pytest.raises(t.Refusal, match=r"INVALID \(LOST\)"):
        t.gate(tmp_path, "probe")
    assert not out.exists()                                     # LOST: s1_out is never recreated by the gate
    shutil.copytree(tmp_path / "backup", out)
    (out / "aborted.json").unlink(missing_ok=True)
    sp = Spies(monkeypatch)
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/LOST\)"):
        commands(tmp_path, sp, c.aware(START) + timedelta(hours=7, minutes=15))["checkpoint"]()
    sp.assert_zero()
    assert ("TRIAL-INVALID", "reason/LOST") in kinds(tmp_path)


def test_invalid_is_irreversible(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    s1_jappend(tmp_path, "TRIAL-INVALID", "reason/registration-artifact", at=c.aware(START) - timedelta(hours=10),
               detail=j.detail_of({"synthetic": "violation"}))
    for attempt in range(2):
        (tmp_path / "s1_out" / "aborted.json").unlink(missing_ok=True)
        sp = Spies(monkeypatch)
        with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/registration-artifact\)"):
            commands(tmp_path, sp, c.aware(START) + timedelta(hours=7, minutes=15))["checkpoint"]()
        sp.assert_zero()


def test_journal_state_governs_over_local_files(tmp_path):
    s1_state(tmp_path, START)
    s1_jappend(tmp_path, "TRIAL-INVALID", "reason/LOST", at=c.aware(START) - timedelta(hours=10),
               detail=j.detail_of({"synthetic": "lost"}))
    assert c.load_abort(tmp_path / "s1_out") is None            # no local witness at all
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/LOST\)"):
        t.gate(tmp_path, "probe")


def test_closure_never_erases_invalidity_or_reuses_the_journal(tmp_path):
    s1_state(tmp_path, START)
    s1_jappend(tmp_path, "TRIAL-INVALID", "reason/LOST", at=c.aware(START) - timedelta(hours=10),
               detail=j.detail_of({"synthetic": "lost"}))
    first_invalid = journal(tmp_path)
    s1_ack(tmp_path, "close", "S1-CLOSE-ACK", c.aware(START) - timedelta(hours=9), reason="INVALID",
           evidence_sha256=[r_ for rows in first_invalid.values() for r_ in rows if r_.kind == "TRIAL-INVALID"][0].sha)
    second = tmp_path / "second"
    with _Clock(c.aware(START) - timedelta(days=20)):
        k.write_plan(second, c.aware(START) + timedelta(days=7), "2026-10-30", [], "2026-10-01", mailbox=mb(tmp_path))
    s1_mailbox(tmp_path, "audit-2", c.audit_token(second / "s1_out"), c.aware(START) - timedelta(hours=8))
    tr = t.open_trial(mb(tmp_path))
    assert tr.trial_id == c.load_json(second / "s1_out" / "plan.json")["trial_id"]
    assert j.read_trial(tr.trial_id, tr.genesis, mb(tmp_path)) == [] and set(tr.acks) == set()
    assert j.trial_state(list(first_invalid.values())[0]) == "INVALID"


def test_before_the_audit_ack_the_opening_and_start_are_blocked(tmp_path, monkeypatch):
    with _Clock(c.aware(START) - timedelta(days=14)):
        k.write_plan(tmp_path, c.aware(START), "2026-10-23", [], "2026-10-01")
    sp = Spies(monkeypatch)
    sch = c.aware("2026-10-23T20:45:00+00:00")
    for name in ("opening", "attest_start"):
        with pytest.raises(t.Refusal, match="zero open trials"):
            commands(tmp_path, sp, sch)[name]()
    sp.assert_zero()


# ---------------------------------------------------------------- controller carry-forwards (Task 2 / Task 4 reviews)
def _ctx_append(root, kind, subject, ctx_fn, at, detail=None):
    tr = t.open_trial(mb(root))
    return j.append(tr.trial_id, tr.genesis, j.Request(kind, subject, j.new_nonce(), j.new_nonce(), detail=detail),
                    ctx_fn, mailbox=mb(root), clock=lambda: at)


def test_product_context_fails_closed_without_a_slot_gate_or_stage_check(tmp_path):
    """Task 2 carry-forward: a product Context is never built with slot_gate or stage_check unset."""
    s1_state(tmp_path, START)
    tr = t.open_trial(mb(tmp_path))
    at = c.aware(START) - timedelta(hours=10)
    far = at + timedelta(days=1)
    times = lambda s: (far, far)                                               # noqa: E731
    slot = j.slot_subject(c.aware(START) + timedelta(hours=7))

    def ctx(**kw):
        fn = t.product_context(tr, **kw)
        return lambda rows, con: (lambda x: (setattr(x, "slot_times", times), x)[1])(fn(rows, con))
    no_gate = _ctx_append(tmp_path, "SLOT-INTENT", slot, ctx(), at)
    assert (no_gate.outcome, no_gate.row) == ("REFUSE", None) and "fail closed" in no_gate.reason
    stage = j.stage_subject("start_attest")
    no_check = _ctx_append(tmp_path, "STAGE-INTENT", stage, ctx(stage_gate=lambda rows, g: None), at,
                           detail=j.detail_of({"x": 1}))
    assert (no_check.outcome, no_check.row) == ("REFUSE", None) and "fail closed" in no_check.reason
    ok = _ctx_append(tmp_path, "SLOT-INTENT", slot, ctx(slot_gate=lambda rows, s: None), at)
    assert ok.outcome == "APPEND" and ok.row.kind == "SLOT-INTENT"                         # positive control


def test_product_context_reads_closed_inside_the_transaction(tmp_path):
    s1_state(tmp_path, START)
    tr = t.open_trial(mb(tmp_path))
    s1_ack(tmp_path, "close", "S1-CLOSE-ACK", c.aware("2026-10-25T23:00:00+00:00"), reason="WITHDRAWN",
           evidence_sha256="e" * 64)
    res = j.append(tr.trial_id, tr.genesis, j.Request("TRIAL-INVALID", "reason/LOST", j.new_nonce(), j.new_nonce(),
                                                      detail=j.detail_of({"x": 1})),
                   t.product_context(tr, slot_gate=lambda rows, s: None, stage_check=lambda rows, s, i: None),
                   mailbox=mb(tmp_path), clock=lambda: c.aware(START))
    assert (res.outcome, res.row) == ("REFUSE", None) and "CLOSED" in res.reason


@pytest.mark.parametrize("where", ["attest_start", "prereg", "attest_stop", "score"])
def test_a_plan_without_trial_id_refuses(tmp_path, where):
    """Task 4 review M2: a plan with no trial_id is a refusal everywhere, never a KeyError or a silent None. (Before
    any journal row: with rows, the gate first runs the legacy detector, which records the registration-artifact
    violation: test_registration_violation_commits_trial_invalid_first.)"""
    s1_plan_audit(tmp_path, START, journal=False)
    p = tmp_path / "s1_out" / "plan.json"
    plan = json.loads(p.read_text(encoding="utf-8"))
    del plan["trial_id"]
    p.write_text(json.dumps(plan), encoding="utf-8")         # the TEST edits its tmp plan
    call = {"attest_start": lambda: r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT),
            "prereg": lambda: r.do_prereg(tmp_path, "run-ack", S1_RECEIPT),
            "attest_stop": lambda: r.attest_stop(tmp_path, r.STOP_STATEMENT),
            "score": lambda: r.score(tmp_path, "score-ack")}[where]
    with pytest.raises(t.Refusal, match="plan.json trial_id None differs"):
        call()
    with pytest.raises(t.Refusal, match="plan.json has no trial_id"):
        r._plan_trial_id(tmp_path / "s1_out")
    with pytest.raises(t.Refusal, match="plan.json has no trial_id"):
        r._score(tmp_path / "s1_out")


def test_explicit_mailbox_is_used_for_token_and_ack(tmp_path, monkeypatch):
    """Task 4 review M1: run_token / acquire_token / score_token and do_prereg use an explicit mailbox for both the
    token and the ACK (s1_common.MAILBOX pointed at a missing file: any default read would be an outage)."""
    info = s1_state(tmp_path, START)
    monkeypatch.setattr(c, "MAILBOX", tmp_path / "absent" / "mailbox.sqlite3")
    with pytest.raises(t.Refusal, match="mailbox unreadable"):
        r.run_token(tmp_path)
    assert r.run_token(tmp_path, mailbox=mb(tmp_path)).startswith("S1-RUN-ACK trial_id=")
    with pytest.raises(t.Refusal, match="no S1-PREREG-ACK"):
        k.acquire_token(tmp_path, mailbox=mb(tmp_path))
    with pytest.raises(t.Refusal, match="no S1-ACQUIRE-ACK"):
        r.score_token(tmp_path, mailbox=mb(tmp_path))
    with _Clock(info["prereg_at"]):
        pr = r.do_prereg(tmp_path, "run-ack", S1_RECEIPT, mailbox=mb(tmp_path))
    assert pr["ack"]["ack_id"] == "run-ack"
    assert not (tmp_path / "absent").exists()


def test_registration_violation_commits_trial_invalid_first(tmp_path):
    """OQ-19: a confirmed legacy registration-artifact violation first commits TRIAL-INVALID (registration-artifact),
    then the local abort; the next command refuses at the gate with no work."""
    s1_register(tmp_path, START)
    (tmp_path / "s1_out" / "prereg.json").unlink()                       # the TEST deletes its tmp artifact
    with pytest.raises(SystemExit, match="registration artifact"):
        r.attest_stop(tmp_path, r.STOP_STATEMENT)
    assert ("TRIAL-INVALID", "reason/registration-artifact") in kinds(tmp_path)
    assert c.load_abort(tmp_path / "s1_out")["reason"] == c.REGISTRATION_ARTIFACT
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/registration-artifact\)"):
        r.attest_stop(tmp_path, r.STOP_STATEMENT)


# ---------------------------------------------------------------- Task 5 fix round 1 (review I-1, I-2, M-3, M-5, M-6)
def test_total_loss_then_outage_then_mailbox_back_never_resumes(tmp_path):
    """Review I-1 (the reviewer's scenario): the audit stage's rows exist; the TEST deletes s1_out; the first command
    meets a mailbox outage; the mailbox returns; the operator restores the files. The gate never writes into or
    recreates s1_out on any path, so the loss is still observed (INVALID (LOST)) and the trial never comes back
    ACTIVE (F6.6)."""
    s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    shutil.copytree(out, tmp_path / "backup")
    shutil.rmtree(out)
    mb(tmp_path).rename(tmp_path / "mailbox.away")                          # the TEST makes its tmp mailbox unreadable
    with pytest.raises(t.Refusal, match="mailbox unreadable"):
        t.gate(tmp_path, "outage")
    assert not out.exists()
    (tmp_path / "mailbox.away").rename(mb(tmp_path))
    with pytest.raises(t.Refusal, match=r"INVALID \(LOST\)"):
        t.gate(tmp_path, "mailbox back")
    assert not out.exists()
    shutil.copytree(tmp_path / "backup", out)
    with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/LOST\)"):
        t.gate(tmp_path, "restored")
    assert ("TRIAL-INVALID", "reason/LOST") in kinds(tmp_path)


def test_total_loss_with_a_bundle_mismatch_is_lost_and_never_recreates_s1_out(tmp_path, monkeypatch):
    """Review I-1 second variant: total loss + a bundle mismatch: INVALID (LOST); s1_out is not recreated."""
    s1_state(tmp_path, START)
    shutil.rmtree(tmp_path / "s1_out")
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    with pytest.raises(t.Refusal, match=r"INVALID \(LOST\)"):
        t.gate(tmp_path, "probe")
    assert not (tmp_path / "s1_out").exists()


@pytest.mark.parametrize("case", ["zero-open", "outage", "bundle-no-row", "plan-gone"])
def test_no_gate_refusal_writes_into_a_missing_s1_out(tmp_path, monkeypatch, case):
    """Review I-1: refusal records never create s1_out (they go to stderr when the tree is absent)."""
    s1_plan_audit(tmp_path, START, journal=False)
    shutil.rmtree(tmp_path / "s1_out")
    if case == "zero-open":
        con = sqlite3.connect(mb(tmp_path))
        con.execute("DELETE FROM messages")
        con.commit()
        con.close()
    elif case == "outage":
        mb(tmp_path).rename(tmp_path / "mailbox.away")
    elif case == "bundle-no-row":
        monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    why = {"zero-open": "zero open trials", "outage": "mailbox unreadable", "bundle-no-row": "no journal row yet",
           "plan-gone": "plan.json trial_id None differs"}[case]
    with pytest.raises(t.Refusal, match=why):
        t.gate(tmp_path, "probe")
    assert not (tmp_path / "s1_out").exists()


def test_an_invalid_trial_adds_no_repeat_invalid_rows_on_re_entry(tmp_path, monkeypatch):
    """Review M-3: the INVALID state is checked before the bundle: re-entry under a bundle mismatch refuses with the
    first reason and appends no further TRIAL-INVALID row."""
    s1_state(tmp_path, START)
    s1_jappend(tmp_path, "TRIAL-INVALID", "reason/LOST", at=c.aware(START) - timedelta(hours=10),
               detail=j.detail_of({"synthetic": "lost"}))
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    for _ in range(2):
        with pytest.raises(t.Refusal, match=r"trial INVALID \(reason/LOST\)"):
            t.gate(tmp_path, "re-entry")
    assert [k_ for k_, _ in kinds(tmp_path)].count("TRIAL-INVALID") == 1


@pytest.mark.parametrize("name", ["do_audit", "opening", "attest_start", "prereg", "checkpoint", "attest_stop",
                                  "final_plan", "final", "final_snapshot", "score"])
def test_the_gate_is_the_first_call_of_every_command(tmp_path, monkeypatch, name):
    """Review M-5 (row 52, "gate call order recorded first"): a profiler records every Python call made directly from
    the command's own frame; the first one is s1_trial.gate (stubbed here to stop the command at once)."""
    class Stop(Exception):
        pass

    def stub(*a, **kw):
        raise Stop()
    monkeypatch.setattr(t, "gate", stub)
    targets = {k.do_audit.__code__, ck.run_opening_checkpoint.__code__, r.attest_start.__code__,
               r.do_prereg.__code__, ck.run_checkpoint.__code__, r.attest_stop.__code__, k.write_final_plan.__code__,
               k.do_final.__code__, ck.run_final_snapshot.__code__, r.score.__code__}
    calls = []

    def prof(frame, event, arg):
        if event == "call" and frame.f_back is not None and frame.f_back.f_code in targets:
            calls.append(frame.f_code.co_name)
    sp = Spies(monkeypatch)
    cmd = commands(tmp_path, sp, c.aware(START) + timedelta(hours=7, minutes=15))[name]
    sys.setprofile(prof)
    try:
        with pytest.raises(Stop):
            cmd()
    finally:
        sys.setprofile(None)
    assert calls[:1] == ["stub"], calls
    sp.assert_zero()


def test_a_raw_context_without_slot_gate_or_stage_check_fails_closed():
    """Review M-6 (Task 2 carry-forward): a raw j.Context with no slot_gate / stage_check refuses the opening row at
    F0.5 step 5 (fail closed); the earlier steps are unchanged (a repeated STAGE-INTENT is still repeat-stage)."""
    now = c.aware(START)
    far = now + timedelta(days=1)
    bare = j.Context(slot_times=lambda s: (far, far), stage_gate=lambda rows, g: None)
    slot = j.slot_subject(now + timedelta(hours=7))
    d = j.decide([], j.Request("SLOT-INTENT", slot, "1" * 32, "2" * 32), bare, now)
    assert d.outcome == "REFUSE" and "no slot gate supplied (fail closed)" in d.reason
    stage = j.stage_subject("start_attest")
    d = j.decide([], j.Request("STAGE-INTENT", stage, "1" * 32, "2" * 32, detail="a" * 64), bare, now)
    assert d.outcome == "REFUSE" and "no stage check supplied (fail closed)" in d.reason
    ok = j.Context(slot_times=lambda s: (far, far), stage_gate=lambda rows, g: None, slot_gate=lambda rows, s: None,
                   stage_check=lambda rows, s, i: None)
    assert j.decide([], j.Request("SLOT-INTENT", slot, "1" * 32, "2" * 32), ok, now).outcome == "APPEND"
    assert j.decide([], j.Request("STAGE-INTENT", stage, "1" * 32, "2" * 32, detail="a" * 64), ok,
                    now).outcome == "APPEND"
    ln = j.format_line(trial_id=OTHER, seq=1, prev="0" * 64, kind="STAGE-INTENT", subject=stage, detail="a" * 64,
                       op="3" * 32, actor="4" * 32, at=j.fmt_at(now))
    prior = [j.Row(**j.parse_line(ln), line=ln, mailbox_id="m", created=now.timestamp())]
    d = j.decide(prior, j.Request("STAGE-INTENT", stage, "5" * 32, "6" * 32, detail="a" * 64), bare, now)
    assert (d.outcome, d.reason) == ("INVALIDATE", "repeat-stage")


def test_final_snapshot_after_its_own_detection_captures_nothing(tmp_path, monkeypatch):
    """Review I-2 (F8.1/F1): the final snapshot's legacy detector commits TRIAL-INVALID (a changed persisted stop: a
    registration artifact the RUN-ACK verification does not cover, so before the fix the command went on to capture);
    the command then re-reads the trial state and refuses: zero captures, no final_snapshot/."""
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    p = tmp_path / "s1_out" / "stop.json"
    p.write_text(json.dumps(dict(json.loads(p.read_text(encoding="utf-8")), edited=True)),
                 encoding="utf-8")                                          # the TEST edits its tmp artifact
    sp = Spies(monkeypatch)
    with _Clock(st_["snapshot_at"]), pytest.raises(t.Refusal, match=r"trial INVALID \(reason/registration-artifact\)"):
        ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: st_["snapshot_at"])
    sp.assert_zero()
    assert not (tmp_path / "s1_out" / "final_snapshot").exists()
    assert ("TRIAL-INVALID", "reason/registration-artifact") in kinds(tmp_path)
