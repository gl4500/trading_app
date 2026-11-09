"""Erratum 2 Clarification 1 r2 C1 (a CLOSE's prev = the latest valid predecessor by creation chronology; ties,
unestablishable chronology and invalid candidates refuse and escalate; first-valid-CLOSE monotonicity) and C2
(CLOSE SCORED evidence is checked at issuance - procedural-model issuer, O-C2; runtime CLOSE under E3.4; the
trusted-issuer residual, NOT detection). Map rows 480-487, with the Codex 59953cfd rulings: NOP-1 (C1.2 kept exactly:
tie / invalid-chain refusal for the SCORED, WITHDRAWN and INVALID reasons; the E4.1-E4.3 attribution boundaries) and
NOP-5 (the row-485 issuer model performs Codex's three exact checks). Every mailbox is the test's tmp mailbox; a spy
proves zero coordination-mailbox writes. Behavioural RED against the H2 stub (s1_evidence/a3/tH2_red.txt)."""
import dataclasses
import json
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_stage as sg
import s1_trial as t
from conftest import _Clock, s1_ack, s1_mailbox, s1_state
from test_s1_a3_nvs import mb, nvs_chain, no_coordination_writes, ok

START = "2026-10-26T13:30:00+00:00"
WITHDRAWAL = "operator withdrawal (fixture only; no product withdrawal)"


def the_trial(root):
    trs = t.trials(t.scan(mb(root)))
    (tr,) = trs.values()
    return tr


def nvs_fork(tmp_path):
    """C1.5: an NVS SCORE-ACK (prev = PREREG), then a later mistaken S1-ACQUIRE-ACK (prev = PREREG)."""
    st_ = nvs_chain(tmp_path)                                         # SCORE-ACK at t0 + 3 d
    s1_ack(tmp_path, "acq-late", "S1-ACQUIRE-ACK", st_["t0"] + timedelta(days=3, hours=1))
    return st_


def close(tmp_path, at, prev, reason="SCORED", evidence=None, mid="close"):
    return s1_ack(tmp_path, mid, "S1-CLOSE-ACK", at, prev=prev, reason=reason,
                  evidence_sha256=evidence or "0" * 64)


def close_line(tr, prev, reason="SCORED", evidence=None) -> str:
    """The exact F7.5 CLOSE line, written by hand (token() refuses while the trial refuses or is closed)."""
    vals = {"trial_id": tr.trial_id, "bundle_sha256": tr.bundle, "prev": prev, "reason": reason,
            "evidence_sha256": evidence or "0" * 64}
    return "S1-CLOSE-ACK " + " ".join(f"{n}={vals[n]}" for n in t.ACK_FIELDS["S1-CLOSE-ACK"])


def post_raw(root, mid, sender, body, created):
    """A message from any sender (E4.2 boundary cases), into the test's tmp mailbox only."""
    con = sqlite3.connect(mb(root))
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)",
                (mid, sender, "claude", "experiments-prereg", body, created.timestamp()))
    con.commit()
    con.close()


@pytest.mark.parametrize("case", ["stale-prev-score-refused", "no-automatic-blocked-invalid-withdrawal"])
def test_nvs_fork_stale_close_refused(tmp_path, monkeypatch, case):                       # row 480 (CL-A1)
    no_coordination_writes(monkeypatch)
    st_ = nvs_fork(tmp_path)
    close(tmp_path, st_["t0"] + timedelta(days=3, hours=2), prev="score-ack")
    tr = the_trial(tmp_path)
    assert tr.closed is None                                           # the trial stays open
    assert any("prev is not the latest ACK 'acq-late'" in p for p in tr.problems)
    with pytest.raises(SystemExit, match=r"refuse and escalate"):
        t.open_trial(mb(tmp_path))
    if case == "no-automatic-blocked-invalid-withdrawal":
        assert not (tmp_path / "s1_out" / "blocked.json").exists()
        rows = j.read_trial(tr.trial_id, tr.genesis, mb(tmp_path))
        assert all(x.kind != "TRIAL-INVALID" for x in rows)
        assert [a.fields.get("reason") for a in t.scan(mb(tmp_path)) if a.kind == "S1-CLOSE-ACK"] == ["SCORED"]


