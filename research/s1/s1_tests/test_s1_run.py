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


# ---------------------------------------------------------------- Task 9 mutant survivors (retrospective tests)
def test_exclusion_window_runs_to_the_stop_not_to_the_lots_actual_exit(tmp_path, monkeypatch):
    """Retrospective (Task 9 mutant survivor "exclusion window shortened to the actual exit"): X bought day 0 and
    sold day 1, a split on X on day 2, stop on day 3 -> the X lot is excluded (paired window = entry date exclusive
    .. stop session inclusive for both arms, never the lot's own exit)."""
    lots = ([{"symbol": "X", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)}]
            + [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (3, 80.0)} for i in range(99)])
    st_, rep, _ = scored(tmp_path, monkeypatch, lots=lots, final_actions=[split("X", "2026-10-28", i="spx")])
    assert st_["stop"]["stop_close"] == "2026-10-29T20:00:00+00:00"
    x_id = next(t["id"] for t in st_["rows"] if t["symbol"] == "X" and t["action"] == "BUY")
    assert rep["k"] == 1 and set(rep["excluded"]) == {str(x_id)}, rep.get("excluded")
    assert any("forward_splits spx on 2026-10-28" in w for w in rep["excluded"][str(x_id)])


# ---------------------------------------------------------------- Task 9 round 2: Cosmic Ray survivors (retrospective)
import s1_books                                                                  # noqa: E402
from conftest import _default_lots                                               # noqa: E402


def _fresh(s):
    """An equal but distinct str object (len >= 2): rules must compare by value, never by identity."""
    return (s + "#")[:-1]


def _row(i, sym, act, sh, ts, px=10.0):
    return {"id": i, "symbol": sym, "action": act, "shares": sh, "price": px, "timestamp": ts, "ts": ts,
            "reasoning_sha256": "0" * 64}


def test_cr_blocks_compares_kinds_and_symbols_by_value():
    """Retrospective (Task 9 CR survivors s1_run:66-76, blocks): kinds and symbols are compared by equality (not
    identity or ordering); only the literal False makes a cash dividend ordinary; affected_symbols add to the named
    set."""
    assert r.blocks({"type": _fresh("cash_dividends"), "symbol": "XY", "special": False}, "XY") is False
    assert r.blocks({"type": _fresh("name_changes"), "old_symbol": "OLD", "new_symbol": "XY"}, "XY") is False
    for kind, field in (("cash_dividends", "symbol"), ("spin_offs", "source_symbol"),
                        ("stock_mergers", "acquiree_symbol"), ("name_changes", "old_symbol")):
        a = {"type": kind, field: "MM", "special": True}
        assert r.blocks(a, _fresh("MM")) is True, kind
        assert r.blocks(a, "AA") is False and r.blocks(a, "ZZ") is False, kind
    assert r.blocks({"type": "cash_dividends", "symbol": "XY", "special": 0}, "XY") is True
    assert r.blocks({"type": "mystery", "symbol": "XY", "affected_symbols": ["XY"]}, "XY") is True
    assert r.blocks({"type": "mystery", "affected_symbols": ["QQ"]}, "QQ") is True


def test_cr_open_lots_before_is_strictly_before_the_day_and_keeps_fractional_lots():
    """Retrospective (Task 9 CR survivors s1_run:99/103): rows of the day itself are not "before" it; a lot of
    0.5 shares is open."""
    rows = [_row(1, "AA", "BUY", 0.5, "2026-10-26T15:00:00+00:00"), _row(2, "BB", "BUY", 1.0, "2026-10-27T15:00:00+00:00")]
    assert [l["id"] for l in r.open_lots_before(rows, "2026-10-27")] == [1]


def test_cr_fifo_untrusted_window_inclusive_and_every_action_scanned():
    """Retrospective (Task 9 CR survivors s1_run:113/114): the window is START session .. stop session, both
    inclusive; an earlier action is ignored; an undated action never ends the scan."""
    rows = [_row(1, "AA", "BUY", 10.0, "2026-10-20T15:00:00+00:00")]

    def sp(d, i):
        return {"type": "forward_splits", "id": i, "symbol": "AA", "ex_date": d}
    assert r.fifo_untrusted(rows, [sp("2026-10-26", "a")], "2026-10-26", "2026-10-30") != {}
    assert r.fifo_untrusted(rows, [sp("2026-10-30", "b")], "2026-10-26", "2026-10-30") != {}
    assert r.fifo_untrusted(rows, [sp("2026-10-23", "c")], "2026-10-26", "2026-10-30") == {}
    assert r.fifo_untrusted(rows, [{"type": "forward_splits", "id": "u", "symbol": "AA"}, sp("2026-10-28", "d")],
                            "2026-10-26", "2026-10-30") == {"AA": ["FIFO attribution untrusted after d on 2026-10-28"]}


def test_cr_exclusions_scan_every_action():
    """Retrospective (Task 9 CR survivor s1_run:139): a non-blocking action before a blocking one does not end the
    scan."""
    acts = [{"type": "forward_splits", "id": "o", "symbol": "OTHER", "ex_date": "2026-10-27"},
            split("A", "2026-10-28", i="s")]
    bars = {"A": {d: bar(d) for d in SESS}}
    assert r.exclusions([lot(1, "A", "2026-10-26")], acts, [], "2026-10-30", SESS, bars, []) == \
        {1: ["forward_splits s on 2026-10-28"]}


def test_cr_disposition_single_lot_fully_excluded_is_inconclusive():
    """Retrospective (Task 9 CR survivor s1_run:156): N = 0 is the only special case; N = 1, K = 1 is
    INCONCLUSIVE (cap) before the minimum."""
    assert r.disposition(1, 1) == "INCONCLUSIVE" and r.disposition(0, 0) == "INSUFFICIENT"


