"""Task 11 (controller-added): final-review fix round (reports/final-review.md, brief task-11-brief.md).

Every test here was written BEFORE the fix it covers (RED files s1_evidence/t11_<item>_red.txt), except the m-6
static R-EST guard, which pins a property the code already has (labelled in its docstring). All synthetic: tmp_path
ledgers, mailboxes and git repos, fixed clocks; no live DB, app, port, network or real mailbox."""
import ast
import json
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

import httpx
import pytest
from hypothesis import given, settings, strategies as st

import s1_books as b
import s1_checkpoint as ck
import s1_collect as k
import s1_common as c
import s1_receipt as rc
import s1_run as r
import s1_seal as z
from conftest import S1_PROCESS, S1_RECEIPT, _Clock, s1_mailbox, s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"                        # Mon; opening close Fri 2026-10-23 (EDT)
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
STOP_CLOSE = "2026-10-27T20:00:00+00:00"                   # default s1_state stop (100 lots sold on session 1)
HERE = Path(__file__).resolve().parent.parent
REAL_MAILBOX = Path("C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3")


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def at(monkeypatch, t):
    monkeypatch.setattr(c, "now_utc", lambda: t)


def sha(p):
    return c.sha256_file(p)


def slot(day: str, minutes=45):
    """A registered seal slot of `day` (EDT close 20:00Z) and its actual time 30 s later."""
    sch = datetime.fromisoformat(f"{day}T20:00:00+00:00") + timedelta(minutes=minutes)
    return sch, sch + timedelta(seconds=30)


def checkpoint(root, st_, day, receipt=None, minutes=45):
    sch, act = slot(day, minutes)
    rec = S1_RECEIPT if receipt is None else receipt
    with _Clock(act):
        return ck.run_checkpoint(root, st_["ledger"].path, sch, lambda: rec, lambda: dict(S1_PROCESS),
                                 Path(root) / "crash.log", now=lambda: act)


def score(root, monkeypatch, st_, ack="score-ack"):
    at(monkeypatch, st_["now"])
    return r.score(root, ack)


# ====================================================================== C-1 post-stop checkpoints
@pytest.mark.parametrize("variant", ["control", "buy", "receipt"])
def test_c1_post_stop_checkpoint_never_seals_or_aborts_and_the_score_is_unchanged(tmp_path, monkeypatch, variant):
    """Task 11 (controller-added), C-1: after the stop (STOPPED at 2026-10-27) the scheduler keeps firing. A new MR
    BUY then the 2026-10-30 checkpoint ("buy"), or the same with a changed receipt ("receipt"), takes and records the
    capture as post_stop but never seals and never writes aborted.json; the score is the control verdict."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    if variant != "control":
        st_["ledger"].trade("ZZZ", "BUY", 1, 10.0, "2026-10-30T15:00:00+00:00")
        st_["ledger"].set_portfolio("ZZZ", 1)
        bad = dict(S1_RECEIPT, head="post-stop-commit") if variant == "receipt" else None
        rep = checkpoint(tmp_path, st_, "2026-10-30", receipt=bad)
        assert rep["post_stop"] is True and rep["seal"]["written"] is False, rep
        assert rep["stop"]["status"] == "STOPPED" and rep["stop"]["stop_close"] == STOP_CLOSE, rep["stop"]
        assert rep["receipt_match"] is (variant != "receipt")                 # reported only
        assert not (out / "aborted.json").exists()
        assert not (out / "seals" / "2026-10-30.json").exists()
    rep = score(tmp_path, monkeypatch, st_)
    assert rep["verdict"] == "SHADOW PASS" and rep["reasons"] == [], rep["reasons"]


def test_c1_post_stop_fence_difference_is_reported_only(tmp_path, monkeypatch):
    """Task 11 (controller-added), C-1: a sealed row deleted after the stop is a fence difference the post-stop
    capture reports; it writes no aborted.json (the final snapshot, taken earlier, already vouched for the slices)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    con = sqlite3.connect(st_["ledger"].path)
    con.execute("UPDATE trades SET price = price + 1 WHERE id = (SELECT MAX(id) FROM trades)")
    con.commit()
    con.close()
    rep = checkpoint(tmp_path, st_, "2026-10-30")
    assert rep["post_stop"] is True and rep["fence_violations"], rep
    assert not (out / "aborted.json").exists() and rep["seal"]["written"] is False


def test_c1_checkpoint_after_an_abort_is_post_stop_and_never_seals(tmp_path, monkeypatch):
    """Task 11 (controller-added), C-1: once aborted.json exists every later capture is post_stop (no seal)."""
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    out = tmp_path / "s1_out"
    (out / "aborted.json").write_text(json.dumps({"reason": "x", "close": "c", "scheduled": "s", "actual": "a"}),
                                      encoding="utf-8")
    rep = checkpoint(tmp_path, st_, "2026-10-26")
    assert rep["post_stop"] is True and rep["seal"]["written"] is False
    assert rep["stop"]["status"] == "ABORTED-INVALID"


