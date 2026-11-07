"""A3 test helpers (Task 8+): fake stage works with real staging, and child-process entry points for real crashes and
live owners (F5.4). Test-only; never imported by product code."""
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))      # research/s1 (child processes run this file)
import s1_common as c                                                  # noqa: E402
import s1_journal as j                                                 # noqa: E402
import s1_stage as sg                                                  # noqa: E402
import s1_trial as t                                                   # noqa: E402


def relax(monkeypatch_or_none, stage, *, state="ACTIVE"):
    """Engine tests: drive `stage` with its F1 prerequisites relaxed (they are tested separately). A `seal/<close>`
    stage has no predecessor or ACK already (SEAL_SPEC), so it is left as is (revision 2)."""
    if stage.startswith(sg.SEAL_PREFIX):
        return
    entry = dict(sg.TABLE[stage], pred=None, ack=None, state=state)
    if monkeypatch_or_none is None:
        sg.TABLE[stage] = entry
    else:
        monkeypatch_or_none.setitem(sg.TABLE, stage, entry)


def fake_single(sw):
    """final_plan-shaped single member that records trial_id and intent_at."""
    sw.put_json("final_plan.json", {"trial_id": sw.trial_id, "intent_at": sw.intent_at, "plan": "synthetic"})
    return []


def fake_audit(sw, pages=2):
    """An audit-shaped tree: the six F4.9 fixed members (the manifest's files/pages consistent with them) + pages."""
    prov = []
    for n in range(pages):
        rel = f"audit/pages/ca_000_page{n:03d}.json"
        data = json.dumps({"corporate_actions": {}, "next_page_token": None if n == pages - 1 else f"tok{n}"}).encode()
        sw.put(rel, data)
        prov.append({"family": "corporate_actions", "scope": "audit", "n": n,
                     "url": "https://data.alpaca.markets/v1/corporate-actions", "params": {"n": n},
                     "page_token_from": None if n == 0 else f"audit/pages/ca_000_page{n - 1:03d}.json",
                     "retrieved_utc": sw.intent_at, "status": 200, "page_relpath": rel,
                     "page_sha256": c.sha256_bytes(data)})
    for name in sg.FIXED_TREE["audit"][:-1]:
        sw.put_json(name, {"trial_id": sw.trial_id, "intent_at": sw.intent_at, "name": name})
    files = {Path(n).name: c.sha256_bytes(sw.files[n]) for n in sg.FIXED_TREE["audit"][:-1]}
    sw.put_json("audit/manifest.json", {"outcome": "COMPLETE", "files": files,
                                        "pages": {p["page_relpath"]: p["page_sha256"] for p in prov}})
    return prov


SEAL_INPUTS = {"qualified_line": "1" * 64, "tree_manifest": "2" * 64}
SEAL_FAKES = {"extra_gate": lambda rows: None, "stage_check": lambda rows, s, inputs: None}   # fake seal-side callables


def fake_seal(sw):
    """A seal stage's one member seals/<close>.json (fake bytes; the real seal is Task 7's)."""
    sw.put(sg.single_member(sw.gv.out, sw.stage), b'{"seal": "fake"}')
    return []


def plan_only(root, start):
    """write_plan + its AUDIT-ACK (no audit files, no journal rows): the audit stage is permitted."""
    import s1_collect as k
    from conftest import _Clock, s1_mailbox
    with _Clock(start - timedelta(days=14)):
        k.write_plan(root, start, "2026-10-23", ["A"], "2026-03-17")
    s1_mailbox(root, "audit-ack", c.audit_token(Path(root) / "s1_out"), start - timedelta(days=13))
    return t.gate(root, "plan_only")