def test_cr_carry_in_reasons_fractional_every_symbol_every_action_start_day_rule():
    """Retrospective (Task 9 CR survivors s1_run:175/176/182/187/197): a fractional holding counts; a zero holding
    or a non-blocking action never ends the scan; an action dated exactly on start_day consults open_across; phase
    is compared by value."""
    def sp(s, d, i):
        return {"type": "forward_splits", "id": i, "symbol": s, "ex_date": d}
    acts = [{"type": "cash_dividends", "id": "x", "symbol": "QQ", "special": True}, sp("BB", "2026-10-20", "s")]
    assert r.carry_in_reasons({"AA": 0.0, "BB": 0.5}, acts, {"BB": "2026-10-01"}) == \
        ["carry-in BB: forward_splits s on 2026-10-20 (held since 2026-10-01)"]
    assert r.carry_in_reasons({"BB": 1.0}, [sp("BB", "2026-10-26", "t")], {"BB": "2026-10-01"},
                              start_day="2026-10-26", open_across=lambda s, d: False) == []
    assert r.carry_in_status({"BB": 1.0}, acts, {"BB": "2026-10-01"}, _fresh("audit")) == "BLOCKED"


def test_cr_candidate_cost_kind_is_terminal_only_at_the_endpoint():
    """Retrospective (Task 9 CR survivors s1_run:205): an endpoint mark pays the terminal cost, a stop exit the exit
    cost."""
    out = r.candidate_economics(lot(1, "A", "2026-10-26"), [bar("2026-10-27"), bar("2026-10-28")], "2026-10-28",
                                bp=10)
    assert out["reason"] == "endpoint" and out["terminal_cost"] > 0 and out["exit_cost"] == 0
    out = r.candidate_economics(lot(1, "A", "2026-10-26"), [bar("2026-10-27", 100, 100, 90, 91)], "2026-10-27",
                                bp=10)
    assert out["reason"] == "hard" and out["exit_cost"] > 0 and out["terminal_cost"] == 0


def _attempt_dir(tmp_path, outcome="COMPLETE", files=None, make=("x.json",)):
    d = tmp_path / "att"
    d.mkdir()
    for n in make:
        (d / n).write_text("[]", encoding="utf-8")
    real = {n: s1_common.sha256_file(d / n) for n in make}
    (d / "manifest.json").write_text(json.dumps({"outcome": outcome, "files": real if files is None else files}),
                                     encoding="utf-8")
    return d


@pytest.mark.parametrize("outcome,files,names", [
    ("ABORTED", None, ["x.json"]), ("RUNNING", None, ["x.json"]), ("COMPLETE", {}, ["x.json"]),
    ("COMPLETE", {"x.json": "0" * 64}, ["x.json"]), ("COMPLETE", {"x.json": "f" * 64}, ["x.json"]),
    ("COMPLETE", {"x.json": None, "y.json": "a" * 64}, ["y.json"]),
])
def test_cr_attempt_rejects_every_manifest_defect(tmp_path, outcome, files, names):
    """Retrospective (Task 9 CR survivors s1_run:263/268, _attempt): outcome must equal COMPLETE; every named file
    must be listed, exist and hash-equal (either sort direction)."""
    d = _attempt_dir(tmp_path, outcome, files)
    with pytest.raises(r.Invalid):
        r._attempt(d, names)
    d2 = tmp_path / "ok"
    d2.mkdir()
    (d2 / "x.json").write_text("[]", encoding="utf-8")
    (d2 / "manifest.json").write_text(json.dumps({"outcome": "COMPLETE",
                                                  "files": {"x.json": s1_common.sha256_file(d2 / "x.json")}}))
    assert r._attempt(d2, ["x.json"])[1] == {"x.json": []}


def test_cr_opening_seal_checks(tmp_path):
    """Retrospective (Task 9 CR survivors s1_run:286/290/292, _opening_seal): a later opening_close is refused; a
    missing seal names the opening session; a seal whose close is off the session close either way is refused."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    plan = read(out / "plan.json")
    cal = r._calendar(read(out / "audit" / "calendar.json"))
    assert r._opening_seal(out, plan, cal)[1]["close"]
    with pytest.raises(r.Invalid, match="opening_close"):
        r._opening_seal(out, dict(plan, opening_close="2026-10-24"), cal)
    p = out / "seals" / "2026-10-23.json"
    good = p.read_text(encoding="utf-8")
    for shift in (-1, 1):
        s = json.loads(good)
        s["close"] = (s1_common.aware(s["close"]) + timedelta(hours=shift)).isoformat()
        p.write_text(json.dumps(s), encoding="utf-8")
        with pytest.raises(r.Invalid, match="opening seal close"):
            r._opening_seal(out, plan, cal)
    p.unlink()
    with pytest.raises(r.Invalid, match="opening seal 2026-10-23 missing"):
        r._opening_seal(out, plan, cal)


def test_cr_carry_in_holdings_and_oldest_open_lot_dates():
    """Retrospective (Task 9 CR survivors s1_run:302-311, _carry_in): held = the exact open economic quantity; held
    since = the date of the oldest OPEN lot (not the symbol's first row, not a closed lot's date)."""
    rows = [_row(1, "AA", "BUY", 10.0, "2026-10-01T15:00:00+00:00"), _row(2, "AA", "SELL", 10.0, "2026-10-02T15:00:00+00:00"),
            _row(3, "AA", "BUY", 5.0, "2026-10-05T15:00:00+00:00"), _row(4, "BB", "BUY", 0.5, "2026-10-02T15:00:00+00:00"),
            _row(5, "BB", "SELL", 0.5, "2026-10-03T15:00:00+00:00"), _row(6, "BB", "BUY", 0.5, "2026-10-04T15:00:00+00:00")]
    held, since = r._carry_in(rows, START_DT)
    assert held == {"AA": 5.0, "BB": 0.5} and since == {"AA": "2026-10-05", "BB": "2026-10-04"}


def test_cr_coverage_reasons_both_kinds():
    """Retrospective (Task 9 CR survivors s1_run:320/323)."""
    assert r._coverage_reasons({"AA": 1.0, "BB": 1.0}, {"AA": "2026-10-01", "BB": "2026-10-10"}, {"BB"},
                               "2026-10-05") == ["carry-in AA: not covered by the corporate-action request"]
    assert r._coverage_reasons({"BB": 1.0}, {"BB": "2026-10-01"}, {"BB"}, "2026-10-05") == \
        ["carry-in BB: request starts 2026-10-05, after its oldest open lot (2026-10-01)"]


def test_cr_attest_start_statement_receipt_and_clock(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivors s1_run:342/352/356): the statement must equal START_STATEMENT by value
    (shorter/longer refused, an equal copy accepted); an opening seal receipt hash sorting below the receipt's is
    still a mismatch; any time after planned START is refused."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    (out / "attest_start.json").unlink()
    at(monkeypatch, START_DT - timedelta(days=1))
    for bad in ("", "~" * 5):
        with pytest.raises(SystemExit, match="statement"):
            r.attest_start(tmp_path, bad, S1_RECEIPT)
    at(monkeypatch, START_DT + timedelta(hours=1))
    with pytest.raises(SystemExit, match="planned START has passed"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    at(monkeypatch, START_DT - timedelta(days=1))
    p = out / "seals" / "2026-10-23.json"
    good = p.read_text(encoding="utf-8")
    p.write_text(json.dumps(dict(json.loads(good), receipt_sha256="0" * 64)), encoding="utf-8")
    with pytest.raises(SystemExit, match="does not match the opening seal"):
        r.attest_start(tmp_path, r.START_STATEMENT, S1_RECEIPT)
    p.write_text(good, encoding="utf-8")
    assert r.attest_start(tmp_path, _fresh(r.START_STATEMENT), S1_RECEIPT)["trial_id"] == "S1"


def test_cr_start_attestation_problem_whichever_way_a_hash_differs(tmp_path):
    """Retrospective (Task 9 CR survivor s1_run:382)."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    plan, seal_p = read(out / "plan.json"), out / "seals" / "2026-10-23.json"
    att = read(out / "attest_start.json")
    assert r._start_attestation_problems(out, att, plan, seal_p, S1_RECEIPT) == []
    for v in ("0" * 64, "f" * 64):
        assert r._start_attestation_problems(out, dict(att, plan_sha256=v), plan, seal_p, S1_RECEIPT) == \
            ["START attestation plan_sha256 does not match"]