def test_c1_final_snapshot_and_score_check_fences_only_against_seals_up_to_the_stop(tmp_path, monkeypatch):
    """Task 11 (controller-added), C-1: a (legacy) seal of a close after the stop whose rows the ledger no longer
    holds is not a fence the final snapshot or the score checks."""
    from conftest import _write_seal
    st_ = s1_state(tmp_path, START, score_ready=True, final_snapshot=False)
    out = tmp_path / "s1_out"
    ghost = dict(st_["rows"][-1], id=10_000, symbol="GHOST", action="BUY", timestamp="2026-10-29T15:00:00+00:00",
                 ts="2026-10-29T15:00:00+00:00")
    _write_seal(out, "2026-10-29", datetime(2026, 10, 29, 20, tzinfo=UTC), st_["rows"] + [ghost], S1_RECEIPT,
                start=START_DT, opening_close=z.close_of("2026-10-23", st_["calendar"]))
    snap_at = st_["snapshot_at"]
    with _Clock(snap_at):
        rep = ck.run_final_snapshot(tmp_path, st_["ledger"].path, now=lambda: snap_at)
    assert rep["fence_violations"] == [] and "2026-10-29.json" not in {x["file"] for x in rep["seals_checked"]}
    s1_mailbox(tmp_path, "ack-c1", r.score_token(tmp_path), st_["now"] - timedelta(hours=1))
    rep = score(tmp_path, monkeypatch, st_, "ack-c1")
    assert not any("final snapshot" in x for x in rep["reasons"]), rep["reasons"]