def child(root, stage, mode, at_iso):
    """Run one stage in this (child) process. mode: die-after-intent | die-after-prepared | hold-after-intent |
    hold-after-prepared | hold-before-created (fix round 1: members published, CREATED not yet requested) | recover |
    hold-recover (fix round 1: the recovery holds the stage lock, after its re-read, just before its CREATED request;
    released by a stdin line, then completes). Prints a status line; 'hold' modes wait on stdin while holding the
    stage lock (a pipe barrier, no sleeps). A `seal/<close>` stage runs fake_seal with permissive fake seal-side
    callables (the slot side is Task 7's)."""
    c.MAILBOX = Path(root) / "mailbox.sqlite3"
    at = c.aware(at_iso)
    c.now_utc = lambda: at
    relax(None, stage)
    sg.ENFORCED = frozenset({stage})
    real = j.append

    def hooked(trial_id, gen, req, ctx_fn, **kw):
        if mode in ("hold-before-created", "hold-recover") and req.kind == "STAGE-CREATED":
            print("held", flush=True)
            sys.stdin.readline()
            if mode == "hold-before-created":
                os._exit(0)
        res = real(trial_id, gen, req, ctx_fn, **kw)
        if mode.startswith("die-after-intent") and req.kind == "STAGE-INTENT":
            os._exit(9)
        if mode == "die-after-prepared" and req.kind == "STAGE-PREPARED":
            os._exit(9)
        if mode.startswith("hold-after-intent") and req.kind == "STAGE-INTENT":
            print("held", flush=True)
            sys.stdin.readline()
            os._exit(0)
        if mode == "hold-after-prepared" and req.kind == "STAGE-PREPARED":
            print("held", flush=True)
            sys.stdin.readline()
            os._exit(0)
        return res
    j.append = hooked
    gv = t.gate(root, f"child {mode}")
    if mode in ("recover", "hold-recover"):
        print(json.dumps(sorted(sg.evaluate(gv) or [])), flush=True)
        return
    if stage.startswith(sg.SEAL_PREFIX):
        sg.run(gv, stage, inputs=SEAL_INPUTS, acks={}, work=fake_seal, mailbox=c.MAILBOX, clock=lambda: at,
               **SEAL_FAKES)
        return
    work = fake_audit if stage == "audit" else fake_single
    sg.run(gv, stage, inputs={"plan.json": c.sha256_file(Path(root) / "s1_out" / "plan.json")}, acks={},
           work=work, mailbox=c.MAILBOX, clock=lambda: at)


# ------------------------------------------------------------------ A3 Task 11 (OQ-8 dispositions, BLK-3)
# The frozen inputs of s1_evidence/a3/t11_dispositions.md (START 2026-10-26T13:30:00+00:00 on the fixture's pinned
# weekday calendar): deadline 2027-04-26T13:30:00+00:00, eligible d0 2026-10-26 .. d129 2027-04-23, d130 2027-04-26
# ineligible. The expected values below are that document's, written out by hand - never computed by s1_seal.
# Revision 1 answers Codex f33d0501 (AMEND): rows 300-305 ACCEPTED as numbers; new cases (i)-(v); the commit
# permission (s1_seal.stop_ready) is separate from the pure candidate (s1_seal.stop_record).
STOP_DISPOSITION_STATUS = ("r1 - rows 300-305 ACCEPTED by Codex f33d0501 (numbers); r1 cases (i)-(v) and the "
                           "readiness/provenance text PENDING Codex acceptance (BLK-3)")
_D = {0: "2026-10-26", 1: "2026-10-27", 2: "2026-10-28", 129: "2027-04-23", 130: "2027-04-26"}
_W_D129 = "slot/20270426T120000Z"                       # the W slot of the last eligible close (2027-04-23)
TIMEOUT_CASES = ("timeout-last-sealed", "no-valid-seal", "deadline-instant-eligibility",
                 "no-valid-seal-ineligible-seal")


def _lots(n, sell):
    """n fixture lots of 10 shares of S{i % 5}, bought on post-START session 0; sell(i) -> (day, px) | None."""
    return [{"symbol": f"S{i % 5}", "qty": 10, "px": 100.0, "buy_day": 0, "sell": sell(i)} for i in range(n)]


def _dates(first, last):
    from conftest import _weekdays
    return [d["date"] for d in _weekdays(first, last)]


