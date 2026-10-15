import pytest
import s1_books as b

T = "2026-10-1{}T14:3{}:00+00:00"


def tr(i, sym, act, sh, px, d=5, m=0):
    return {"id": i, "symbol": sym, "action": act, "shares": sh, "price": px, "timestamp": T.format(d, m),
            "ts": T.format(d, m), "reasoning_sha256": "0" * 64}


def test_dusty_closure_then_reentry_books_and_bridge():                       # design example 3
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 9.9995, 55, 6), tr(3, "A", "BUY", 10, 52, 7)]
    op = b.operational_replay(t)
    assert op["qty"] == {"A": 10.0} and op["writeoffs"] == [{"id": 2, "symbol": "A", "qty": pytest.approx(0.0005)}]
    assert b.consistency(t, {"A": 10.0})["consistent"]
    lots = {l["id"]: l for l in b.economic_lots(t, b.rows(t)[-1]["ts"])}
    assert float(lots[1]["rem_qty"]) == pytest.approx(0.0005) and float(lots[3]["rem_qty"]) == 10.0
    assert b.sold_events(t)[1]["sell_id"] == 2 and 3 not in b.sold_events(t)
    assert b.bridge(t, b.rows(t)[-1]["ts"])["A"] == {"writeoff": pytest.approx(0.0005),
                                                       "economic_residual": pytest.approx(10.0005)}


def test_two_same_symbol_lots_fifo_count():                                    # example 4
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "BUY", 10, 51, 5, 1), tr(3, "A", "SELL", 10, 55, 6)]
    assert set(b.sold_events(t)) == {1}


def test_tiny_buy_without_sell_never_sold():                                   # example 5
    assert b.sold_events([tr(1, "A", "BUY", 0.0005, 50, 5)]) == {}


@pytest.mark.parametrize("left,sold", [(0.001, False), (0.000999, True)])
def test_threshold_exactly_0_001_vs_below(left, sold):                         # example 6
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 10 - left, 55, 6)]
    assert (1 in b.sold_events(t)) is sold


def test_sold_event_is_absorbing_and_attribution_unchanged():
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 9.9995, 55, 6), tr(3, "A", "BUY", 10, 52, 7),
         tr(4, "A", "SELL", 5, 56, 8)]
    ev = b.sold_events(t)
    assert ev[1]["sell_id"] == 2                       # still the first event after later rows
    lots = {l["id"]: l for l in b.economic_lots(t, b.rows(t)[-1]["ts"])}
    assert float(lots[1]["rem_qty"]) == 0.0            # residual consumed FIFO by SELL 4 (economic rule)


def test_symbol_spelling_mismatch_is_flagged_not_merged():                     # Review Focus 2
    t = [tr(1, "BRK.B", "BUY", 3, 400, 5)]
    r = b.consistency(t, {"brk.b": 3.0})
    assert r["consistent"] is False and {d["symbol"] for d in r["diffs"]} == {"BRK.B", "brk.b"}


def test_operational_oversell_beyond_tolerance_is_an_anomaly():
    """Amended by controller ruling (Task 2 review fix round 1): was the plan's raises-test; the design reports
    inconsistencies instead of crashing."""
    t = [tr(1, "A", "BUY", 1, 50, 5), tr(2, "A", "SELL", 1.01, 55, 6)]
    op = b.operational_replay(t)
    assert [a["id"] for a in op["anomalies"]] == [2]
    r = b.consistency(t, {})
    assert r["consistent"] is False and [a["id"] for a in r["anomalies"]] == [2]
    with pytest.raises(b.BookError):
        b.economic_lots(t, b.rows(t)[-1]["ts"])


def test_orphan_sell_raises_in_economic_books():
    with pytest.raises(b.BookError):
        b.economic_lots([tr(1, "A", "SELL", 0.0000005, 55, 6)], b.rows([tr(1, "A", "SELL", 0.0000005, 55, 6)])[0]["ts"])


from hypothesis import given, settings, strategies as st


@settings(max_examples=200, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(["A", "B"]), st.integers(1, 5000)), min_size=1, max_size=12),
       st.data())
def test_prop_operational_replay_matches_a_hand_model(buys, data):
    """Independent hand model of the app rule: per symbol, subtract, then zero if < 0.001."""
    t, i, held = [], 0, {}
    for sym, q in buys:
        i += 1; t.append(tr(i, sym, "BUY", q / 100, 10, 5)); held[sym] = held.get(sym, 0) + q / 100
        if data.draw(st.booleans()):
            s_q = data.draw(st.integers(1, int(held[sym] * 100))) / 100
            i += 1; t.append(tr(i, sym, "SELL", s_q, 11, 6))
            held[sym] -= s_q
            if held[sym] < 0.001:
                held[sym] = 0.0
    got = b.operational_replay(t)["qty"]
    assert set(got) <= set(held) and all(got.get(k, 0.0) == pytest.approx(v, abs=1e-9) for k, v in held.items())


# ---- Task 2 review fix round 1 (new tests; brief tests above are unchanged) ----
from datetime import datetime, timezone

