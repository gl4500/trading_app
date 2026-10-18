"""Task 12 (A10.2) follow-up tests for targeted mutants whose behaviour no earlier test pinned.
ALL RETROSPECTIVE: written after the code (and after the mutant was drafted) to give the mutant a meaningful, named
killing assertion; each docstring names the mutant (s1_evidence/s1_mutants_t12_*.py). Synthetic only."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import s1_books as b
import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_receipt as rc
import s1_run as r
import s1_seal as z
import s1_snapshot
from conftest import (S1_PROCESS, S1_RECEIPT, _Clock, s1_mailbox, s1_plan_audit, s1_state, s1_sync_portfolio,
                      s1_unattest)

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
OPEN_CLOSE = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
MON = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _registered(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


def _run(tmp_path, st_, slot, at):
    with _Clock(at):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, slot, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                 tmp_path / "crash.log", now=lambda: at)


# ---------------------------------------------------------------------- s1_checkpoint
def test_mf_a_tampered_deferred_capture_never_seals(tmp_path):
    """Mutant "_seal_from: projection not re-verified": a deferred candidate whose projection changed before a
    later invocation would seal it is refused (no seal)."""
    st_ = _registered(tmp_path)
    s47, s55 = MON + timedelta(minutes=47), MON + timedelta(minutes=55)
    rep = _run(tmp_path, st_, s47, s47 + timedelta(seconds=30))
    assert rep.get("deferred") and rep.get("candidate")
    proj = Path(rep["candidate"]["dir"]) / "projection.json"
    proj.write_bytes(proj.read_bytes() + b" ")
    rep = _run(tmp_path, st_, s55, s55 + timedelta(seconds=30))
    assert not (tmp_path / "s1_out" / "seals" / "2026-10-26.json").exists()
    assert "differs from its recorded projection" in str(rep.get("refused")), rep


def test_mf_every_seal_records_its_measured_capture_interval(tmp_path):
    """Mutant "_seal_from: seal records no capture start/end": the seal's capture keeps the measured start/end."""
    st_ = _registered(tmp_path)
    s45 = MON + timedelta(minutes=45)
    _run(tmp_path, st_, s45, s45 + timedelta(seconds=30))
    cap = read(tmp_path / "s1_out" / "seals" / "2026-10-26.json")["capture"]
    assert c.aware(cap["capture_start"]) == c.aware(cap["capture_end"]) == s45 + timedelta(seconds=30)


def test_mf_an_opening_capture_ending_after_E_never_seals(tmp_path, ledger, monkeypatch):
    """Mutant "run_opening_checkpoint: a late capture may seal": an opening capture started in time whose measured
    end is after E never seals."""
    s1_plan_audit(tmp_path, START)
    real = s1_snapshot.take_snapshot

    def slow(db, d, now=c.now_utc):
        meta = real(db, d, now=now)
        meta["capture_end"] = (c.aware(meta["capture_start"]) + timedelta(seconds=61)).isoformat()
        return meta
    monkeypatch.setattr(s1_snapshot, "take_snapshot", slow)
    sch = OPEN_CLOSE + timedelta(minutes=45)
    act = sch + timedelta(minutes=9)
    with _Clock(act):
        rep = ck.run_opening_checkpoint(tmp_path, ledger.path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                        tmp_path / "crash.log", now=lambda: act)
    assert rep["late"] is True and rep["seal"]["written"] is False


# ---------------------------------------------------------------------- s1_seal
def test_mf_calendar_rows_keep_only_date_open_close():
    """Mutants "calendar_rows keeps extra provider fields" / "_calendar keeps extra fields"."""
    raw = [{"date": "2026-10-26", "open": "09:30", "close": "16:00", "session_open": "0400"}]
    assert z.calendar_rows(raw) == r._calendar(raw) == [{"date": "2026-10-26", "open": "09:30", "close": "16:00"}]