def _early_failed(root, subject, day_iso, intent_at, failed_at):
    """OQ-33 early invocation: SLOT-INTENT before the slot (journal: only now < E is required), consumed as SLOT-FAILED
    with zero capture - its claim and failure report carry the INTENT's op/actor, FAILED detail = their tree (F3)."""
    from conftest import s1_jappend
    import s1_slot as sl
    out = Path(root) / "s1_out"
    slot = sl.slot_of(subject)
    intent = s1_jappend(root, "SLOT-INTENT", subject, at=c.aware(intent_at))
    n = sl.names(out, slot, day_iso)
    n["claim"].parent.mkdir(parents=True, exist_ok=True)
    who = {"op": intent.op, "actor": intent.actor}
    n["claim"].write_text(json.dumps(dict(who, scheduled=slot.isoformat(), invoked_utc=intent.at,
                                          intent_seq=intent.seq, capture_dir=None)), encoding="utf-8")
    n["report"].write_text(json.dumps(dict(who, scheduled=slot.isoformat(), outcome="FAILED",
                                           reason="early invocation (OQ-33): no capture")), encoding="utf-8")
    s1_jappend(root, "SLOT-FAILED", subject, at=c.aware(failed_at), op=intent.op, actor=intent.actor,
               detail=j.detail_of(sl.failed_tree(out, slot, day_iso)))


