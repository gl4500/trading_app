from datetime import datetime, timezone
from fractions import Fraction

import pytest
import s1_run as r
from conftest import s1_state

UTC = timezone.utc
SESS = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]


def bar(d, o=100, h=101, l=99, c=100):
    return {"date": d, "o": o, "h": h, "l": l, "c": c}


def lot(i, sym, day, qty=10, px=100.0):
    return {"id": i, "symbol": sym, "entry_ts": datetime.fromisoformat(f"{day}T15:00:00+00:00"), "qty": qty,
            "entry_px": px, "entry_notional": qty * px}


def test_exclusion_window_resolved_vs_inside():                                          # example 21
    acts = [{"type": "forward_splits", "id": "s", "symbol": "A", "ex_date": "2026-10-27", "old_rate": 1,
             "new_rate": 2}]
    bars = {"A": {d: bar(d) for d in SESS}}
    ex = r.exclusions([lot(1, "A", "2026-10-26"), lot(2, "A", "2026-10-28")], acts, [], "2026-10-30", SESS, bars, [])
    assert 1 in ex and 2 not in ex


def test_undated_action_excludes_all_lots_of_symbol():                                   # example 22
    acts = [{"type": "spin_offs", "id": "u", "source_symbol": "A"}]
    bars = {"A": {d: bar(d) for d in SESS}}
    ex = r.exclusions([lot(1, "A", "2026-10-26"), lot(2, "A", "2026-10-29")], acts, [], "2026-10-30", SESS, bars, [])
    assert set(ex) == {1, 2}


def test_endpoint_day_entry_missing_stop_close_excluded():                               # example 23
    bars = {"A": {d: bar(d) for d in SESS[:-1]}}
    assert 1 in r.exclusions([lot(1, "A", "2026-10-30")], [], [], "2026-10-30", SESS, bars, [])


@pytest.mark.parametrize("n,k,want", [(40, 4, "OK"), (40, 5, "INCONCLUSIVE"), (30, 1, "INSUFFICIENT"),
                                      (0, 0, "INSUFFICIENT"), (300, 30, "OK")])
def test_cap_boundary(n, k, want):
    assert r.disposition(n, k) == want


def test_independent_oracle_for_p13_economics():
    """Hand computation (no e1_sim) of one lot: entry 100 x 10 on 10-26; 10-27 close 110 (hw 110); 10-28 low 96
    <= trail 110*0.88 = 96.8 -> exit at 96.8. 5 bp costs on entry and exit."""
    bars = [bar("2026-10-27", 100, 111, 99, 110), bar("2026-10-28", 100, 100, 96, 97)]
    out = r.candidate_economics(lot(1, "A", "2026-10-26"), bars, "2026-10-28", bp=5)
    proceeds = Fraction(968, 10) * 10
    pnl = proceeds - 1000 - Fraction(1000 * 5, 10000) - proceeds * Fraction(5, 10000)
    assert out["_pnl"] == pnl and out["reason"] == "trail"


def test_missing_attestation_is_unverified_and_not_a_nomination():                       # example 9
    v = r.final_verdict(numeric="SHADOW PASS", attest_stop=None)
    assert v == {"verdict": "SHADOW PASS", "provenance": "UNVERIFIED-PROVENANCE", "nomination": False}
    assert r.final_verdict(numeric="SHADOW PASS", attest_stop={"ok": True})["nomination"] is True


def test_prereg_after_planned_start_refused(tmp_path, monkeypatch):                      # example 16
    s1_state(tmp_path, planned_start="2026-10-26T13:30:00+00:00")
    monkeypatch.setattr(r.c, "now_utc", lambda: datetime(2026, 10, 26, 13, 31, tzinfo=UTC))
    with pytest.raises(SystemExit, match="START"):
        r.do_prereg(tmp_path, "m", receipt={})
    assert not (tmp_path / "s1_out" / "prereg.json").exists()


def test_mismatched_or_duplicate_acks_make_no_request_no_output(tmp_path):              # example 18
    s1_state(tmp_path, planned_start="2026-10-26T13:30:00+00:00", score_ready=True)
    with pytest.raises(SystemExit):
        r.score(tmp_path, "wrong-id")
    assert not (tmp_path / "s1_out" / "score").exists()


def test_carry_in_split_blocked_or_inconclusive():                                       # example 12
    acts = [{"type": "forward_splits", "id": "s", "symbol": "B", "ex_date": "2026-09-01", "old_rate": 1,
             "new_rate": 2}]
    assert r.carry_in_status({"B": 5.0}, acts, held_since={"B": "2026-08-01"}, phase="audit") == "BLOCKED"
    assert r.carry_in_status({"B": 5.0}, acts, held_since={"B": "2026-08-01"}, phase="final") == "INCONCLUSIVE"
    assert r.carry_in_status({"B": 5.0}, [], held_since={"B": "2026-08-01"}, phase="final") == "OK"


def test_bridge_ticker_unaudited_split_inconclusive():                                   # example 20
    acts = [{"type": "reverse_splits", "id": "s", "symbol": "NEW", "ex_date": "2026-10-23", "old_rate": 10,
             "new_rate": 1}]
    assert r.carry_in_status({"NEW": 5.0}, acts, held_since={"NEW": "2026-10-22"}, phase="final") == "INCONCLUSIVE"


# ====================================================================== additional tests (written before the code)
import json                                                                      # noqa: E402
import sqlite3                                                                   # noqa: E402
from datetime import timedelta                                                   # noqa: E402

import s1_common                                                                 # noqa: E402
from conftest import S1_RECEIPT, s1_bar, s1_mailbox                              # noqa: E402
from hypothesis import given, settings, strategies as st                        # noqa: E402

