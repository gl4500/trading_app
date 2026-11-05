"""Task 12 fix round 1 (reports/task-12-review.md): I-1, I-4b, m-1, m-4. Written BEFORE the fixes (behavioural RED:
s1_evidence/t12_fix1_<item>_red.txt). Synthetic only: tmp_path repos, ledgers, mailbox and HMAC key."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import s1_checkpoint as ck
import s1_common as c
import s1_receipt as rc
import s1_run as r
import s1_seal as z
from conftest import s1_prereg_at  # A3 Task 10 (fixture instant)
from conftest import s1_prereg_ack  # A3 Task 6
from conftest import S1_PROCESS, S1_RECEIPT, _Clock, s1_mailbox, s1_state

UTC = timezone.utc
START = "2026-10-26T13:30:00+00:00"
START_DT = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
MON = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _cp(tmp_path, st_, day_close, receipt_fn=None, minutes=45):
    sch = day_close + timedelta(minutes=minutes)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        return ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, receipt_fn or (lambda: S1_RECEIPT),
                                 lambda: dict(S1_PROCESS), tmp_path / "crash.log", now=lambda: act)


def _reg(tmp_path, receipt=None):
    st_ = s1_state(tmp_path, START, receipt=receipt)
    with _Clock(s1_prereg_at(tmp_path)):
        r.do_prereg(tmp_path, "run-ack", receipt or S1_RECEIPT)
    s1_prereg_ack(tmp_path)                    # A3 Task 6 (F7.4): the PREREG-ACK before captures
    st_["ledger"].trade("A", "BUY", 10, 50.0, "2026-10-26T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 10)
    return st_


# ====================================================================== I-1
def test_fix1_i1_an_unparseable_closure_member_is_a_terminal_receipt_failure(tmp_path):
    """I-1 (A1.3/A9.2): a closure member that no longer parses (merge conflict) is a terminal ReceiptError, never a
    transient foreign exception."""
    from test_s1_t12_a1 import ROOTS, contract, repo
    root = repo(tmp_path)
    (root / "backend" / "agents" / "mean_reversion_agent.py").write_text("<<<<<<< HEAD\nx = 1\n=======\n")
    with pytest.raises(rc.ReceiptError) as e:
        rc.semantic_receipt(root, root / ".env", None, roots=ROOTS, contract=contract())
    assert e.value.terminal is True and "agents/mean_reversion_agent.py" in str(e.value)


def test_fix1_i1_merge_conflict_mid_trial_is_aborted_invalid_and_restoring_does_not_resume(tmp_path):
    """I-1, the reviewer's scenario: the live MR file is mid-merge at a checkpoint -> ABORTED-INVALID; restoring the
    old bytes does not resume the trial (no later seal)."""
    from test_s1_t12_a1 import ROOTS, contract, repo
    root = repo(tmp_path / "live")

    def receipt():
        return rc.semantic_receipt(root, root / ".env", None, roots=ROOTS, contract=contract())
    st_ = _reg(tmp_path, receipt())
    mr = root / "backend" / "agents" / "mean_reversion_agent.py"
    old = mr.read_bytes()
    mr.write_text("<<<<<<< HEAD\nx = 1\n=======\n")
    rep = _cp(tmp_path, st_, MON, receipt)
    assert rep["stop"]["status"] == "ABORTED-INVALID" and rep["seal"]["written"] is False
    assert "semantic receipt" in str(read(tmp_path / "s1_out" / "aborted.json")["reason"])
    mr.write_bytes(old)
    with pytest.raises(SystemExit, match=r"trial INVALID \(reason/established-violation\)"):   # A3 Task 6 (F1)
        _cp(tmp_path, st_, MON, receipt, minutes=47)                     # restoring never resumes: no work
    assert not (tmp_path / "s1_out" / "seals" / "2026-10-26.json").exists()


# ====================================================================== I-4b
def test_fix1_i4b_a_corrupt_trial_seal_is_a_preserved_terminal_integrity_failure(tmp_path):
    """I-4b (A9.1/A9.2/A2.3), the reviewer's probe: a trial seal that is no longer readable JSON makes the next
    checkpoint write its report and the persistent abort - never a crash with no record."""
    st_ = _reg(tmp_path)
    out = tmp_path / "s1_out"
    assert _cp(tmp_path, st_, MON)["seal"]["written"]
    (out / "seals" / "2026-10-26.json").write_text("{not json", encoding="utf-8")
    st_["ledger"].trade("A", "BUY", 1, 50.0, "2026-10-27T15:00:00+00:00")
    st_["ledger"].set_portfolio("A", 11)
    # A3 Task 7 (E2.6 r3): the seal is a CREATED seal/<close> stage, so the next command's gate finds its member
    # changed and unparseable: TRIAL-INVALID (stage-replaced) recorded before any capture - a refusal with an
    # external record (and its evidence copy), never a crash with no record; no seal of the next close
    with pytest.raises(SystemExit, match=r"seals/2026-10-26\.json missing or changed.*INVALID \(stage-replaced\)"):
        _cp(tmp_path, st_, MON + timedelta(days=1))
    assert not (out / "seals" / "2026-10-27.json").exists()
    assert not (out / "captures" / "2026-10-27").exists()
    obs = read(next((out / "invalid").glob("*.json")))
    assert obs["stage"] == "seal/2026-10-26" and any("unparseable" in x or "changed" in x for x in obs["problems"])


# ====================================================================== m-1
@pytest.mark.parametrize("how", ["prereg_missing", "prereg_unreadable"])
def test_fix1_m1_a_bundle_mismatch_is_persisted_even_on_a_prereg_refusal_path(tmp_path, monkeypatch, how):
    """m-1 (A3.2/A3.3): with an AUDIT-ACK'd audit and the opening seal on disk, the bundle is compared (and a mismatch
    persisted) BEFORE a prereg-dependent refusal."""
    st_ = _reg(tmp_path)
    out = tmp_path / "s1_out"
    p = out / "prereg.json"
    if how == "prereg_missing":
        p.rename(out / "prereg.moved")
    else:
        p.write_text("{garbage", encoding="utf-8")
    monkeypatch.setattr(c, "bundle_sha256", lambda *a, **kw: "f" * 64)
    with pytest.raises(SystemExit):
        _cp(tmp_path, st_, MON)
    assert read(out / "aborted.json")["reason"] == "bundle"


# ====================================================================== m-4
def _live_stop(tmp_path):
    from test_s1_t12_a2 import _live_stop as ls
    return ls(tmp_path)


def test_fix1_m4_a_deleted_persisted_stop_is_an_integrity_failure_not_a_recompute(tmp_path):
    """m-4 (A2.1): stop.json deleted after it was persisted (its hash is recorded by the stop checkpoint's report)
    is never silently recomputed: the next checkpoint records the persistent abort; stop.json stays absent."""
    st_, lg, rows = _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    (out / "stop.json").unlink()
    # (fix round 2, Addendum 2 B3.1/B3.3: stop.json is a registered frozen artifact - registry/stop.json - so the
    # registration gate observes the deletion first: persistent abort, a clean refusal, never a recompute)
    with pytest.raises(SystemExit, match="registration artifact"):
        _cp(tmp_path, st_, MON + timedelta(days=2))
    assert not (out / "stop.json").exists() and not (out / "seals" / "2026-10-28.json").exists()
    ab = read(out / "aborted.json")
    assert ab["reason"] == "registration artifact" and any("stop.json" in x for x in ab["problems"])


def test_fix1_m4_a_changed_persisted_stop_before_the_attestation_is_detected(tmp_path):
    """m-4: stop.json edited after persistence (before any attestation) differs from the hash the checkpoint
    reports recorded -> stop_problems reports it."""
    st_, lg, rows = _live_stop(tmp_path)
    out = tmp_path / "s1_out"
    p = out / "stop.json"
    p.write_text(json.dumps(dict(read(p), decided_by="edited")), encoding="utf-8")
    # A3 Task 6 (OQ-11): a capture report no longer records stop_sha256 (the report is final before J; the stop is
    # display-only in after.json, which is never authority, E5.2); the persisted stop stays bound by its registry
    # records (B3.1), so the registration check reports the change (Task 11: TRIAL-STOP's detail)
    probs = c.registration_problems(out)
    assert any("stop.json" in x and "changed" in x for x in probs), probs


def test_fix1_m4_the_persisted_stops_bundle_is_checked(tmp_path):
    """m-4 (A3.4): stop.json's bundle_sha256 must be the registered bundle."""
    st_ = s1_state(tmp_path, START, score_ready=True)
    out = tmp_path / "s1_out"
    p = out / "stop.json"
    p.write_text(json.dumps(dict(read(p), bundle_sha256="0" * 64)), encoding="utf-8")
    probs = z.stop_problems(out, START_DT, st_["calendar"], recheck=False)
    assert any("bundle" in x for x in probs), probs
