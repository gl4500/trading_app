"""Addendum 3 rev 5 F1 (graph steps 1-3; STOP prefix; post-STOP rules), F2.1-F2.5 (the stop record, TRIAL-STOP then
stop.json, the publication gap, required evidence after a finalization INTENT), F4.8 rows stop_attest/final_plan,
OQ-8/OQ-9. Behavioural RED against the Task 11 stub (s1_evidence/a3/t11_red.txt). Synthetic seals with real slot rows
(conftest._write_seal); tmp mailbox; spies.

Rows 300-305 (test_stop_dispositions) carry the dispositions of s1_evidence/a3/t11_dispositions.md: their numbers were
ACCEPTED by Codex f33d0501; revision 1's cases (i)-(v), the commit-readiness rule (s1_seal.stop_ready, BLK3-C1) and
the provenance wording (BLK3-C2) are PENDING Codex acceptance (BLK-3): if Codex amends a disposition,
a3_helpers.stop_history's `want` changes before Step 4."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
import a3_helpers as h
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_stage as sg
import s1_trial as t
from conftest import S1_RECEIPT, Spies, _Clock, _write_seal, s1_ack, s1_jappend, s1_state

START = "2026-10-26T13:30:00+00:00"


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    tr = t.open_trial(mb(root))
    return j.read_trial(tr.trial_id, tr.genesis, mb(root))


def stopped(tmp_path, *, attest=False):
    """A lot-count STOP on post-START day 1 (100 default lots bought day 0, sold day 1), decided by decide_stop."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=attest, final=False)
    return st_


def test_stop_record_is_a_pure_function_of_committed_history(tmp_path):
    st_ = stopped(tmp_path)
    out = tmp_path / "s1_out"
    rows = jrows(tmp_path)
    stop = j.first(rows, "TRIAL-STOP")
    pre = [x for x in rows if x.seq < stop.seq]
    a = z.stop_record(out, pre, st_["start"], st_["calendar"], t.open_trial(mb(tmp_path)).bundle)
    b = z.stop_record(out, list(pre), st_["start"], st_["calendar"], t.open_trial(mb(tmp_path)).bundle)
    assert a == b and j.detail_of(a) == stop.detail
    trig = next(x for x in pre if x.subject == a["triggering_slot"] and x.kind in j.TERMINAL)
    assert (a["rule"], a["status"], a["terminal_seq"], a["terminal_line_sha256"], a["determined_utc"]) == (
        "lots", "STOPPED", trig.seq, trig.sha, trig.at)
    assert set(a) >= {"lots", "stop_close", "stop_seal", "stop_seal_sha256", "cohort_row_ids", "seals", "missed",
                      "bundle_sha256", "trial_id"} and "decided_utc" not in a


def test_trial_stop_is_appended_before_stop_json_is_published(tmp_path, monkeypatch):
    seen = {}
    real = c.publish_text_exclusive

    def spy(path, text):
        if Path(path).name == "stop.json":
            seen["rows"] = [x.kind for x in jrows(Path(path).parent.parent)]
        return real(path, text)
    monkeypatch.setattr(c, "publish_text_exclusive", spy)
    stopped(tmp_path)
    assert "TRIAL-STOP" in seen["rows"]
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    assert j.detail_of(json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))) == stop.detail


def test_publication_gap_recovers_matching_bytes(tmp_path, monkeypatch):
    real = c.publish_text_exclusive
    calls = []

    def crash_once(path, text):
        if Path(path).name == "stop.json" and not calls:
            calls.append(1)
            raise KeyboardInterrupt                               # a crash between TRIAL-STOP and stop.json
        return real(path, text)
    monkeypatch.setattr(c, "publish_text_exclusive", crash_once)
    with pytest.raises(KeyboardInterrupt, match=r"^$"):
        stopped(tmp_path)
    monkeypatch.setattr(c, "publish_text_exclusive", real)
    assert not (tmp_path / "s1_out" / "stop.json").exists() and j.first(jrows(tmp_path), "TRIAL-STOP")
    t.gate(tmp_path, "gap recovery")
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    assert j.detail_of(json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))) == stop.detail
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


def test_publication_gap_with_different_history_is_stop_conflict(tmp_path):
    st_ = s1_state(tmp_path, START)                              # no stop rule met yet
    s1_jappend(tmp_path, "TRIAL-STOP", "trial", at=st_["now"], detail=j.detail_of({"forged": True}))
    with pytest.raises(SystemExit, match=r"INVALID \(stop-conflict\)"):
        t.gate(tmp_path, "gap recovery")


@pytest.mark.parametrize("damage", ["deleted", "changed", "unparseable"])
def test_stop_json_damaged_after_a_finalization_intent_is_invalid(tmp_path, monkeypatch, damage):
    stopped(tmp_path, attest=True)                               # stop_attest CREATED: a finalization INTENT exists
    p = tmp_path / "s1_out" / "stop.json"
    keep = p.read_bytes()
    if damage == "deleted":
        p.unlink()
    else:
        p.write_text("{}" if damage == "changed" else "{not JSON", encoding="utf-8")
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "stop evidence")
    p.unlink(missing_ok=True)
    p.write_bytes(keep)
    (tmp_path / "s1_out" / "aborted.json").unlink(missing_ok=True)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "restored")
    sp.assert_zero()