def stop_history(root, start, case) -> dict:
    """Build the history of one t11_dispositions.md example (rows 300-305 and r1 cases (i)-(v); synthetic seals with
    real slot rows) under `root`, and return {"calendar", "want"}: `want` is the example's expected stop CANDIDATE
    record fields (None: no candidate). Seq, line sha256 and seal sha256 are read from the named journal row / CREATED
    seal file (independently chosen committed fixture records, never stop_record). Test-only."""
    from conftest import S1_RECEIPT, _write_seal, s1_close_out, s1_jappend, s1_state
    import s1_seal as z
    import s1_slot as sl
    root = Path(root)
    out = root / "s1_out"
    mbx = root / "mailbox.sqlite3"
    lots, seal_days = {
        "lots-earliest": (None, [0, 1]),
        "lots-later-not-chosen": (_lots(200, lambda i: (1 if i < 100 else 2, 80.0)), [1, 2]),
        "timeout-last-sealed": (_lots(100, lambda i: (1, 80.0) if i < 99 else None), [0, 1, 2]),
        "no-valid-seal": (None, []),
        "pending-excluded": (None, []),
        "deadline-instant-eligibility": (_lots(100, lambda i: (130, 80.0)), [0]),
        "early-w-failed": (None, []),                                    # r1 (i)
        "pending-after-timeout": (None, []),                             # r1 (ii)
        "unresolved-blocks": (None, [0]),                                # r1 (iii) before the MISSED
        "unresolved-resolved-by-missed": (None, [0]),                    # r1 (iii) after the MISSED
        "delayed-qualified-clock": (None, [0]),                          # r1 (iv)
        "no-valid-seal-ineligible-seal": (_lots(100, lambda i: (130, 80.0)), []),   # r1 (v)
    }[case]
    st_ = s1_state(root, start, score_ready=True, lots=lots, seal_days=seal_days, stop=False)
    cal, sess = st_["calendar"], st_["sessions"]
    assert all(sess[i] == d for i, d in _D.items()), "fixture calendar differs from t11_dispositions.md section 0"
    oc = z.close_of(st_["opening_close"], cal)

    def trades_by(cl):
        return [x for x in st_["rows"] if c.aware(x["ts"]) <= cl + timedelta(minutes=45)]

    def seal(i, **kw):
        cl = z.close_of(sess[i], cal)
        _write_seal(out, sess[i], cl, trades_by(cl), S1_RECEIPT, start=c.aware(start), opening_close=oc, **kw)

    def seal_stage(i, at):                               # the seal stage of a close determined after its QUALIFIED
        day_row = next(d for d in cal if d["date"] == sess[i])
        gv = t.gate(root, "fixture seal (r1)", mailbox=mbx)
        res = sl.run_seal_stage(gv, day_row, cal, mailbox=mbx, clock=lambda: c.aware(at))
        assert res["written"], res

    if case in ("pending-excluded", "pending-after-timeout"):     # d0's first slot: INTENT, no terminal; d1 sealed
        intent = s1_jappend(root, "SLOT-INTENT", "slot/20261026T204500Z", at=c.aware("2026-10-26T20:45:01+00:00"))
        seal(1)
        if case == "pending-after-timeout":                       # the finalizer's late TIMEOUT unblocks d0
            s1_jappend(root, "SLOT-TIMEOUT", "slot/20261026T204500Z", at=c.aware("2026-10-27T21:00:00+00:00"),
                       op=intent.op, due=True)
    if case in ("unresolved-blocks", "unresolved-resolved-by-missed"):
        seal(1, minutes=47, with_stage=False)            # d1 20:47 QUALIFIED (100 sold); 20:45 has no row yet
        seal(2)                                          # d2 sealed (also 100 sold: the rev-0 draft's wrong stop)
        if case == "unresolved-resolved-by-missed":
            s1_jappend(root, "SLOT-MISSED", "slot/20261027T204500Z", at=c.aware("2026-10-28T21:00:00+00:00"),
                       due=True)
            seal_stage(1, "2026-10-28T21:00:01+00:00")
    if case == "delayed-qualified-clock":                # BLK3-C2: the completing QUALIFIED's R predates the MISSED
        seal(1, minutes=47, r_at=c.aware("2026-10-27T20:56:00.000000+00:00"),
             q_at=c.aware("2026-10-27T20:56:00.200000+00:00"),
             before_qualified=lambda: s1_jappend(root, "SLOT-MISSED", "slot/20261027T204500Z",
                                                 at=c.aware("2026-10-27T20:56:00.100000+00:00"), due=True),
             stage_at=c.aware("2026-10-27T20:56:01+00:00"))
    if case == "early-w-failed":                         # BLK3-C1 counterexample: W slot early INTENT + FAILED
        _early_failed(root, _W_D129, _D[129], "2027-04-23T20:46:00+00:00", "2027-04-23T20:46:30+00:00")
    if case in TIMEOUT_CASES:
        s1_close_out(root, cal, _D[129])                 # every d129 slot MISSED at W = 2027-04-26T12:00Z
    if case in ("deadline-instant-eligibility", "no-valid-seal-ineligible-seal"):
        seal(130)                                        # the ineligible deadline-date close sells 100
    tr = t.open_trial(mbx)
    rows = j.read_trial(tr.trial_id, tr.genesis, mbx)

    def trig(subject, kind, at):
        r = j.first(j.subject_rows(rows, subject), kind)
        assert r is not None, f"fixture has no {kind} on {subject}"
        assert r.at == at, (r.at, at)                    # the document's hand-written `at` (provenance only, C2)
        return {"triggering_slot": subject, "terminal_seq": r.seq, "terminal_line_sha256": r.sha,
                "determined_utc": at}

    def seals(*days):
        return {f"seals/{d}.json": c.sha256_file(out / "seals" / f"{d}.json") for d in days}

    def lots_stop(d, trigger, cohort, sold, missed, sealed):
        return dict(common, **trigger, rule="lots", status="STOPPED", stop_close=f"{d}T20:00:00+00:00",
                    stop_seal=f"seals/{d}.json", stop_seal_sha256=seals(d)[f"seals/{d}.json"],
                    cohort_row_ids=cohort, lots={"sold": sold, "cohort": len(cohort)}, missed=missed,
                    seals=seals(*sealed))

    def nvs(trigger):
        missed = _dates(_D[0], _D[129])
        assert len(missed) == 130
        return dict(common, **trigger, rule="timeout", status="NO-VALID-SEAL", stop_close=None, stop_seal=None,
                    stop_seal_sha256=None, cohort_row_ids=[], lots=None, missed=missed, seals={})

    common = {"trial_id": tr.trial_id, "bundle_sha256": tr.bundle}
    ids100 = list(range(2, 102))
    w_missed = (trig(_W_D129, "SLOT-MISSED", "2027-04-26T12:00:00.000000+00:00") if case in TIMEOUT_CASES
                else None)
    if case in ("pending-excluded", "unresolved-blocks"):
        want = None
    elif case == "lots-earliest":
        want = lots_stop(_D[1], trig("slot/20261027T204500Z", "SLOT-QUALIFIED", "2026-10-27T20:45:31.000000+00:00"),
                         ids100, 100, [], [_D[0], _D[1]])
    elif case == "lots-later-not-chosen":
        want = lots_stop(_D[1], trig("slot/20261027T204500Z", "SLOT-QUALIFIED", "2026-10-27T20:45:31.000000+00:00"),
                         list(range(2, 202)), 100, [_D[0]], [_D[1]])
    elif case == "pending-after-timeout":
        want = lots_stop(_D[1], trig("slot/20261026T204500Z", "SLOT-TIMEOUT", "2026-10-27T21:00:00.000000+00:00"),
                         ids100, 100, [_D[0]], [_D[1]])
    elif case == "unresolved-resolved-by-missed":
        want = lots_stop(_D[1], trig("slot/20261027T204500Z", "SLOT-MISSED", "2026-10-28T21:00:00.000000+00:00"),
                         ids100, 100, [], [_D[0], _D[1]])
    elif case == "delayed-qualified-clock":
        want = lots_stop(_D[1], trig("slot/20261027T204700Z", "SLOT-QUALIFIED", "2026-10-27T20:56:00.000000+00:00"),
                         ids100, 100, [], [_D[0], _D[1]])
    elif case == "timeout-last-sealed":
        missed = _dates("2026-10-29", _D[129])
        assert len(missed) == 127
        want = dict(common, **w_missed, rule="timeout", status="TIMEOUT", stop_close="2026-10-28T20:00:00+00:00",
                    stop_seal="seals/2026-10-28.json", stop_seal_sha256=seals(_D[2])["seals/2026-10-28.json"],
                    cohort_row_ids=ids100, lots={"sold": 99, "cohort": 100}, missed=missed,
                    seals=seals(_D[0], _D[1], _D[2]))
    elif case in ("no-valid-seal", "no-valid-seal-ineligible-seal"):
        want = nvs(w_missed)
    elif case == "early-w-failed":                       # the CANDIDATE; permission is stop_ready's (C1)
        want = nvs(trig(_W_D129, "SLOT-FAILED", "2027-04-23T20:46:30.000000+00:00"))
    else:                                                # deadline-instant-eligibility
        missed = _dates(_D[1], _D[129])
        assert len(missed) == 129
        want = dict(common, **w_missed, rule="timeout", status="TIMEOUT", stop_close="2026-10-26T20:00:00+00:00",
                    stop_seal="seals/2026-10-26.json", stop_seal_sha256=seals(_D[0])["seals/2026-10-26.json"],
                    cohort_row_ids=ids100, lots={"sold": 0, "cohort": 100}, missed=missed, seals=seals(_D[0]))
    return {"calendar": cal, "want": want}


def later_close_after_the_stop_close(st_) -> dict:
    """Row 262 helper: the next eligible close after the fixture's lot-count stop close (s1_state's default seals run
    through the last trade's session, so that close is the session after it), with the trades a seal of it would
    carry (every fixture row stored by then - none after the stop close, so the stop record is unchanged)."""
    import s1_seal as z
    cal, sess = st_["calendar"], st_["sessions"]
    last = max(c.aware(x["ts"]).astimezone(c.NY).date().isoformat() for x in st_["rows"])
    day = next(d for d in sess if d > last)
    close = z.close_of(day, cal)
    return {"date": day, "close": close,
            "trades": [x for x in st_["rows"] if c.aware(x["ts"]) <= close + timedelta(minutes=45)]}


if __name__ == "__main__":
    child(*sys.argv[1:5])