def test_nvs_fork_withdrawn_names_latest_acquire(tmp_path, monkeypatch):                  # row 481 (CL-A2)
    no_coordination_writes(monkeypatch)
    st_ = nvs_fork(tmp_path)
    tr0 = the_trial(tmp_path)                                         # (fix round 1, M-3: C1.1 chronology)
    assert tr0.latest.mailbox_id == "acq-late"                       # rank-last would be the SCORE-ACK
    line = t.token("S1-CLOSE-ACK", tmp_path, mailbox=mb(tmp_path), reason="SCORED", evidence_sha256="0" * 64)
    assert t.parse_ack_line(line)[1]["prev"] == "acq-late"
    ev = t.close_evidence("WITHDRAWN", withdrawal=WITHDRAWAL)          # the issuance evidence (fixture only)
    close(tmp_path, st_["t0"] + timedelta(days=3, hours=2), prev="acq-late", reason="WITHDRAWN", evidence=ev)
    tr = the_trial(tmp_path)
    assert tr.closed is not None and tr.closed.fields["prev"] == "acq-late"
    assert tr.closed.fields["evidence_sha256"] == c.sha256_bytes(WITHDRAWAL.encode("utf-8"))


@pytest.mark.parametrize("case", ["scored-after-score", "invalid-after-prereg", "withdrawn-after-acquire"])
def test_normal_chain_close_unchanged(tmp_path, monkeypatch, case):                       # row 482 (CL-A3)
    """C1.4: in a valid normal chain chronology = chain rank, so the verdicts are the rank reading's."""
    no_coordination_writes(monkeypatch)
    kw = {"scored-after-score": {}, "invalid-after-prereg": {"final": False},
          "withdrawn-after-acquire": {"upto": "after-final"}}[case]
    st_ = s1_state(tmp_path, START, score_ready=True, **kw)
    tr0 = the_trial(tmp_path)
    by_rank = ([tr0.audit] + [tr0.acks[k] for k in t.CHAIN[1:] if k in tr0.acks])[-1]
    by_time = max([tr0.audit] + list(tr0.acks.values()), key=lambda a: a.created)
    assert by_rank.mailbox_id == by_time.mailbox_id                    # the derivation, observed
    reason = {"scored-after-score": "SCORED", "invalid-after-prereg": "INVALID",
              "withdrawn-after-acquire": "WITHDRAWN"}[case]
    close(tmp_path, st_["now"] + timedelta(days=1), prev=by_time.mailbox_id, reason=reason)
    assert the_trial(tmp_path).closed is not None


REASONS = ("SCORED", "WITHDRAWN", "INVALID")                         # NOP-1: every reason refuses alike