def test_stop_outcome_is_fixed_by_the_journal(tmp_path):
    stopped(tmp_path)
    tr = t.open_trial(mb(tmp_path))
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    same = j.append(tr.trial_id, tr.genesis, j.Request("TRIAL-STOP", "trial", j.new_nonce(), j.new_nonce(),
                                                       detail=stop.detail),
                    t.product_context(tr), mailbox=mb(tmp_path), clock=c.now_utc)
    assert same.outcome == "LOST-RACE"
    other = j.append(tr.trial_id, tr.genesis, j.Request("TRIAL-STOP", "trial", j.new_nonce(), j.new_nonce(),
                                                        detail="9" * 64),
                     t.product_context(tr), mailbox=mb(tmp_path), clock=c.now_utc)
    assert (other.outcome, other.reason) == ("INVALIDATE", "stop-conflict")


def test_a_stop_with_a_different_detail_is_invalid_stop_conflict(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    first = j.first(jrows(tmp_path), "TRIAL-STOP")
    (tmp_path / "s1_out" / "stop.json").unlink()                  # a gap, then a different history is recomputed
    monkeypatch.setattr(z, "stop_record", lambda *a, **kw: {"forged": "different"})
    with pytest.raises(SystemExit, match=r"INVALID \(stop-conflict\)"):
        t.gate(tmp_path, "recompute")
    assert first is not None


def test_stop_rule_not_met_refuses_with_no_row(tmp_path):
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[{"symbol": "A", "qty": 1, "px": 10.0, "buy_day": 0,
                                                             "sell": (1, 9.0)}], stop_attest=False, final=False,
                   stop=False)
    gv = t.gate(tmp_path, "decide")
    assert z.decide_stop(gv, st_["calendar"], st_["start"], lambda: st_["now"], mailbox=mb(tmp_path)) is None
    assert j.first(jrows(tmp_path), "TRIAL-STOP") is None


def test_pending_slot_blocks_the_stop(tmp_path):
    """B1.5 kept (OQ-8): an in-flight slot on an eligible close before the triggering close blocks the stop."""
    st_ = s1_state(tmp_path, START, score_ready=True, seal_days=[1], stop_attest=False, final=False, stop=False)
    day0 = st_["sessions"][0]
    s45 = z.close_of(day0, st_["calendar"]) + timedelta(minutes=45)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(s45), at=s45 + timedelta(seconds=1))
    gv = t.gate(tmp_path, "decide")
    assert z.stop_record(gv.out, gv.rows, st_["start"], st_["calendar"], gv.trial.bundle) is None


def test_stop_lock_is_taken_before_the_journal_read(tmp_path, monkeypatch):
    import s1_locks as L
    order = []
    real_acq, real_read, real_app = L.OwnershipLock.acquire, j.read_trial, j.append
    monkeypatch.setattr(L.OwnershipLock, "acquire", lambda self: order.append(("lock", self.path.name))
                        or real_acq(self))
    monkeypatch.setattr(j, "read_trial", lambda *a, **kw: order.append(("read",)) or real_read(*a, **kw))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(("append", a[2].kind)) or real_app(*a, **kw))
    stopped(tmp_path)
    assert ("lock", "stop.lock") in order and ("append", "TRIAL-STOP") in order      # (Deviation 3: assert, not
    i_lock, i_stop = order.index(("lock", "stop.lock")), order.index(("append", "TRIAL-STOP"))   # a ValueError)
    assert i_lock < i_stop and ("read",) in order[i_lock:i_stop]


def _envelope(root, stage):
    tr = t.open_trial(mb(root))
    p = sg.staging_dir(root, tr.trial_id, stage) / "intent.json"
    assert p.is_file(), f"no {stage} STAGE-INTENT envelope"                 # (Deviation 4: assert, not an OSError)
    return json.loads(p.read_bytes())


def test_stop_attest_envelope_and_member(tmp_path):
    stopped(tmp_path, attest=True)
    e = _envelope(tmp_path, "stop_attest")
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    assert e["inputs"] == {"stop.json": c.sha256_file(tmp_path / "s1_out" / "stop.json"), "trial_stop_line": stop.sha}
    att = json.loads((tmp_path / "s1_out" / "attest_stop.json").read_text(encoding="utf-8"))
    assert att["stop_line_sha256"] == stop.sha and att["trial_id"] == t.open_trial(mb(tmp_path)).trial_id


def test_final_plan_envelope_and_member(tmp_path):
    stopped(tmp_path, attest=True)
    with _Clock(jrows(tmp_path)[-1].instant + timedelta(hours=1)):
        k.write_final_plan(tmp_path)
    e = _envelope(tmp_path, "final_plan")
    assert set(e["inputs"]) == {"stop.json", "attest_stop.json", "prereg.json", "plan.json"}
    assert json.loads((tmp_path / "s1_out" / "final_plan.json").read_text(encoding="utf-8"))["trial_id"]


FINAL_PLAN_BEFORE_ATTEST = r"stop attestation|attest_stop|stop_attest"   # (Deviation 5: match= on every raises)


def test_final_plan_before_stop_attest_refuses_with_no_row(tmp_path):
    stopped(tmp_path, attest=False)
    with _Clock(jrows(tmp_path)[-1].instant + timedelta(hours=1)), \
            pytest.raises(SystemExit, match=FINAL_PLAN_BEFORE_ATTEST):
        k.write_final_plan(tmp_path)
    assert [x.kind for x in j.subject_rows(jrows(tmp_path), "stage/final_plan")] == []