START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)


def split(sym, day, kind="forward_splits", i="sp"):
    return {"type": kind, "id": i, "symbol": sym, "ex_date": day, "old_rate": 1, "new_rate": 2}


def at(monkeypatch, t):
    monkeypatch.setattr(s1_common, "now_utc", lambda: t)


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def scored(tmp_path, monkeypatch, ack="score-ack", **kw):
    st_ = s1_state(tmp_path, START, score_ready=True, **kw)
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, ack)
    return st_, rep, read(tmp_path / "s1_out" / "score" / "s1.json")


def all_hashes(root):
    return {p.relative_to(root).as_posix(): s1_common.sha256_file(p)
            for p in sorted((root / "s1_out").rglob("*")) if p.is_file()}


# ---------------------------------------------------------------- unit rules: blocks / windows / carry-in
@pytest.mark.parametrize("action,sym,want", [
    ({"type": "stock_mergers", "acquirer_symbol": "A", "acquiree_symbol": "T", "effective_date": "2026-10-27"}, "A",
     False),
    ({"type": "stock_mergers", "acquirer_symbol": "A", "acquiree_symbol": "T", "effective_date": "2026-10-27"}, "T",
     True),
    ({"type": "cash_mergers", "acquiree_symbol": "T", "effective_date": "2026-10-27"}, "T", True),
    ({"type": "spin_offs", "source_symbol": "P", "new_symbol": "C", "ex_date": "2026-10-27"}, "P", True),
    ({"type": "spin_offs", "source_symbol": "P", "new_symbol": "C", "ex_date": "2026-10-27"}, "C", False),
    ({"type": "rights_distributions", "source_symbol": "P", "new_symbol": "R", "ex_date": "2026-10-27"}, "P", True),
    ({"type": "cash_dividends", "symbol": "D", "special": True, "ex_date": "2026-10-27"}, "D", True),
    ({"type": "cash_dividends", "symbol": "D", "special": False, "ex_date": "2026-10-27"}, "D", False),
    ({"type": "cash_dividends", "symbol": "D", "ex_date": "2026-10-27"}, "D", True),          # unknown kind: block
    ({"type": "name_changes", "old_symbol": "O", "new_symbol": "N", "process_date": "2026-10-27"}, "O", True),
    ({"type": "unit_splits", "old_symbol": "U", "new_symbol": "V", "alternate_symbol": "W",
      "effective_date": "2026-10-27"}, "W", True),
    ({"type": "stock_dividends", "symbol": "S", "ex_date": "2026-10-27"}, "S", True),
    ({"type": "redemptions", "symbol": "R", "process_date": "2026-10-27"}, "R", True),
    ({"type": "worthless_removals", "symbol": "Z", "process_date": "2026-10-27"}, "Z", True),
    ({"type": "brand_new_kind", "acquirer_symbol": "Q"}, "Q", True),                           # unknown type
    ({"type": "forward_splits", "symbol": "OTHER", "ex_date": "2026-10-27"}, "A", False),
])
def test_blocks_by_side_and_kind(action, sym, want):
    assert r.blocks(action, sym) is want


def test_acquirer_side_merger_does_not_exclude_but_acquiree_does():
    acts = [{"type": "stock_mergers", "id": "m", "acquirer_symbol": "A", "acquiree_symbol": "T",
             "effective_date": "2026-10-28"}]
    bars = {s: {d: bar(d) for d in SESS} for s in ("A", "T")}
    ex = r.exclusions([lot(1, "A", "2026-10-26"), lot(2, "T", "2026-10-26")], acts, [], "2026-10-30", SESS, bars, [])
    assert set(ex) == {2}


def test_action_after_stop_or_on_entry_day_does_not_exclude():
    bars = {"A": {d: bar(d) for d in SESS}}
    after = r.exclusions([lot(1, "A", "2026-10-26")], [split("A", "2026-10-31")], [], "2026-10-30", SESS, bars, [])
    entry_day = r.exclusions([lot(1, "A", "2026-10-27")], [split("A", "2026-10-27")], [], "2026-10-30", SESS, bars,
                             [])
    on_stop = r.exclusions([lot(1, "A", "2026-10-26")], [split("A", "2026-10-30")], [], "2026-10-30", SESS, bars, [])
    assert after == {} and entry_day == {} and 1 in on_stop


def test_malformed_action_date_is_treated_as_undated():
    bars = {"A": {d: bar(d) for d in SESS}}
    ex = r.exclusions([lot(1, "A", "2026-10-29")], [split("A", "2026-13-45")], [], "2026-10-30", SESS, bars, [])
    assert 1 in ex


def test_problem_record_and_flagged_bar_exclude():
    bars = {s: {d: bar(d) for d in SESS} for s in ("A", "B", "C")}
    ex = r.exclusions([lot(1, "A", "2026-10-26"), lot(2, "B", "2026-10-26"), lot(3, "C", "2026-10-26")], [],
                      [{"problem": "conflicting duplicate id", "blocks_symbols": ["A"]}], "2026-10-30", SESS, bars,
                      [{"symbol": "B", "session": "2026-10-28", "problem": "invalid"},
                       {"symbol": "C", "session": "2026-10-23", "problem": "invalid"}])     # C: before entry
    assert set(ex) == {1, 2}


def test_required_sessions_always_include_the_stop_close():
    assert r.required_sessions("2026-10-30", "2026-10-30", SESS) == ["2026-10-30"]
    assert r.required_sessions("2026-10-27", "2026-10-29", SESS) == ["2026-10-28", "2026-10-29"]


