"""Task 12 fix round 8 (re-review 6: H-1, H-2; operator-approved structural rule, brief task-12-fix8.md). Written
BEFORE the restructure; behavioural RED in s1_evidence/t12_fix8_<id>_red.txt. The reviewer probes
scratchpad/probe/test_probe11.py and test_probe12.py are permanent tests here, plus the exhaustive subset test the
brief requires (every non-empty subset of the six editable registration files x 3 modes, enumerated, no sampling).
Time is an injected aware clock. Synthetic only: tmp_path ledgers and mailbox (read-only); no live DB, network, real
mailbox or scheduler."""
import itertools
import json
import shutil
from datetime import timedelta

import pytest

import s1_common as c
import s1_run as r
from conftest import S1_RECEIPT, _Clock, s1_mailbox_init, s1_state
from test_s1_t12_fix2_b3 import MON, _aborted, _cp
from test_s1_t12_fix4 import START, START_DT

FILES = ("plan.json", "audit/manifest.json", "registry/opening.json", "witnesses/opening.json", "attest_start.json",
         "prereg.json")
MODES = ("edit", "delete", "corrupt")
SHORT = dict(zip(FILES, ("plan", "manifest", "registry", "witnesses", "attest", "prereg")))
SUBSETS = [s for n in range(1, len(FILES) + 1) for s in itertools.combinations(FILES, n)]
T = MON + timedelta(minutes=45)


def _registered(tmp_path):
    st_ = s1_state(tmp_path, START)
    with _Clock(START_DT - timedelta(days=1)):
        r.do_prereg(tmp_path, "run-ack", S1_RECEIPT)
    return st_, tmp_path / "s1_out"


# ====================================================================== H-1 (probe11)
@pytest.mark.parametrize("mode", ["delete", "corrupt", "list"])
def test_h1_probe_an_edited_plan_with_an_unreadable_manifest_aborts_and_restoring_does_not_resume(tmp_path, mode):
    """H-1 reviewer probe test_manifest_none (B3.3/B3.5), healthy mailbox, after prereg: plan.json's opening_close
    moved and audit/manifest.json deleted, corrupted ("{x") or replaced by a JSON list. Registration is witnessed by
    the RUN-ACK found by its bundle, and the anchor comes only from the AUDIT-ACK, so the next checkpoint records the
    persistent "registration artifact" abort; restoring both files keeps the trial ABORTED-INVALID."""
    st_, out = _registered(tmp_path)
    p, mp = out / "plan.json", out / "audit" / "manifest.json"
    gp, gm = p.read_bytes(), mp.read_bytes()
    plan = json.loads(gp)
    plan["opening_close"] = "2027-12-31"
    p.write_text(json.dumps(plan), encoding="utf-8")
    if mode == "delete":
        mp.unlink()
    else:
        mp.write_text("{x" if mode == "corrupt" else "[]", encoding="utf-8")
    with pytest.raises(SystemExit):
        _cp(tmp_path, st_["ledger"].path)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    p.write_bytes(gp)
    mp.write_bytes(gm)
    try:
        rep = _cp(tmp_path, st_["ledger"].path, minutes=47)
    except SystemExit:
        rep = None
    assert c.load_abort(out)["reason"] == "registration artifact"
    assert rep is None or rep["stop"]["status"] == "ABORTED-INVALID", rep["stop"]