# ====================================================================== I-1 toolchain binding
def _independent_toolchain(d: Path) -> str:
    files = sorted(d.glob("s1_*.py")) + [d / "e1_sim.py", d / "e1_fetch.py"]
    pairs = sorted([p.name, c.sha256_bytes(p.read_bytes())] for p in files)
    return c.sha256_bytes(json.dumps(pairs, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def test_i1_toolchain_sha_is_every_s1_module_plus_the_e1_pins(tmp_path, monkeypatch):
    """Task 11 (controller-added), I-1: sha256 over the sorted (name, sha256) of every research/s1 s1_*.py plus
    e1_sim.py and e1_fetch.py. Any one byte of any of them changes it; an unrelated file does not."""
    assert c.toolchain_sha256() == _independent_toolchain(HERE)
    d = tmp_path / "copy"
    d.mkdir()
    for p in list(HERE.glob("s1_*.py")) + [HERE / "e1_sim.py", HERE / "e1_fetch.py"]:
        shutil.copy2(p, d / p.name)
    monkeypatch.setattr(c, "HERE", d)
    base = c.toolchain_sha256()
    assert base == _independent_toolchain(HERE)
    (d / "notes.py").write_text("x = 1\n")
    assert c.toolchain_sha256() == base
    for name in ("s1_seal.py", "s1_books.py", "e1_sim.py"):
        p = d / name
        old = p.read_bytes()
        p.write_bytes(old + b"\n")
        assert c.toolchain_sha256() != base, name
        p.write_bytes(old)
    (d / "s1_extra.py").write_text("x = 1\n")
    assert c.toolchain_sha256() != base


def test_i1_prereg_and_run_ack_bind_the_toolchain(tmp_path):
    """Task 11 (controller-added), I-1: RUN-ACK's token carries toolchain_sha256 and prereg records it; an ACK
    without the toolchain field (the old token) is refused."""
    s1_state(tmp_path, START)
    tok = r.run_token(tmp_path)
    assert f" toolchain_sha256={c.toolchain_sha256()} " in tok
    old = " ".join(x for x in tok.split(" ") if not x.startswith("toolchain_sha256="))
    s1_mailbox(tmp_path, "old-ack", old, START_DT - timedelta(days=1, hours=1))
    with _Clock(START_DT - timedelta(days=1)):
        with pytest.raises(SystemExit):
            r.do_prereg(tmp_path, "old-ack", S1_RECEIPT)
        pr = r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    assert pr["toolchain_sha256"] == c.toolchain_sha256()


def _prereg_state(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


def test_i1_every_seal_records_the_checkpoint_toolchain(tmp_path):
    """Task 11 (controller-added), I-1: the opening seal and every scheduled seal record the toolchain hash of the
    checkpoint that wrote them."""
    st_ = _prereg_state(tmp_path)
    out = tmp_path / "s1_out"
    assert read(out / "seals" / "2026-10-23.json")["toolchain_sha256"] == c.toolchain_sha256()
    rep = checkpoint(tmp_path, st_, "2026-10-26")
    assert rep["seal"]["written"] is True
    assert read(out / "seals" / "2026-10-26.json")["toolchain_sha256"] == c.toolchain_sha256()


def test_i1_checkpoint_with_a_different_toolchain_refuses_to_seal_without_abort(tmp_path, monkeypatch):
    """Task 11 (controller-added), I-1: a checkpoint whose toolchain differs from prereg's records the refusal, writes
    no seal and no aborted.json."""
    st_ = _prereg_state(tmp_path)
    out = tmp_path / "s1_out"
    monkeypatch.setattr(c, "toolchain_sha256", lambda: "f" * 64)
    rep = checkpoint(tmp_path, st_, "2026-10-26")
    assert rep["seal"]["written"] is False and "toolchain" in str(rep.get("refused")), rep
    assert not (out / "seals" / "2026-10-26.json").exists() and not (out / "aborted.json").exists()


def test_i1_score_requires_every_seal_and_itself_to_match_the_prereg_toolchain(tmp_path, monkeypatch):
    """Task 11 (controller-added), I-1: a seal recording another toolchain, or a score run by another toolchain, is
    ABORTED-INVALID ("toolchain")."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    p = tmp_path / "s1_out" / "seals" / "2026-10-26.json"
    s = read(p)
    s["toolchain_sha256"] = "0" * 64
    p.write_text(json.dumps(s), encoding="utf-8")
    rep = score(tmp_path, monkeypatch, st_)
    assert rep["verdict"] == "ABORTED-INVALID" and any("toolchain" in x for x in rep["reasons"]), rep["reasons"]


def test_i1_score_by_a_different_toolchain_is_aborted_invalid(tmp_path, monkeypatch):
    """Task 11 (controller-added), I-1."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    monkeypatch.setattr(c, "toolchain_sha256", lambda: "e" * 64)
    rep = score(tmp_path, monkeypatch, st_)
    assert rep["verdict"] == "ABORTED-INVALID" and any("toolchain" in x for x in rep["reasons"]), rep["reasons"]


# ====================================================================== I-2 / m-3 receipt dirty list, git locks
def _git_repo(tmp_path):
    be = tmp_path / "backend"
    (be / "agents").mkdir(parents=True)
    (be / "agents" / "mean_reversion_agent.py").write_text("X = 1\n")
    (be / "data.json").write_text("{}\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                   check=True)
    return tmp_path


def _receipt(root):
    return rc.semantic_receipt(root, root / ".env", None, roots=["agents/mean_reversion_agent.py"])


def test_i2_untracked_non_py_runtime_files_do_not_change_the_receipt(tmp_path):
    """Task 11 (controller-added), I-2: an untracked backend/trading.db-journal (a SQLite sidecar that exists during
    every app write transaction) is not in the dirty list; an untracked backend/x.py is; a tracked modification of a
    non-.py file still is."""
    root = _git_repo(tmp_path)
    base = _receipt(root)
    (root / "backend" / "trading.db-journal").write_bytes(b"\0" * 16)
    (root / "backend" / "logs").mkdir()
    (root / "backend" / "logs" / "crash.log").write_text("x\n")
    assert _receipt(root) == base
    (root / "backend" / "x.py").write_text("y = 2\n")
    assert "backend/x.py" in _receipt(root)["dirty"]
    (root / "backend" / "x.py").unlink()
    (root / "backend" / "data.json").write_text('{"a": 1}\n')
    assert _receipt(root)["dirty"] == ["backend/data.json"]


def test_m3_every_git_call_uses_no_optional_locks(tmp_path, monkeypatch):
    """Task 11 (controller-added), m-3: every git call in s1_receipt passes --no-optional-locks (read-only
    observation of the live checkout never takes index.lock or refreshes .git/index)."""
    root = _git_repo(tmp_path)
    real, calls = subprocess.run, []

    def spy(args, *a, **kw):
        calls.append(list(args))
        return real(args, *a, **kw)
    monkeypatch.setattr(rc.subprocess, "run", spy)
    _receipt(root)
    git = [x for x in calls if x and x[0] == "git"]
    assert len(git) >= 2 and all(x[1] == "--no-optional-locks" for x in git), git


# ====================================================================== I-3 sold-count performance
def _reference_sold_events(trades) -> dict:
    """Task 11 (controller-added), I-3: the pre-Task-11 s1_books.sold_events, kept HERE ONLY as the reference the
    per-symbol replay must equal (whole-prefix replay at every SELL)."""
    rs, events, prev_fills = b.rows(trades), {}, {}
    limit = c.sim().x(c.SOLD_LT)
    for i, row in enumerate(rs):
        if row["action"] != "SELL":
            continue
        orphans = []
        lots = b._economic(rs[: i + 1], row["ts"], orphans)
        if orphans:
            raise b.BookError(f"orphan SELL(s) with no open lot: {[o['id'] for o in orphans]}")
        for lot in lots:
            n = len(lot["fills"])
            if n > prev_fills.get(lot["id"], 0) and lot["rem_qty"] < limit and lot["id"] not in events:
                events[lot["id"]] = {"sold_at": row["ts"].isoformat(), "sell_id": row["id"]}
            prev_fills[lot["id"]] = n
    return events


_QTY = st.sampled_from([0.0000005, 0.0005, 0.001, 0.0011, 1, 2.5, 2.5000005, 3, 9.9995, 10, 10.0000005,
                        0.999])
_OP = st.tuples(st.sampled_from(["A", "B", "C"]), st.sampled_from(["BUY", "SELL", "SELL"]), _QTY,
                st.integers(0, 3))


def _ledger(ops) -> list:
    t0, out, minute = datetime(2026, 10, 26, 14, tzinfo=UTC), [], 0
    for i, (sym, act, q, dt) in enumerate(ops, start=1):
        minute += dt                                                           # dt == 0: same instant, id order
        out.append({"id": i, "symbol": sym, "action": act, "shares": q, "price": 10.0 + i,
                    "ts": (t0 + timedelta(minutes=minute)).isoformat()})
    return out


def _outcome(fn, trades):
    try:
        return ("ok", fn(trades))
    except b.BookError as e:
        return ("BookError", str(e))


@settings(max_examples=300, deadline=None)
@given(st.lists(_OP, max_size=24))
def test_i3_per_symbol_sold_events_equal_the_whole_prefix_reference(ops):
    """Task 11 (controller-added), I-3 (Hypothesis): identical events, and identical BookError text on oversells and
    orphan SELLs, on generated multi-symbol ledgers with dust, threshold quantities and tied instants."""
    trades = _ledger(ops)
    assert _outcome(b.sold_events, trades) == _outcome(_reference_sold_events, trades)


def test_i3_sold_events_on_2000_rows_completes_in_under_5_seconds():
    """Task 11 (controller-added), I-3: 2000 MR rows over 20 symbols (round trips with partial sells and dust) -
    the review measured 51.7 s for one count at this size with the whole-prefix replay."""
    import random
    rng = random.Random(11)
    t0, trades, held = datetime(2026, 1, 2, 14, tzinfo=UTC), [], {}
    for i in range(1, 2001):
        sym = f"S{rng.randrange(20):02d}"
        q = held.get(sym, 0.0)
        if q > 0 and rng.random() < 0.5:
            act, sh = "SELL", (q if rng.random() < 0.6 else round(q / 2, 4))
        else:
            act, sh = "BUY", float(rng.choice([1, 2.5, 10, 7.25]))
        held[sym] = q + sh if act == "BUY" else q - sh
        trades.append({"id": i, "symbol": sym, "action": act, "shares": sh, "price": 10.0,
                       "ts": (t0 + timedelta(minutes=7 * i)).isoformat()})
    t = time.perf_counter()
    ev = b.sold_events(trades)
    assert time.perf_counter() - t < 5.0 and ev


# ====================================================================== I-4 final acquisition order
BRIDGE_NEW = (("NEWB", "BUY", 5, 20.0, "2026-10-24T00:00:00+00:00"),)           # Fri 20:00 ET, after the opening seal


def test_i4_final_plan_is_derived_from_the_stop_seal(tmp_path):
    """Task 11 (controller-added), I-4: write_final_plan takes no hand-typed stop or symbols: the stop close, cohort
    symbols, carry-in symbols (bridge-introduced included) and history start come from the stop seal/state."""
    s1_state(tmp_path, START, score_ready=True, bridge=BRIDGE_NEW)
    out = tmp_path / "s1_out"
    plan = read(out / "final_plan.json")
    assert plan["stop_close"] == STOP_CLOSE and plan["stop_date"] == "2026-10-27" and plan["stop_status"] == "STOPPED"
    assert plan["ca_symbols_window"] == ["S0", "S1", "S2", "S3", "S4"]
    assert plan["ca_symbols_full_history"] == ["CI", "NEWB"]
    assert plan["bar_symbols"] == ["CI", "NEWB", "S0", "S1", "S2", "S3", "S4"]
    assert plan["full_history_start"] == "2026-10-01"
    assert plan["stop_seal_sha256"] == sha(out / "seals" / "2026-10-27.json")
    seal = read(out / "seals" / "2026-10-27.json")                               # equals the score's carry-in book
    held, _ = r._carry_in(z.split_bridge(seal["trades"], START_DT)[0], START_DT)
    assert sorted(held) == plan["ca_symbols_full_history"]


def test_i4_final_plan_refused_while_running_aborted_or_unattested(tmp_path):
    """Task 11 (controller-added), I-4: no final plan while RUNNING, once aborted.json exists (nothing to acquire),
    or before the stop attestation."""
    s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    with _Clock(START_DT + timedelta(days=2)):
        with pytest.raises(SystemExit, match="RUNNING"):
            k.write_final_plan(tmp_path)
    assert not (tmp_path / "s1_out" / "final_plan.json").exists()


def test_i4_final_plan_refused_after_an_abort(tmp_path):
    """Task 11 (controller-added), I-4."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    (out / "final_plan.json").unlink()
    (out / "aborted.json").write_text(json.dumps({"reason": "x"}), encoding="utf-8")
    with _Clock(st_["now"]):
        with pytest.raises(SystemExit, match="ABORTED"):
            k.write_final_plan(tmp_path)
    assert not (out / "final_plan.json").exists()


def test_i4_final_plan_refused_without_the_stop_attestation(tmp_path):
    """Task 11 (controller-added), I-4."""
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False)
    out = tmp_path / "s1_out"
    (out / "final_plan.json").unlink()
    with _Clock(st_["now"]):
        with pytest.raises(SystemExit, match="stop attestation"):
            k.write_final_plan(tmp_path)
    assert not (out / "final_plan.json").exists()


def _bars_client(calls):
    def handler(req):
        calls.append(req)
        if "/bars" in str(req.url):
            syms = req.url.params["symbols"].split(",")
            page = {s: [{"t": f"{d}T04:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10, "v": 1}
                        for d in ("2026-10-26", "2026-10-27")] for s in syms}
            return httpx.Response(200, json={"bars": page, "next_page_token": None})
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _acquire_ready(tmp_path, **kw):
    st_ = s1_state(tmp_path, START, score_ready=True, **kw)
    shutil.rmtree(tmp_path / "s1_out" / "final")                    # the fixture's hand-made attempt
    return st_


def test_i4_acquire_ack_binds_the_stop_attestation_and_do_final_records_the_plan(tmp_path):
    """Task 11 (controller-added), I-4 + m-1: the ACQUIRE-ACK token binds attest_stop.json's sha256; the COMPLETE
    final manifest records the final plan's and the stop attestation's sha256."""
    st_ = _acquire_ready(tmp_path)
    out = tmp_path / "s1_out"
    tok = k.acquire_token(tmp_path)
    assert f"attest_stop_sha256={sha(out / 'attest_stop.json')}" in tok and "{attest}" in k.ACQUIRE_ACK
    s1_mailbox(tmp_path, "acq", tok, st_["now"] - timedelta(hours=1))
    calls = []
    with _Clock(st_["now"]):
        m = k.do_final(tmp_path, "acq", _bars_client(calls), ("K", "S"))
    assert m["outcome"] == "COMPLETE" and calls
    assert m["final_plan_sha256"] == sha(out / "final_plan.json")
    assert m["attest_stop_sha256"] == sha(out / "attest_stop.json")


@pytest.mark.parametrize("breakage", ["aborted", "hand-typed plan", "ack before attestation"])
def test_i4_do_final_rechecks_the_stop_before_reserving(tmp_path, breakage):
    """Task 11 (controller-added), I-4: do_final re-derives the plan from the stop seal and re-checks the state, the
    abort marker and the attestation order before reserving: on any failure no request and no final/ attempt."""
    st_ = _acquire_ready(tmp_path)
    out = tmp_path / "s1_out"
    created = st_["now"] - timedelta(hours=1)
    if breakage == "hand-typed plan":
        fp = out / "final_plan.json"
        plan = read(fp)
        plan["ca_symbols_full_history"] = []                                       # CI omitted by hand
        fp.write_text(json.dumps(plan, indent=1, sort_keys=True), encoding="utf-8")
    if breakage == "ack before attestation":
        created = c.aware(read(out / "attest_stop.json")["recorded_utc"]) - timedelta(minutes=1)
    s1_mailbox(tmp_path, "acq", k.acquire_token(tmp_path), created)
    if breakage == "aborted":
        (out / "aborted.json").write_text(json.dumps({"reason": "x"}), encoding="utf-8")
    calls = []
    with _Clock(st_["now"]):
        with pytest.raises(SystemExit):
            k.do_final(tmp_path, "acq", _bars_client(calls), ("K", "S"))
    assert calls == [] and not (out / "final").exists()


@pytest.mark.parametrize("mutate,why", [
    (lambda cal: cal + [dict(cal[3])], "duplicate date"),
    (lambda cal: [dict(x, close="09:30") if i == 4 else x for i, x in enumerate(cal)], "open == close"),
    (lambda cal: [dict(x, close="09:00") if i == 4 else x for i, x in enumerate(cal)], "open > close"),
])
def test_i4_t6_calendar_duplicates_or_open_not_before_close_are_structural(mutate, why):
    """Task 11 (controller-added), I-4 fold-in of the T6 deferred calendar items."""
    from conftest import _weekdays
    cal = _weekdays("2026-10-01", "2027-06-30")
    plan = {"planned_start": "2026-11-02T14:30:00+00:00", "created_utc": "2026-10-19T12:00:00+00:00",
            "deadline": "2027-05-02"}
    k._validate_calendar(cal, plan)                                              # control: accepted
    with pytest.raises(k.Structural):
        k._validate_calendar(mutate(cal), plan)


# ====================================================================== I-5 mailbox location
def test_i5_mailbox_constant_is_the_coordination_mailbox():
    """Task 11 (controller-added), I-5: the module constant (read from source: tests redirect it at run time)."""
    tree = ast.parse((HERE / "s1_common.py").read_text(encoding="utf-8"))
    vals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "MAILBOX" for t in n.targets)]
    assert len(vals) == 1 and ast.unparse(vals[0]) == "Path('C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3')"


def test_i5_no_test_can_open_the_real_mailbox():
    """Task 11 (controller-added), I-5: the conftest redirect is active for every test."""
    got = Path(c.MAILBOX).resolve()
    assert got != REAL_MAILBOX.resolve() and REAL_MAILBOX.parent.resolve() not in got.parents, got


def _msg(path, mid, body, created):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT, sender TEXT, recipient TEXT, request_key TEXT, "
                "body TEXT, created REAL, acknowledged REAL)")
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)",
                (mid, "codex", "claude", "experiments-prereg", body, created.timestamp()))
    con.commit()
    con.close()


def test_i5_ack_reads_the_given_mailbox_read_only_never_the_output_root(tmp_path, monkeypatch):
    """Task 11 (controller-added), I-5: _ack opens the explicit mailbox (else MAILBOX) with a mode=ro URI; a message
    left in <root>/mailbox.sqlite3 (the old location) is not read; a missing mailbox is never created."""
    at(monkeypatch, datetime(2026, 10, 21, tzinfo=UTC))
    mb = tmp_path / "coord" / "mailbox.sqlite3"
    mb.parent.mkdir()
    _msg(mb, "m1", "TOKEN", datetime(2026, 10, 20, tzinfo=UTC))
    seen, real = [], sqlite3.connect

    def spy(dsn, *a, **kw):
        seen.append((dsn, kw.get("uri")))
        return real(dsn, *a, **kw)
    monkeypatch.setattr(k.sqlite3, "connect", spy)
    assert k._ack("m1", "TOKEN", mailbox=mb)["ack_id"] == "m1"
    assert seen[-1] == (f"file:{mb.as_posix()}?mode=ro", True)
    monkeypatch.setattr(c, "MAILBOX", mb)
    assert k._ack("m1", "TOKEN")["ack_id"] == "m1"                              # the default is MAILBOX
    root = tmp_path / "root"
    root.mkdir()
    _msg(root / "mailbox.sqlite3", "m2", "TOKEN", datetime(2026, 10, 20, tzinfo=UTC))
    with pytest.raises(SystemExit):
        k._ack("m2", "TOKEN")
    missing = tmp_path / "nowhere" / "mailbox.sqlite3"
    with pytest.raises(sqlite3.Error):
        k._ack("m1", "TOKEN", mailbox=missing)
    assert not missing.exists()


def test_i5_lifecycle_gates_take_an_explicit_mailbox(tmp_path):
    """Task 11 (controller-added), I-5: do_prereg (and so every gate built on s1_collect._ack) reads the mailbox it
    is given."""
    s1_state(tmp_path, START)
    moved = tmp_path / "elsewhere.sqlite3"
    shutil.move(str(c.MAILBOX), str(moved))
    with _Clock(START_DT - timedelta(days=1)):
        with pytest.raises((SystemExit, sqlite3.Error)):
            r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
        assert r.do_prereg(tmp_path, "run-ack", S1_RECEIPT, mailbox=moved)["ack"]["ack_id"] == "run-ack"


# ====================================================================== I-6 carry-in action scope
def test_i6_carry_in_reasons_use_unit_identity_actions_only():
    """Task 11 (controller-added), I-6 (design §11 wins): a special dividend or a spin-off/rights source on a held
    carry-in symbol does not untrust carry-in; a split still does."""
    held, since = {"CI": 10.0}, {"CI": "2026-10-01"}
    for a in ({"type": "cash_dividends", "id": "d", "symbol": "CI", "special": True, "ex_date": "2026-10-27"},
              {"type": "spin_offs", "id": "so", "source_symbol": "CI", "new_symbol": "CJ", "ex_date": "2026-10-27"},
              {"type": "rights_distributions", "id": "rd", "source_symbol": "CI", "new_symbol": "CR",
               "ex_date": "2026-10-27"},
              {"type": "cash_dividends", "id": "u", "symbol": "CI", "special": True}):            # undated
        assert r.carry_in_reasons(held, [a], since) == [], a
    split = {"type": "forward_splits", "id": "s", "symbol": "CI", "ex_date": "2026-10-05"}
    assert r.carry_in_reasons(held, [split], since) == ["carry-in CI: forward_splits s on 2026-10-05 "
                                                         "(held since 2026-10-01)"]


def test_i6_special_dividend_on_a_held_carry_in_symbol_is_scored_not_inconclusive(tmp_path, monkeypatch):
    """Task 11 (controller-added), I-6: audit (pre-START) and final special dividends on CI, held at START and still
    open across the trial -> prereg not BLOCKED and the trial is scored."""
    div = {"type": "cash_dividends", "id": "sd", "symbol": "CI", "special": True, "ex_date": "2026-10-27"}
    pre = dict(div, id="sd0", ex_date="2026-10-05")
    st_ = s1_state(tmp_path, START, score_ready=True, audit_actions=[pre], final_actions=[div])
    rep = score(tmp_path, monkeypatch, st_)
    assert rep["verdict"] == "SHADOW PASS" and rep["reasons"] == [], rep["reasons"]


# ====================================================================== m-1 / m-2 integrity bindings
def test_m1_final_plan_edited_after_the_acquisition_is_aborted_invalid(tmp_path, monkeypatch):
    """Task 11 (controller-added), m-1: the final manifest binds final_plan.json; a plan edited afterwards (claiming
    carry-in coverage never requested) is ABORTED-INVALID."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    fp = tmp_path / "s1_out" / "final_plan.json"
    plan = read(fp)
    plan["ca_symbols_full_history"] = sorted(plan["ca_symbols_full_history"] + ["ZZZ"])
    fp.write_text(json.dumps(plan, indent=1, sort_keys=True), encoding="utf-8")
    rep = score(tmp_path, monkeypatch, st_)
    assert rep["verdict"] == "ABORTED-INVALID" and any("final plan" in x for x in rep["reasons"]), rep["reasons"]


@pytest.mark.parametrize("how", ["missing", "different"])
def test_m2_capture_report_naming_a_seal_that_is_not_on_disk_is_aborted_invalid(tmp_path, monkeypatch, how):
    """Task 11 (controller-added), m-2: every capture report with seal.written=true must name an existing seal file
    with that sha256 (a deleted seal would move the stop)."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    if how == "missing":
        d = out / "captures" / "2026-10-28"
        d.mkdir(parents=True)
        (d / "20261028T204500Z.report.json").write_text(json.dumps({
            "close": "2026-10-28T20:00:00+00:00", "scheduled": "2026-10-28T20:45:00+00:00",
            "seal": {"written": True, "sha256": "ab" * 32}, "restart_gaps": []}), encoding="utf-8")
    else:                                                    # the real opening checkpoint's report, hash edited
        p = next((out / "captures" / "2026-10-23").glob("*.report.json"))
        rp = read(p)
        assert rp["seal"]["written"] is True
        rp["seal"]["sha256"] = "cd" * 32
        p.write_text(json.dumps(rp), encoding="utf-8")
    rep = score(tmp_path, monkeypatch, st_)
    assert rep["verdict"] == "ABORTED-INVALID" and any("seal missing" in x for x in rep["reasons"]), rep["reasons"]


# ====================================================================== m-4 redirects
@pytest.mark.parametrize("cl", [lambda: httpx.Client(follow_redirects=True, transport=httpx.MockTransport(
    lambda req: httpx.Response(200, json=[]))), lambda: object()])
def test_m4_collectors_refuse_a_client_that_may_follow_redirects(tmp_path, cl):
    """Task 11 (controller-added), m-4: do_audit and do_final refuse (before any ACK, reservation or request) a
    client whose follow_redirects is not False."""
    with pytest.raises(SystemExit, match="follow_redirects"):
        k.do_audit(tmp_path, "a", cl(), ("K", "S"))
    with pytest.raises(SystemExit, match="follow_redirects"):
        k.do_final(tmp_path, "f", cl(), ("K", "S"))
    assert not (tmp_path / "s1_out").exists()


# ====================================================================== m-6 R-EST static guard
PRODUCT = sorted(p for p in HERE.glob("s1_*.py"))
FORBIDDEN_TOP = {"backend", "agents", "trading", "loops", "main", "lifespan", "database", "config", "logging_setup",
                 "httpx", "requests", "urllib", "urllib3", "http", "socket", "aiohttp", "websocket", "websockets",
                 "alpaca", "alpaca_trade_api", "ftplib", "smtplib", "asyncio"}


def _tree(p):
    return ast.parse(p.read_text(encoding="utf-8"))


def _imports(tree) -> set:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            out.add(n.module.split(".")[0])
    return out


def _calls(tree, attr):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == attr]


def test_m6_r_est_no_app_import_network_library_or_live_write_path():
    """Task 11 (controller-added), m-6 - a static guard for R-EST (spec §2: offline, no live change, app import,
    broker API or restart). It pins properties the code already has, so it passed before the fix round too (no RED).
    - no product module imports the app (backend/agents/trading/...) or a network/async library;
    - sqlite3.connect appears only in s1_snapshot (the online backup) and s1_collect._ack (the mailbox, mode=ro);
    - only s1_checkpoint names the live DB path, and it never connects (it hands the path to s1_snapshot);
    - requests are issued only by s1_collect, only through the injected `client`;
    - subprocess only in s1_receipt (git / process table / runtime versions), no kill/restart command anywhere."""
    assert {p.name for p in PRODUCT} >= {"s1_common.py", "s1_snapshot.py", "s1_books.py", "s1_seal.py",
                                         "s1_receipt.py", "s1_checkpoint.py", "s1_collect.py", "s1_run.py"}
    for p in PRODUCT:
        t, src = _tree(p), p.read_text(encoding="utf-8")
        assert not _imports(t) & FORBIDDEN_TOP, (p.name, _imports(t) & FORBIDDEN_TOP)
        connects = [n for n in _calls(t, "connect") if isinstance(n.func.value, ast.Name) and n.func.value.id ==
                    "sqlite3"]
        if p.name == "s1_collect.py":
            assert len(connects) == 1 and "mode=ro" in ast.unparse(connects[0].args[0]) and \
                any(kw.arg == "uri" and kw.value.value is True for kw in connects[0].keywords)
        elif p.name != "s1_snapshot.py":
            assert not connects, p.name
        if p.name != "s1_checkpoint.py":
            assert "trading.db\")" not in src and "backend/trading.db" not in src, p.name
        client_calls = [n for a in ("get", "post", "put", "delete", "request", "stream", "send")
                        for n in _calls(t, a) if isinstance(n.func.value, ast.Name) and n.func.value.id == "client"]
        assert not client_calls or p.name == "s1_collect.py", p.name
        assert "subprocess" not in _imports(t) or p.name == "s1_receipt.py", p.name
        for word in ("Stop-Process", "taskkill", "os.kill", "Restart-", "shutdown"):
            assert word not in src, (p.name, word)
    snap = _tree(HERE / "s1_snapshot.py")
    ro = [n for n in _calls(snap, "connect") if "mode=ro" in ast.unparse(n)]
    assert ro, "s1_snapshot opens its source read-only"
    chk = _tree(HERE / "s1_checkpoint.py")
    assert not [n for n in _calls(chk, "connect")] and "sqlite3" not in _imports(chk)


# ====================================================================== m-7 report kinds
@pytest.mark.parametrize("kind", ["aborted", "blocked", "no-valid-seal"])
def test_m7_every_report_kind_carries_restarts_and_the_quantity_bridge(tmp_path, monkeypatch, kind):
    """Task 11 (controller-added), m-7: restarts and the quantity bridge are keys of the ABORTED-INVALID, BLOCKED and
    NO-VALID-SEAL reports too (design §14 Report), not only of priced ones."""
    if kind == "aborted":
        st_ = s1_state(tmp_path, START, score_ready=True)
        (tmp_path / "s1_out" / "aborted.json").write_text(json.dumps({"reason": "x"}), encoding="utf-8")
        want = "ABORTED-INVALID"
    elif kind == "blocked":
        monkeypatch.setattr(r, "carry_in_reasons", lambda *a, **kw: [])           # bypass prereg's BLOCKED gate
        split = {"type": "forward_splits", "id": "sp", "symbol": "CI", "ex_date": "2026-10-05"}
        st_ = s1_state(tmp_path, START, score_ready=True, audit_actions=[split])
        monkeypatch.undo()
        want = "BLOCKED"
    else:
        st_ = s1_state(tmp_path, START, score_ready=True, lots=[], seal_days=[])
        want = "NO-VALID-SEAL"
    rep = score(tmp_path, monkeypatch, st_)
    assert rep["verdict"] == want, rep["reasons"]
    assert "observed_in_crash_log_minimum" in rep["restarts"] and "observation_gaps" in rep["restarts"]
    assert "quantity_bridge" in rep
    if kind != "no-valid-seal":
        assert isinstance(rep["quantity_bridge"], dict)