@settings(max_examples=200, deadline=None)
@given(st.integers(0, 4), st.integers(0, 4), st.integers(0, 4))
def test_exclusion_window_property(entry, action, stop):
    """Window = entry NY date EXCLUSIVE .. stop session INCLUSIVE, independent of any exit."""
    if entry > stop:
        return
    bars = {"A": {d: bar(d) for d in SESS}}
    ex = r.exclusions([lot(1, "A", SESS[entry])], [split("A", SESS[action])], [], SESS[stop], SESS, bars, [])
    assert (1 in ex) == (entry < action <= stop)


def test_carry_in_ignores_actions_before_holding_or_after_stop_and_flags_problems():
    acts = [split("B", "2026-07-01"), split("B", "2026-12-01")]
    assert r.carry_in_status({"B": 5.0}, acts, held_since={"B": "2026-08-01"}, phase="final",
                             until="2026-11-30") == "OK"
    assert r.carry_in_status({"B": 0.0}, [split("B", "2026-09-01")], held_since={"B": "2026-08-01"},
                             phase="audit") == "OK"
    assert r.carry_in_status({"B": 5.0}, [], held_since={"B": "2026-08-01"}, phase="audit",
                             problems=[{"blocks_symbols": ["B"]}]) == "BLOCKED"


# ---------------------------------------------------------------- START attestation / prereg gates
def test_attest_start_requires_exact_statement_once_and_before_start(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    a = read(out / "attest_start.json")
    assert a["statement"] == r.START_STATEMENT and a["trial_id"] == "S1" and a["planned_start"] == START
    assert a["plan_sha256"] == s1_common.sha256_file(out / "plan.json")
    assert a["audit_manifest_sha256"] == s1_common.sha256_file(out / "audit" / "manifest.json")
    assert a["opening_seal_sha256"] == s1_common.sha256_file(out / "seals" / "2026-10-23.json")
    assert a["receipt_sha256"] == s1_common.sha256_bytes(s1_common.canonical(S1_RECEIPT))
    at(monkeypatch, START_DT - timedelta(days=1))
    with pytest.raises(SystemExit):
        r.attest_start(tmp_path, r.START_STATEMENT + " ", S1_RECEIPT)
    with pytest.raises(SystemExit):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)                   # already recorded
    (out / "attest_start.json").unlink()
    at(monkeypatch, START_DT)
    with pytest.raises(SystemExit, match="START"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    at(monkeypatch, START_DT - timedelta(days=1))
    (out / "seals" / "2026-10-23.json").unlink()
    with pytest.raises(SystemExit, match="opening seal"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    assert not (out / "attest_start.json").exists()


def test_prereg_writes_what_checkpoint_and_collectors_read_once(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    at(monkeypatch, START_DT - timedelta(hours=2))
    pr = r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    on_disk = read(out / "prereg.json")
    assert on_disk == pr
    assert pr["start"] == START and pr["receipt"] == S1_RECEIPT
    assert pr["calendar"] == [{k: d[k] for k in ("date", "open", "close")} for d in st_["calendar"]]
    assert pr["plan_sha256"] == s1_common.sha256_file(out / "plan.json")
    assert pr["attest_start_sha256"] == s1_common.sha256_file(out / "attest_start.json")
    assert pr["runner_sha256"] == r.runner_sha() and pr["ack"]["ack_id"] == "run-ack"
    before = s1_common.sha256_file(out / "prereg.json")
    with pytest.raises(SystemExit):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert s1_common.sha256_file(out / "prereg.json") == before


@pytest.mark.parametrize("breakage,match", [
    ("receipt", "receipt"), ("ack", "ack"), ("audit", "audit"), ("attest", "START attestation")])
def test_prereg_refusals_write_nothing(tmp_path, monkeypatch, breakage, match):
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    at(monkeypatch, START_DT - timedelta(hours=2))
    receipt, ack = S1_RECEIPT, "run-ack"
    if breakage == "receipt":
        receipt = dict(S1_RECEIPT, head="other")
    elif breakage == "ack":
        s1_mailbox(tmp_path, "bad", "approve, roughly", START_DT - timedelta(days=1))
        ack = "bad"
    elif breakage == "audit":
        m = read(out / "audit" / "manifest.json")
        (out / "audit" / "manifest.json").write_text(json.dumps(dict(m, outcome="ABORTED")), encoding="utf-8")
    else:
        (out / "attest_start.json").unlink()
    with pytest.raises(SystemExit, match=match):
        r.do_prereg(tmp_path, ack, receipt)
    assert not (out / "prereg.json").exists()


def test_prereg_blocked_by_known_carry_in_split(tmp_path, monkeypatch):                  # example 12 (known)
    s1_state(tmp_path, START, audit_actions=[split("CI", "2026-10-05")])
    at(monkeypatch, START_DT - timedelta(hours=2))
    with pytest.raises(SystemExit, match="BLOCKED"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert not (tmp_path / "s1_out" / "prereg.json").exists()
    assert (tmp_path / "s1_out" / "blocked.json").exists()


def test_prereg_not_blocked_by_split_before_holding(tmp_path, monkeypatch):
    s1_state(tmp_path, START, audit_actions=[split("CI", "2026-09-01")])          # CI bought 2026-10-01
    at(monkeypatch, START_DT - timedelta(hours=2))
    assert r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)["start"] == START


# ---------------------------------------------------------------- stop attestation
def test_attest_stop_requires_statement_and_a_recorded_stop(tmp_path, monkeypatch):
    s1_state(tmp_path, START)
    at(monkeypatch, START_DT - timedelta(hours=2))
    r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    at(monkeypatch, START_DT + timedelta(days=3))
    with pytest.raises(SystemExit, match="stop"):
        r.attest_stop(tmp_path, r.STOP_STATEMENT)                                    # no seal, trial RUNNING
    with pytest.raises(SystemExit):
        r.attest_stop(tmp_path, "I confirm.")
    assert not (tmp_path / "s1_out" / "attest_stop.json").exists()


def test_attest_stop_binds_start_attestation_stop_and_sealed_ledger(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    a = read(out / "attest_stop.json")
    assert a["statement"] == r.STOP_STATEMENT and a["start"] == START
    assert a["stop_close"] == st_["stop"]["stop_close"] == "2026-10-27T20:00:00+00:00"
    assert a["attest_start_sha256"] == s1_common.sha256_file(out / "attest_start.json")
    assert a["sealed_final_ledger_sha256"] == s1_common.sha256_file(out / "seals" / "2026-10-27.json")
    (out / "attest_stop.json").unlink()
    at(monkeypatch, st_["now"])
    with pytest.raises(SystemExit, match="acquisition"):                             # final already exists
        r.attest_stop(tmp_path, r.STOP_STATEMENT)


# ---------------------------------------------------------------- score: lifecycle, verdicts, outputs
def test_score_shadow_pass_verified_nomination_and_oracle_lot(tmp_path, monkeypatch):
    """Baseline sells at 80; P13 hard stop 92 hits on day 1 (low 85) -> exit at 92. Hand Fraction oracle."""
    fn = lambda s, d: s1_bar(d, 100, 100, 85, 90) if d == "2026-10-27" else s1_bar(d)
    _, rep, disk = scored(tmp_path, monkeypatch, bar_fn=fn)
    assert disk == rep
    assert (rep["verdict"], rep["provenance"], rep["nomination"]) == ("SHADOW PASS", "VERIFIED", True)
    assert rep["n"] == 100 and rep["k"] == 0 and rep["retained"] == 100
    one = rep["lots"][0]
    for bp in (5, 10):
        rate = Fraction(bp, 10000)
        cand = Fraction(920) - 1000 - 1000 * rate - 920 * rate
        base = Fraction(800) - 1000 - 1000 * rate - 800 * rate
        assert one["cand"][str(bp)]["P13"]["pnl"] == pytest.approx(float(cand), abs=1e-9)
        assert one["base"][str(bp)]["pnl"] == pytest.approx(float(base), abs=1e-9)
        assert rep["levels"][str(bp)]["improves"] is True
    assert one["cand"]["5"]["P13"]["reason"] == "hard"
    assert set(rep["levels"]) == {"0", "1", "5", "10"} and set(rep["bootstrap"]) == {"5", "10"}


def test_score_fail_when_baseline_better(tmp_path, monkeypatch):
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 120.0)} for i in range(100)]
    _, rep, _ = scored(tmp_path, monkeypatch, lots=lots)
    assert (rep["verdict"], rep["nomination"]) == ("FAIL", False)


def test_score_without_stop_attestation_is_unverified_not_nominated(tmp_path, monkeypatch):    # example 9
    _, rep, _ = scored(tmp_path, monkeypatch, stop_attest=False)
    assert rep["verdict"] == "SHADOW PASS" and rep["provenance"] == "UNVERIFIED-PROVENANCE"
    assert rep["nomination"] is False


def test_score_stop_attestation_with_wrong_binding_is_unverified(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "attest_stop.json"
    p.write_text(json.dumps(dict(read(p), sealed_final_ledger_sha256="0" * 64)), encoding="utf-8")
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(hours=1))
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, "score-ack-2")
    assert rep["provenance"] == "UNVERIFIED-PROVENANCE" and rep["nomination"] is False


