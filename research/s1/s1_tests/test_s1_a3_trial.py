"""Addendum 3 rev 5 F6.1-F6.3, F6.5, F7.1, F7.5, F9 (trial identity, ACK grammar and chain, CLOSE, write_plan), with
Erratum 1 E3.4 (BLOCKED CLOSE, monotone closure, no recomputation) and E4 (official-channel candidates, E4.3
attribution). Behavioural RED against the Task 4 stub (s1_evidence/a3/t4_red.txt).

Mailbox: only the conftest autouse tmp mailbox (<tmp_path>/mailbox.sqlite3, the file s1_common.MAILBOX points at
and the code under test reads). Never the real mailbox; mailbox.py is never imported. No network, live DB or
scheduler. ACK lines are synthetic test data. Every expected refusal is asserted with pytest.raises(<exact type>,
match=<reason>) or an explicit assert (Task 15 B3)."""
import inspect
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_trial as t
from conftest import s1_mailbox_init

UTC = timezone.utc
START = datetime(2026, 11, 16, 14, 30, tzinfo=UTC)
T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
BUNDLE = "b" * 64
H = "1" * 64
UUID4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


class _clock:
    def __init__(self, at):
        self.at = at

    def __enter__(self):
        self.old = c.now_utc
        c.now_utc = lambda: self.at

    def __exit__(self, *exc):
        c.now_utc = self.old


def post(mb, mid, body, at, sender="codex", recipient="claude", key="experiments-prereg"):
    """Insert one message into the conftest tmp mailbox (never the coordination mailbox)."""
    assert mb == c.MAILBOX, "tests write only the conftest tmp mailbox"
    con = sqlite3.connect(mb)
    try:
        con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", (mid, sender, recipient, key, body,
                                                                       at.timestamp()))
        con.commit()
    finally:
        con.close()