def test_cr_prereg_refusal_paths(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivors s1_run:405/412/420): an incomplete audit and an unreadable opening ledger
    are refusals (SystemExit), and a second BLOCKED attempt is refused again (the record is written once)."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    at(monkeypatch, START_DT - timedelta(hours=2))
    mp = out / "audit" / "manifest.json"
    good = mp.read_text(encoding="utf-8")
    mp.write_text(json.dumps(dict(json.loads(good), outcome="ABORTED")), encoding="utf-8")
    with pytest.raises(SystemExit, match="prereg refused: audit not COMPLETE"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    mp.write_text(good, encoding="utf-8")

    def unreadable(*a, **kw):
        raise s1_books.BookError("corrupt row")
    monkeypatch.setattr(r, "_carry_in", unreadable)
    with pytest.raises(SystemExit, match="opening ledger unreadable"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert not (out / "prereg.json").exists()


def test_cr_second_blocked_prereg_is_refused_again(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivor s1_run:420)."""
    s1_state(tmp_path, START, audit_actions=[split("CI", "2026-10-05")])
    at(monkeypatch, START_DT - timedelta(hours=2))
    for _ in range(2):
        with pytest.raises(SystemExit, match="BLOCKED"):
            r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)


def test_cr_attest_stop_statement_and_bad_seal(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivors s1_run:441/454): the stop statement must equal STOP_STATEMENT (the
    refusal names the statement); two seals for one close are a refusal, not a crash."""
    for bad in ("", "~" * 5):
        with pytest.raises(SystemExit, match="statement"):
            r.attest_stop(tmp_path, bad)
    s1_state(tmp_path, START)
    at(monkeypatch, START_DT - timedelta(hours=2))
    r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    seals = tmp_path / "s1_out" / "seals"
    (seals / "zz.json").write_bytes((seals / "2026-10-23.json").read_bytes())
    at(monkeypatch, START_DT + timedelta(days=3))
    with pytest.raises(SystemExit, match="bad seal record"):
        r.attest_stop(tmp_path, r.STOP_STATEMENT)


def test_cr_no_valid_seal_end_when_the_deadline_is_not_a_session(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivor s1_run:527): START 2026-11-02 -> deadline 2027-05-02 (a Sunday); the
    NO-VALID-SEAL end is still the last eligible session's window end, so an ACK before it is refused."""
    start = "2026-11-02T14:30:00+00:00"
    st_ = s1_state(tmp_path, start, score_ready=True, lots=[], seal_days=[])
    assert s1_common.sim().ny_date(s1_common.aware(start)) and str(r.z.deadline(s1_common.aware(start))) == "2027-05-02"
    s1_mailbox(tmp_path, "before-end", r.score_token(tmp_path), st_["now"] - timedelta(days=5))
    at(monkeypatch, st_["now"])
    with pytest.raises(SystemExit, match="SCORE-ACK"):
        r.score(tmp_path, "before-end")


def test_cr_malformed_seal_without_final_manifest_is_still_scored_invalid(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivor s1_run:530): when the trial end cannot be placed, no final manifest is
    demanded; the attempt records ABORTED-INVALID."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    shutil.rmtree(out / "final")
    p = out / "seals" / "2026-10-26.json"
    seal = read(p)
    del seal["close"]
    p.write_text(json.dumps(seal), encoding="utf-8")
    s1_mailbox(tmp_path, "ack-nf", r.score_token(tmp_path), st_["now"] - timedelta(hours=1))
    at(monkeypatch, st_["now"])
    try:
        r.score(tmp_path, "ack-nf")
    except SystemExit:
        pass
    assert read(out / "score" / "s1.json")["verdict"] == "ABORTED-INVALID"


def test_cr_runner_ok_attempts_counts_only_a_literal_true(tmp_path):
    """Retrospective (Task 9 CR survivors s1_run:555/557)."""
    metas = {"attempt-01": '{"ok": 1}', "attempt-02": '{"ok": 2}', "attempt-03": None, "attempt-04": "{oops",
             "attempt-05": "[]", "attempt-06": '{"ok": true}', "attempt-07": '{"ok": 0}'}
    for name, text in metas.items():
        (tmp_path / name).mkdir()
        if text is not None:
            (tmp_path / name / "meta.json").write_text(text, encoding="utf-8")
    assert r._ok_attempts(tmp_path) == ["attempt-06"]


def _fs(tmp_path):
    """A clean scored-ready state; returns (out, seals, report path, its text)."""
    s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    rp = out / "final_snapshot" / "report.json"
    return out, r._seals(out), rp, rp.read_text(encoding="utf-8")


def test_cr_final_snapshot_problems_every_defect(tmp_path):
    """Retrospective (Task 9 CR survivors s1_run:573-591, _final_snapshot_problems)."""
    out, seals, rp, good = _fs(tmp_path)
    rep = json.loads(good)
    assert r._final_snapshot_problems(out, seals) == []

    def probs(**kw):
        rp.write_text(json.dumps(dict(rep, **kw)), encoding="utf-8")
        return r._final_snapshot_problems(out, seals)
    for ok, fc in ((False, True), (True, False), (1, True), (True, 1)):
        assert probs(capture_ok=ok, fence_checked=fc) == ["final snapshot capture failed: None"], (ok, fc)
    assert probs(fence_violations=["v1"]) == ["final snapshot: v1"]
    d = out / "final_snapshot"
    (d / "attempt-01").rename(d / "kept-01")                       # no ok attempt besides the (bogus) reported one
    assert probs(fence_violations=["v1"], attempt="bogus") == \
        ["final snapshot: v1", "final snapshot: report names no valid attempt ('bogus')"]
    (d / "kept-01").rename(d / "attempt-01")
    assert probs(projection_sha256="f" * 64) == ["final snapshot: projection differs from its recorded hash"]
    shutil.copytree(d / "attempt-01", d / "attempt-02")
    assert probs(attempt="attempt-02") == ["final snapshot: successful attempt(s) other than the reported "
                                           "'attempt-02': attempt-01"]
    shutil.rmtree(d / "attempt-02")
    rp.unlink()
    assert "attempt-01" in r._final_snapshot_problems(out, seals)[0]
    rp.write_text(good, encoding="utf-8")
    for edit, kind in ((lambda s: s.pop("fence"), "KeyError"), (lambda s: s.update(fence={"x": "h"}), "ValueError"),
                       (lambda s: s.update(max_id="a"), "TypeError")):
        bad = [(p, json.loads(json.dumps(s))) for p, s in seals]
        edit(bad[-1][1])
        assert r._final_snapshot_problems(out, bad)[0].startswith(f"final snapshot: bad seal record: {kind}")


def test_cr_seal_chain_problems_every_defect(tmp_path):
    """Retrospective (Task 9 CR survivors s1_run:603-615, _seal_chain_problems)."""
    out, seals, _, _ = _fs(tmp_path)
    pr = read(out / "prereg.json")
    rsha, tc = r._receipt_sha(pr["receipt"]), pr["toolchain_sha256"]           # Task 11 (I-1) interface: tc
    assert r._seal_chain_problems(out, seals, rsha, tc) == []

    def with_last(edit):
        cp = [(p, json.loads(json.dumps(s))) for p, s in seals]
        edit(cp[-1][1])
        return r._seal_chain_problems(out, cp, rsha, tc)
    p_last = seals[-1][0].stem
    for shift in (-1, 1):
        assert any("is not that session" in x for x in with_last(
            lambda s: s.update(close=(s1_common.aware(s["close"]) + timedelta(days=shift)).isoformat())))
    assert f"seal {p_last}: fence does not match its rows" in with_last(lambda s: s["fence"].update({"1": "x"}))
    for kw in ({"receipt_match": False}, {"receipt_match": 1}, {"receipt_sha256": "0" * 64}):
        assert with_last(lambda s: s.update(kw)) == [f"seal {p_last}: semantic receipt differs from prereg"], kw
    assert with_last(lambda s: s["capture"].update(projection_sha256="0" * 64)) == \
        [f"seal {p_last}: rows differ from the preserved capture projection"]

    def price_edit(s):
        s["trades"][-1]["price"] = 1.0
        s["fence"] = {str(i): h for i, h in r.z.fence({"trades": s["trades"]}).items()}
    assert any("rows differ from the preserved capture projection" in x for x in with_last(price_edit))

    def drop_first_row(s):
        s["trades"] = s["trades"][1:]
        s["fence"] = {str(i): h for i, h in r.z.fence({"trades": s["trades"]}).items()}
    assert any("sealed row 1 deleted" in x for x in with_last(drop_first_row))


def test_cr_bridge_problems_branches(tmp_path):
    """Retrospective (Task 9 CR survivors s1_run:631-638, _bridge_problems)."""
    out, seals, _, _ = _fs(tmp_path)
    pr = read(out / "prereg.json")
    start, cal = s1_common.aware(pr["start"]), pr["calendar"]
    ss = [s for _, s in seals]
    post = r.z.post_start_seals(ss, start)
    assert len(post) >= 2
    rep = {}
    asof = post[-1]["trades"]
    assert r._bridge_problems(rep, ss, asof, start, cal) == []
    assert rep["bridge_provenance"]["first_post_start_seal"] == post[0]["close"]
    changed = [dict(t, shares=t["shares"] + 1) if c_ == 0 else t for c_, t in enumerate(asof)]
    assert any("bridge (pre-START rows) changed" in x for x in r._bridge_problems({}, ss, changed, start, cal))
    cp = json.loads(json.dumps(ss))
    last = [s for s in cp if s["close"] == post[-1]["close"]][0]
    last["trades"] = [dict(t, shares=t["shares"] + 1) if c_ == 0 else t for c_, t in enumerate(last["trades"])]
    assert r._bridge_problems({}, cp, None, start, cal) == \
        [f"post-START seal {post[-1]['close']}: bridge record does not match its rows"]
    assert r._bridge_problems({}, ss, asof, start, [d for d in cal if d["date"] >= "2026-10-26"])[0].startswith(
        "bridge check failed: ValueError")
    for edit, kind in ((lambda s: s.pop("trades"), "KeyError"), (lambda s: s.update(trades=None), "TypeError")):
        cp = json.loads(json.dumps(ss))
        edit([s for s in cp if s["close"] == post[0]["close"]][0])
        assert r._bridge_problems({}, cp, asof, start, cal)[0].startswith(f"bridge check failed: {kind}")


def test_cr_stop_attestation_every_check(tmp_path):
    """Retrospective (Task 9 CR survivors s1_run:646-668, _stop_attestation): absent -> present False; each binding
    differing in either direction, a missing stop, and the recorded-time boundaries are problems."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    pr, stop = read(out / "prereg.json"), st_["stop"]
    stop_p = out / "seals" / f"{s1_common.aware(stop['stop_close']).astimezone(s1_common.NY).date()}.json"
    ap = out / "attest_stop.json"
    good = read(ap)

    def check(stop_=stop, reserved=None, **kw):
        ap.write_text(json.dumps(dict(good, **kw)), encoding="utf-8")
        return r._stop_attestation(out, pr, stop_, stop_p, reserved)
    assert check() == {"ok": True, "present": True, "problems": []}
    cases = [({"statement": ""}, "statement differs"), ({"statement": "~"}, "statement differs"),
             ({"attest_start_sha256": "0" * 64}, "START attestation hash differs"),
             ({"attest_start_sha256": "f" * 64}, "START attestation hash differs"),
             ({"start": "2026-10-26T13:29:00+00:00"}, "START differs"),
             ({"start": "2026-10-26T13:31:00+00:00"}, "START differs"),
             ({"sealed_final_ledger_sha256": "0" * 64}, "sealed final ledger hash differs"),
             ({"stop_close": (s1_common.aware(stop["stop_close"]) - timedelta(days=1)).isoformat()}, "stop close differs"),
             ({"stop_close": (s1_common.aware(stop["stop_close"]) + timedelta(days=1)).isoformat()}, "stop close differs"),
             ({"recorded_utc": stop["stop_close"]}, "recorded before the stop"),
             ({"recorded_utc": (s1_common.aware(stop["stop_close"]) - timedelta(hours=1)).isoformat()},
              "recorded before the stop")]
    for kw, want in cases:
        assert want in check(**kw)["problems"], kw
    assert "stop close differs" in check(stop_=None)["problems"]
    assert "stop close differs" in check(stop_={"stop_close": None})["problems"]
    t = s1_common.aware(good["recorded_utc"])
    for reserved in (t, t - timedelta(hours=1)):
        assert "recorded after the final acquisition began" in check(reserved=reserved)["problems"]
    ap.unlink()
    assert r._stop_attestation(out, pr, stop, stop_p, None)["present"] is False


@pytest.mark.parametrize("attest,lots_kw,note", [(False, {}, True), (True, {}, False), (False, {"sell_px": 120.0}, False)])
def test_cr_unverified_numeric_pass_note_only_on_a_pass(tmp_path, monkeypatch, attest, lots_kw, note):
    """Retrospective (Task 9 CR survivors s1_run:697): the "flagged exploratory" note appears exactly for a SHADOW
    PASS without verified provenance."""
    lots = None
    if lots_kw:
        lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, lots_kw["sell_px"])}
                for i in range(100)]
    _, rep, _ = scored(tmp_path, monkeypatch, stop_attest=attest, lots=lots)
    assert ("note" in rep) is note, rep["verdict"]


def test_cr_runner_hash_differing_upward_is_invalid(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivor s1_run:704)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "runner_sha", lambda: "f" * 64)
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(hours=1))
    at(monkeypatch, st_["now"])
    assert "runner changed since prereg" in r.score(tmp_path, "score-ack-2")["reasons"]


@pytest.mark.parametrize("field,value", [(f, v) for f in ("plan_sha256", "audit_manifest_sha256", "attest_start_sha256")
                                         for v in ("0" * 64, "f" * 64)])
def test_cr_each_prereg_binding_alone_is_checked(tmp_path, monkeypatch, field, value):
    """Retrospective (Task 9 CR survivors s1_run:709-711): any ONE changed binding, in either sort direction."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "prereg.json"
    p.write_text(json.dumps(dict(read(p), **{field: value})), encoding="utf-8")
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert "prereg bindings (plan / audit manifest / START attestation) changed" in rep["reasons"]


@pytest.mark.parametrize("edit", [
    lambda pr: pr.update(start="2026-10-26T13:29:00+00:00"), lambda pr: pr.update(start="2026-10-26T13:31:00+00:00"),
    lambda pr: pr.update(calendar=pr["calendar"][:-1]),
    lambda pr: pr.update(calendar=pr["calendar"] + [{"date": "2099-01-02", "open": "09:30", "close": "16:00"}]),
])
def test_cr_prereg_start_or_calendar_alone_is_checked(tmp_path, monkeypatch, edit):
    """Retrospective (Task 9 CR survivors s1_run:713): START or calendar differing alone, either direction."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "prereg.json"
    pr = read(p)
    edit(pr)
    p.write_text(json.dumps(pr), encoding="utf-8")
    at(monkeypatch, st_["now"])
    try:
        rep = r.score(tmp_path, "score-ack")
    except SystemExit:
        rep = read(tmp_path / "s1_out" / "score" / "s1.json")
    assert "prereg START or calendar differs from the plan/audit" in rep["reasons"], rep["reasons"]


def test_cr_incomplete_audit_is_a_recorded_reason_not_a_score_error(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivor s1_run:717 Invalid): an incomplete audit is recorded as its own reason
    inside the ABORTED-INVALID score, not as a generic score error."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    mp = out / "audit" / "manifest.json"
    mp.write_text(json.dumps(dict(read(mp), outcome="ABORTED")), encoding="utf-8")
    at(monkeypatch, st_["now"])
    try:
        rep = r.score(tmp_path, "score-ack")
    except SystemExit:
        rep = read(out / "score" / "s1.json")
    assert any(x.startswith("Invalid: audit attempt outcome is 'ABORTED'") for x in rep["reasons"]), rep["reasons"]
    assert not any(x.startswith("score error") for x in rep["reasons"])


def test_cr_plan_key_error_is_a_recorded_reason(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivor s1_run:717 KeyError)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    pp = tmp_path / "s1_out" / "plan.json"
    plan = read(pp)
    del plan["planned_start"]
    pp.write_text(json.dumps(plan), encoding="utf-8")
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert "KeyError: 'planned_start'" in rep["reasons"], rep["reasons"]


def test_cr_duplicate_seal_is_a_bad_seal_record_reason(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivors s1_run:725/730)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    (out / "seals" / "zz.json").write_bytes((out / "seals" / "2026-10-26.json").read_bytes())
    at(monkeypatch, st_["now"])
    try:
        rep = r.score(tmp_path, "score-ack")
    except SystemExit:
        rep = read(out / "score" / "s1.json")
    assert any(x.startswith("bad seal record: ValueError") for x in rep["reasons"]), rep["reasons"]


@pytest.mark.parametrize("what", ["prereg0", "preregf", "plan-1", "plan+1", "outcome", "noplan"])
def test_cr_final_acquisition_binding_checks(tmp_path, monkeypatch, what):
    """Retrospective (Task 9 CR survivors s1_run:743/745/747): the final manifest must bind this prereg (either
    sort direction), the final plan's stop must equal the stop (either side), and an incomplete attempt or a
    missing final plan is "final acquisition unusable"."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    mp, fp = out / "final" / "manifest.json", out / "final_plan.json"
    want = {"prereg0": "final acquisition is not bound to this prereg", "preregf": "final acquisition is not bound",
            "plan-1": "final plan stop", "plan+1": "final plan stop", "outcome": "final acquisition unusable",
            "noplan": "final acquisition unusable"}[what]
    if what.startswith("prereg"):
        mp.write_text(json.dumps(dict(read(mp), prereg_sha256=("0" if what == "prereg0" else "f") * 64)))
    elif what.startswith("plan"):
        fplan = read(fp)
        d = timedelta(days=-1 if what == "plan-1" else 1)
        fp.write_text(json.dumps(dict(fplan, stop_close=(s1_common.aware(fplan["stop_close"]) + d).isoformat())))
    elif what == "outcome":
        mp.write_text(json.dumps(dict(read(mp), outcome="ABORTED")))
    else:
        fp.unlink()
    s1_mailbox(tmp_path, "ack-f", r.score_token(tmp_path), st_["now"] - timedelta(hours=1))
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, "ack-f")
    assert any(want in x for x in rep["reasons"]), rep["reasons"]


def test_cr_ledger_errors_name_which_ledger(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivors s1_run:754/765): a BookError reading the opening / the final ledger is
    recorded as "opening ledger unreadable" / "final ledger unreadable"."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    real, calls = r._carry_in, []

    def flaky(rows, start):
        calls.append(1)
        if len(calls) == 2:
            raise s1_books.BookError("final corrupt")
        return real(rows, start)
    monkeypatch.setattr(r, "_carry_in", flaky)
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert "final ledger unreadable: final corrupt" in rep["reasons"], rep["reasons"]


def test_cr_opening_ledger_error_is_named(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivor s1_run:754)."""
    st_ = s1_state(tmp_path, START, score_ready=True)

    def bad(rows, start):
        raise s1_books.BookError("opening corrupt")
    monkeypatch.setattr(r, "_carry_in", bad)
    at(monkeypatch, st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert "opening ledger unreadable: opening corrupt" in rep["reasons"], rep["reasons"]


def test_cr_scored_report_counts_concentration_and_ages(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivors s1_run:760/789/804/828-841): a BUY stored exactly at the stop close is in
    the frozen ledger and the cohort; a carry-in row stored exactly at the opening close is not a post-opening
    bridge row; a cohort lot of a carry-in symbol (in both CA lists) is covered; sessions_to_stop is 0 for an
    endpoint-day entry and 1 otherwise; lots_per_symbol and top_symbol_share are exact."""
    lots = _default_lots() + [{"symbol": "CI", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)},
                              {"symbol": "EP", "qty": 10, "px": 100.0, "buy_day": 1, "sell": None}]
    st_, rep, _ = scored(tmp_path, monkeypatch, lots=lots,
                         carry_in=(("CI", 10, 50.0, "2026-10-01T15:00:00+00:00"),
                                   ("OC", 5, 20.0, "2026-10-23T20:00:00+00:00")),
                         bridge=(("ZZ", "BUY", 1, 10.0, "2026-10-27T20:00:00+00:00"),))
    assert st_["stop"]["stop_close"] == "2026-10-27T20:00:00+00:00"
    assert rep["n"] == 103 and rep["k"] == 0, (rep["n"], rep.get("excluded"))
    assert rep["carry_in"]["bridge_rows"] == []
    ages = {l["symbol"]: l["sessions_to_stop"] for l in rep["lots"]}
    assert ages["EP"] == 0 and ages["ZZ"] == 0 and ages["CI"] == 1 and ages["S0"] == 1
    assert rep["concentration"]["lots_per_symbol"] == {"S0": 20, "S1": 20, "S2": 20, "S3": 20, "S4": 20, "CI": 1,
                                                       "EP": 1, "ZZ": 1}
    assert rep["concentration"]["top_symbol_share"] == pytest.approx(20 / 103)