F1_ACTIVE = r"not allowed while ACTIVE|no TRIAL-STOP"                     # s1_stage.permitted (F1 table)
ACTIVE_REFUSAL = {                         # (Deviation 5: match= on every raises) the F1 refusal, or the existing
    "stop_attest": F1_ACTIVE + r"|no stop",                              # precondition that ACTIVE implies
    "final_plan": F1_ACTIVE + r"|no stop attestation|is RUNNING",        # (no stop / attestation / final plan /
    "final": F1_ACTIVE + r"|final plan|final_plan",                      # SCORE-ACK: the chain needs a STOP)
    "score": F1_ACTIVE + r"|no S1-SCORE-ACK"}


def _refused(fn):
    """(Deviation 6) the oracle is a refusal (SystemExit): any other exception - the legacy do_final reads a missing
    final_plan.json before any gate - fails that oracle (pytest.fail) instead of erroring the test."""
    try:
        fn()
    except SystemExit:
        raise
    except Exception as e:                                                  # noqa: BLE001 - reported, never hidden
        pytest.fail(f"not a refusal: {type(e).__name__}: {e}")


@pytest.mark.parametrize("stage", ["stop_attest", "final_plan", "final", "score"])
def test_finalization_stages_are_refused_while_active(tmp_path, monkeypatch, stage):
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False, stop=False)
    sp = Spies(monkeypatch)
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=ACTIVE_REFUSAL[stage]):
        _refused({"stop_attest": lambda: r.attest_stop(tmp_path, r.STOP_STATEMENT),
                  "final_plan": lambda: k.write_final_plan(tmp_path),
                  "final": lambda: k.do_final(tmp_path, "acq-ack", sp.client(), ("k", "s")),
                  "score": lambda: r.score(tmp_path, "score-ack")}[stage])
    sp.assert_zero()
    assert j.subject_rows(jrows(tmp_path), j.stage_subject(stage)) == []


def _in_flight_across_the_stop(tmp_path, monkeypatch):
    """A day-2 slot's INTENT commits before the STOP (decided on the day-1 seal) and its QUALIFIED after it: the
    TRIAL-STOP is appended from inside the worker, just before its J (F1 row 2: INTENT seq < STOP seq)."""
    import s1_checkpoint as ck
    from conftest import S1_PROCESS
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False, stop=False)
    day2 = st_["sessions"][2]
    sch = z.close_of(day2, st_["calendar"]) + timedelta(minutes=45)
    at = sch + timedelta(seconds=30)
    real = sl.Worker._append

    def stop_first(self, req):
        if req.kind == "SLOT-QUALIFIED":
            z.decide_stop(t.gate(tmp_path, "stop decision"), st_["calendar"], st_["start"], lambda: at,
                          mailbox=mb(tmp_path))
        return real(self, req)
    monkeypatch.setattr(sl.Worker, "_append", stop_first)
    with _Clock(at):
        rep = ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, lambda reference=None: S1_RECEIPT,
                                lambda: dict(S1_PROCESS), tmp_path / "c.log", now=lambda: at)
    monkeypatch.setattr(sl.Worker, "_append", real)
    rows = jrows(tmp_path)
    mine = j.subject_rows(rows, j.slot_subject(sch))
    return st_, day2, rows, mine, j.first(rows, "TRIAL-STOP"), rep


@pytest.mark.skip(reason="held with Task 13: needs s1_seal.sampled_history (progress.md ruling B11/B12/B16)")
def test_in_flight_slot_started_before_the_stop_completes_but_never_enters_final_or_score(tmp_path, monkeypatch):
    st_, day2, rows, mine, stop, rep = _in_flight_across_the_stop(tmp_path, monkeypatch)
    intent, qual = j.first(mine, "SLOT-INTENT"), j.first(mine, "SLOT-QUALIFIED")
    assert intent.seq < stop.seq < qual.seq                       # completed after the stop (allowed)
    rec = json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))
    assert f"seals/{day2}.json" not in rec["seals"]
    hist = z.sampled_history(rows, stop, z.sampled_seals(tmp_path / "s1_out", rows, st_["calendar"], st_["start"],
                                                         upto_seq=stop.seq))
    assert qual.sha not in hist["rows"] and f"seals/{day2}.json" not in hist["seals"]


def test_post_stop_sampled_slot_is_excluded_from_the_sampled_history(tmp_path, monkeypatch):
    st_, day2, rows, mine, stop, rep = _in_flight_across_the_stop(tmp_path, monkeypatch)
    assert stop is not None, "no TRIAL-STOP row"                            # (Deviation 3: assert, not AttributeError)
    assert day2 not in z.sampled_seals(tmp_path / "s1_out", rows, st_["calendar"], st_["start"], upto_seq=stop.seq)
    assert day2 not in z.sampled_seals(tmp_path / "s1_out", rows, st_["calendar"], st_["start"])   # never sealed


def test_no_new_seal_after_the_stop(tmp_path, monkeypatch):
    st_, day2, rows, mine, stop, rep = _in_flight_across_the_stop(tmp_path, monkeypatch)
    assert not (tmp_path / "s1_out" / "seals" / f"{day2}.json").exists()
    assert "not allowed while STOPPED" in (rep.get("refused") or "")   # F1 (s1_stage.permitted; Deviation 7: the
                                                                         # plan's "outside ACTIVE" is not product text)