def test_second_score_refused_and_nothing_overwritten(tmp_path, monkeypatch):            # example 18
    scored(tmp_path, monkeypatch)
    before = all_hashes(tmp_path)
    with pytest.raises(SystemExit):
        r.score(tmp_path, "score-ack")
    assert all_hashes(tmp_path) == before


def test_score_reserves_before_any_priced_computation(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True)
    at(monkeypatch, st_["now"])
    seen = []
    real = r.b.economic_lots

    def spy(*a, **kw):
        seen.append((tmp_path / "s1_out" / "score" / "attempt.json").exists())
        return real(*a, **kw)
    monkeypatch.setattr(r.b, "economic_lots", spy)
    r.score(tmp_path, "score-ack")
    assert seen and all(seen)


def test_score_output_strips_exact_values(tmp_path, monkeypatch):
    scored(tmp_path, monkeypatch)
    text = (tmp_path / "s1_out" / "score" / "s1.json").read_text(encoding="utf-8")
    assert '"_pnl"' not in text and '"_ret"' not in text and "Fraction" not in text


def test_score_aborted_checkpoint_is_invalid_and_unpriced(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True)
    (tmp_path / "s1_out" / "aborted.json").write_text(json.dumps({"reason": "semantic receipt changed"}),
                                                      encoding="utf-8")
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == "ABORTED-INVALID" and rep["nomination"] is False and "levels" not in rep


@pytest.mark.parametrize("tamper", ["row", "receipt", "capture"])
def test_score_seal_or_receipt_violation_is_invalid(tmp_path, monkeypatch, tamper):
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "seals" / "2026-10-26.json"
    seal = read(p)
    if tamper == "row":
        seal["trades"][-1]["price"] = 99.5                                     # fence no longer matches the row
    elif tamper == "receipt":
        seal["receipt_sha256"] = "f" * 64
    else:
        seal["capture"]["projection_sha256"] = "e" * 64
    p.write_text(json.dumps(seal), encoding="utf-8")
    at(monkeypatch, st_["now"])
    assert r.score(tmp_path, "score-ack")["verdict"] == "ABORTED-INVALID"