def test_cr_empty_cohort_reports_zero_excluded_notional_share(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivor s1_run:814)."""
    _, rep, _ = scored(tmp_path, monkeypatch, lots=[], seal_days=[0])
    assert rep["n"] == 0 and rep["excluded_notional_share"] == 0.0 and rep["verdict"] == "INSUFFICIENT"


def test_cr_carry_in_open_across_uses_only_that_symbols_pre_start_lots(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivors s1_run:793, open_across): carry-in BB is fully sold on the START session,
    then BB is split; other carry-ins (AA, CC) stay open and BB cohort lots (one bought exactly at START) are open
    across the split -> no carry-in INCONCLUSIVE (the BB lots are per-lot exclusions)."""
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (3, 80.0)} for i in range(100)]
    lots.append({"symbol": "BB", "qty": 5, "px": 100.0, "buy_day": 1, "sell": None})
    _, rep, _ = scored(tmp_path, monkeypatch, lots=lots,
                       carry_in=(("AA", 10, 50.0, "2026-10-01T15:00:00+00:00"),
                                 ("BB", 10, 50.0, "2026-10-01T15:00:00+00:00"),
                                 ("CC", 10, 50.0, "2026-10-01T15:00:00+00:00")),
                       bridge=(("BB", "BUY", 1, 100.0, START), ("BB", "SELL", 10, 55.0, "2026-10-26T16:00:00+00:00")),
                       final_actions=[split("BB", "2026-10-28", i="bb-split")])
    assert rep["verdict"] != "INCONCLUSIVE" and not any("carry-in" in x for x in rep["reasons"]), rep["reasons"]
    assert len(rep["excluded"]) == 2