def test_stop_operation_runs_pending_seal_stages_before_trial_stop(tmp_path, monkeypatch):   # rows 323, 334
    """E2.5 r3: the stop operation runs every pending seal stage, then appends TRIAL-STOP."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False, seal_stage=False)   # determined, no seal stages
    order = []
    real_app = j.append
    monkeypatch.setattr(j, "append", lambda *a, **k: (order.append((a[2].kind, a[2].subject)),
                                                      real_app(*a, **k))[1])
    gv = t.gate(tmp_path, "decide")
    at = c.aware(START) + timedelta(days=2)               # after post-START day 1's close
    with _Clock(at):
        rec = z.decide_stop(gv, st_["calendar"], c.aware(START), lambda: at, mailbox=mb(tmp_path))
    assert rec is not None
    created = [i for i, (k_, s_) in enumerate(order) if k_ == "STAGE-CREATED" and s_.startswith("stage/seal/")]
    assert created and max(created) < order.index(("TRIAL-STOP", "trial"))


def test_later_close_qualified_before_stop_with_unchanged_record_is_fenced(tmp_path, monkeypatch):   # row 262
    """E2.8 r3 (A3-PR1-1): the stop operation finishes its seal pass; then a later-close QUALIFIED commits (that close
    becomes determined) before TRIAL-STOP, and the chosen stop record is unchanged. TRIAL-STOP is refused in its own
    transaction (step 5 fence); after that close's seal stage the STOP commits."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False)    # lots stop at post-START day 1, sealed
    later = h.later_close_after_the_stop_close(st_)                  # the next eligible close (fixture helper)
    gv = t.gate(tmp_path, "decide")
    out = tmp_path / "s1_out"
    before_rec = z.stop_record(out, jrows(tmp_path), c.aware(START), st_["calendar"], gv.trial.bundle)
    real_app, injected, seen = j.append, [], []

    def inject_then_append(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "TRIAL-STOP" and not injected:               # after the seal pass, before the STOP append
            injected.append(1)
            _write_seal(out, later["date"], later["close"], later["trades"], S1_RECEIPT, start=c.aware(START),
                        with_stage=False)                           # QUALIFIED; determined; no seal stage
            assert z.stop_record(out, jrows(tmp_path), c.aware(START), st_["calendar"], gv.trial.bundle) == \
                before_rec                                          # the chosen stop record is unchanged
        res = real_app(trial_id, gen, req, ctx_fn, **kw)
        if req.kind == "TRIAL-STOP":
            seen.append((res.outcome, res.reason))
        return res
    monkeypatch.setattr(j, "append", inject_then_append)
    at = c.aware(START) + timedelta(days=4)
    with _Clock(at):
        rec = z.decide_stop(gv, st_["calendar"], c.aware(START), lambda: at, mailbox=mb(tmp_path))
    assert seen, "no TRIAL-STOP request"                               # (Deviation 3: assert, not an IndexError)
    assert seen[0][0] == "REFUSE" and "not sealed" in seen[0][1]       # fenced in its own transaction
    assert seen[-1][0] == "APPEND" and rec == before_rec               # retried after the seal stage
    kinds_ = [x.kind for x in j.subject_rows(jrows(tmp_path), f"stage/seal/{later['date']}")]
    assert kinds_ == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    assert j.first(j.subject_rows(jrows(tmp_path), f"stage/seal/{later['date']}"), "STAGE-CREATED").seq < stop.seq


# ---------------------------------------------------------------- OQ-8 dispositions (rows 300-305; BLK-3)
# Rows 300-305: numbers ACCEPTED by Codex f33d0501. The r1 cases (i)-(v) and the readiness/provenance rules are
# t11_dispositions.md r1, PENDING Codex acceptance (h.STOP_DISPOSITION_STATUS). stop_record is the pure CANDIDATE;
# permission to commit it is s1_seal.stop_ready (BLK3-C1).
@pytest.mark.parametrize("case", ["lots-earliest", "lots-later-not-chosen", "timeout-last-sealed", "no-valid-seal",
                                  "pending-excluded", "deadline-instant-eligibility",
                                  "early-w-failed", "pending-after-timeout", "unresolved-blocks",
                                  "unresolved-resolved-by-missed", "delayed-qualified-clock",
                                  "no-valid-seal-ineligible-seal"])
def test_stop_dispositions(tmp_path, case):
    """Expected outcomes are the Step 2a dispositions as ACCEPTED by Codex (BLK-3); s1_state builds each history
    from `a3_helpers.stop_history(case)` (synthetic seals with real slot rows)."""
    hist = h.stop_history(tmp_path, START, case)
    rec = z.stop_record(tmp_path / "s1_out", jrows(tmp_path), c.aware(START), hist["calendar"],
                        t.open_trial(mb(tmp_path)).bundle)
    want = hist["want"]                                   # from t11_dispositions.md as accepted
    if want is None:
        assert rec is None
    else:
        assert rec is not None, "no stop record"           # (Deviation 3: assert, not a TypeError on None)
        assert {k_: rec[k_] for k_ in want} == want


# BLK3-C1 (Codex f33d0501): permission to COMMIT is the transaction clock, never a terminal row or its `at`.
# (case, transaction clock, permitted). W(d129) = 2027-04-26T12:00Z; W(d0) = 2026-10-27T12:00Z (t11_dispositions r1).
READINESS = [
    ("early-w-failed", "2027-04-23T20:47:00+00:00", False),          # (i) 69 d129 windows still open
    ("early-w-failed", "2027-04-26T12:00:00+00:00", True),           # (i) positive control: clock at W
    ("timeout-last-sealed", "2027-04-26T11:59:59+00:00", False),     # boundary: 1 s before W
    ("timeout-last-sealed", "2027-04-26T12:00:00+00:00", True),      # boundary: at W (>=)
    ("lots-later-not-chosen", "2026-10-27T11:59:59+00:00", False),   # the missed d0's windows not all expired
    ("lots-later-not-chosen", "2026-10-27T12:00:00+00:00", True),    # W(d0)
]


@pytest.mark.parametrize("case,now,ready", READINESS, ids=[f"{x[0]}@{x[1][:19]}" for x in READINESS])
def test_stop_readiness_is_the_transaction_clock(tmp_path, case, now, ready):
    hist = h.stop_history(tmp_path, START, case)
    tr = t.open_trial(mb(tmp_path))
    why = z.stop_ready(tmp_path / "s1_out", jrows(tmp_path), c.aware(START), hist["calendar"], tr.bundle,
                       c.aware(now))
    if ready:
        assert why is None, why
    else:
        assert isinstance(why, str) and why, "TRIAL-STOP permitted before every counted window expired (BLK3-C1)"


def test_early_w_failed_commits_no_stop(tmp_path):
    """BLK3-C1 counterexample: the W slot of the last eligible close is early-INTENT + FAILED (OQ-33) while 69 of its
    windows are still open: the NO-VALID-SEAL candidate must not commit (no TRIAL-STOP)."""
    hist = h.stop_history(tmp_path, START, "early-w-failed")
    at = c.aware("2027-04-23T20:47:00+00:00")
    tr = t.open_trial(mb(tmp_path))
    assert z.stop_ready(tmp_path / "s1_out", jrows(tmp_path), c.aware(START), hist["calendar"], tr.bundle, at) \
        is not None, "permitted before W"
    with _Clock(at):
        z.decide_stop(t.gate(tmp_path, "early W"), hist["calendar"], c.aware(START), lambda: at, mailbox=mb(tmp_path))
    assert j.first(jrows(tmp_path), "TRIAL-STOP") is None


def test_completing_row_at_is_provenance_not_commit_time(tmp_path):
    """BLK3-C2 (case iv): the unblocking MISSED commits first (lower seq, at 20:56:00.1); the completing QUALIFIED
    commits after it (higher seq) with R = 20:56:00.0. determined_utc is that row's `at` verbatim (provenance only):
    it predates the MISSED it depends on, and differs from the QUALIFIED row's own commit time (created)."""
    hist = h.stop_history(tmp_path, START, "delayed-qualified-clock")
    rec = z.stop_record(tmp_path / "s1_out", jrows(tmp_path), c.aware(START), hist["calendar"],
                        t.open_trial(mb(tmp_path)).bundle)
    assert rec is not None, "no stop record"
    rows = jrows(tmp_path)
    missed = j.first(j.subject_rows(rows, "slot/20261027T204500Z"), "SLOT-MISSED")
    qual = j.first(j.subject_rows(rows, "slot/20261027T204700Z"), "SLOT-QUALIFIED")
    assert (rec["terminal_seq"], rec["determined_utc"]) == (qual.seq, qual.at) == (
        missed.seq + 1, "2026-10-27T20:56:00.000000+00:00")
    assert c.aware(rec["determined_utc"]) < missed.instant                 # R predates the premise it completes
    assert qual.created > c.aware(qual.at).timestamp()                    # commit time is journal metadata, not `at`


@pytest.mark.parametrize("damage", ["deleted", "corrupt"])
@pytest.mark.parametrize("case", ["deadline-instant-eligibility", "no-valid-seal-ineligible-seal"])
def test_damaged_ineligible_seal_is_invalid(tmp_path, case, damage):
    """A4 / Codex f33d0501 (v): the ineligible deadline-date seal is never a sampled stop input, but its CREATED
    seal stage stays required integrity evidence (E2.6 / F4 table): missing or corrupt is INVALID (stage-replaced)."""
    from conftest import s1_first_invalid, s1_replaced
    h.stop_history(tmp_path, START, case)
    p = tmp_path / "s1_out" / "seals" / "2027-04-26.json"
    assert p.is_file()
    if damage == "deleted":
        p.unlink()
    else:
        p.write_text("{not JSON", encoding="utf-8")
    with pytest.raises(SystemExit, match=s1_replaced("seals/2027-04-26.json")):
        t.gate(tmp_path, "integrity")
    assert s1_first_invalid(tmp_path) == "reason/stage-replaced"


# ---------------------------------------------------------------- Codex 28e08272 implementation checkpoint
# stop_ready is evaluated INSIDE the TRIAL-STOP transaction on the clock j.append samples there (Context.stop_ready
# (rows, now)). These tests make the caller's (preflight) clock and the append's in-transaction clock straddle W_last
# (2027-04-26T12:00Z) on the early-W history (a NO-VALID-SEAL candidate needing now >= W_last), so a correct pure
# stop_ready alone cannot hide missing wiring.
BEFORE_W, AFTER_W = "2027-04-26T11:00:00+00:00", "2027-04-26T13:00:00+00:00"


def _straddle(tmp_path, monkeypatch, pre, txn):
    """decide_stop with the caller's clock `pre`; the TRIAL-STOP append's own clock sample is `txn`."""
    hist = h.stop_history(tmp_path, START, "early-w-failed")
    real, seen = j.append, []

    def append(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "TRIAL-STOP":
            kw["clock"] = lambda: c.aware(txn)                    # the in-transaction now (the row's `at`)
        res = real(trial_id, gen, req, ctx_fn, **kw)
        if req.kind == "TRIAL-STOP":
            seen.append(res)
        return res
    monkeypatch.setattr(j, "append", append)
    pre_t = c.aware(pre)
    with _Clock(pre_t):
        rec = z.decide_stop(t.gate(tmp_path, "straddle"), hist["calendar"], c.aware(START), lambda: pre_t,
                            mailbox=mb(tmp_path))
    monkeypatch.setattr(j, "append", real)
    return rec, seen, j.first(jrows(tmp_path), "TRIAL-STOP")


@pytest.mark.parametrize("pre,txn", [(BEFORE_W, AFTER_W), (AFTER_W, BEFORE_W)], ids=["pre<W<=txn", "txn<W<=pre"])
def test_stop_readiness_follows_the_in_transaction_clock(tmp_path, monkeypatch, pre, txn):
    rec, seen, stop = _straddle(tmp_path, monkeypatch, pre, txn)
    assert seen, "no TRIAL-STOP request: a preflight time decided before the transaction"
    if txn == AFTER_W:
        assert stop is not None and rec is not None and stop.at == j.fmt_at(c.aware(AFTER_W))
        assert rec["status"] == "NO-VALID-SEAL"
    else:
        assert stop is None and rec is None
        assert (seen[-1].outcome, "not ready" in seen[-1].reason) == ("REFUSE", True)


@pytest.mark.parametrize("pre,txn", [(BEFORE_W, AFTER_W), (AFTER_W, BEFORE_W)], ids=["pre<W<=txn", "txn<W<=pre"])
def test_preflight_clock_mutant_is_killed(tmp_path, monkeypatch, pre, txn):
    """Semantic mutant (Codex checkpoint): stop_ready fed the PREFLIGHT time instead of the transaction's `now`. On the
    straddling history the mutant's decision is the opposite of test_stop_readiness_follows_the_in_transaction_clock's
    oracle, so that test kills it."""
    real = z.stop_ready
    monkeypatch.setattr(z, "stop_ready", lambda out, rows, start, cal, bundle, now: real(out, rows, start, cal, bundle,
                                                                                          c.aware(pre)))
    rec, seen, stop = _straddle(tmp_path, monkeypatch, pre, txn)
    correct_appends = txn == AFTER_W
    assert (stop is not None) != correct_appends, "the preflight-time mutant survives the straddle oracle"


# ---------------------------------------------------------------- Task 11 fix round 1 (review C1, M1, I1, M2-M5, M7)
W_LAST = "2027-04-26T12:00:00+00:00"


def _sealed_last_close(tmp_path):
    """C1 history: 100 lots, 99 sold on d1 (no lots stop); seals d0 and the LAST eligible close d129 (2027-04-23,
    its first slot) - the W slot of d129 has no row (its own invocation at W is refused: E(W) = W)."""
    st_ = s1_state(tmp_path, START, score_ready=True, lots=h._lots(100, lambda i: (1, 80.0) if i < 99 else None),
                   seal_days=[0], stop=False)
    cal, sess = st_["calendar"], st_["sessions"]
    assert sess[129] == "2027-04-23"
    cl = z.close_of(sess[129], cal)
    _write_seal(tmp_path / "s1_out", sess[129], cl,
                [x for x in st_["rows"] if c.aware(x["ts"]) <= cl + timedelta(minutes=45)],
                S1_RECEIPT, start=c.aware(START), opening_close=z.close_of(st_["opening_close"], cal))
    return st_


def _sealed_state(tmp_path):
    return (c.sha256_file(tmp_path / "s1_out" / "seals" / "2027-04-23.json"),
            j.first(j.subject_rows(jrows(tmp_path), "slot/20270423T204500Z"), "SLOT-QUALIFIED").sha)


def _assert_timeout_at_the_sealed_last_close(tmp_path, before):
    rows = jrows(tmp_path)
    stop = j.first(rows, "TRIAL-STOP")
    assert stop is not None, "no TRIAL-STOP: the timeout is unreachable (review C1)"
    rec = json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))
    assert (rec["status"], rec["stop_close"], rec["stop_seal"]) == ("TIMEOUT", "2027-04-23T20:00:00+00:00",
                                                                   "seals/2027-04-23.json")
    w = j.first(j.subject_rows(rows, "slot/20270426T120000Z"), *j.TERMINAL)
    assert w is not None and w.kind == "SLOT-MISSED" and rec["triggering_slot"] == w.subject
    # the sealed close's selected QUALIFIED and its seal are untouched by the later MISSED rows
    q = j.first(j.subject_rows(rows, "slot/20270423T204500Z"), "SLOT-QUALIFIED")
    assert _sealed_state(tmp_path) == before
    assert [x.kind for x in j.subject_rows(rows, q.subject)] == ["SLOT-INTENT", "SLOT-QUALIFIED"]