@pytest.mark.parametrize("reason", REASONS)
@pytest.mark.parametrize("case", ["created-tie", "invalid-chain-candidate", "duplicate-before-close"])
def test_ambiguous_or_invalid_predecessor_refuses(tmp_path, monkeypatch, case, reason):  # row 483 (CL-A4)
    """C1.2 kept exactly (NOP-1): no reason-specific exemption - a SCORED, WITHDRAWN or INVALID CLOSE naming either
    candidate is refused and escalated; no predecessor is chosen, nothing is withdrawn, invented or deleted."""
    no_coordination_writes(monkeypatch)
    if case == "duplicate-before-close":                              # (fix round 1, review I-1): a normal
        st_ = s1_state(tmp_path, START, score_ready=True)               # chain ACQUIRE, SCORE, then a second
        st_["t0"] = st_["now"] - timedelta(days=3)                      # ACQUIRE-ACK, then the CLOSE naming SCORE
    else:
        st_ = nvs_chain(tmp_path)                                      # SCORE-ACK "score-ack" at t0 + 3 d
    tr = the_trial(tmp_path)
    if case == "duplicate-before-close":
        s1_ack(tmp_path, "acq-dup", "S1-ACQUIRE-ACK", st_["t0"] + timedelta(days=3, hours=1))
        assert t.scan(mb(tmp_path))[-1].created > tr.acks["S1-SCORE-ACK"].created
    elif case == "created-tie":                                         # O-C1: exact equality of persisted created
        s1_ack(tmp_path, "acq-tie", "S1-ACQUIRE-ACK", st_["t0"] + timedelta(days=3))
        assert t.scan(mb(tmp_path))[-1].created == tr.acks["S1-SCORE-ACK"].created
    else:                                                             # a candidate before X that is not chain-valid
        s1_ack(tmp_path, "acq-bad", "S1-ACQUIRE-ACK", st_["t0"] + timedelta(days=3, hours=1),
               bundle_sha256="0" * 64)
    n_rows = len(j.read_trial(tr.trial_id, tr.genesis, mb(tmp_path)))
    other = {"created-tie": "acq-tie", "invalid-chain-candidate": "acq-bad", "duplicate-before-close": "acq-dup"}[case]
    for prev in ("score-ack", other):
        con = sqlite3.connect(mb(tmp_path))
        con.execute("DELETE FROM messages WHERE id='close'")
        con.commit()
        con.close()
        s1_mailbox(tmp_path, "close", close_line(tr, prev, reason), st_["t0"] + timedelta(days=3, hours=2))
        trx = the_trial(tmp_path)
        assert trx.closed is None and any("escalate" in p and "C1.2" in p for p in trx.problems), trx.problems
        with pytest.raises(SystemExit, match=r"refuse and escalate"):
            t.open_trial(mb(tmp_path))
    assert len(j.read_trial(tr.trial_id, tr.genesis, mb(tmp_path))) == n_rows   # no INVALID, nothing written
    assert {a.mailbox_id for a in t.scan(mb(tmp_path)) if a.kind == "S1-ACQUIRE-ACK"} == \
        ({"acq-ack", other} if case == "duplicate-before-close" else {other})   # kept, never deleted


@pytest.mark.parametrize("case", ["non-official-ack-ignored", "malformed-attributed-refuses",
                                  "unattributable-malformed-not-this-trials"])
def test_close_chronology_attribution_boundaries(tmp_path, monkeypatch, case):           # row 483 (NOP-1, E4.1-E4.3)
    """NOP-1's E4.1-E4.3 boundaries of the C1 candidate set: a chain-ACK-shaped line outside the official channel is
    no candidate (E4.2: the CLOSE naming the official latest closes); an official MALFORMED line naming this trial,
    created before the CLOSE, makes the predecessor chronology unestablishable (C1.2: refuse and escalate - fail
    closed, S1 never picks a predecessor around it); an unattributable malformed line names no trial, so it is no
    candidate of this trial (its E4.3 refusal of every trial-bound command is unchanged)."""
    no_coordination_writes(monkeypatch)
    st_ = nvs_chain(tmp_path)
    tr = the_trial(tmp_path)
    between = st_["t0"] + timedelta(days=3, hours=1)
    acq = (f"S1-ACQUIRE-ACK trial_id={tr.trial_id} bundle_sha256={tr.bundle} prev=prereg-ack "
           + " ".join(f"{n}={'0' * 64}" for n in ("collector_sha256", "final_plan_sha256", "prereg_sha256",
                                                    "attest_stop_sha256"))
           + f" journal_seq=1 journal_head_sha256={'0' * 64} stop_line_sha256={'0' * 64}")
    if case == "non-official-ack-ignored":
        post_raw(tmp_path, "peer", "claude", acq, between)             # E4.2: another sender, never a candidate
    elif case == "malformed-attributed-refuses":
        s1_mailbox(tmp_path, "bad", f"S1-ACQUIRE-ACK trial_id={tr.trial_id} broken=1", between)
    else:
        s1_mailbox(tmp_path, "bad", "S1-ACQUIRE-ACK broken=1", between)
    s1_mailbox(tmp_path, "close", close_line(tr, "score-ack"), st_["t0"] + timedelta(days=3, hours=2))
    trx = the_trial(tmp_path)
    if case == "malformed-attributed-refuses":
        assert trx.closed is None and any("C1.2" in p and "escalate" in p for p in trx.problems), trx.problems
    else:
        assert trx.closed is not None and trx.closed.mailbox_id == "close"
    if case == "unattributable-malformed-not-this-trials":
        with pytest.raises(SystemExit, match=r"unattributable malformed official ACK line"):
            t.open_trial(mb(tmp_path))