def test_cr_prereg_refuses_when_the_opening_seal_is_missing(tmp_path, monkeypatch):
    """Retrospective (Task 9 CR survivor s1_run:405): an Invalid opening seal is a refusal (SystemExit), not a
    crash."""
    s1_state(tmp_path, START)
    (tmp_path / "s1_out" / "seals" / "2026-10-23.json").unlink()
    at(monkeypatch, START_DT - timedelta(hours=2))
    with pytest.raises(SystemExit, match="prereg refused: opening seal 2026-10-23 missing"):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)


def test_cr_stop_attestation_ledger_hash_above_the_real_one_differs(tmp_path):
    """Retrospective (Task 9 CR survivor s1_run:658): a recorded sealed-ledger hash sorting ABOVE the real one is a
    mismatch too."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    stop = st_["stop"]
    stop_p = out / "seals" / f"{s1_common.aware(stop['stop_close']).astimezone(s1_common.NY).date()}.json"
    ap = out / "attest_stop.json"
    ap.write_text(json.dumps(dict(read(ap), sealed_final_ledger_sha256="f" * 64)), encoding="utf-8")
    assert "sealed final ledger hash differs" in r._stop_attestation(out, read(out / "prereg.json"), stop, stop_p,
                                                                     None)["problems"]


# ---------------------------------------------------------------- Task 9 fix round 1 (review I-1, I-2, M-1, M-2, M-5)
def test_fr1_attest_stop_accepts_an_equal_but_distinct_statement(tmp_path, monkeypatch):
    """Retrospective (Task 9 fix round 1, review I-1: CR timeout survivor s1_run:441 NotEq_IsNot): the operator's
    statement is compared by value; an equal str that is a different object (as typed or read from a file) is
    accepted."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    (out / "attest_stop.json").unlink()
    shutil.rmtree(out / "final")
    at(monkeypatch, st_["now"])
    stmt = "".join(list(r.STOP_STATEMENT))
    assert stmt is not r.STOP_STATEMENT
    assert r.attest_stop(tmp_path, stmt)["statement"] == r.STOP_STATEMENT