def test_score_no_valid_seal_is_never_fail(tmp_path, monkeypatch):                       # Review Focus 5
    _, rep, _ = scored(tmp_path, monkeypatch, lots=[], seal_days=[])
    assert rep["verdict"] == "NO-VALID-SEAL" and rep["nomination"] is False


def test_score_timeout_with_few_lots_is_insufficient_not_fail(tmp_path, monkeypatch):   # Review Focus 5
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 120.0)} for i in range(20)]
    st_, rep, _ = scored(tmp_path, monkeypatch, lots=lots)
    assert st_["stop"]["status"] == "TIMEOUT"
    assert rep["verdict"] == "INSUFFICIENT" and rep["n"] == 20 and "levels" not in rep


def test_score_carry_in_split_revealed_by_final_is_inconclusive(tmp_path, monkeypatch):  # example 12 (final)
    _, rep, _ = scored(tmp_path, monkeypatch, carry_in=(("B", 5, 50.0, "2026-08-03T15:00:00+00:00"),),
                       final_actions=[split("B", "2026-09-01")])
    assert rep["verdict"] == "INCONCLUSIVE" and "levels" not in rep
    assert any("B" in x for x in rep["reasons"])


def test_score_bridge_ticker_split_is_inconclusive(tmp_path, monkeypatch):               # example 20
    _, rep, _ = scored(tmp_path, monkeypatch, bridge=(("NEW", "BUY", 5, 20.0, "2026-10-24T00:00:00+00:00"),),
                       final_actions=[split("NEW", "2026-10-23", kind="reverse_splits")])
    assert rep["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("n_x,want", [(10, "SHADOW PASS"), (11, "INCONCLUSIVE")])
def test_score_exclusion_cap_exactly_ten_percent_allowed(tmp_path, monkeypatch, n_x, want):
    lots = ([{"symbol": "X", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for _ in range(n_x)]
            + [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)}
               for i in range(100 - n_x)])
    _, rep, _ = scored(tmp_path, monkeypatch, lots=lots, final_actions=[split("X", "2026-10-27")])
    assert rep["verdict"] == want and rep["k"] == n_x and rep["n"] == 100
    assert len(rep["excluded"]) == n_x and all("forward_splits" in " ".join(v) for v in rep["excluded"].values())
    assert rep["excluded_notional_share"] == pytest.approx(n_x / 100)


def test_score_missing_bar_excludes_lot_in_both_arms(tmp_path, monkeypatch):
    fn = lambda s, d: None if (s == "S0" and d == "2026-10-27") else s1_bar(d)
    _, rep, _ = scored(tmp_path, monkeypatch, bar_fn=fn)
    assert rep["k"] == 20 and rep["verdict"] == "INCONCLUSIVE"
    assert all("2026-10-27" in " ".join(v) for v in rep["excluded"].values())