@pytest.mark.parametrize("prev", ["score-ack", "acq-at-close"])
def test_close_candidate_strictly_before_boundary(tmp_path, monkeypatch, prev):          # row 483 (fix 1, M-2)
    """H2 fix round 1 (review M-2; C1.1 "created STRICTLY before X"): a chain ACK created at exactly the CLOSE's
    persisted `created` is no candidate - a CLOSE naming the latest ACK created before it (the SCORE-ACK) closes,
    the equal-instant ACK is an escalation of the closed trial only; a CLOSE naming the equal-instant ACK refuses."""
    no_coordination_writes(monkeypatch)
    st_ = nvs_chain(tmp_path)
    tr = the_trial(tmp_path)
    x_at = st_["t0"] + timedelta(days=3, hours=1)
    s1_ack(tmp_path, "acq-at-close", "S1-ACQUIRE-ACK", x_at)
    s1_mailbox(tmp_path, "close", close_line(tr, prev), x_at)
    acks = {a.mailbox_id: a for a in t.scan(mb(tmp_path))}
    assert acks["close"].created == acks["acq-at-close"].created     # exact equality of the persisted values
    trx = the_trial(tmp_path)
    if prev == "score-ack":
        assert trx.closed is not None and trx.closed.mailbox_id == "close"
        assert any("acq-at-close created after the closure" in p for p in trx.problems), trx.problems
    else:
        assert trx.closed is None
        assert any("prev is not the latest ACK 'score-ack' created before it" in p for p in trx.problems)


@pytest.mark.parametrize("case", ["ack-after-closure", "second-close-after-closure"])
def test_first_valid_close_monotone(tmp_path, monkeypatch, case):                         # row 484 (CL-A5)
    no_coordination_writes(monkeypatch)
    st_ = nvs_chain(tmp_path)
    close(tmp_path, st_["t0"] + timedelta(days=5), prev="score-ack", mid="close-1")
    first = the_trial(tmp_path).closed
    assert first is not None
    tr = the_trial(tmp_path)                                           # token() refuses on a closed trial, so the
    if case == "ack-after-closure":                                    # issuer-shaped lines are written by hand
        vals = {"trial_id": tr.trial_id, "bundle_sha256": tr.bundle, "prev": tr.acks["S1-PREREG-ACK"].mailbox_id,
                "journal_seq": "1", "journal_head_sha256": j.read_trial(tr.trial_id, tr.genesis, mb(tmp_path))[0].sha}
        line = "S1-ACQUIRE-ACK " + " ".join(f"{n}={vals.get(n, '0' * 64)}" for n in t.ACK_FIELDS["S1-ACQUIRE-ACK"])
        s1_mailbox(tmp_path, "acq-after", line, st_["t0"] + timedelta(days=6))
    else:
        s1_mailbox(tmp_path, "close-2", close_line(tr, "score-ack", "WITHDRAWN"), st_["t0"] + timedelta(days=6))
    tr = the_trial(tmp_path)
    assert tr.closed.mailbox_id == first.mailbox_id                    # never re-opened
    assert any("escalate (the trial stays closed, E3.4)" in p for p in tr.problems)