def test_fr1_gate_constants_compared_by_value(tmp_path):
    """Retrospective (Task 9 fix round 1, review I-1 "same pattern for the attestation gates"): the START
    attestation's statement / trial id and a numeric SHADOW PASS are matched by value, not identity."""
    s1_state(tmp_path, START)
    out = tmp_path / "s1_out"
    plan, seal_p = read(out / "plan.json"), out / "seals" / "2026-10-23.json"
    att = dict(read(out / "attest_start.json"), statement="".join(list(r.START_STATEMENT)),
               trial_id="".join(list(r.TRIAL_ID)))
    assert r._start_attestation_problems(out, att, plan, seal_p, S1_RECEIPT) == []
    assert r.final_verdict("".join(list("SHADOW PASS")), {"ok": True})["nomination"] is True


def test_fr1_score_as_of_rows_exclude_a_row_stored_after_the_stop_close(tmp_path, monkeypatch):
    """Retrospective (Task 9 fix round 1, review I-1: CR timeout survivors s1_run:760; design example 2 at score
    level): a BUY stored 10 minutes after the stop close is in the stop seal's rows but not in the frozen as-of
    ledger: not in the cohort and not in the quantity bridge."""
    st_, rep, _ = scored(tmp_path, monkeypatch, bridge=(("ZZ", "BUY", 1, 10.0, "2026-10-27T20:10:00+00:00"),))
    assert st_["stop"]["stop_close"] == "2026-10-27T20:00:00+00:00"
    seal = read(tmp_path / "s1_out" / "seals" / "2026-10-27.json")
    assert any(t["symbol"] == "ZZ" for t in seal["trades"])
    assert rep["n"] == 100 and "ZZ" not in rep["quantity_bridge"], rep["quantity_bridge"]