def _rehash(audit, name):
    m = read(audit / "manifest.json")
    m["files"][name] = c.sha256_file(audit / name)
    (audit / "manifest.json").write_text(json.dumps(m), encoding="utf-8")


def test_mf_a_calendar_json_differing_from_its_pinned_raw_page_refuses(tmp_path, ledger):
    """Mutant "calendar_pin_problems: raw page binding skipped": calendar.json edited (and its manifest hash
    rewritten) no longer equals the pinned raw page -> the opening refuses."""
    s1_plan_audit(tmp_path, START)
    audit = tmp_path / "s1_out" / "audit"
    cal = read(audit / "calendar.json")
    (audit / "calendar.json").write_text(json.dumps([d for d in cal if d["date"] != "2026-10-21"]), encoding="utf-8")
    _rehash(audit, "calendar.json")
    sch = OPEN_CLOSE + timedelta(minutes=45)
    with _Clock(sch + timedelta(seconds=30)):
        with pytest.raises(SystemExit, match="pinned raw page"):
            ck.run_opening_checkpoint(tmp_path, ledger.path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                      tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))


def test_mf_a_calendar_pinned_with_other_request_parameters_refuses(tmp_path, ledger):
    """Mutant "calendar_pin_problems: params not compared": a pin whose request range is not the plan's refuses."""
    s1_plan_audit(tmp_path, START)
    audit = tmp_path / "s1_out" / "audit"
    src = read(audit / "calendar_source.json")
    src["params"]["end"] = "2027-01-01"
    (audit / "calendar_source.json").write_text(json.dumps(src), encoding="utf-8")
    _rehash(audit, "calendar_source.json")
    sch = OPEN_CLOSE + timedelta(minutes=45)
    with _Clock(sch + timedelta(seconds=30)):
        with pytest.raises(SystemExit, match="request parameters"):
            ck.run_opening_checkpoint(tmp_path, ledger.path, sch, lambda: S1_RECEIPT, lambda: dict(S1_PROCESS),
                                      tmp_path / "crash.log", now=lambda: sch + timedelta(seconds=30))


def test_mf_cohort_ids_are_the_stop_seals_cohort_through_the_stop_close(tmp_path):
    """Mutant "stop_record: cohort ids include the post-stop rows": a BUY stored after the stop close (but captured
    by the stop seal) is not a cohort id."""
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    lg, rows = st_["ledger"], list(st_["rows"])

    def add(sym, act, ts):
        rid = lg.trade(sym, act, 10, 100.0, ts)
        rows.append({"id": rid, "symbol": sym, "action": act, "shares": 10.0, "price": 100.0, "timestamp": ts,
                     "ts": ts})
        return rid
    for i in range(100):
        add(f"S{i % 5}", "BUY", "2026-10-26T15:00:00+00:00")
    s1_sync_portfolio(lg, rows)
    _run(tmp_path, st_, MON + timedelta(minutes=45), MON + timedelta(minutes=45, seconds=30))
    for i in range(100):
        add(f"S{i % 5}", "SELL", "2026-10-27T18:00:00+00:00")
    late = add("ZZ", "BUY", "2026-10-27T20:30:00+00:00")                 # after the 20:00 stop close
    s1_sync_portfolio(lg, rows)
    t = MON + timedelta(days=1, minutes=45)
    assert _run(tmp_path, st_, t, t + timedelta(seconds=30))["stop"]["status"] == "STOPPED"
    ids = read(tmp_path / "s1_out" / "stop.json")["cohort_row_ids"]
    assert late not in ids and len(ids) == 100


def test_mf_frozen_slices_stop_at_the_stop_close(tmp_path):
    """Mutant "stop_record: frozen slices = every seal": a seal of a close after the stop (written before the stop
    was persisted) is not a frozen slice."""
    s1_state(tmp_path, START, score_ready=True, seal_days=range(0, 3), final=False)
    s = read(tmp_path / "s1_out" / "stop.json")
    assert s["status"] == "STOPPED" and "seals/2026-10-28.json" not in s["seals"] and "seals/2026-10-27.json" in s["seals"]