def issue_close_scored(root, at, *, mailbox_root=None):
    """PROCEDURAL-MODEL issuer (O-C2; test-side only, never product), performing Codex 59953cfd NOP-5's exact checks
    against the trial's OWN root `root` (the mailbox of `mailbox_root`, default `root`). Any failed check: None, no
    line, nothing sent. Not a production issuer guard; proves no future compliance.
    1. Bind the official trial/AUDIT identity (the unique open trial, no refusal problems; the root's plan.json names
       it) and the verified score STAGE-INTENT, STAGE-PREPARED and STAGE-CREATED rows of ONE operation (same op; the
       CREATED row carries the PREPARED detail).
    2. sha256 of the RAW <root>/s1_staging/<trial>/score/prepared.json equals the PREPARED detail; the commitment's
       trial_id, stage=score, kind and op match the journal operation.
    3. Read <root>/s1_out/score/s1.json as raw published bytes; the committed member hash equals sha256(those bytes);
       then close_evidence("SCORED", score_record=those bytes). prepared.json is never the evidence, the score JSON is
       never re-serialized, and no other trial's or root's file is substituted."""
    root, mroot = Path(root), Path(mailbox_root or root)
    trs = [x for x in t.trials(t.scan(mb(mroot))).values() if x.closed is None]
    if len(trs) != 1 or trs[0].problems:                                       # 1. the official trial / AUDIT
        return None
    tr = trs[0]
    try:
        if json.loads((root / "s1_out" / "plan.json").read_bytes()).get("trial_id") != tr.trial_id:
            return None                                                        # (not this trial's root)
        rows = j.read_trial(tr.trial_id, tr.genesis, mb(mroot))
    except (OSError, ValueError, AttributeError, j.JournalError):
        return None
    m = sg.stage_rows(rows, "score")
    if None in m.values() or len({m["intent"].op, m["prepared"].op, m["created"].op}) != 1 \
            or m["created"].detail != m["prepared"].detail:
        return None                                                            # incomplete stage / another op
    try:                                                                       # 2. the raw commitment bytes
        blob = (sg.staging_dir(root, tr.trial_id, "score") / "prepared.json").read_bytes()
        if c.sha256_bytes(blob) != m["prepared"].detail:
            return None
        com = json.loads(blob)
        if (com.get("trial_id"), com.get("stage"), com.get("kind"), com.get("op")) != \
                (tr.trial_id, "score", sg.spec("score")["kind"], m["prepared"].op):
            return None
        data = (root / "s1_out" / "score" / "s1.json").read_bytes()           # 3. the raw published bytes
    except (OSError, ValueError, AttributeError):
        return None
    if (com.get("members") or {}).get("score/s1.json") != c.sha256_bytes(data):
        return None
    return close(mroot, at, prev=tr.latest.mailbox_id, evidence=t.close_evidence("SCORED", score_record=data))


ISSUER_CASES = ("record-absent", "hash-mismatch", "hash-match", "prepared-mismatch", "prepared-without-created",
                "wrong-trial", "wrong-root", "wrong-op", "unreadable-source")


