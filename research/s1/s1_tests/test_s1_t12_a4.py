"""Task 12 (controller-added): Addendum 1 rev 3 section A4 (unit/identity trust vs economic per-lot exclusions;
the pre-registered contaminated-symbol rule 2a/2b/2c with its precedence; replaces the Task-7 C-2 ruling) and the
A7.3 effective-date rule it depends on (no processing/publication date is an effective date). Written BEFORE the
implementation (RED: s1_evidence/t12_A4_red.txt). Synthetic s1_out/ through the real gates (conftest.s1_state)."""
from datetime import datetime, timedelta, timezone

import pytest

import s1_common as c
import s1_run as r
from conftest import s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"                 # sessions: 0 = 10-26, 1 = 10-27, 2 = 10-28, 3 = 10-29, 4 = 10-30
D = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]


def split(sym, day, i="sp", **kw):
    return dict({"type": "forward_splits", "id": i, "symbol": sym, "ex_date": day, "old_rate": 1, "new_rate": 2,
                 "process_date": day}, **kw)


def base_lots(n=100, sell_day=1):
    return [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (sell_day, 80.0)}
            for i in range(n)]


def score(tmp_path, monkeypatch, **kw):
    st_ = s1_state(tmp_path, START, score_ready=True, **kw)
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    return r.score(tmp_path, "score-ack")


def no_valuation(monkeypatch):
    sim = c.sim()
    for name in ("simulate_lot", "lot_economics", "baseline_economics", "compare", "paired_bootstrap"):
        monkeypatch.setattr(sim, name, lambda *a, **kw: pytest.fail(f"valuation helper {name} called"))


A_LOT = {"symbol": "A", "qty": 10, "px": 50.0, "buy_day": 0}


# ====================================================================== A7.3 effective dates
def test_a7_no_processing_or_publication_date_is_an_effective_date():
    """A7.3: only the registered effective field (ex_date / effective_date) dates an action; process_date never
    does; missing or ambiguous (both present and different) or conflicting -> unknown (None)."""
    assert r.effective_date(split("A", "2026-10-27")) == "2026-10-27"
    assert r.effective_date({"type": "forward_splits", "id": "x", "symbol": "A", "process_date": "2026-10-27"}) is None
    assert r.effective_date({"type": "name_changes", "id": "n", "old_symbol": "A", "new_symbol": "B",
                             "process_date": "2026-10-27"}) is None
    assert r.effective_date({"type": "unit_splits", "id": "u", "old_symbol": "A",
                             "effective_date": "2026-10-28", "process_date": "2026-10-27"}) == "2026-10-28"
    assert r.effective_date(split("A", "2026-10-27", effective_date="2026-10-29")) is None          # ambiguous
    assert r.effective_date(split("A", "2026-10-27", effective_conflict=True)) is None              # conflicting
    assert r.effective_date(split("A", "27/10/2026")) is None


def test_a7_an_undated_action_with_only_a_process_date_blocks_every_lot_of_its_symbol():
    """A7.3 + v5 §11: a record dated only by process_date has unknown effective timing: the conservative unknown-
    action rule (every lot of the symbol excluded), never the date comparison."""
    from test_s1_run import SESS, bar, lot
    acts = [{"type": "spin_offs", "id": "so", "source_symbol": "A", "new_symbol": "B", "process_date": "2026-10-20"}]
    bars = {"A": {d: bar(d) for d in SESS}}
    ex = r.exclusions([lot(1, "A", "2026-10-26"), lot(2, "A", "2026-10-29")], acts, [], "2026-10-30", SESS, bars, [])
    assert set(ex) == {1, 2} and all("undated" in " ".join(v) for v in ex.values())


# ====================================================================== A4.2 contamination
def test_a4_2b_a_post_event_sell_makes_the_whole_trial_inconclusive(tmp_path, monkeypatch):
    """A4.2b: a cohort lot of A open across A's split, and ANY SELL of A on/after the effective date and at or before
    the stop close -> whole-trial INCONCLUSIVE ("unit event may affect stop/cohort attribution"), whatever the
    unrepaired FIFO allocation shows; no SHADOW PASS/FAIL from the remaining symbols; no valuation."""
    no_valuation(monkeypatch)
    rep = score(tmp_path, monkeypatch, lots=base_lots() + [dict(A_LOT, sell=(1, 55.0))],
                final_actions=[split("A", D[1])])
    assert rep["verdict"] == "INCONCLUSIVE", rep["reasons"]
    assert any("unit event may affect stop/cohort attribution" in x for x in rep["reasons"]), rep["reasons"]
    assert "levels" not in rep


