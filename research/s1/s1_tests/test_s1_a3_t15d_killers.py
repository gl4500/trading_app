"""Task 15d killer oracles (Codex proposal_v1, CONDITIONAL_CONSENSUS), installed unchanged in 15d-1.

Run by test_s1_a3_mutants.py via t15_agreed_assertions.json (selection, nodeid, terminal).
Each ORACLE end-of-line comment marks an agreed structural terminal; rebind after any edit.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
import s1_books as b
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_trial as t
import test_s1_a3_audit as au
import test_s1_a3_prestart as pre
import test_s1_a3_stage as stage
from conftest import S1_RECEIPT, Spies, _Clock, s1_jappend, s1_state

START = "2026-10-26T13:30:00+00:00"


def test_t15d_f1_audit_completes_with_the_intent_cutoff(tmp_path, monkeypatch):
    pre_at = datetime(2026, 10, 13, 3, 59, 59, 999999, tzinfo=timezone.utc)
    expected_day = "2026-10-12"
    au.setup(tmp_path, ("A",), now=pre_at - timedelta(minutes=1))
    post_at = pre_at + timedelta(microseconds=2)
    now, append = [pre_at - timedelta(seconds=10)], j.append

    def at_intent(trial_id, genesis, req, ctx_fn, **kw):
        if req.kind == "STAGE-INTENT":
            kw["clock"] = lambda: pre_at
            result = append(trial_id, genesis, req, ctx_fn, **kw)
            now[0] = post_at
            return result
        return append(trial_id, genesis, req, ctx_fn, **kw)

    monkeypatch.setattr(j, "append", at_intent)
    provider, spies, refusal = au.Provider(), Spies(monkeypatch), None
    with au._clock(lambda: now[0]):
        try:
            manifest = k.do_audit(tmp_path, "audit-ack", spies.client(provider), au.KEYS)
            observed = ("returned", manifest["outcome"], manifest["publication_cutoff"])
        except SystemExit as exc:
            refusal, observed = str(exc), ("refused", None, None)
    assert observed == ("returned", "COMPLETE", expected_day), refusal  # ORACLE:F1
    reserved = json.loads((tmp_path / "s1_out/audit/attempt.json").read_bytes())["reserved_utc"]
    assert c.aware(reserved).astimezone(c.NY).date().isoformat() != expected_day
    assert all(req.url.params.get("end") == expected_day for req in provider.sent if "corporate-actions" in str(req.url))


def test_t15d_f4_opening_books_is_an_envelope_input(tmp_path, monkeypatch):
    _start, _cal, _oc, w = pre._open_and_ack(tmp_path)
    real_hooks = r.start_attest_publish_hooks

    def checked_hooks(gv, inputs):
        assert inputs.get("opening_books.json") == c.sha256_file(gv.out / "opening_books.json")  # ORACLE:F4
        return real_hooks(gv, inputs)

    monkeypatch.setattr(r, "start_attest_publish_hooks", checked_hooks)
    with _Clock(w + timedelta(minutes=2)):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    envelope = pre.env(tmp_path, "start_attest")
    assert envelope["inputs"]["opening_books.json"] == c.sha256_file(tmp_path / "s1_out/opening_books.json")


def test_t15d_f7_recovery_creates_with_the_intents_own_op(tmp_path, monkeypatch):
    stage.h.plan_only(tmp_path, stage.START)
    stage.h.relax(monkeypatch, "final_plan")
    assert stage.child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    before = j.subject_rows(stage.jrows(tmp_path), j.stage_subject("final_plan"))
    intent, prepared = j.first(before, "STAGE-INTENT"), j.first(before, "STAGE-PREPARED")
    assert intent is not None and prepared is not None and j.first(before, "STAGE-CREATED") is None
    refusal = None
    try:
        t.gate(tmp_path, "t15d recovery")
        after = j.subject_rows(stage.jrows(tmp_path), j.stage_subject("final_plan"))
        created = j.first(after, "STAGE-CREATED")
        observed = ("created", created.op, created.detail) if created is not None else ("not-created", None, None)
    except SystemExit as exc:
        refusal, observed = str(exc), ("refused", None, None)
    assert observed == ("created", intent.op, prepared.detail), refusal  # ORACLE:F7
    assert all(row.kind != "TRIAL-INVALID" for row in stage.jrows(tmp_path))


def test_t15d_f9_fifo_includes_the_current_sell():
    trades = [
        {"id": 5, "symbol": "B", "action": "SELL", "shares": 3, "price": 8, "ts": "2026-10-26T14:34:00+00:00"},
        {"id": 2, "symbol": "B", "action": "BUY", "shares": 3, "price": 7, "ts": "2026-10-26T14:31:00+00:00"},
        {"id": 4, "symbol": "A", "action": "SELL", "shares": 1, "price": 12, "ts": "2026-10-26T14:33:00+00:00"},
        {"id": 1, "symbol": "A", "action": "BUY", "shares": 2, "price": 10, "ts": "2026-10-26T14:30:00+00:00"},
        {"id": 3, "symbol": "A", "action": "SELL", "shares": 1, "price": 11, "ts": "2026-10-26T14:32:00+00:00"},
    ]
    expected = {1: {"sold_at": "2026-10-26T14:33:00+00:00", "sell_id": 4},
                2: {"sold_at": "2026-10-26T14:34:00+00:00", "sell_id": 5}}
    with z.seal_pass() as px:
        observed = b._sold_events(trades, px)
    assert observed == expected  # ORACLE:F9


@pytest.mark.parametrize("context", ["missing", "ended"])
def test_t15d_f10_invalid_pass_precedes_malformed_trades(context):
    px = None
    if context == "ended":
        with z.seal_pass() as px:
            pass
    trades = [{"id": 1, "symbol": "A", "action": "HOLD", "shares": 1, "price": 1, "ts": START}]
    try:
        b._sold_events(trades, px)
        observed = ("returned", None)
    except SystemExit as exc:
        observed = ("pass-refusal", str(exc))
    except b.BookError as exc:
        observed = ("book-error", str(exc))
    assert observed == ("pass-refusal", z.PASS_REFUSAL)  # ORACLE:F10


def test_t15d_f11_pending_close_does_not_consume_qualified_evidence(tmp_path, monkeypatch):
    state = s1_state(tmp_path, START, score_ready=True, seal_days=[1], stop_attest=False, final=False, stop=False)
    day = state["sessions"][0]
    slot = z.close_of(day, state["calendar"]) + timedelta(minutes=45)
    s1_jappend(tmp_path, "SLOT-INTENT", j.slot_subject(slot), at=slot + timedelta(seconds=1))
    gv = t.gate(tmp_path, "t15d pending")
    real_resolution = sl._resolution_evidence

    def committed_qualified_only(out, q, day_iso, *, ps=None):
        assert q is not None and q.kind == "SLOT-QUALIFIED", "pending close is not a committed QUALIFIED selection"  # ORACLE:F11
        return real_resolution(out, q, day_iso, ps=ps)

    monkeypatch.setattr(sl, "_resolution_evidence", committed_qualified_only)
    observed = z.stop_record(gv.out, gv.rows, state["start"], state["calendar"], gv.trial.bundle)
    assert observed is None
    fresh = j.read_trial(gv.trial.trial_id, gv.trial.genesis, tmp_path / "mailbox.sqlite3")
    assert j.first(fresh, "TRIAL-STOP") is None


def test_t15d_f12_sampled_prefix_includes_its_qualified_boundary(tmp_path):
    state = s1_state(tmp_path, START, score_ready=True, seal_days=[0], stop_attest=False, final=False, stop=False)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    rows = j.read_trial(tr.trial_id, tr.genesis, tmp_path / "mailbox.sqlite3")
    q = next(row for row in rows if row.kind == "SLOT-QUALIFIED" and sl.slot_of(row.subject) >= state["start"])
    out = tmp_path / "s1_out"
    before = z.sampled_seals(out, rows, state["calendar"], state["start"], upto_seq=q.seq - 1)
    assert before == {}
    selected = z.sampled_seals(out, rows, state["calendar"], state["start"], upto_seq=q.seq)
    assert [pair[0].sha for pair in selected.values()] == [q.sha]  # ORACLE:F12