def test_score_failure_inside_the_attempt_is_preserved_as_aborted(tmp_path, monkeypatch):
    """Retrospective (added after the code): a SystemExit from inside the computation (e.g. the pinned E1 core's
    hash check) still leaves the reserved attempt with an ABORTED record, and a retry is refused."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    at(monkeypatch, st_["now"])

    # Input adjusted in fix round 1 (ruling I-1): the stop state is now computed before reserving, so a broken
    # s1_common.sim() is refused before the attempt; the in-attempt SystemExit is injected via p13() instead.
    def boom():
        raise SystemExit("P13 in the pinned core is not the registered rule")
    monkeypatch.setattr(s1_common, "p13", boom)
    with pytest.raises(SystemExit, match="ABORTED"):
        r.score(tmp_path, "score-ack")
    rec = read(tmp_path / "s1_out" / "score" / "s1.json")
    assert rec["outcome"] == "ABORTED" and rec["verdict"] == "ABORTED-INVALID" and rec["nomination"] is False
    with pytest.raises(SystemExit):
        r.score(tmp_path, "score-ack")


def test_prereg_after_start_refused_even_with_valid_ack_and_receipt(tmp_path, monkeypatch):
    """Retrospective (added after the code; a hand mutant removing the START check survived the brief's example-16
    test, whose receipt={} is refused by the receipt binding instead): everything else valid, clock at START."""
    s1_state(tmp_path, START)
    for t in (START_DT, START_DT + timedelta(minutes=1)):
        at(monkeypatch, t)
        with pytest.raises(SystemExit, match="planned START has passed"):
            r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert not (tmp_path / "s1_out" / "prereg.json").exists()


@pytest.mark.parametrize("n,k,want", [(30, 0, "OK"), (33, 3, "OK"), (31, 2, "INSUFFICIENT"), (10, 1, "INSUFFICIENT")])
def test_minimum_retained_boundary(n, k, want):
    """Retrospective (added after the code; a hand mutant `<= 30` survived): exactly 30 retained is enough."""
    assert r.disposition(n, k) == want


# ---------------------------------------------------------------- Task 7 controller rulings (C-2, runner change)
def row(i, sym, act, sh, day, hhmm="15:00", px=100.0):
    ts = f"{day}T{hhmm}:00+00:00"
    return {"id": i, "symbol": sym, "action": act, "shares": sh, "price": px, "timestamp": ts, "ts": ts,
            "reasoning_sha256": "0" * 64}


def test_split_with_a_lot_open_across_it_excludes_every_lot_of_the_symbol():
    """Retrospective (Task 7 controller rulings): lot A entered before the split and still open across it, lot B
    entered after it -> FIFO attribution untrusted, both excluded in both arms."""
    rows = [row(1, "A", "BUY", 10, "2026-10-26"), row(2, "A", "BUY", 10, "2026-10-29")]
    acts = [split("A", "2026-10-28", i="sp1")]
    untrusted = r.fifo_untrusted(rows, acts, "2026-10-26", "2026-10-30")
    assert untrusted == {"A": ["FIFO attribution untrusted after sp1 on 2026-10-28"]}
    bars = {"A": {d: bar(d) for d in SESS}}
    lots = [lot(1, "A", "2026-10-26"), lot(2, "A", "2026-10-29")]
    ex = r.exclusions(lots, acts, [], "2026-10-30", SESS, bars, [], untrusted=untrusted)
    assert set(ex) == {1, 2}
    assert any("FIFO attribution untrusted after sp1 on 2026-10-28" in w for w in ex[2])


def test_split_with_no_lot_open_across_it_does_not_exclude_later_lots():
    """Retrospective (Task 7 controller rulings): the earlier lot was fully closed before the split; lots entered
    after the split are not excluded for it."""
    rows = [row(1, "A", "BUY", 10, "2026-10-26"), row(2, "A", "SELL", 10, "2026-10-27"),
            row(3, "A", "BUY", 10, "2026-10-29")]
    acts = [split("A", "2026-10-28", i="sp1")]
    assert r.fifo_untrusted(rows, acts, "2026-10-26", "2026-10-30") == {}
    bars = {"A": {d: bar(d) for d in SESS}}
    assert r.exclusions([lot(3, "A", "2026-10-29")], acts, [], "2026-10-30", SESS, bars, [], untrusted={}) == {}


def test_fifo_untrusted_ignores_actions_outside_the_trial_window_and_acquirer_side():
    """Retrospective (Task 7 controller rulings)."""
    rows = [row(1, "A", "BUY", 10, "2026-10-26")]
    acts = [split("A", "2026-10-31", i="late"),
            {"type": "stock_mergers", "id": "m", "acquirer_symbol": "A", "acquiree_symbol": "T",
             "effective_date": "2026-10-28"}]
    assert r.fifo_untrusted(rows, acts, "2026-10-26", "2026-10-30") == {}


def test_score_excludes_post_split_lot_when_an_earlier_lot_was_open_across_the_split(tmp_path, monkeypatch):
    """Retrospective (Task 7 controller rulings): X1 bought day 0 and sold day 2, split on day 1, X2 bought day 2
    (after the split) -> both X lots excluded; X2 with the FIFO-attribution reason."""
    lots = ([{"symbol": "X", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (2, 80.0)},
             {"symbol": "X", "qty": 10, "px": 100.0, "buy_day": 2, "sell": (2, 80.0)}]
            + [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(98)])
    st_, rep, _ = scored(tmp_path, monkeypatch, lots=lots, final_actions=[split("X", "2026-10-27", i="spx")])
    assert st_["stop"]["stop_close"] == "2026-10-28T20:00:00+00:00"
    x_ids = [t["id"] for t in st_["rows"] if t["symbol"] == "X" and t["action"] == "BUY"]
    assert set(rep["excluded"]) == {str(i) for i in x_ids}
    assert any("FIFO attribution untrusted after spx on 2026-10-27" in w for w in rep["excluded"][str(x_ids[1])])
    assert rep["k"] == 2 and rep["verdict"] == "SHADOW PASS"


def test_score_runner_changed_since_prereg_is_invalid(tmp_path, monkeypatch):
    """Retrospective (Task 7 controller rulings): a runner hash different from prereg's runner_sha256 makes the
    verdict ABORTED-INVALID, even under a SCORE-ACK that binds the new runner."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "runner_sha", lambda: "0" * 64)
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(hours=1))
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, "score-ack-2")
    assert rep["verdict"] == "ABORTED-INVALID" and "runner changed since prereg" in rep["reasons"]
    assert "levels" not in rep and rep["nomination"] is False


# ---------------------------------------------------------------- Task 7 review fix round 1 (I-1..I-3, M-1..M-4, M-6)
def test_early_score_ack_while_running_is_refused_with_no_output(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 1), I-1: an early SCORE-ACK (absent/absent token) while the trial is
    RUNNING writes nothing; once the trial has ended (here NO-VALID-SEAL) a post-end ACK scores normally.
    Input adjusted in fix round 2 (ruling R-1): reusing the early ACK after the end is now refused by design, so
    the second step uses s1_state's "score-ack", created after the window end."""
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[])
    at(monkeypatch, START_DT + timedelta(days=2))
    s1_mailbox(tmp_path, "early", r.score_token(tmp_path), START_DT + timedelta(days=1))
    with pytest.raises(SystemExit, match="RUNNING"):
        r.score(tmp_path, "early")
    assert not (tmp_path / "s1_out" / "score").exists()
    at(monkeypatch, st_["now"])
    assert r.score(tmp_path, "score-ack")["verdict"] == "NO-VALID-SEAL"


@pytest.mark.parametrize("offset", [timedelta(hours=-1), timedelta(0)])
def test_run_ack_not_strictly_after_start_attestation_is_refused(tmp_path, monkeypatch, offset):
    """Retrospective (Task 7 review fix round 1), I-2: the RUN-ACK binds attest_start_sha256 and must be created
    strictly after the START attestation was recorded."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    assert f"attest_start_sha256={s1_common.sha256_file(out / 'attest_start.json')}" in r.run_token(tmp_path)
    recorded = s1_common.aware(read(out / "attest_start.json")["recorded_utc"])
    s1_mailbox(tmp_path, "too-early", r.run_token(tmp_path), recorded + offset)
    at(monkeypatch, START_DT - timedelta(hours=2))
    with pytest.raises(SystemExit, match="START attestation"):
        r.do_prereg(tmp_path, "too-early", S1_RECEIPT)
    assert not (out / "prereg.json").exists()
    assert r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)["start"] == START          # the proper ACK still works


def test_carry_in_sold_before_a_later_split_is_not_inconclusive(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 1), I-3: carry-in CI fully sold on the START session; a CI split the
    next session finds no carry-in lot open across it, so the trial is not INCONCLUSIVE."""
    _, rep, _ = scored(tmp_path, monkeypatch, bridge=(("CI", "SELL", 10, 55.0, "2026-10-26T18:30:00+00:00"),),
                       final_actions=[split("CI", "2026-10-27", i="ci-split")])
    assert rep["verdict"] == "SHADOW PASS" and not any("CI" in x for x in rep["reasons"])