def test_sealed_last_close_reaches_its_timeout_through_the_finalizer_command(tmp_path):
    """Review C1 (ruling): once the clock is >= W of the last eligible close, the finalizer COMMAND (s1_checkpoint
    --finalize -> run_finalizer) finalizes that close even though it is sealed (MISSED reaches its W slot) and then
    decides the stop: TIMEOUT at the sealed last close, through the product command only."""
    import s1_checkpoint as ck
    _sealed_last_close(tmp_path)
    before = _sealed_state(tmp_path)
    assert hasattr(ck, "run_finalizer"), "no product finalizer command (review C1)"
    at = c.aware(W_LAST) + timedelta(hours=1)
    with _Clock(at):
        ck.run_finalizer(tmp_path, now=lambda: at, mailbox=mb(tmp_path))
    _assert_timeout_at_the_sealed_last_close(tmp_path, before)


def test_sealed_last_close_reaches_its_timeout_through_a_later_checkpoint(tmp_path):
    """Review C1 (ruling): the checkpoint's post-capture finalizer does the same - a later (ineligible d130) slot's
    QUALIFIED at 2027-04-26 20:45Z finalizes the sealed last close (its W slot MISSED) and the stop decision commits
    the TIMEOUT."""
    import s1_checkpoint as ck
    from conftest import S1_PROCESS
    st_ = _sealed_last_close(tmp_path)
    before = _sealed_state(tmp_path)
    s130 = c.aware("2027-04-26T20:45:00+00:00")
    a130 = s130 + timedelta(seconds=30)
    with _Clock(a130):
        ck.run_checkpoint(tmp_path, st_["ledger"].path, s130, lambda reference=None: S1_RECEIPT,
                          lambda: dict(S1_PROCESS), tmp_path / "c.log", now=lambda: a130)
    _assert_timeout_at_the_sealed_last_close(tmp_path, before)