def n_messages(mb) -> int:
    con = sqlite3.connect(f"file:{mb.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    finally:
        con.close()


def line(kind, **f):
    return " ".join([kind] + [f"{n}={f[n]}" for n in t.ACK_FIELDS[kind]])


def audit(tid, bundle=BUNDLE):
    return line("S1-AUDIT-ACK", trial_id=tid, bundle_sha256=bundle, collector_sha256=H, plan_sha256=H,
                start=START.isoformat())


def opening(tid, prev, seq=1, head=H, bundle=BUNDLE):
    return line("S1-OPENING-ACK", trial_id=tid, bundle_sha256=bundle, prev=prev, plan_sha256=H,
                audit_manifest_sha256=H, opening_slot="slot/20261113T214500Z", opening_seal_sha256=H,
                opening_receipt_sha256=H, journal_seq=seq, journal_head_sha256=head, evidence_manifest_sha256=H)


def close(tid, prev, bundle=BUNDLE, reason="WITHDRAWN", evidence=H):
    return line("S1-CLOSE-ACK", trial_id=tid, bundle_sha256=bundle, prev=prev, reason=reason,
                evidence_sha256=evidence)


def tid():
    return str(uuid.uuid4())


def stage_row(trial, mb, at):
    """One real journal row for `trial` (STAGE-INTENT stage/audit), appended through s1_journal.append."""
    return j.append(trial.trial_id, trial.genesis,
                    j.Request("STAGE-INTENT", "stage/audit", "1" * 32, "2" * 32, detail=H),
                    lambda rows, con: j.Context(stage_gate=lambda r_, g: None), mailbox=mb,
                    clock=lambda: at).row


def plan_args():
    return START, "2026-11-13", ["A"], "2026-03-17"


# ---------------------------------------------------------------- F6.2 / F9: write_plan (rows 140, 168, 170, 253)
def test_write_plan_records_a_uuid4_trial_id_and_makes_no_request_callback_or_journal_write(tmp_path):
    mb = c.MAILBOX
    with _clock(T0):
        p = k.write_plan(tmp_path, *plan_args())
    plan = json.loads(p.read_text(encoding="utf-8"))
    assert re.fullmatch(UUID4, plan["trial_id"]), plan["trial_id"]      # canonical lowercase uuid4
    assert uuid.UUID(plan["trial_id"]).version == 4
    assert j.read_all(mb) == [] and n_messages(mb) == 0                 # no journal write, no message
    with _clock(T0):
        q = k.write_plan(tmp_path / "other", *plan_args())
    assert json.loads(q.read_text(encoding="utf-8"))["trial_id"] != plan["trial_id"]   # generated per plan


@pytest.mark.parametrize("case", ["open", "outage"])
def test_write_plan_refuses_with_an_open_trial_or_an_unreadable_mailbox(tmp_path, monkeypatch, case):
    mb = c.MAILBOX
    a = tid()
    post(mb, "a1", audit(a), T0)
    if case == "outage":
        monkeypatch.setattr(c, "MAILBOX", tmp_path / "gone.sqlite3")
    reason = f"trial {a} is open" if case == "open" else "write_plan refused: mailbox unreadable"
    with _clock(T0), pytest.raises(t.Refusal, match=reason):
        k.write_plan(tmp_path, *plan_args())
    assert not (tmp_path / "s1_out" / "plan.json").exists()
    assert not (tmp_path / "gone.sqlite3").exists()                     # mode=ro: never created


# ---------------------------------------------------------------- F6.1 grammar (row 138)
@pytest.mark.parametrize("kind", sorted(t.ACK_FIELDS))
def test_ack_lines_have_exactly_the_listed_fields_in_order(kind):
    vals = {n: (str(uuid.uuid4()) if n == "trial_id" else "1" if n == "journal_seq" else START.isoformat()
                if n == "start" else "slot/20261113T214500Z" if n == "opening_slot" else "SCORED" if n == "reason"
                else "m-1" if n == "prev" else H) for n in t.ACK_FIELDS[kind]}
    got_kind, got = t.parse_ack_line(line(kind, **vals))
    assert got_kind == kind and list(got) == list(t.ACK_FIELDS[kind]) and got == vals


@pytest.mark.parametrize("dev", ["extra", "missing", "reordered", "bad-hex", "bad-uuid"])
def test_ack_line_deviation_refuses(dev):
    good = audit(tid())
    bad = {"extra": good + " note=x", "missing": good.rsplit(" ", 1)[0],
           "reordered": good.replace(f"collector_sha256={H} plan_sha256={H}", f"plan_sha256={H} collector_sha256={H}"),
           "bad-hex": good.replace(f"bundle_sha256={BUNDLE}", "bundle_sha256=XYZ"),
           "bad-uuid": good.replace(good.split(" ")[1], "trial_id=S1")}[dev]
    why = {"extra": "not exactly", "missing": "not exactly", "reordered": "not exactly",
           "bad-hex": "bundle_sha256 is not a 64-hex", "bad-uuid": "trial_id is not a uuid4"}[dev]
    with pytest.raises(ValueError, match=why):
        t.parse_ack_line(bad)


# ---------------------------------------------------------------- F6.3 open trial (row 143)
@pytest.mark.parametrize("case", ["one", "zero", "two", "outage"])
def test_open_trial_cases(tmp_path, monkeypatch, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    if case in ("one", "two"):
        post(mb, "a1", audit(a), T0)
    if case == "two":
        post(mb, "a2", audit(tid()), T0 + timedelta(minutes=1))
    if case == "outage":
        mb = tmp_path / "missing.sqlite3"
    if case == "one":
        tr = t.open_trial(mb)
        assert (tr.trial_id, tr.bundle, tr.genesis) == (a, BUNDLE, j.line_sha256(audit(a)))
        assert tr.audit.mailbox_id == "a1" and tr.latest is tr.audit and tr.problems == []
        return
    reason = {"zero": "zero open trials", "two": "2 open trials", "outage": "mailbox unreadable"}[case]
    with pytest.raises(t.Refusal, match=reason):
        t.open_trial(mb)


def test_duplicate_trial_id_refuses_every_trial_with_that_id(tmp_path):            # row 141
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    post(mb, "a2", audit(a).replace(f"plan_sha256={H}", "plan_sha256=" + "2" * 64), T0 + timedelta(minutes=1))
    with pytest.raises(t.Refusal, match=f"trial_id {a} is on 2 AUDIT-ACKs"):
        t.open_trial(mb)


# ---------------------------------------------------------------- F7.1 chain (rows 148, 149)
@pytest.mark.parametrize("case", ["distinct", "identical"])
def test_second_ack_of_a_kind_refuses_even_byte_identical(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    post(mb, "o1", opening(a, "a1"), T0 + timedelta(hours=1))
    second = opening(a, "a1") if case == "identical" else opening(a, "a1", head="3" * 64)
    post(mb, "o2", second, T0 + timedelta(hours=2))
    with pytest.raises(t.Refusal, match="2 S1-OPENING-ACK"):
        t.open_trial(mb)


@pytest.mark.parametrize("case", ["ok", "prev-not-predecessor", "wrong-bundle", "no-predecessor"])
def test_ack_chain_prev_is_the_predecessor_mailbox_id(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    if case != "no-predecessor":
        post(mb, "o1", opening(a, "a1", bundle="9" * 64 if case == "wrong-bundle" else BUNDLE), T0 + timedelta(hours=1))
    run = line("S1-RUN-ACK", trial_id=a, bundle_sha256=BUNDLE, prev="a1" if case == "prev-not-predecessor" else "o1",
               runner_sha256=H, plan_sha256=H, audit_manifest_sha256=H, attest_start_sha256=H, opening_seal_sha256=H,
               opening_books_sha256=H, start=START.isoformat(), journal_seq=1, journal_head_sha256=H)
    post(mb, "r1", run, T0 + timedelta(hours=2))
    if case == "ok":
        tr = t.open_trial(mb)
        assert tr.acks["S1-RUN-ACK"].mailbox_id == "r1" and tr.latest.mailbox_id == "r1"
        return
    reason = {"prev-not-predecessor": "prev 'a1' is not the S1-OPENING-ACK 'o1'",
              "wrong-bundle": "S1-OPENING-ACK o1: bundle chain broken",
              "no-predecessor": "S1-RUN-ACK r1: no S1-OPENING-ACK predecessor"}[case]
    with pytest.raises(t.Refusal, match=reason):
        t.open_trial(mb)


@pytest.mark.parametrize("case", ["equal-pred", "before-row"])
def test_ack_created_not_after_its_predecessor_or_referenced_row_refuses(tmp_path, case):   # row 139
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    row = stage_row(t.open_trial(mb), mb, T0 + timedelta(hours=2))
    when = T0 if case == "equal-pred" else T0 + timedelta(hours=1)
    post(mb, "o1", opening(a, "a1", seq=1, head=row.sha), when)
    if case == "equal-pred":
        with pytest.raises(t.Refusal, match="created not after its predecessor"):
            t.open_trial(mb)
        return
    tr = t.open_trial(mb)
    rows = j.read_trial(a, tr.genesis, mb)
    assert any("created not after the journal row it references" in p for p in t.check_journal(tr, rows))
    with _clock(T0 + timedelta(days=1)), pytest.raises(t.Refusal, match="created not after the journal row"):
        t.verify_ack(tr, rows, "S1-OPENING-ACK", "o1", {})


@pytest.mark.parametrize("case", ["ok", "wrong-head", "seq-beyond", "forked"])
def test_journal_seq_and_head_must_be_extended_without_fork(tmp_path, case):           # row 150 (P35 killer)
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    row = stage_row(t.open_trial(mb), mb, T0)
    head = {"ok": row.sha, "wrong-head": "4" * 64, "seq-beyond": row.sha, "forked": row.sha}[case]
    post(mb, "o1", opening(a, "a1", seq=2 if case == "seq-beyond" else 1, head=head), T0 + timedelta(hours=1))
    tr = t.open_trial(mb)
    rows = j.read_trial(a, tr.genesis, mb)
    if case == "forked":
        rows = [j.Row(**dict(j.parse_line(rows[0].line), detail="5" * 64), line=rows[0].line.replace(H, "5" * 64),
                      mailbox_id="x", created=rows[0].created)]
    probs = t.check_journal(tr, rows)
    assert (probs == []) == (case == "ok"), probs
    with _clock(T0 + timedelta(days=1)):
        if case == "ok":
            assert t.verify_ack(tr, rows, "S1-OPENING-ACK", "o1", {"journal_head_sha256": row.sha}).mailbox_id == "o1"
            return
        reason = {"wrong-head": "journal head at seq 1 differs", "seq-beyond": "journal_seq 2 beyond the journal",
                  "forked": "journal head at seq 1 differs"}[case]
        with pytest.raises(t.Refusal, match=reason):                # verify_ack refuses on check_journal problems
            t.verify_ack(tr, rows, "S1-OPENING-ACK", "o1", {})


# ---------------------------------------------------------------- F7.5 CLOSE (rows 54, 158, 159)
@pytest.mark.parametrize("case", ["valid", "prev-not-latest", "before-audit", "wrong-bundle", "duplicate"])
def test_close_refused_cases(tmp_path, case):
    """Row 158 (E4.4): official CLOSE candidates only; wrong-role/key lines are no candidates (rows 275-277)."""
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    post(mb, "o1", opening(a, "a1"), T0 + timedelta(hours=1))
    at = T0 - timedelta(hours=1) if case == "before-audit" else T0 + timedelta(hours=2)
    post(mb, "c1", close(a, "a1" if case in ("prev-not-latest", "duplicate") else "o1",
                         bundle="9" * 64 if case == "wrong-bundle" else BUNDLE), at)
    if case == "duplicate":                         # fix round 1: a duplicate before any valid CLOSE (both refused)
        post(mb, "c2", close(a, "a1"), T0 + timedelta(hours=3))
    tr = t.trials(t.scan(mb))[a]
    if case == "valid":
        assert tr.closed is not None and tr.closed.mailbox_id == "c1" and tr.problems == []
        with pytest.raises(t.Refusal, match="zero open trials"):
            t.open_trial(mb)
        return
    reason = {"prev-not-latest": "prev is not the latest ACK 'o1'", "before-audit": "before the AUDIT-ACK",
              "wrong-bundle": "bundle differs", "duplicate": "2 CLOSE-ACKs"}[case]
    assert tr.closed is None                                          # the trial stays open ...
    with pytest.raises(t.Refusal, match=reason):                      # ... and its commands refuse
        t.open_trial(mb)
    with pytest.raises(t.Refusal, match=f"trial {a} is open"):        # and it still blocks a new plan (F9)
        t.require_no_open_trial(mb)


def test_closed_is_layered_on_the_journal_state(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    tr = t.open_trial(mb)
    assert t.state(tr, []) == "ACTIVE"
    post(mb, "c1", close(a, "a1"), T0 + timedelta(hours=1))
    closed = t.trials(t.scan(mb))[a]
    assert closed.closed is not None and t.state(closed, []) == "CLOSED"


@pytest.mark.parametrize("kind", ["SCORED", "INVALID", "WITHDRAWN"])
def test_close_evidence_hashes(kind):
    rows = [j.Row(trial_id="x", seq=1, prev="0" * 64, kind="TRIAL-INVALID", subject="reason/LOST", detail=H,
                  op="1" * 32, actor="2" * 32, at="2026-11-02T12:00:00.000000+00:00", line="LINE-1", mailbox_id="m",
                  created=1.0)]
    got = t.close_evidence(kind, score_record=b"{score}", rows=rows, withdrawal="operator withdrew")
    want = {"SCORED": c.sha256_bytes(b"{score}"), "INVALID": j.line_sha256("LINE-1"),
            "WITHDRAWN": c.sha256_bytes("operator withdrew".encode("utf-8"))}[kind]
    assert got == want


# ---------------------------------------------------------------- F6.5 other trials (row 146; B7)
def test_other_trials_acks_and_rows_never_count_even_with_the_same_bundle(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    old, new = tid(), tid()
    post(mb, "a0", audit(old), T0 - timedelta(days=9))
    old_tr = t.open_trial(mb)
    old_row = stage_row(old_tr, mb, T0 - timedelta(days=9) + timedelta(hours=1))
    post(mb, "o0", opening(old, "a0", head=old_row.sha), T0 - timedelta(days=8))
    post(mb, "c0", close(old, "o0"), T0 - timedelta(days=7))
    post(mb, "a1", audit(new), T0)                                    # same bundle as the old trial
    tr = t.open_trial(mb)
    assert tr.trial_id == new and "S1-OPENING-ACK" not in tr.acks and tr.latest.mailbox_id == "a1"
    rows = j.read_trial(new, tr.genesis, mb)
    assert rows == [] and t.state(tr, rows) == "ACTIVE"                # the old trial's row never counts
    with _clock(T0 + timedelta(days=1)):
        with pytest.raises(t.Refusal, match=f"no S1-OPENING-ACK for trial {new}"):    # o0 is not this trial's
            t.verify_ack(tr, rows, "S1-OPENING-ACK", "o0", {})
        row = stage_row(tr, mb, T0 + timedelta(hours=1))
        post(mb, "o1", opening(new, "a1", head=row.sha), T0 + timedelta(hours=2))
        tr = t.open_trial(mb)
        rows = j.read_trial(new, tr.genesis, mb)
        with pytest.raises(t.Refusal, match="'o0' is not the trial's S1-OPENING-ACK"):
            t.verify_ack(tr, rows, "S1-OPENING-ACK", "o0", {})
        assert t.verify_ack(tr, rows, "S1-OPENING-ACK", "o1", {}).mailbox_id == "o1"


def test_verify_ack_binds_the_expected_fields_and_refuses_a_future_ack(tmp_path):     # F6.1/F7 binding (extra)
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    tr = t.open_trial(mb)
    with _clock(T0 + timedelta(hours=1)):
        assert t.verify_ack(tr, [], "S1-AUDIT-ACK", "a1", {"plan_sha256": H}).mailbox_id == "a1"
        with pytest.raises(t.Refusal, match=r"\['plan_sha256'\] differ from the current artifacts"):
            t.verify_ack(tr, [], "S1-AUDIT-ACK", "a1", {"plan_sha256": "2" * 64})
        with pytest.raises(t.Refusal, match="no S1-RUN-ACK for trial"):
            t.verify_ack(tr, [], "S1-RUN-ACK", None, {})
    with _clock(T0 - timedelta(minutes=1)), pytest.raises(t.Refusal, match="ack is in the future"):
        t.verify_ack(tr, [], "S1-AUDIT-ACK", "a1", {})
    assert t.ack_record(tr.audit) == {"ack_id": "a1", "created_utc": T0.isoformat()}


def test_closed_in_reads_the_closes_on_the_given_connection(tmp_path):               # E2.3 r3 reader (extra)
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    tr = t.open_trial(mb)
    ghost = t.Trial(tid(), BUNDLE, tr.audit, {}, None, [], tr.genesis)
    con = sqlite3.connect(f"file:{mb.as_posix()}?mode=ro", uri=True)
    try:
        assert t.closed_in(con, tr) is False
        assert t.closed_in(con, ghost) is True                        # an unknown trial is never open (fail closed)
        post(mb, "c1", close(a, "a1"), T0 + timedelta(hours=1))
        assert t.closed_in(con, tr) is True
    finally:
        con.close()


def test_token_builds_the_exact_line_and_refuses_without_a_predecessor(tmp_path):    # Task 5 consumer (extra)
    mb = c.MAILBOX
    with _clock(T0):
        k.write_plan(tmp_path, *plan_args())
    out = tmp_path / "s1_out"
    post(mb, "a1", c.audit_token(out), T0 + timedelta(hours=1))
    tr = t.open_trial()
    assert t.parse_ack_line(c.audit_token(out))[1].get("trial_id") == tr.trial_id
    with pytest.raises(t.Refusal, match="no S1-OPENING-ACK for trial"):
        t.token("S1-RUN-ACK", tmp_path)
    with pytest.raises(ValueError, match="journal_seq"):              # no journal row yet: nothing to bind
        t.token("S1-OPENING-ACK", tmp_path, opening_slot="slot/20261113T214500Z", evidence_manifest_sha256=H)
    row = stage_row(tr, mb, T0 + timedelta(hours=2))
    tok = t.token("S1-OPENING-ACK", tmp_path, opening_slot="slot/20261113T214500Z", evidence_manifest_sha256=H)
    kind, f = t.parse_ack_line(tok)
    assert kind == "S1-OPENING-ACK" and f["trial_id"] == tr.trial_id and f["prev"] == "a1"
    assert (f["journal_seq"], f["journal_head_sha256"]) == ("1", row.sha)
    assert f["plan_sha256"] == c.sha256_file(out / "plan.json") and f["opening_receipt_sha256"] == c.ABSENT


# ---------------------------------------------------------------- E4 (rows 275-278)
@pytest.mark.parametrize("case", ["wrong-role-close", "wrong-key-close", "peer-draft", "indented-line", "quoted-line",
                                  "historical-other-trial"])
def test_non_official_lines_are_never_candidates(tmp_path, case):
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    post(mb, "a1", audit(a), T0)
    later = T0 + timedelta(hours=1)
    official = ["a1"]
    if case == "wrong-role-close":
        post(mb, "x1", close(a, "a1"), later, sender="claude")
    elif case == "wrong-key-close":
        post(mb, "x1", close(a, "a1"), later, key="other-key")
    elif case == "peer-draft":                      # an arbitrary draft from a peer, malformed and well-formed lines
        post(mb, "x1", "draft:\n" + close(a, "a1") + "\nS1-OPENING-ACK trial_id=" + a + " junk\nS1-OPENING-ACK junk",
             later, sender="claude", recipient="codex", key="experiments-s1-review")
    elif case == "indented-line":                   # the official channel, but not at line start
        post(mb, "x1", "  " + close(a, "a1"), later)
    elif case == "quoted-line":
        post(mb, "x1", "> " + close(a, "a1"), later)
    else:                                           # another, closed trial's history (official, well formed)
        old = tid()
        post(mb, "a0", audit(old), T0 - timedelta(days=9))
        post(mb, "c0", close(old, "a0"), T0 - timedelta(days=8))
        official = ["a0", "a1", "c0"]
    assert sorted(x.mailbox_id for x in t.scan(mb)) == official      # E4.2: no other line is a candidate
    tr = t.open_trial(mb)                                            # no refusal, no closure
    assert tr.trial_id == a and tr.closed is None and tr.problems == []
    with pytest.raises(t.Refusal, match=f"trial {a} is open"):       # the trial stays open
        t.require_no_open_trial(mb)


@pytest.mark.parametrize("case", ["attributable", "unattributable", "names-another-trial"])
def test_malformed_candidate_refuses_its_own_trial_or_all(tmp_path, case):             # row 278 (E4.3)
    mb = s1_mailbox_init(tmp_path)
    a, b = tid(), tid()
    post(mb, "a1", audit(a), T0)
    post(mb, "b1", audit(b), T0 + timedelta(minutes=1))
    post(mb, "c1", close(a, "a1"), T0 + timedelta(minutes=2))            # trial a closed; b is the open trial
    bad = {"attributable": f"S1-OPENING-ACK trial_id={b} broken", "unattributable": "S1-OPENING-ACK broken",
           "names-another-trial": f"S1-OPENING-ACK trial_id={a} broken"}[case]
    post(mb, "m1", bad, T0 + timedelta(minutes=3))
    trs = t.trials(t.scan(mb))
    if case == "names-another-trial":               # it names a, so b (the open trial) is unaffected
        assert t.open_trial(mb).trial_id == b and trs[b].problems == []
        assert trs[a].problems and trs[a].closed is not None
        return
    reason = {"attributable": f"trial {b}: .*malformed official ACK line in m1 names this trial \\(E4.3\\)",
              "unattributable": r"unattributable malformed official ACK line\(s\) in \['m1'\].*\(E4.3\)"}[case]
    with pytest.raises(t.Refusal, match=reason):
        t.open_trial(mb)
    if case == "attributable":                      # it names b; a different trial is unaffected
        assert trs[b].problems and trs[a].problems == []


def test_attribution_grammar_is_the_e43_grammar():                                    # row 278 (E4.3 r1 grammar)
    u = "3f2b8c1e-5d4a-4b6c-9e7f-0a1b2c3d4e5f"
    assert t.attributed_trial(f"S1-OPENING-ACK trial_id={u} junk") == u
    assert t.attributed_trial(f"S1-OPENING-ACK\ttrial_id={u}\tjunk") == u            # whitespace-separated
    assert t.attributed_trial(f"S1-OPENING-ACK trial_id={u.upper()} junk") is None   # not canonical lowercase
    assert t.attributed_trial(f"S1-OPENING-ACK junk trial_id={u}") is None           # not the second token
    assert t.attributed_trial(f"S1-OPENING-ACK trial_id={u}x") is None               # not exactly a uuid4
    assert t.attributed_trial("S1-OPENING-ACK trial_id=3f2b8c1e-5d4a-1b6c-9e7f-0a1b2c3d4e5f") is None   # not v4


# ---------------------------------------------------------------- E3.4 BLOCKED CLOSE (rows 273, 337)
@pytest.mark.parametrize("case", ["ok", "wrong-prev", "wrong-bundle"])
def test_close_blocked_is_validated_like_every_close(tmp_path, monkeypatch, case):     # row 273 (E3.4 r3)
    """E3.4 r3 (A3-PR1-2): a BLOCKED CLOSE is validated by F7.5 grammar, prev, bundle and channel only, from the
    mailbox alone; S1 never recomputes its evidence (Codex checked it against the trial's own root at issuance).
    `close_evidence` stays the helper Codex uses for h = sha256(canonical({trial_id, reasons}))."""
    mb = s1_mailbox_init(tmp_path)
    a = tid()
    rec = {"trial_id": a, "reasons": ["coverage"]}
    h = t.close_evidence("BLOCKED", blocked_record=rec)
    assert h == c.sha256_bytes(c.canonical(rec))
    on_disk = dict(rec, status="BLOCKED", recorded_utc=T0.isoformat())
    assert h != c.sha256_bytes(c.canonical(on_disk))                  # never the blocked.json file bytes
    post(mb, "a1", audit(a), T0)
    post(mb, "c1", line("S1-CLOSE-ACK", trial_id=a, bundle_sha256="9" * 64 if case == "wrong-bundle" else BUNDLE,
                        prev="zz" if case == "wrong-prev" else "a1", reason="BLOCKED", evidence_sha256=h),
         T0 + timedelta(hours=1))

    def never(*a_, **k_):
        raise AssertionError("S1 recomputed a historical CLOSE's evidence (E3.4)")
    monkeypatch.setattr(t, "close_evidence", never)                   # the reader never recomputes (P21)
    if case == "ok":
        with pytest.raises(t.Refusal, match="zero open trials"):
            t.open_trial(mb)
        assert t.trials(t.scan(mb))[a].closed.fields["reason"] == "BLOCKED"
        return
    reason = {"wrong-prev": "prev is not the latest ACK 'a1'", "wrong-bundle": "bundle differs"}[case]
    with pytest.raises(t.Refusal, match=reason):
        t.open_trial(mb)


def test_two_root_blocked_lifecycle_closure_is_monotone(tmp_path, monkeypatch):       # row 337 (E3.6 r3)
    """Root A BLOCKED -> valid BLOCKED CLOSE -> root B write_plan + AUDIT-ACK: B is the unique open trial and A stays
    closed, rootless and from either root. Both plans come from the real write_plan and both AUDIT-ACKs carry the
    real audit_token; the mailbox is the conftest tmp mailbox (s1_common.MAILBOX)."""
    mb = c.MAILBOX
    root_a, root_b = tmp_path / "A", tmp_path / "B"
    assert list(inspect.signature(t.open_trial).parameters) == ["mailbox"]           # no root parameter exists
    with _clock(T0):
        k.write_plan(root_a, *plan_args())
    out_a = root_a / "s1_out"
    a = c.load_json(out_a / "plan.json")["trial_id"]
    post(mb, "a1", c.audit_token(out_a), T0 + timedelta(hours=1))
    assert t.open_trial().trial_id == a
    reasons = ["coverage"]                                                         # root A is BLOCKED (E3.2)
    (out_a / "blocked.json").write_bytes(c.canonical({"status": "BLOCKED", "reasons": reasons,
                                                      "recorded_utc": (T0 + timedelta(hours=2)).isoformat(),
                                                      "trial_id": a}))
    with _clock(T0 + timedelta(hours=2)), pytest.raises(t.Refusal, match=f"trial {a} is open"):
        k.write_plan(root_b, *plan_args())                                         # A still open: B refused (F9)
    assert not (root_b / "s1_out" / "plan.json").exists()
    h = t.close_evidence("BLOCKED", blocked_record={"trial_id": a, "reasons": reasons})
    post(mb, "ca", line("S1-CLOSE-ACK", trial_id=a, bundle_sha256=c.bundle_sha256(), prev="a1", reason="BLOCKED",
                        evidence_sha256=h), T0 + timedelta(hours=3))
    with pytest.raises(t.Refusal, match="zero open trials"):
        t.open_trial()
    with _clock(T0 + timedelta(hours=4)):
        t.require_no_open_trial()                                                  # B's write_plan precondition
        k.write_plan(root_b, *plan_args())
    out_b = root_b / "s1_out"
    b = c.load_json(out_b / "plan.json")["trial_id"]
    assert b != a
    post(mb, "b1", c.audit_token(out_b), T0 + timedelta(hours=5))

    def check():
        assert t.open_trial().trial_id == b and t.open_trial(mb).trial_id == b    # rootless
        for root in (root_a, root_b):                                              # from either root
            monkeypatch.chdir(root)
            assert t.open_trial().trial_id == b
            f = t.parse_ack_line(t.token("S1-CLOSE-ACK", root, reason="WITHDRAWN", evidence_sha256=H))[1]
            assert (f["trial_id"], f["prev"]) == (b, "b1")
        trs = t.trials(t.scan())
        assert trs[a].closed is not None and trs[a].closed.mailbox_id == "ca" and trs[a].problems == []
        assert trs[b].closed is None and trs[b].problems == []
        assert sorted(x.trial_id for x in trs.values() if x.closed is None) == [b]
        with pytest.raises(t.Refusal, match=f"trial {b} is open"):
            t.require_no_open_trial()
    check()
    (out_a / "blocked.json").unlink()                                              # no local state re-opens A
    check()
    (out_a / "blocked.json").write_bytes(c.canonical({"status": "BLOCKED", "reasons": ["other"], "trial_id": a}))
    check()


@pytest.mark.parametrize("extra", ["repost-identical-close", "later-chain-ack", "second-different-close"])
def test_a_valid_close_is_permanent_whatever_the_mailbox_adds_later(tmp_path, extra):   # E3.4 monotone (fix 1, I1)
    """Controller ruling (Task 4 fix round 1): the first CLOSE, in mailbox order, that validates against the ACKs
    created before it is the trial's closure, permanently. A later CLOSE or ACK for the closed trial is an escalation
    problem of that trial only: it never re-opens it and never refuses another trial's commands. The row-337 setup:
    root A closed (BLOCKED), then the extra message for A, then root B's write_plan and AUDIT-ACK."""
    mb = c.MAILBOX
    root_a, root_b = tmp_path / "A", tmp_path / "B"
    with _clock(T0):
        k.write_plan(root_a, *plan_args())
    a = c.load_json(root_a / "s1_out" / "plan.json")["trial_id"]
    post(mb, "a1", c.audit_token(root_a / "s1_out"), T0 + timedelta(hours=1))
    h = t.close_evidence("BLOCKED", blocked_record={"trial_id": a, "reasons": ["coverage"]})
    ca = line("S1-CLOSE-ACK", trial_id=a, bundle_sha256=c.bundle_sha256(), prev="a1", reason="BLOCKED",
              evidence_sha256=h)
    post(mb, "ca", ca, T0 + timedelta(hours=3))
    body = {"repost-identical-close": ca,
            "later-chain-ack": opening(a, "a1", bundle=c.bundle_sha256()),
            "second-different-close": close(a, "a1", bundle=c.bundle_sha256())}[extra]
    post(mb, "x1", body, T0 + timedelta(hours=3, minutes=30))
    with _clock(T0 + timedelta(hours=4)):
        try:                                                   # write_plan behaves as with no extra message
            t.require_no_open_trial()
        except t.Refusal as e:
            pytest.fail(f"the closed trial re-opened: {e}")
        k.write_plan(root_b, *plan_args())
    b = c.load_json(root_b / "s1_out" / "plan.json")["trial_id"]
    post(mb, "b1", c.audit_token(root_b / "s1_out"), T0 + timedelta(hours=5))
    trs = t.trials(t.scan())
    assert trs[a].closed is not None and trs[a].closed.mailbox_id == "ca"         # closed, rootless
    assert any("x1" in p and "escalate" in p for p in trs[a].problems), trs[a].problems
    assert trs[b].closed is None and trs[b].problems == []
    assert t.open_trial().trial_id == b and t.open_trial(mb).trial_id == b       # B is the unique open trial
    with pytest.raises(t.Refusal, match=f"trial {b} is open"):
        t.require_no_open_trial()
    con = sqlite3.connect(f"file:{mb.as_posix()}?mode=ro", uri=True)
    try:
        assert t.closed_in(con, trs[a]) is True and t.closed_in(con, trs[b]) is False
    finally:
        con.close()


# ---------------------------------------------------------------- OQ-30 (row 318)
def test_opening_receipt_sha256_is_the_raw_file_hash(tmp_path, monkeypatch):
    out = tmp_path / "s1_out"
    out.mkdir()
    rec = {"fingerprint": {"x": 1}, "receipt_sha256": "0" * 64}
    (out / "opening_receipt.json").write_bytes(c.canonical(rec))                       # canonical -> bytes
    (out / "plan.json").write_bytes(c.canonical({"trial_id": tid(), "planned_start": "2026-11-09T14:30:00+00:00",
                                                 "opening_close": "2026-11-06"}))
    monkeypatch.setattr(c, "opening_seal_path", lambda o, p: o / "absent-seal.json")
    fields = t.artifact_fields("S1-OPENING-ACK", out)
    assert "opening_receipt_sha256" in fields, fields
    got = fields["opening_receipt_sha256"]
    assert got == c.sha256_file(out / "opening_receipt.json")
    assert got != c.receipt_sha256(rec)                              # the fingerprint hash