def test_a4_2b_a_sell_allocated_by_unrepaired_fifo_to_a_newer_lot_is_still_inconclusive(tmp_path, monkeypatch):
    """A4.3 acceptance: lot A1 open across the split; post-event BUY A2; a SELL (allocated by the unrepaired FIFO
    to A1, under the true post-split units it would leave A1 half open) -> 2b INCONCLUSIVE; the post-event BUY
    whose SELL is consumed by the contaminated earlier lot does not rescue it."""
    no_valuation(monkeypatch)
    lots = base_lots(sell_day=3) + [dict(A_LOT), {"symbol": "A", "qty": 10, "px": 52.0, "buy_day": 2,
                                                   "sell": (3, 51.0)}]                 # stop on session 3
    rep = score(tmp_path, monkeypatch, lots=lots, final_actions=[split("A", D[1])])
    assert rep["verdict"] == "INCONCLUSIVE" and any("A" in x and "unit event" in x for x in rep["reasons"]), rep


def test_a4_2b_a_unit_event_changing_the_apparent_100th_sale(tmp_path, monkeypatch):
    """A4.3 acceptance: 99 ordinary sales plus the A lot (open across A's split, sold after it) make the apparent
    100th sale; the stop it creates cannot be trusted -> INCONCLUSIVE."""
    no_valuation(monkeypatch)
    rep = score(tmp_path, monkeypatch, lots=base_lots(99) + [dict(A_LOT, sell=(1, 55.0))],
                final_actions=[split("A", D[1])])
    assert rep["stop"]["status"] == "STOPPED" and rep["verdict"] == "INCONCLUSIVE", rep["reasons"]


def test_a4_2a_a_contaminated_carry_in_without_any_sell_is_whole_trial_inconclusive(tmp_path, monkeypatch):
    """A4.2a/A4.1 precedence: a split during the trial on a carry-in symbol still held (no SELL of it at all) is the
    carry-in rule's INCONCLUSIVE - never downgraded to a symbol exclusion."""
    no_valuation(monkeypatch)
    rep = score(tmp_path, monkeypatch, lots=base_lots(), final_actions=[split("CI", D[1])])
    assert rep["verdict"] == "INCONCLUSIVE" and any("carry-in CI" in x for x in rep["reasons"]), rep["reasons"]
    assert "excluded" not in rep


def test_a4_2c_cohort_only_contamination_without_a_sell_excludes_every_cohort_lot_of_the_symbol(tmp_path,
                                                                                                monkeypatch):
    """A4.2c: cohort-only contamination with no SELL of A from the effective date through the stop: every cohort lot
    of A is excluded in both arms from action metadata only, the original N and the > 10 % cap unchanged, the basis
    recorded in the report."""
    lots = base_lots() + [dict(A_LOT), {"symbol": "A", "qty": 5, "px": 51.0, "buy_day": 1}]
    rep = score(tmp_path, monkeypatch, lots=lots, final_actions=[split("A", D[1])])
    assert rep["n"] == 102 and rep["k"] == 2 and rep["retained"] == 100, (rep["n"], rep["k"], rep.get("reasons"))
    assert len(rep["excluded"]) == 2
    assert all(any("contaminated" in w for w in why) for why in rep["excluded"].values()), rep["excluded"]
    basis = rep["contamination"]
    assert set(basis) == {"A"} and basis["A"]["rule"] == "2c" and basis["A"]["actions"] == ["sp"]
    assert rep["verdict"] in ("SHADOW PASS", "FAIL")


def test_a4_2c_exclusions_count_against_the_unchanged_cap(tmp_path, monkeypatch):
    """A4.2c: the exclusions are not replaced and the fixed > 10 % cap of the ORIGINAL N applies: 12 unsold A lots
    open across A's split among 100 + 12 -> K = 12, 10 * 12 = 120 > 112 -> INCONCLUSIVE (no valuation)."""
    lots = base_lots() + [dict(A_LOT) for _ in range(12)]
    no_valuation(monkeypatch)
    rep = score(tmp_path, monkeypatch, lots=lots, final_actions=[split("A", D[1])])
    assert (rep["n"], rep["k"], rep["verdict"]) == (112, 12, "INCONCLUSIVE"), rep.get("reasons")


def test_a4_a_resolved_pre_entry_event_does_not_contaminate(tmp_path, monkeypatch):
    """A4.2 / A4.3: a split effective on the A lot's entry day (no A lot open across it) is fully resolved: A is not
    contaminated and the lot is scored (not excluded)."""
    rep = score(tmp_path, monkeypatch, lots=base_lots() + [dict(A_LOT, sell=(2, 55.0))],
                final_actions=[split("A", D[0])])
    assert rep["verdict"] in ("SHADOW PASS", "FAIL") and rep["k"] == 0, rep.get("reasons")
    assert rep.get("contamination") == {}