def test_the_finalize_mode_dispatches_to_the_finalizer_command(monkeypatch, capsys):
    """Review C1: `s1_checkpoint.py --finalize` is the finalizer command's CLI entry (exactly one mode per call)."""
    import s1_checkpoint as ck
    try:
        mode = ck.parse_mode(["--finalize"])
    except SystemExit as e:                                        # argparse rejects an unknown option (exit 2)
        pytest.fail(f"--finalize is not a checkpoint mode (argparse exit {e})")
    assert mode == ("finalize", None)
    seen = []
    monkeypatch.setattr(ck, "run_finalizer", lambda root, *a, **kw: seen.append(root) or {"mode": "finalize"},
                        raising=False)
    ck.main(["--finalize"])
    assert seen and json.loads(capsys.readouterr().out)["mode"] == "finalize"
    with pytest.raises(SystemExit, match="2"):                     # argparse: --finalize takes no other mode
        ck.parse_mode(["--finalize", "--final-snapshot"])


class _Advancing:
    """A clock that moves forward when the TRIAL-STOP append starts (time passes inside the command)."""
    def __init__(self, t_):
        self.t = t_

    def __call__(self):
        return self.t


@pytest.mark.parametrize("pre,txn", [(BEFORE_W, AFTER_W), (AFTER_W, BEFORE_W)], ids=["pre<W<=txn", "txn<W<=pre"])
def test_the_finalizer_command_decides_on_the_append_clock_not_its_start_instant(tmp_path, monkeypatch, pre, txn):
    """Review M1 (ruling, Important): the finalizer command passes its clock CALLABLE to the stop decision, so append
    samples the instant inside the TRIAL-STOP transaction; a fixed command-start instant (preflight-time reuse) would
    decide on `pre`. The clock advances from `pre` to `txn` just as the TRIAL-STOP append begins."""
    import s1_checkpoint as ck
    h.stop_history(tmp_path, START, "early-w-failed")
    clk = _Advancing(c.aware(pre))
    real = j.append

    def append(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "TRIAL-STOP":
            clk.t = c.aware(txn)
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", append)
    monkeypatch.setattr(c, "now_utc", clk)
    assert hasattr(ck, "run_finalizer"), "no product finalizer command (review C1)"
    ck.run_finalizer(tmp_path, now=clk, mailbox=mb(tmp_path))
    monkeypatch.setattr(j, "append", real)
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    if txn == AFTER_W:
        assert stop is not None and stop.at == j.fmt_at(c.aware(AFTER_W)), "decided on the command's start instant"
    else:
        assert stop is None, "a STOP committed on the command's start instant, not the transaction's"


@pytest.mark.parametrize("failures", [1, 99], ids=["transient", "persistent"])
def test_a_stop_json_read_error_is_confirmed_and_never_invalidates(tmp_path, monkeypatch, failures):
    """Review I1 (ruling): an OSError reading stop.json is re-read before any decision; a transient error passes, a
    persistent one refuses with no row - never TRIAL-INVALID (Task 7 confirm-on-re-read)."""
    s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    real, n = Path.read_text, [0]

    def flaky(self, *a, **kw):
        if self.name == "stop.json" and self.parent.name == "s1_out" and n[0] < failures:
            n[0] += 1
            raise PermissionError(13, "sharing violation (simulated)")
        return real(self, *a, **kw)
    monkeypatch.setattr(Path, "read_text", flaky)
    if failures == 1:
        try:
            t.gate(tmp_path, "transient")
        except SystemExit as e:
            pytest.fail(f"a transient stop.json read error was not confirmed by a re-read: {e}")
    else:
        with pytest.raises(SystemExit, match=r"stop\.json unreadable .*refused with no row"):
            t.gate(tmp_path, "persistent")
    monkeypatch.setattr(Path, "read_text", real)
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


def test_the_score_threads_its_mailbox_into_the_stop_read(tmp_path, monkeypatch):
    """Review M2: every journal read of the score - _trial_end's current_stop included - uses the score's mailbox."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    real, seen = z.current_stop, []
    monkeypatch.setattr(z, "current_stop", lambda *a, **kw: seen.append(kw.get("mailbox")) or real(*a, **kw))
    with _Clock(st_["now"]):
        r.score(tmp_path, "score-ack", mailbox=mb(tmp_path))
    assert seen and all(x == mb(tmp_path) for x in seen), seen


def _raise(e):
    raise e


def test_a_publication_failure_after_the_stop_row_is_reported_truthfully(tmp_path, monkeypatch):
    """Review M3: stop.json failing to publish AFTER the TRIAL-STOP committed is reported as the F2.3 publication gap
    (the row exists), never as "refused with no row"; the next gate republishes the same record."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False)
    real = z.persist_stop
    monkeypatch.setattr(z, "persist_stop", lambda out, rec: _raise(OSError("disk full (simulated)")))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"TRIAL-STOP committed .*publication pending"):
        z.decide_stop(t.gate(tmp_path, "decide"), st_["calendar"], st_["start"], lambda: st_["now"],
                      mailbox=mb(tmp_path))
    stop = j.first(jrows(tmp_path), "TRIAL-STOP")
    assert stop is not None and not (tmp_path / "s1_out" / "stop.json").exists()
    monkeypatch.setattr(z, "persist_stop", real)
    t.gate(tmp_path, "gap recovery")
    assert j.detail_of(json.loads((tmp_path / "s1_out" / "stop.json").read_text(encoding="utf-8"))) == stop.detail