def test_fr1_younger_carry_in_lot_open_across_a_trial_split_is_inconclusive(tmp_path, monkeypatch):
    """Retrospective (Task 9 fix round 1, review I-2: CR survivor s1_run:793 Eq_Is, re-triaged): two carry-in lots
    of one symbol (separate BUY rows, read back from the seal JSON as distinct str objects); the older is sold after
    START, the younger is still open across a post-START split -> INCONCLUSIVE."""
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (3, 80.0)} for i in range(100)]
    _, rep, _ = scored(tmp_path, monkeypatch, lots=lots,
                       carry_in=(("AAPL", 10, 100.0, "2026-10-01T15:00:00+00:00"),
                                 ("AAPL", 5, 101.0, "2026-10-05T15:00:00+00:00")),
                       bridge=(("AAPL", "SELL", 10, 102.0, "2026-10-26T16:00:00+00:00"),),
                       final_actions=[split("AAPL", "2026-10-28", i="aapl-split")])
    assert rep["verdict"] == "INCONCLUSIVE" and any("aapl-split" in x for x in rep["reasons"]), rep["reasons"]


def test_fr1_candidate_endpoint_reason_compared_by_value(monkeypatch):
    """Retrospective (Task 9 fix round 1, review M-1: s1_run:205 Eq_Is): an "endpoint" reason that is an equal but
    distinct str still marks the terminal cost."""
    sim = s1_common.sim()
    real = sim.simulate_lot

    def fresh_reason(**kw):
        out = real(**kw)
        return dict(out, reason="".join(list(out["reason"])))
    monkeypatch.setattr(sim, "simulate_lot", fresh_reason)
    out = r.candidate_economics(lot(1, "A", "2026-10-26"), [bar("2026-10-27"), bar("2026-10-28")], "2026-10-28",
                                bp=10)
    assert out["reason"] == "endpoint" and out["terminal_cost"] > 0 and out["exit_cost"] == 0