def test_mf_a_stop_json_naming_a_non_qualifying_close_is_aborted_invalid(tmp_path):
    """Mutant "stop_problems: no consistency re-check": a stop.json forged consistently with its slices (stop seal,
    cohort ids, frozen slices) but naming a close that does not qualify is caught by the score's re-check."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    s = read(out / "stop.json")
    d0 = out / "seals" / "2026-10-26.json"
    seal = read(d0)
    sc = c.aware(seal["close"])
    s.update(stop_close=sc.isoformat(), stop_seal="seals/2026-10-26.json", stop_seal_sha256=c.sha256_file(d0),
             cohort_row_ids=sorted(t["id"] for t in z.cohort([t for t in seal["trades"] if c.aware(t["ts"]) <= sc],
                                                              START_DT, sc)),
             seals={k_: v for k_, v in s["seals"].items() if k_ != "seals/2026-10-27.json"})
    (out / "stop.json").write_text(json.dumps(s), encoding="utf-8")
    probs = z.stop_problems(out, START_DT, st_["calendar"])
    assert any("is not the frozen slices' stop" in p for p in probs), probs


# ---------------------------------------------------------------------- s1_collect
def _plan(tmp_path, monkeypatch):
    t = datetime(2026, 10, 21, 12, tzinfo=UTC)
    monkeypatch.setattr(c, "now_utc", lambda: t)
    k.write_plan(tmp_path, datetime(2026, 11, 2, 14, 30, tzinfo=UTC), "2026-10-30", ["A"], "2026-03-17")
    monkeypatch.setattr(c, "now_utc", lambda: t + timedelta(hours=2))
    return t


def _client(calls):
    def handler(req):
        calls.append(req)
        if "calendar" in str(req.url):
            d, out = datetime(2026, 10, 21).date(), []
            while d <= datetime(2027, 5, 31).date():
                if d.weekday() < 5:
                    out.append({"date": d.isoformat(), "open": "09:30", "close": "16:00"})
                d += timedelta(days=1)
            return httpx.Response(200, json=out)
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_mf_do_audit_refuses_an_ack_for_another_bundle_before_any_request(tmp_path, monkeypatch):
    """Mutant "_approved_bundle returns nothing": an AUDIT-ACK approving another bundle is refused by the bundle
    gate (S1 bundle differs), before any request or reservation."""
    t = _plan(tmp_path, monkeypatch)
    tok = k.audit_token(tmp_path).replace(f"bundle_sha256={c.bundle_sha256()}", "bundle_sha256=" + "0" * 64)
    s1_mailbox(tmp_path, "a1", tok, t + timedelta(hours=1))
    calls = []
    with pytest.raises(SystemExit, match="S1 bundle"):
        k.do_audit(tmp_path, "a1", _client(calls), ("K", "S"))
    assert calls == [] and not (tmp_path / "s1_out" / "audit").exists()


def test_mf_do_audit_manifest_binds_plan_and_bundle(tmp_path, monkeypatch):
    """Mutant "do_audit: manifest does not bind the plan": a COMPLETE audit manifest binds plan and bundle."""
    t = _plan(tmp_path, monkeypatch)
    s1_mailbox(tmp_path, "a1", k.audit_token(tmp_path), t + timedelta(hours=1))
    m = k.do_audit(tmp_path, "a1", _client([]), ("K", "S"))
    assert m["plan_sha256"] == c.sha256_file(tmp_path / "s1_out" / "plan.json") and m["bundle_sha256"] == c.bundle_sha256()


def test_mf_the_final_manifest_binds_the_bundle_and_the_persisted_stop(tmp_path, monkeypatch):
    """Mutant "do_final: manifest binds no bundle"."""
    from test_s1_collect import bars_handler, final_setup
    final_setup(tmp_path, monkeypatch)
    calls = []
    m = k.do_final(tmp_path, "f1", httpx.Client(transport=httpx.MockTransport(bars_handler(calls)),
                                                follow_redirects=False), ("K", "S"))
    assert m["bundle_sha256"] == c.bundle_sha256()
    assert m["stop_sha256"] == c.sha256_file(tmp_path / "s1_out" / "stop.json")


def test_mf_the_final_plan_refuses_a_changed_frozen_slice(tmp_path):
    """Mutant "_stop_state ignores the persisted stop's integrity": a frozen slice changed after the stop refuses
    the final plan."""
    st_ = s1_state(tmp_path, START, score_ready=True, final=False, final_snapshot=False)
    p = tmp_path / "s1_out" / "seals" / "2026-10-26.json"
    p.write_text(json.dumps(dict(read(p), note="x")), encoding="utf-8")
    with _Clock(st_["stop_attested_at"] + timedelta(hours=1)):
        # (fix round 2, B3.3: the post-stop integrity check is now the registration gate's persistent abort,
        # observed before _stop_state's own check; the frozen slice is named either way)
        with pytest.raises(SystemExit, match="frozen slice"):
            k.write_final_plan(tmp_path)


def test_mf_the_final_plan_binds_the_persisted_stop(tmp_path):
    """Mutants "final_plan_record binds no persisted stop" / "_stop_attestation (collect) ignores stop.json": the
    plan binds stop.json and the stop attestation must bind the same stop.json."""
    st_ = s1_state(tmp_path, START, score_ready=True, final=False, final_snapshot=False)
    out = tmp_path / "s1_out"
    with _Clock(st_["stop_attested_at"] + timedelta(hours=1)):
        assert k.final_plan_record(tmp_path)["stop_sha256"] == c.sha256_file(out / "stop.json")
        p = out / "attest_stop.json"
        p.write_text(json.dumps(dict(read(p), stop_sha256="0" * 64)), encoding="utf-8")
        with pytest.raises(SystemExit, match="does not bind"):
            k.write_final_plan(tmp_path)


# ---------------------------------------------------------------------- s1_receipt
def test_mf_the_secret_fingerprint_is_keyed(tmp_path):
    """Mutant "_hmac unkeyed": the same secret under two keys gives two fingerprints."""
    from test_s1_t12_a1 import ROOTS, contract, repo
    root = repo(tmp_path)
    k1, k2 = tmp_path / "k1.key", tmp_path / "k2.key"
    a = rc.semantic_receipt(root, root / ".env", None, roots=ROOTS, contract=contract(), hmac_key=k1)
    b_ = rc.semantic_receipt(root, root / ".env", None, roots=ROOTS, contract=contract(), hmac_key=k2)
    assert a["fingerprint"]["config"]["secrets"]["ALPACA_API_KEY"]["hmac"] != \
        b_["fingerprint"]["config"]["secrets"]["ALPACA_API_KEY"]["hmac"]


def test_mf_a_receipt_error_is_terminal_unless_declared_transient():
    """Mutant "ReceiptError defaults to transient"."""
    assert rc.ReceiptError("x").terminal is True and rc.ReceiptError("y", terminal=False).terminal is False


# ---------------------------------------------------------------------- s1_run (named helpers, serialisation)
def test_mf_runner_sha_or_absent_hashes_an_existing_file(tmp_path):
    """Mutant "_sha_or_absent always absent" (Codex-named helper)."""
    p = tmp_path / "x.json"
    p.write_text("{}")
    assert r._sha_or_absent(p) == c.sha256_file(p) and r._sha_or_absent(tmp_path / "nope") == "absent"


def test_mf_runner_ack_unreadable_mailbox_is_a_refusal(tmp_path):
    """Mutant "_ack: an unreadable mailbox crashes" (Codex-named helper): never created, a refusal."""
    with pytest.raises(SystemExit, match="mailbox unreadable"):
        r._ack("x", "t", mailbox=tmp_path / "nope.sqlite3")
    assert not (tmp_path / "nope.sqlite3").exists()


def test_mf_the_score_report_has_no_private_keys_and_no_secret(tmp_path, monkeypatch):
    """Mutants "_clean keeps private keys" / "_serialise unsorted / unclean" (report serialisation, private-key
    leakage): no '_'-prefixed key reaches s1.json and no file under s1_out holds the HMAC key bytes."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    r.score(tmp_path, "score-ack")
    text = (tmp_path / "s1_out" / "score" / "s1.json").read_text(encoding="utf-8")

    def keys(o):
        if isinstance(o, dict):
            for k_, v in o.items():
                yield k_
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    assert not [k_ for k_ in keys(json.loads(text)) if str(k_).startswith("_")]
    rc.load_or_create_key()
    key_hex = rc.HMAC_KEY.read_bytes().hex()
    for f in (tmp_path / "s1_out").rglob("*"):
        if f.is_file():
            assert key_hex not in f.read_bytes().hex(), f