# ====================================================================== H-2 (probe12)
def test_h2_probe_a_six_file_coordinated_edit_aborts_through_the_ack_found_by_its_bundle(tmp_path):
    """H-2 reviewer probe test_six_file_combo: plan, manifest (ack bogus, plan hash re-pointed), both opening records
    (seal path moved, hashes re-pointed), attest_start and prereg (hashes re-pointed) edited together with a healthy
    mailbox. The RUN-ACK is found by bundle_sha256 (no local key), and it and the AUDIT-ACK bind the original hashes:
    the persistent abort; restoring the six files keeps the trial ABORTED-INVALID."""
    st_, out = _registered(tmp_path)
    good = {n: (out / n).read_bytes() for n in FILES}
    plan = json.loads(good["plan.json"])
    plan["opening_close"] = "2027-12-31"
    (out / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    m = json.loads(good["audit/manifest.json"])
    m["ack"]["ack_id"] = "bogus"
    m["plan_sha256"] = c.sha256_file(out / "plan.json")
    (out / "audit/manifest.json").write_text(json.dumps(m), encoding="utf-8")
    for n in ("registry/opening.json", "witnesses/opening.json"):
        rec = json.loads(good[n])
        a = {k.replace("2026-10-23", "2027-12-31"): v for k, v in rec["artifacts"].items()}
        a["plan.json"] = c.sha256_file(out / "plan.json")
        a["audit/manifest.json"] = c.sha256_file(out / "audit/manifest.json")
        rec["artifacts"] = a
        (out / n).write_text(json.dumps(rec), encoding="utf-8")
    for n in ("attest_start.json", "prereg.json"):
        x = json.loads(good[n])
        x["plan_sha256"] = c.sha256_file(out / "plan.json")
        x["audit_manifest_sha256"] = c.sha256_file(out / "audit/manifest.json")
        (out / n).write_text(json.dumps(x), encoding="utf-8")
    with pytest.raises(SystemExit):
        _cp(tmp_path, st_["ledger"].path)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    for n, b in good.items():
        (out / n).write_bytes(b)
    try:
        rep = _cp(tmp_path, st_["ledger"].path, minutes=47)
    except SystemExit:
        rep = None
    assert c.load_abort(out)["reason"] == "registration artifact"
    assert rep is None or rep["stop"]["status"] == "ABORTED-INVALID", rep["stop"]


# ====================================================================== exhaustive subsets (brief)
@pytest.fixture(scope="module")
def template(tmp_path_factory):
    """One registered trial (after prereg), built once; each case works on a copy of the whole root (s1_out and the
    synthetic mailbox)."""
    root = tmp_path_factory.mktemp("fix8_template")
    old = c.MAILBOX
    c.MAILBOX = s1_mailbox_init(root)      # Task 4: write_plan reads the mailbox (F9), so it must exist
    try:
        _registered(root)
    finally:
        c.MAILBOX = old
    return root


def _tamper(out, rel, mode):
    p = out / rel
    if mode == "delete":
        p.unlink()
    elif mode == "corrupt":
        p.write_text("{x", encoding="utf-8")
    else:                                                # edit: the content changes, still well-formed JSON
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rel.endswith("opening.json"):
            rec["artifacts"]["plan.json"] = "0" * 64
        else:
            rec["tampered"] = True
        p.write_text(json.dumps(rec), encoding="utf-8")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("subset", SUBSETS, ids=["+".join(SHORT[x] for x in s) for s in SUBSETS])
def test_h_every_subset_of_the_editable_registration_files_tampered_is_the_persistent_abort(tmp_path, template,
                                                                                            subset, mode):
    """Brief (fix round 8): a registered trial (after prereg), healthy mailbox; EVERY non-empty subset of {plan,
    audit manifest, both opening records, attest_start, prereg} edited, deleted or corrupted: the next command
    records the persistent "registration artifact" abort, and restoring the files does not resume (aborted.json
    stays, the next command still sees ABORTED-INVALID)."""
    shutil.copytree(template, tmp_path, dirs_exist_ok=True)
    out = tmp_path / "s1_out"
    good = {rel: (out / rel).read_bytes() for rel in subset}
    for rel in subset:
        _tamper(out, rel, mode)
    with pytest.raises(SystemExit):
        c.verify_bundle_first(out, "checkpoint", now=lambda: T, need="prereg")
    assert (c.load_abort(out) or {}).get("reason") == "registration artifact", (subset, mode, c.load_abort(out))
    first = (out / "aborted.json").read_bytes()
    for rel, b in good.items():
        (out / rel).write_bytes(b)
    rep = _cp(tmp_path, tmp_path / "s1_ledger.sqlite3", minutes=47)     # fix round 9 (item 3): asserted, not swallowed
    assert rep["stop"]["status"] == "ABORTED-INVALID" and rep["stop"]["reason"] == "registration artifact", rep["stop"]
    assert (out / "aborted.json").read_bytes() == first


# ====================================================================== the rule's other edges (written before the code)
def test_h_a_run_ack_carrying_the_bundle_is_a_registration_even_before_the_opening(tmp_path, monkeypatch):
    """RETROSPECTIVE (written after the restructure). Fix round 8 rule 1a/2/5 (replaces fix4::test_n3_clock_anchor_nothing_is_registered_before_the_first_opening_
    slot): with plan + audit, a codex S1-RUN-ACK carrying the registered bundle exists BEFORE the opening's first slot
    (the anchor never cancels an external ACK; an ACK with this bundle is this registered bundle - fail closed), plus a
    prereg naming it: the gate records the persistent "registration artifact" abort with zero live callbacks."""
    import s1_checkpoint as ck
    import s1_seal as z
    from conftest import Ledger, s1_mailbox, s1_plan_audit
    from test_s1_t12_fix2_b3 import Spies
    from test_s1_t12_fix4 import _fabricate
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    out = tmp_path / "s1_out"
    _fabricate(tmp_path, ["prereg.json"], cal)
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    pr["ack"] = {"ack_id": "forged-run"}
    (out / "prereg.json").write_text(json.dumps(pr), encoding="utf-8")
    slot0 = z.schedule(next(d for d in cal if d["date"] == oc), cal)[0]
    before = c.opening_anchor(out) - timedelta(minutes=10)      # (fix round 9: before the calendar-free anchor)
    s1_mailbox(tmp_path, "forged-run", f"S1-RUN-ACK plan_sha256={c.sha256_file(out / 'plan.json')} "
                                       f"bundle_sha256={c.bundle_sha256()} start={START}", before - timedelta(minutes=5))
    spies = Spies(monkeypatch)
    with _Clock(before), pytest.raises(SystemExit):
        ck.run_opening_checkpoint(tmp_path, Ledger(tmp_path / "l.sqlite3").path, slot0, spies.receipt, spies.process,
                                  tmp_path / "crash.log", now=lambda: before)
    assert _aborted(tmp_path)["reason"] == "registration artifact"
    assert spies.zero(), spies.n


# Fix round 9: test_h_opening_evidence_without_any_audit_ack_for_the_bundle_is_the_abort REMOVED - the
# controller corrected the fix-8 brief rule 3 (B3.2 / I-2): no AUDIT-ACK for the bundle = always a refusal.
# Replaced by fix9::test_rule3_no_audit_ack_for_the_bundle_is_always_a_refusal_even_with_opening_evidence.


def test_h_guard_without_any_audit_ack_and_no_opening_evidence_is_a_refusal(tmp_path):
    """RETROSPECTIVE (written after the restructure). Fix round 8 rule 3 guard: plan + audit files but no AUDIT-ACK message and no opening evidence, plus a hand-made
    prereg: not past audit - a preserved refusal, no abort."""
    import sqlite3
    from conftest import s1_plan_audit
    from test_s1_t12_fix4 import _fabricate
    start, cal, oc, _ = s1_plan_audit(tmp_path, START)
    con = sqlite3.connect(tmp_path / "mailbox.sqlite3")
    con.execute("DELETE FROM messages WHERE id=?", ("audit-ack",))
    con.commit()
    con.close()
    _fabricate(tmp_path, ["prereg.json"], cal)
    with pytest.raises(SystemExit):
        c.registration_gate(tmp_path / "s1_out", "checkpoint", now=lambda: T)
    assert c.load_abort(tmp_path / "s1_out") is None


def test_h_retro_only_the_external_acks_bind_a_coordinated_attestation_edit(tmp_path):
    """RETROSPECTIVE (fix round 8; REWRITTEN in fix round 9, A10.2: the fix-8 version edited plan.json, which the
    round-9 plan binding now catches first, so it no longer isolated the external-ACK check). After prereg,
    attest_start.json gains a field and EVERY local copy of its hash is re-pointed: both attest_start records and
    prereg.json's attest_start_sha256. Only the RUN-ACK (found by bundle_sha256) still binds the original
    attestation hash: the persistent abort, reported as bound by the external ACK."""
    st_, out = _registered(tmp_path)
    att = json.loads((out / "attest_start.json").read_text(encoding="utf-8"))
    att["tampered"] = True
    (out / "attest_start.json").write_text(json.dumps(att), encoding="utf-8")
    h = c.sha256_file(out / "attest_start.json")
    for n in ("registry/attest_start.json", "witnesses/attest_start.json"):
        rec = json.loads((out / n).read_text(encoding="utf-8"))
        rec["artifacts"]["attest_start.json"] = h
        (out / n).write_text(json.dumps(rec), encoding="utf-8")
    pr = json.loads((out / "prereg.json").read_text(encoding="utf-8"))
    pr["attest_start_sha256"] = h
    (out / "prereg.json").write_text(json.dumps(pr), encoding="utf-8")
    for n in ("registry/prereg.json", "witnesses/prereg.json"):
        rec = json.loads((out / n).read_text(encoding="utf-8"))
        rec["artifacts"]["prereg.json"] = c.sha256_file(out / "prereg.json")
        (out / n).write_text(json.dumps(rec), encoding="utf-8")
    with pytest.raises(SystemExit):
        c.registration_gate(out, "checkpoint", now=lambda: T)
    ab = _aborted(tmp_path)
    assert ab["reason"] == "registration artifact" and any("external ACK" in x for x in ab["problems"]), ab