@pytest.mark.parametrize("case", ISSUER_CASES)
def test_scored_close_issuer_validation_no_send(tmp_path, monkeypatch, case):            # row 485 (CL-A6)
    """PROCEDURAL-MODEL TEST ONLY (O-C2): it exercises the trial/root committed-record identity and the actual byte
    hash. It does not establish an enforced production issuer guard or prove future Codex compliance."""
    no_coordination_writes(monkeypatch)
    st_ = nvs_chain(tmp_path)
    out = tmp_path / "s1_out"
    s1p = out / "score" / "s1.json"
    if case == "prepared-without-created":                             # crash after PREPARED, before publication
        real_pub = sg._publish_one
        monkeypatch.setattr(sg, "_publish_one", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt("crash")))
        with _Clock(st_["now"]), pytest.raises(KeyboardInterrupt, match=r"crash"):
            r.score(tmp_path, "score-ack")
        monkeypatch.setattr(sg, "_publish_one", real_pub)
    elif case != "record-absent":
        with _Clock(st_["now"]):
            ok(r.score, tmp_path, "score-ack")
    tid = the_trial(tmp_path).trial_id
    issuer_root = tmp_path
    if case == "hash-mismatch":                                        # the root's record is not the committed one
        s1p.write_bytes(s1p.read_bytes() + b" ")
    elif case == "prepared-mismatch":
        p = sg.staging_dir(tmp_path, tid, "score") / "prepared.json"
        p.write_bytes(p.read_bytes() + b" ")
    elif case == "wrong-trial":                                        # the root's plan names another trial
        plan = json.loads((out / "plan.json").read_bytes())
        (out / "plan.json").write_text(json.dumps(dict(plan, trial_id="0" * 8 + "-0000-4000-8000-" + "0" * 12)),
                                       encoding="utf-8")
    elif case == "wrong-root":                                         # another root: never substitute this one's
        issuer_root = tmp_path / "other-root"
        (issuer_root / "s1_out").mkdir(parents=True)
        shutil.copyfile(out / "plan.json", issuer_root / "s1_out" / "plan.json")
    elif case == "wrong-op":                                           # the CREATED row of another operation
        real_read = j.read_trial
        monkeypatch.setattr(j, "read_trial", lambda *a, **kw: [
            dataclasses.replace(x, op=j.new_nonce()) if x.kind == "STAGE-CREATED" and x.subject == "stage/score"
            else x for x in real_read(*a, **kw)])
    elif case == "unreadable-source":
        real_rb = Path.read_bytes
        monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(PermissionError(13, "denied"))
                            if self == s1p else real_rb(self))
    before = len(t.scan(mb(tmp_path)))
    line = issue_close_scored(issuer_root, st_["now"] + timedelta(hours=1), mailbox_root=tmp_path)
    after = t.scan(mb(tmp_path))
    if case == "hash-match":
        assert line is not None and len(after) == before + 1
        assert after[-1].kind == "S1-CLOSE-ACK"
        assert after[-1].fields["evidence_sha256"] == c.sha256_bytes(s1p.read_bytes())
        assert the_trial(tmp_path).closed is not None
    else:
        assert line is None and len(after) == before                   # no CLOSE line, nothing sent
        assert the_trial(tmp_path).closed is None


@pytest.mark.parametrize("case", ["closes-every-root", "rootless-lookup", "no-reopen-from-filesystem"])
def test_issued_close_runtime_lifecycle(tmp_path, monkeypatch, case):                     # row 486 (CL-A7)
    no_coordination_writes(monkeypatch)
    st_ = nvs_chain(tmp_path)
    with _Clock(st_["now"]):
        ok(r.score, tmp_path, "score-ack")
    h = c.sha256_bytes((tmp_path / "s1_out" / "score" / "s1.json").read_bytes())
    close(tmp_path, st_["now"] + timedelta(hours=1), prev="score-ack", evidence=h)
    if case == "closes-every-root":
        other = tmp_path / "other-root"
        other.mkdir()
        for root in (tmp_path, other):
            with pytest.raises(SystemExit, match=r"zero open trials"):
                t.gate(root, "probe", mailbox=mb(tmp_path))
    elif case == "rootless-lookup":
        with pytest.raises(SystemExit, match=r"zero open trials"):
            t.open_trial(mb(tmp_path))
    else:
        (tmp_path / "s1_out" / "score" / "s1.json").write_bytes(b"{}")      # S1 never reopens from files
        shutil.rmtree(tmp_path / "s1_out" / "final_snapshot")
        assert the_trial(tmp_path).closed is not None
        with pytest.raises(SystemExit, match=r"zero open trials"):
            t.open_trial(mb(tmp_path))


def test_trusted_issuer_residual_wrong_hash_closes(tmp_path, monkeypatch):                # row 487 (CL-A8)
    """RESIDUAL CHARACTERIZATION (C2.2; NOT runtime detection, never a refusal test): an official, otherwise valid
    CLOSE SCORED with a hex-valid WRONG evidence hash closes the trial at runtime (the trusted-issuer residual)."""
    no_coordination_writes(monkeypatch)
    st_ = nvs_chain(tmp_path)
    with _Clock(st_["now"]):
        ok(r.score, tmp_path, "score-ack")
    right = c.sha256_bytes((tmp_path / "s1_out" / "score" / "s1.json").read_bytes())
    wrong = c.sha256_bytes(b"a different record")
    assert wrong != right
    close(tmp_path, st_["now"] + timedelta(hours=1), prev="score-ack", evidence=wrong)
    assert the_trial(tmp_path).closed is not None                      # closes: the disclosed residual