def test_mf_an_edited_opening_books_file_refuses_the_start_attestation(tmp_path):
    """Mutant "_opening_books accepts a changed existing file"."""
    st_ = s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    s1_unattest(tmp_path, books=False)                    # (fix round 2 migration, B3: the pre-attestation state)
    p = out / "opening_books.json"
    p.write_text(json.dumps(dict(read(p), operational={"qty": {}})), encoding="utf-8")
    with _Clock(START_DT - timedelta(days=1)):
        with pytest.raises(SystemExit, match="opening_books.json differs"):
            r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)


def test_mf_the_score_reverifies_the_run_token_bindings(tmp_path, monkeypatch):
    """Mutant "_score: RUN-ACK not re-verified": a prereg recorded before its RUN-ACK is ABORTED-INVALID."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "prereg.json"
    pr = read(p)
    pr["recorded_utc"] = (c.aware(pr["ack"]["created_utc"]) - timedelta(minutes=1)).isoformat()
    p.write_text(json.dumps(pr), encoding="utf-8")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == "ABORTED-INVALID" and any("registration not verified" in x for x in rep["reasons"])


def test_mf_an_edited_opening_books_file_is_aborted_invalid_at_score(tmp_path, monkeypatch):
    """Mutant "_start_attestation_problems: books not bound"."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "opening_books.json"
    p.write_text(json.dumps(dict(read(p), note="x")), encoding="utf-8")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert "START attestation opening_books_sha256 does not match" in rep["reasons"], rep["reasons"]


