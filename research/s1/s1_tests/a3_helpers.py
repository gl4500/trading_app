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


if __name__ == "__main__":
    child(*sys.argv[1:5])