def test_a_gap_whose_recompute_raises_is_never_left_silent(tmp_path, monkeypatch):
    """Review M4: in the publication gap, an evidence error raised by the recompute (after the F4/F3 tables passed)
    is an explicit refusal with no row - never a silent pass that leaves the trial in the gap."""
    import s1_slot as sl
    s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    (tmp_path / "s1_out" / "stop.json").unlink()
    monkeypatch.setattr(z, "stop_record", lambda *a, **kw: _raise(sl.QualifiedEvidence("damaged (simulated)")))
    with pytest.raises(SystemExit, match=r"publication gap: .*cannot be recomputed.*refused with no row"):
        t.gate(tmp_path, "gap")
    assert all(x.kind != "TRIAL-INVALID" for x in jrows(tmp_path))


def test_a_damaged_slot_tree_in_the_gap_is_judged_by_the_evidence_table(tmp_path):
    """Review M4: in the publication gap the F3 evidence table decides first - a damaged QUALIFIED tree is INVALID
    (registration-artifact), not a stop-conflict from a recompute over damaged evidence."""
    import s1_slot as sl
    from conftest import s1_first_invalid
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    out = tmp_path / "s1_out"
    (out / "stop.json").unlink()
    sch = z.close_of(st_["sessions"][1], st_["calendar"]) + timedelta(minutes=45)
    res = sl.names(out, sch, st_["sessions"][1])["resolution"]
    res.write_text(res.read_text(encoding="utf-8") + " ", encoding="utf-8")         # parseable, tree changed
    with pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
        t.gate(tmp_path, "gap")
    assert s1_first_invalid(tmp_path) == "reason/registration-artifact"