def test_a4_a_closed_and_reopened_symbol_is_not_contaminated_by_an_event_between(tmp_path, monkeypatch):
    """A4.3 acceptance: carry-in A fully sold before START (bridge SELL after the opening seal), a split while no lot
    of A is open, then a cohort lot of A: A is neither carry-in-untrusted nor contaminated."""
    rep = score(tmp_path, monkeypatch, carry_in=(("CI", 10, 50.0, "2026-10-01T15:00:00+00:00"),
                                                 ("A", 10, 40.0, "2026-10-01T15:00:00+00:00")),
                bridge=(("A", "SELL", 10, 41.0, "2026-10-23T21:30:00+00:00"),),
                lots=base_lots() + [dict(A_LOT, sell=(2, 55.0))], final_actions=[split("A", "2026-10-25")])
    assert rep["verdict"] in ("SHADOW PASS", "FAIL"), rep["reasons"]
    assert rep.get("contamination") == {} and rep["k"] == 0


def test_a4_an_event_after_the_carry_in_was_fully_sold_is_not_a_carry_in_or_contamination_trigger(tmp_path,
                                                                                                   monkeypatch):
    """A4.3 acceptance: carry-in CI is fully sold on session 1 (a cohort-era SELL row); a CI split on session 2
    finds no CI lot open across it: neither the carry-in rule nor contamination applies; the trial (stop on
    session 3) is scored."""
    rep = score(tmp_path, monkeypatch, lots=base_lots(sell_day=3),
                bridge=(("CI", "SELL", 10, 50.0, "2026-10-27T18:30:00+00:00"),), final_actions=[split("CI", D[2])])
    assert rep["verdict"] in ("SHADOW PASS", "FAIL"), rep["reasons"]
    assert not any("carry-in CI" in x for x in rep["reasons"]) and rep.get("contamination") == {}


@pytest.mark.parametrize("action", [
    {"type": "forward_splits", "id": "nd", "symbol": "A", "old_rate": 1, "new_rate": 2, "process_date": D[1]},
    split("A", D[1], i="amb", effective_date=D[3]),
])
def test_a4_a_unit_action_with_missing_or_ambiguous_date_follows_the_conservative_rule(tmp_path, monkeypatch, action):
    """A4.2 / A4.3: a unit/identity action on A whose effective date is missing (only a process date) or ambiguous is
    never treated as outside the date comparison: A (with a cohort lot) is contaminated; with an A SELL in the
    window -> 2b INCONCLUSIVE."""
    no_valuation(monkeypatch)
    rep = score(tmp_path, monkeypatch, lots=base_lots() + [dict(A_LOT, sell=(1, 55.0))], final_actions=[action])
    assert rep["verdict"] == "INCONCLUSIVE" and any("unit event" in x for x in rep["reasons"]), rep["reasons"]


def test_a4_missing_action_identity_is_a_conservative_block(tmp_path, monkeypatch):
    """A4.3 acceptance: a record without identity is an incomplete-record problem (E1 classify_ca) that blocks
    every lot of its symbols (excluded, both arms)."""
    rep = score(tmp_path, monkeypatch, lots=base_lots() + [dict(A_LOT, sell=(2, 55.0))],
                final_problems=[{"problem": "incomplete record", "type": "forward_splits", "id": None,
                                 "blocks_symbols": ["A"]}])
    assert rep["k"] == 1 and any("problem" in w for w in next(iter(rep["excluded"].values()))), rep.get("excluded")


def test_a4_a_special_dividend_on_a_carry_in_symbol_is_scored_with_lot_level_exclusion_only(tmp_path, monkeypatch):
    """A4.1 acceptance: a special cash dividend on a held carry-in symbol is not a carry-in or contamination
    trigger (Q5): the trial is scored."""
    rep = score(tmp_path, monkeypatch, lots=base_lots(),
                final_actions=[{"type": "cash_dividends", "id": "dv", "symbol": "CI", "special": True,
                                "ex_date": D[1], "process_date": D[1]}])
    assert rep["verdict"] in ("SHADOW PASS", "FAIL") and rep.get("contamination") == {}, rep["reasons"]


def test_a4_1_prereg_bounds_the_opening_audit_to_actions_effective_before_start(tmp_path, monkeypatch):
    """A4.1: the opening audit's carry-in check has an explicit pre-START effective-date bound: an audit record of a
    split effective AFTER START (pre-announced) does not BLOCK the registration (the final acquisition and the
    held-interval rule decide it later)."""
    from datetime import timedelta as td
    st_ = s1_state(tmp_path, START, audit_actions=[split("CI", D[2])])
    with __import__("conftest")._Clock(st_["start"] - td(days=1)):
        pr = r.do_prereg(tmp_path, "run-ack", __import__("conftest").S1_RECEIPT)
    assert pr["trial_id"] == __import__("json").loads((tmp_path / "s1_out" / "plan.json").read_text("utf-8"))["trial_id"]


def test_a4_the_task7_c2_fifo_untrust_rule_is_replaced():
    """A4.2 replaces ruling C-2: the old symbol-exclusion-only function is gone; the contamination decision is the
    registered contaminated_symbols()."""
    assert not hasattr(r, "fifo_untrusted") and callable(r.contaminated_symbols)