def test_fr1_running_status_compared_by_value_at_the_score_gate(tmp_path, monkeypatch):
    """Retrospective (Task 9 fix round 1, review M-1: s1_run:522 Eq_Is): a RUNNING status that is an equal but
    distinct str still refuses the score with nothing written."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r.z, "stop_decision", lambda *a, **kw: {"status": "".join(list("RUNNING")),
                                                                "stop_close": None, "missed": []})
    at(monkeypatch, st_["now"])
    with pytest.raises(SystemExit, match="still RUNNING"):
        r.score(tmp_path, "score-ack")
    assert not (tmp_path / "s1_out" / "score").exists()


def test_fr1_ok_disposition_compared_by_value(tmp_path, monkeypatch):
    """Retrospective (Task 9 fix round 1, review M-1: s1_run:816 NotEq_IsNot): an "OK" disposition that is an equal
    but distinct str proceeds to the paired economics."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(r, "disposition", lambda n, k_: "".join(list("OK")))
    at(monkeypatch, st_["now"])
    assert r.score(tmp_path, "score-ack")["verdict"] == "SHADOW PASS"


def test_fr1_unreadable_seal_rows_are_a_bad_seal_record_reason(tmp_path, monkeypatch):
    """Retrospective (Task 9 fix round 1, review M-2: the _score handler at s1_run:725-726): a seal row the books
    cannot read (BookError inside stop_decision) is recorded as "bad seal record: BookError ..." in the attempt."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "seals" / "2026-10-26.json"
    seal = read(p)
    seal["trades"][-1]["action"] = "HOLD"
    p.write_text(json.dumps(seal), encoding="utf-8")
    at(monkeypatch, st_["now"])
    try:
        rep = r.score(tmp_path, "score-ack")
    except SystemExit:
        rep = read(tmp_path / "s1_out" / "score" / "s1.json")
    assert rep["outcome"] == "SCORED" and rep["verdict"] == "ABORTED-INVALID"
    assert any(x.startswith("bad seal record: BookError") for x in rep["reasons"]), rep["reasons"]


def test_fr1_write_once_refuses_with_the_recorded_message(tmp_path):
    """Retrospective (Task 9 fix round 1, review M-5: s1_run:331 _write_once, excluded scope): a second write is the
    "<what> already recorded: refusing" refusal (SystemExit), never a raw FileExistsError; the first is kept."""
    p = tmp_path / "x.json"
    r._write_once(p, {"a": 1}, "thing")
    with pytest.raises(SystemExit, match="thing already recorded: refusing"):
        r._write_once(p, {"a": 2}, "thing")
    assert read(p) == {"a": 1}


def test_fr1_restarts_report_new_starts_and_every_observation_gap(tmp_path):
    """Retrospective (Task 9 fix round 1, review M-5: s1_run:675 _restarts, excluded scope)."""
    d = tmp_path / "captures" / "2026-10-27"
    d.mkdir(parents=True)
    (d / "20261027T204500Z.report.json").write_text(json.dumps(
        {"scheduled": "2026-10-27T20:45:00+00:00", "restart_gaps": ["g1", "g2"]}), encoding="utf-8")
    opening = {"restart_record": {"starts": [{"ts": "a", "pid": 1}]}}
    stop = {"restart_record": {"starts": [{"ts": "a", "pid": 1}, {"ts": "b", "pid": 2}]}}
    assert r._restarts(opening, stop, tmp_path) == {
        "observed_in_crash_log_minimum": [{"ts": "b", "pid": 2}],
        "observation_gaps": [{"scheduled": "2026-10-27T20:45:00+00:00", "gap": "g1"},
                             {"scheduled": "2026-10-27T20:45:00+00:00", "gap": "g2"}]}


def test_fr1_sell_stored_after_the_stop_close_writes_nothing_off_in_the_bridge(tmp_path, monkeypatch):
    """Retrospective (Task 9 fix round 1, review I-1: CR timeout survivor s1_run:760 LtE_IsNot): a SELL stored after
    the stop close (in the stop seal) is outside the frozen as-of ledger, so its operational write-off does not
    reach the quantity bridge; the stop-day ZZ lot keeps its full residual."""
    _, rep, _ = scored(tmp_path, monkeypatch, bridge=(("ZZ", "BUY", 1, 10.0, "2026-10-27T15:00:00+00:00"),
                                                      ("ZZ", "SELL", 0.9995, 10.0, "2026-10-27T20:10:00+00:00")))
    assert rep["quantity_bridge"]["ZZ"] == {"writeoff": 0.0, "economic_residual": 1.0}, rep["quantity_bridge"]


def test_fr1_opening_seal_refuses_an_earlier_opening_close_and_unreadable_stop_time(tmp_path):
    """Retrospective (Task 9 fix round 1, review I-1: CR timeout survivors s1_run:286 NotEq_Lt and s1_run:666
    ExceptionReplacer): an opening_close EARLIER than the session before START is refused; a stop attestation whose
    recorded_utc cannot be read is the problem "recorded_utc unreadable", not a crash."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    plan = read(out / "plan.json")
    cal = r._calendar(read(out / "audit" / "calendar.json"))
    with pytest.raises(r.Invalid, match="opening_close"):
        r._opening_seal(out, dict(plan, opening_close="2026-10-22"), cal)
    stop = st_["stop"]
    stop_p = out / "seals" / f"{s1_common.aware(stop['stop_close']).astimezone(s1_common.NY).date()}.json"
    ap = out / "attest_stop.json"
    ap.write_text(json.dumps(dict(read(ap), recorded_utc="not a time")), encoding="utf-8")
    assert "recorded_utc unreadable" in r._stop_attestation(out, read(out / "prereg.json"), stop, stop_p,
                                                            None)["problems"]