def test_carry_in_still_open_across_a_trial_split_is_inconclusive(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 1), I-3, other side: CI never sold; split inside the trial."""
    _, rep, _ = scored(tmp_path, monkeypatch, final_actions=[split("CI", "2026-10-27", i="ci-split")])
    assert rep["verdict"] == "INCONCLUSIVE" and any("ci-split" in x for x in rep["reasons"])


@pytest.mark.parametrize("action,trigger", [
    ({"type": "cash_dividends", "id": "d", "symbol": "A", "special": True, "ex_date": "2026-10-28"}, False),
    ({"type": "spin_offs", "id": "so", "source_symbol": "A", "new_symbol": "C", "ex_date": "2026-10-28"}, False),
    ({"type": "rights_distributions", "id": "rd", "source_symbol": "A", "new_symbol": "R",
      "ex_date": "2026-10-28"}, False),
    ({"type": "stock_dividends", "id": "sd", "symbol": "A", "ex_date": "2026-10-28"}, True),
    ({"type": "name_changes", "id": "nc", "old_symbol": "A", "new_symbol": "B", "process_date": "2026-10-28"}, True),
    ({"type": "cash_mergers", "id": "cm", "acquiree_symbol": "A", "effective_date": "2026-10-28"}, True),
    ({"type": "redemptions", "id": "rm", "symbol": "A", "process_date": "2026-10-28"}, True),
    ({"type": "worthless_removals", "id": "wr", "symbol": "A", "process_date": "2026-10-28"}, True),
    ({"type": "unit_splits", "id": "us", "old_symbol": "A", "new_symbol": "V", "alternate_symbol": "W",
      "effective_date": "2026-10-28"}, True),
    ({"type": "brand_new_kind", "id": "nk", "symbol": "A", "ex_date": "2026-10-28"}, True),
])
def test_fifo_untrust_triggers_are_unit_identity_actions_only(action, trigger):
    """Retrospective (Task 7 review fix round 1), M-1: special dividends and spin-off/rights sources stay ordinary
    per-lot exclusions (lot 1's window still excludes it) but do not untrust the symbol's later lots."""
    rows = [row(1, "A", "BUY", 10, "2026-10-26"), row(2, "A", "BUY", 10, "2026-10-29")]
    untrusted = r.fifo_untrusted(rows, [action], "2026-10-26", "2026-10-30")
    assert ("A" in untrusted) is trigger
    bars = {"A": {d: bar(d) for d in SESS}}
    ex = r.exclusions([lot(1, "A", "2026-10-26"), lot(2, "A", "2026-10-29")], [action], [], "2026-10-30", SESS,
                      bars, [], untrusted=untrusted)
    assert 1 in ex and (2 in ex) is trigger


def test_combined_carry_in_and_cap_reports_carry_in_inconclusive(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 1), M-3: carry-in INCONCLUSIVE precedes the exclusion cap."""
    lots = ([{"symbol": "X", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for _ in range(20)]
            + [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(80)])
    _, rep, _ = scored(tmp_path, monkeypatch, lots=lots, carry_in=(("B", 5, 50.0, "2026-08-03T15:00:00+00:00"),),
                       final_actions=[split("B", "2026-09-01"), split("X", "2026-10-27", i="spx")])
    assert rep["verdict"] == "INCONCLUSIVE" and any("carry-in B" in x for x in rep["reasons"])
    assert "k" not in rep                                                       # the cap was never evaluated


def test_combined_abort_and_no_valid_seal_is_aborted_invalid(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 1), M-3."""
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[])
    (tmp_path / "s1_out" / "aborted.json").write_text(json.dumps({"reason": "x"}), encoding="utf-8")
    at(monkeypatch, st_["now"])
    assert r.score(tmp_path, "score-ack")["verdict"] == "ABORTED-INVALID"


def test_combined_blocked_and_insufficient_is_blocked(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 1), M-3: a known pre-START carry-in split (prereg's refusal bypassed
    to reach the score) outranks a 20-lot timeout INSUFFICIENT."""
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 120.0)} for i in range(20)]
    monkeypatch.setattr(r, "carry_in_reasons", lambda *a, **kw: [])               # bypass prereg's BLOCKED gate
    st_ = s1_state(tmp_path, START, score_ready=True, lots=lots, audit_actions=[split("CI", "2026-10-05")])
    monkeypatch.undo()
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert rep["verdict"] == "BLOCKED" and any("CI" in x for x in rep["reasons"])