def test_mf_an_attestation_binding_another_stop_json_is_unverified(tmp_path, monkeypatch):
    """Mutant "_stop_attestation (score): stop.json not bound"."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "attest_stop.json"
    p.write_text(json.dumps(dict(read(p), stop_sha256="0" * 64)), encoding="utf-8")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(minutes=30))
    rep = r.score(tmp_path, "score-ack-2")
    assert "persisted stop (stop.json) hash differs" in rep["stop_attestation"]["problems"]


def test_mf_an_ack_message_with_two_run_lines_refuses():
    """Mutant "ack_line takes the first of several lines": two S1-RUN-ACK lines are ambiguous."""
    msg = {"ack_id": "m", "lines": ["S1-RUN-ACK bundle_sha256=a", "S1-RUN-ACK bundle_sha256=b"]}
    with pytest.raises(SystemExit, match="exactly one"):
        c.ack_line(msg, "S1-RUN-ACK")


def test_mf_the_score_ack_binds_the_persisted_stop(tmp_path, monkeypatch):
    """Mutant "score_token binds no persisted stop": stop.json edited after the SCORE-ACK makes it stale."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "stop.json"
    p.write_text(json.dumps(dict(read(p), decided_by="edited")), encoding="utf-8")
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    with pytest.raises(SystemExit, match="ack lacks the standalone line"):
        r.score(tmp_path, "score-ack")
    assert not (tmp_path / "s1_out" / "score").exists()