import s1_common as c

ENDPOINT = datetime(2026, 10, 20, tzinfo=timezone.utc)


def test_oversell_past_position_is_anomaly_not_raise():
    """Retrospective (Task 2 review fix round 1): I-1. Economic book accepts the SELL; operational book reports it."""
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 9.9995, 55, 6), tr(3, "A", "SELL", 0.0005, 55, 7)]
    lots = b.economic_lots(t, b.rows(t)[-1]["ts"])
    assert float(next(l for l in lots if l["id"] == 1)["rem_qty"]) == 0.0
    op = b.operational_replay(t)
    assert len(op["anomalies"]) == 1
    assert op["anomalies"][0]["id"] == 3 and op["anomalies"][0]["symbol"] == "A"
    assert op["anomalies"][0]["qty"] == pytest.approx(-0.0005)
    r = b.consistency(t, {})
    assert r["consistent"] is False and len(r["anomalies"]) == 1
    assert "A" in b.bridge(t, b.rows(t)[-1]["ts"])


def test_operational_anomaly_key_always_present_when_clean():
    """Retrospective (Task 2 review fix round 1): I-1. The anomalies key exists even with no anomalies."""
    t = [tr(1, "A", "BUY", 10, 50, 5)]
    assert b.operational_replay(t)["anomalies"] == []
    assert b.consistency(t, {"A": 10.0})["anomalies"] == []


@pytest.mark.parametrize("bad", [
    tr(1, "A", "BUY", float("nan"), 50, 5),
    tr(1, "A", "BUY", -1, 50, 5),
    tr(1, "A", "BUY", 1, 0, 5),
    tr(1, "A", "HOLD", 1, 50, 5),
], ids=["nan-shares", "negative-shares", "zero-price", "unknown-action"])
def test_invalid_row_raises_in_every_book_function(bad):
    """Retrospective (Task 2 review fix round 1): I-2. Row validation in rows() covers all four entry points."""
    with pytest.raises(b.BookError, match="1"):
        b.operational_replay([bad])
    with pytest.raises(b.BookError, match="1"):
        b.consistency([bad], {})
    with pytest.raises(b.BookError, match="1"):
        b.economic_lots([bad], ENDPOINT)
    with pytest.raises(b.BookError, match="1"):
        b.sold_events([bad])


def test_in_tolerance_oversell_is_not_a_writeoff():
    """Retrospective (Task 2 review fix round 1): M-1. A within-tolerance oversell zeroes the position, no entry."""
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 10.0000005, 55, 6)]
    op = b.operational_replay(t)
    assert op["writeoffs"] == [] and op["anomalies"] == [] and op["qty"] == {}


def test_oversell_at_tolerance_boundary_accepted_by_both_books():
    """Retrospective (Task 2 review fix round 1): I-3. SELL exactly 1e-6 over the position is accepted."""
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 10 + 1e-6, 55, 6)]
    assert b.operational_replay(t)["anomalies"] == []
    assert b.consistency(t, {})["consistent"] is True
    assert b.economic_lots(t, ENDPOINT)
    assert b.sold_events(t)[1]["sell_id"] == 2
    assert b.OP_OVERSELL_TOL == c.sim().QTY_TOL


def test_oversell_past_tolerance_boundary_rejected_by_both_books():
    """Retrospective (Task 2 review fix round 1): I-3. SELL 2e-6 over the position: operational anomaly, economic raise."""
    t = [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "SELL", 10 + 2e-6, 55, 6)]
    assert len(b.operational_replay(t)["anomalies"]) == 1
    assert b.consistency(t, {})["consistent"] is False
    with pytest.raises(b.BookError):
        b.economic_lots(t, ENDPOINT)


@pytest.mark.parametrize("trades", [
    [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "BUY", 10, 51, 5, 1), tr(3, "A", "SELL", 19.9995, 55, 6)],
    [tr(1, "A", "BUY", 10, 50, 5), tr(2, "A", "BUY", 0.0005, 51, 5, 1), tr(3, "A", "SELL", 10.0005, 55, 6)],
], ids=["two-full-lots", "full-plus-dust-lot"])
def test_single_sell_split_across_two_lots_marks_both_sold(trades):
    """Retrospective (Task 2 review fix round 1): I-3 / Risk 1. One SELL allocates to two lots, both end < 0.001."""
    ev = b.sold_events(trades)
    assert ev == {1: {"sold_at": ev[1]["sold_at"], "sell_id": 3}, 2: {"sold_at": ev[2]["sold_at"], "sell_id": 3}}


@pytest.mark.parametrize("trades", [
    [tr(1, "A", "SELL", 0.0000005, 55, 6)],
    [tr(1, "A", "BUY", 1, 50, 5), tr(2, "A", "SELL", 1.01, 55, 6)],
], ids=["orphan-sell", "engine-oversell"])
def test_sold_events_wraps_engine_errors_as_book_error(trades):
    """Retrospective (Task 2 review fix round 1): M-2. sold_events raises BookError like economic_lots."""
    with pytest.raises(b.BookError):
        b.sold_events(trades)