def test_a_busy_stop_lock_defers_but_another_lock_error_is_a_refusal(tmp_path, monkeypatch):
    """Review M5: only the STOP lock held by another stop operation means "decide later" (None, no row); a lock held
    elsewhere inside the operation is reported as a refusal, never misattributed."""
    import s1_locks as L
    import s1_slot as sl
    st_ = s1_state(tmp_path, START, score_ready=True, stop=False, seal_stage=False)
    gv = t.gate(tmp_path, "decide")
    real = L.OwnershipLock.acquire

    def busy_stop(self):
        if self.path.name == "stop.lock":
            raise L.LockHeld("stop.lock: byte range locked by another process (simulated)")
        return real(self)
    monkeypatch.setattr(L.OwnershipLock, "acquire", busy_stop)
    with _Clock(st_["now"]):
        assert z.decide_stop(gv, st_["calendar"], st_["start"], lambda: st_["now"], mailbox=mb(tmp_path)) is None
    monkeypatch.setattr(L.OwnershipLock, "acquire", real)
    monkeypatch.setattr(sl, "run_seal_stage", lambda *a, **kw: _raise(L.LockHeld("stage-seal lock held (simulated)")))
    with _Clock(st_["now"]), pytest.raises(SystemExit, match=r"stop decision refused with no row .*LockHeld"):
        z.decide_stop(gv, st_["calendar"], st_["start"], lambda: st_["now"], mailbox=mb(tmp_path))
    assert j.first(jrows(tmp_path), "TRIAL-STOP") is None


def test_persist_stop_never_recreates_a_lost_s1_out(tmp_path):
    """Review M7 (F6.6): publishing stop.json into a vanished s1_out refuses; s1_out is not recreated."""
    out = tmp_path / "s1_out"
    with pytest.raises(SystemExit, match=r"s1_out is gone"):
        z.persist_stop(out, {"status": "STOPPED"})
    assert not out.exists()