@pytest.mark.parametrize("edit", ["attest_stop.json", "final/manifest.json"])
def test_score_ack_with_stale_hash_is_refused_with_no_output(tmp_path, monkeypatch, edit):
    """Retrospective (Task 7 review fix round 1), M-4: the stop attestation or the final manifest edited after the
    SCORE-ACK means the ACK no longer matches; no score/ is written."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / edit
    p.write_text(json.dumps(dict(read(p), edited=True)), encoding="utf-8")
    at(monkeypatch, st_["now"])
    with pytest.raises(SystemExit):
        r.score(tmp_path, "score-ack")
    assert not (tmp_path / "s1_out" / "score").exists()


def test_report_is_serialised_before_the_output_file_is_opened(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 1), M-6: an unserialisable report never leaves an empty s1.json; the
    ABORTED record is written instead."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    at(monkeypatch, st_["now"])
    real = r._score
    monkeypatch.setattr(r, "_score", lambda out: dict(real(out), bad=object()))
    with pytest.raises(SystemExit, match="ABORTED"):
        r.score(tmp_path, "score-ack")
    rec = read(tmp_path / "s1_out" / "score" / "s1.json")
    assert rec["outcome"] == "ABORTED" and rec["verdict"] == "ABORTED-INVALID"


# ---------------------------------------------------------------- Task 7 review fix round 2 (R-1, m-1, m-2)
import shutil                                                                    # noqa: E402

STOP_CLOSE = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)                          # default s1_state stop


def drop_final_and_attestation(root):
    out = root / "s1_out"
    shutil.rmtree(out / "final")
    for f in ("final_plan.json", "attest_stop.json"):
        if (out / f).exists():
            (out / f).unlink()


def test_score_ack_created_while_running_is_refused_after_the_stop(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 2), R-1: an absent/absent SCORE-ACK created while the trial was RUNNING
    is still refused once the trial has stopped; nothing is written."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    drop_final_and_attestation(tmp_path)
    s1_mailbox(tmp_path, "early", r.score_token(tmp_path), START_DT + timedelta(hours=6))
    at(monkeypatch, st_["now"])
    with pytest.raises(SystemExit, match="SCORE-ACK"):
        r.score(tmp_path, "early")
    assert not (tmp_path / "s1_out" / "score").exists()


def test_score_ack_after_the_stop_but_before_any_final_manifest_is_refused(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 2), R-1: STOPPED/TIMEOUT need s1_out/final/manifest.json first."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    drop_final_and_attestation(tmp_path)
    s1_mailbox(tmp_path, "post-stop", r.score_token(tmp_path), STOP_CLOSE + timedelta(hours=1))
    at(monkeypatch, st_["now"])
    with pytest.raises(SystemExit, match="final"):
        r.score(tmp_path, "post-stop")
    assert not (tmp_path / "s1_out" / "score").exists()


def test_score_ack_strictly_after_the_stop_with_a_final_manifest_scores(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 2), R-1: an ACK at exactly the stop close is refused; one minute later
    (final manifest present) it scores."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    s1_mailbox(tmp_path, "at-stop", r.score_token(tmp_path), STOP_CLOSE)
    s1_mailbox(tmp_path, "after-stop", r.score_token(tmp_path), STOP_CLOSE + timedelta(minutes=1))
    at(monkeypatch, st_["now"])
    with pytest.raises(SystemExit, match="SCORE-ACK"):
        r.score(tmp_path, "at-stop")
    assert not (tmp_path / "s1_out" / "score").exists()
    assert r.score(tmp_path, "after-stop")["verdict"] == "SHADOW PASS"


def test_score_ack_before_the_no_valid_seal_window_end_is_refused(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 2), R-1: for NO-VALID-SEAL the end instant is the last eligible
    session's seal window end."""
    st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[])
    s1_mailbox(tmp_path, "before-end", r.score_token(tmp_path), st_["now"] - timedelta(days=5))
    at(monkeypatch, st_["now"])
    with pytest.raises(SystemExit, match="SCORE-ACK"):
        r.score(tmp_path, "before-end")
    assert not (tmp_path / "s1_out" / "score").exists()
    assert r.score(tmp_path, "score-ack")["verdict"] == "NO-VALID-SEAL"


def test_score_ack_before_the_recorded_abort_is_refused(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 2), R-1: for an abort the end instant is aborted.json's recorded
    (capture) time."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    (tmp_path / "s1_out" / "aborted.json").write_text(json.dumps(
        {"reason": "semantic receipt changed", "actual": (st_["now"] - timedelta(hours=1)).isoformat()}),
        encoding="utf-8")
    at(monkeypatch, st_["now"])
    with pytest.raises(SystemExit, match="SCORE-ACK"):
        r.score(tmp_path, "score-ack")                                           # created before the abort
    assert not (tmp_path / "s1_out" / "score").exists()
    s1_mailbox(tmp_path, "after-abort", r.score_token(tmp_path), st_["now"] - timedelta(minutes=30))
    assert r.score(tmp_path, "after-abort")["verdict"] == "ABORTED-INVALID"


def test_malformed_seal_is_recorded_as_aborted_invalid_not_refused_forever(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 2), m-1: a seal missing "close" does not block the pre-reservation
    check; the attempt records ABORTED-INVALID."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "seals" / "2026-10-26.json"
    seal = read(p)
    del seal["close"]
    p.write_text(json.dumps(seal), encoding="utf-8")
    at(monkeypatch, st_["now"])
    try:
        rep = r.score(tmp_path, "score-ack")
    except SystemExit:
        rep = None
    rec = read(tmp_path / "s1_out" / "score" / "s1.json")
    assert rec["verdict"] == "ABORTED-INVALID" and (rep is None or rep == rec)


def test_pinned_core_hash_mismatch_is_refused_before_reservation(tmp_path, monkeypatch):
    """Retrospective (Task 7 review fix round 2), m-2: a pinned E1 core that fails its hash check refuses the score
    before the reservation; nothing is written."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    at(monkeypatch, st_["now"])

    def mismatch():
        raise SystemExit("e1_sim.py: missing or hash differs from the pinned 68f21ab19d74")
    monkeypatch.setattr(s1_common, "sim", mismatch)
    with pytest.raises(SystemExit, match="hash differs"):
        r.score(tmp_path, "score-ack")
    assert not (tmp_path / "s1_out" / "score").exists()
