"""Task 12 (controller-added): Addendum 1 rev 3 section A7 (final acquisition). A7.1 (derived plan, ACQUIRE-ACK
bindings) is covered by test_s1_t12_a3_a8.py / test_s1_t12_a2.py and the Task 11 I-4 tests; A7.3 (effective dates)
by test_s1_t12_a4.py. This file covers A7.2 (global reconciliation by provider action identity) and A7.4 (raw page
re-verification at later stages).
RETROSPECTIVE: reconcile_actions and the score's raw-page re-check were written in the A4 implementation step,
BEFORE these tests (a sequencing slip, disclosed in reports/task-12-report.md); their behavioural evidence is the
targeted mutants in s1_evidence/s1_mutants_t12.txt. All synthetic."""
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

import s1_collect as k
import s1_common as c
import s1_run as r
from conftest import s1_mailbox, s1_state

START = "2026-10-26T13:30:00+00:00"


def split(sym, day, i="sp", **kw):
    return dict({"type": "forward_splits", "id": i, "symbol": sym, "ex_date": day, "old_rate": 1, "new_rate": 2,
                 "process_date": day, "affected_symbols": [sym]}, **kw)


def test_a7_2_identical_records_are_kept_once_and_a_conflict_blocks_the_union_of_symbols():
    """A7.2 (retrospective): one identity, identical in type/date/symbol/ratio -> one record; any difference ->
    a conflict problem blocking the union of the affected symbols, both versions marked effective_conflict."""
    a, same = split("A", "2026-10-27"), split("A", "2026-10-27", request_batch=["A", "B"])
    recs, probs = k.reconcile_actions([a], [same])
    assert len(recs) == 1 and probs == []
    for other in (split("A", "2026-10-28"), split("B", "2026-10-27", affected_symbols=["B"]),
                  split("A", "2026-10-27", new_rate=3), dict(split("A", "2026-10-27"), type="reverse_splits")):
        recs, probs = k.reconcile_actions([dict(a)], [other])
        assert len(recs) == 2 and len(probs) == 1 and all(x.get("effective_conflict") for x in recs), other
        assert set(probs[0]["blocks_symbols"]) >= {"A"} | ({"B"} if other["symbol"] == "B" else set())
        assert r.effective_date(recs[0]) is None and r.effective_date(recs[1]) is None


def test_a7_2_the_identity_is_the_provider_id_alone_not_type_scoped():
    """A7.2 (retrospective): no pinned provider contract scopes ids by type, so a changed type under one id is a
    conflict (conservative), never a second identity."""
    _, probs = k.reconcile_actions([split("A", "2026-10-27")],
                                   [dict(split("A", "2026-10-27"), type="stock_dividends", rate=0.1)])
    assert probs and probs[0]["types"] == ["forward_splits", "stock_dividends"]


def test_a7_2_codex_probe_i_window_and_full_history_records_are_reconciled_at_the_acquisition(tmp_path, monkeypatch):
    """A7.2 / Codex probe i (retrospective): the same id with conflicting ex_dates in the window call and the
    full-history call gives ONE conflict problem in the final acquisition (not two silent records)."""
    from test_s1_collect import final_setup, good_bars
    final_setup(tmp_path, monkeypatch)

    def handler(req):
        p = req.url.params
        if "/bars" in str(req.url):
            return httpx.Response(200, json={"bars": {s: good_bars() for s in p["symbols"].split(",")},
                                             "next_page_token": None})
        day = "2026-10-27" if p["symbols"] == "A" else "2026-10-28"
        item = {"id": "dup-1", "symbol": "B", "cusip": "c", "new_rate": 2.0, "old_rate": 1.0, "process_date": day,
                "ex_date": day}
        return httpx.Response(200, json={"corporate_actions": {"forward_splits": [item]}, "next_page_token": None})
    k.do_final(tmp_path, "f1", httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
               ("K", "S"))
    fin = tmp_path / "s1_out" / "final"
    probs = json.loads((fin / "ca_problems.json").read_text(encoding="utf-8"))
    assert [p for p in probs if p["problem"] == "conflicting records for one provider action identity"], probs


def test_a7_2_audit_and_final_records_are_reconciled_at_the_score(tmp_path, monkeypatch):
    """A7.2 (retrospective): an audit record and a final record of one identity that disagree (the date moved) are
    a conflict at the score: the conflict blocks every lot of the symbol (never two independent records)."""
    lots = [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": (1, 80.0)} for i in range(100)]
    lots.append({"symbol": "A", "qty": 10, "px": 50.0, "buy_day": 0})
    st_ = s1_state(tmp_path, START, score_ready=True, lots=lots,
                   carry_in=(("CI", 10, 50.0, "2026-10-01T15:00:00+00:00"), ("A", 1, 40.0, "2026-10-01T15:00:00+00:00")),
                   audit_actions=[split("A", "2026-09-01", i="x9")], final_actions=[split("A", "2026-10-29", i="x9")])
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    rep = r.score(tmp_path, "score-ack")
    assert rep["ca_conflicts"] and rep["ca_conflicts"][0]["id"] == "x9", rep.get("reasons")
    # A is held at START: the conflicting identity has unknown timing -> the carry-in rule (A4.1) decides
    assert rep["verdict"] == "INCONCLUSIVE" and any("carry-in A" in x for x in rep["reasons"]), rep["reasons"]


def test_a7_4_a_tampered_final_raw_page_is_an_integrity_failure_at_score(tmp_path, monkeypatch):
    """A7.4 (retrospective): every raw page is hashed in its manifest and re-verified at each later stage: a raw page
    changed after the final acquisition makes the score ABORTED-INVALID (derived files unchanged)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    page = out / "final" / "pages" / "bars_page000.json"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_bytes(b'{"bars": {}, "next_page_token": null}')
    mp = out / "final" / "manifest.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["pages"] = {"final/pages/bars_page000.json": c.sha256_file(page)}
    mp.write_text(json.dumps(m), encoding="utf-8")
    page.write_bytes(page.read_bytes() + b" ")                         # tampered after the manifest
    monkeypatch.setattr(c, "now_utc", lambda: st_["now"])
    s1_mailbox(tmp_path, "score-ack-2", r.score_token(tmp_path), st_["now"] - timedelta(minutes=30))
    rep = r.score(tmp_path, "score-ack-2")
    assert rep["verdict"] == "ABORTED-INVALID" and any("raw page" in x for x in rep["reasons"]), rep["reasons"]
