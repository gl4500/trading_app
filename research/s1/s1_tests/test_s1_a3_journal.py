"""Addendum 3 rev 5 (d9dd3759...) A3.1 and F0.1-F0.4: the bundle pin, the journal line grammar, the chain, the mode=ro
readers and the one INSERT. Written BEFORE the implementation (behavioural RED against the Task 1 stub:
s1_evidence/a3/t1_red.txt). Synthetic only: every mailbox is a tmp_path file; no real mailbox, network or live DB."""
import ast
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import s1_common as c
import s1_journal as j
from conftest import s1_mailbox_init

UTC = timezone.utc
HERE = Path(__file__).resolve().parent.parent
A3_SHA = "d9dd37595f0e0e73098ade1b8548e8cda2dc47fe49243f4d44735508029b9fb2"
ERRATUM1 = "b03464669673927fdb057acad9b0dc3258b1f08692d55ec3b0cffd4550f6ca2f"   # adopted Erratum 1 (de008b1)
T0 = datetime(2026, 11, 2, 21, 45, 30, tzinfo=UTC)
FAR = datetime(2030, 1, 1, tzinfo=UTC)
TRIAL = "3f2b8c1e-5d4a-4b6c-9e7f-0a1b2c3d4e5f"
AUDIT_LINE = (f"S1-AUDIT-ACK trial_id={TRIAL} bundle_sha256={'a' * 64} collector_sha256={'b' * 64} "
              f"plan_sha256={'c' * 64} start=2026-11-16T14:30:00+00:00")
GEN = c.sha256_bytes(AUDIT_LINE.encode("utf-8"))
OP, ACTOR = "1" * 32, "2" * 32
SLOT, SLOT2 = "slot/20261102T214500Z", "slot/20261102T214700Z"


def OPEN(rows, con):
    """A context every Task-2 rule accepts for these requests (E and D far ahead, gates open)."""
    return j.Context(slot_times=lambda s: (FAR, FAR + timedelta(minutes=30)), stage_gate=lambda rows, g: None,
                     slot_gate=lambda rows, s: None)


def base_line(**kw):
    f = dict(trial_id=TRIAL, seq=1, prev=GEN, kind="SLOT-INTENT", subject=SLOT, detail="absent", op=OP, actor=ACTOR,
             at="2026-11-02T21:45:30.000000+00:00")
    f.update(kw)
    return j.format_line(**f)


def intent(subject=SLOT, op=OP, actor=ACTOR):
    return j.Request("SLOT-INTENT", subject, op, actor)


def stored(mb):
    con = sqlite3.connect(mb)
    try:
        return con.execute("SELECT sender, recipient, request_key, body, created, acknowledged FROM messages").fetchall()
    finally:
        con.close()


def put(mb, mid, body, sender="s1", recipient="codex", key="experiments-s1-journal", created=1.0):
    con = sqlite3.connect(mb)
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", (mid, sender, recipient, key, body, created))
    con.commit()
    con.close()


# ---------------------------------------------------------------- A3.1
def test_bundle_pins_addendum3_and_lists_every_new_module():
    assert c.DOC_PINS["docs/s1_design_v5_addendum3.md"] == A3_SHA
    assert c.sha256_file(HERE / "docs" / "s1_design_v5_addendum3.md") == A3_SHA
    assert c.DOC_PINS["docs/s1_design_v5_addendum3_erratum1.md"] == ERRATUM1
    assert c.sha256_file(HERE / "docs" / "s1_design_v5_addendum3_erratum1.md") == ERRATUM1   # the adopted copy
    assert "s1_journal.py" in c.BUNDLE_CODE
    m = c.bundle_manifest()
    assert m["unexpected"] == {} and c.bundle_problems(m) == []


# ---------------------------------------------------------------- F0.2 grammar
def test_line_format_round_trip_exact_bytes():
    ln = base_line()
    assert ln == (f"S1-JOURNAL trial_id={TRIAL} seq=1 prev_sha256={GEN} kind=SLOT-INTENT subject={SLOT} "
                  f"detail_sha256=absent op={OP} actor={ACTOR} at=2026-11-02T21:45:30.000000+00:00")
    f = j.parse_line(ln)
    assert f["seq"] == 1 and j.format_line(**f) == ln and "\n" not in ln


BAD = {
    "trailing-newline": lambda ln: ln + "\n",
    "double-space": lambda ln: ln.replace(" seq=", "  seq="),
    "field-order": lambda ln: ln.replace(f"op={OP} actor={ACTOR}", f"actor={ACTOR} op={OP}"),
    "uppercase-hex": lambda ln: ln.replace(GEN, GEN.upper()),
    "uuid-not-v4": lambda ln: ln.replace(TRIAL, TRIAL[:14] + "1" + TRIAL[15:]),
    "seq-zero": lambda ln: ln.replace(" seq=1 ", " seq=0 "),
    "seq-leading-zero": lambda ln: ln.replace(" seq=1 ", " seq=01 "),
    "at-no-microseconds": lambda ln: ln.replace(".000000+00:00", "+00:00"),
    "at-not-utc": lambda ln: ln.replace("+00:00", "-05:00"),
    "at-z-suffix": lambda ln: ln.replace("+00:00", "Z"),
    "at-impossible-date": lambda ln: ln.replace("2026-11-02T", "2026-13-02T"),
    "unknown-kind": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=SLOT-RETRY"),
    "slot-subject-on-stage-kind": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=STAGE-INTENT").replace(
        "detail_sha256=absent", "detail_sha256=" + "9" * 64),
    "unknown-stage": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=STAGE-INTENT").replace(
        f"subject={SLOT}", "subject=stage/bogus").replace("detail_sha256=absent", "detail_sha256=" + "9" * 64),
    "detail-on-slot-intent": lambda ln: ln.replace("detail_sha256=absent", "detail_sha256=" + "9" * 64),
    "absent-on-qualified": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=SLOT-QUALIFIED"),
    "short-op": lambda ln: ln.replace(f"op={OP}", f"op={OP[:-1]}"),
    "unknown-reason": lambda ln: ln.replace("kind=SLOT-INTENT", "kind=TRIAL-INVALID").replace(
        f"subject={SLOT}", "subject=reason/bogus").replace("detail_sha256=absent", "detail_sha256=" + "9" * 64),
    "extra-field": lambda ln: ln + " note=x",
}


@pytest.mark.parametrize("case", sorted(BAD))
def test_line_rejects_every_grammar_deviation(case):
    with pytest.raises(j.ChainError):
        j.parse_line(BAD[case](base_line()))


@pytest.mark.parametrize("kind", ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"])
def test_seal_stage_subject_is_accepted_for_a_real_close_date(kind):
    """Erratum 1 E2.1 (controller ruling B1): a post-START seal is the stage `stage/seal/<close date>`, besides the
    eight named stages; the date is YYYY-MM-DD and a real calendar date."""
    ln = base_line(kind=kind, subject="stage/seal/2026-11-02", detail="9" * 64)
    f = j.parse_line(ln)
    assert f["subject"] == "stage/seal/2026-11-02" and j.format_line(**f) == ln
    assert j.stage_subject("seal/2026-11-02") == "stage/seal/2026-11-02"
    assert j.validate_request(j.Request(kind, "stage/seal/2026-11-02", OP, ACTOR, detail="9" * 64)) is None


BAD_SEAL = ["seal/2026-13-40", "seal/x", "seal/2026-02-30", "seal/20261102", "seal/2026-11-2", "seal/", "seal",
            "seal/2026-11-02/x", "seal/2026-11-02T00:00:00"]


@pytest.mark.parametrize("stage", BAD_SEAL)
def test_malformed_seal_stage_subject_is_rejected(stage):
    """Erratum 1 E2.1 (controller ruling B1): anything but `seal/<real YYYY-MM-DD>` is not a seal stage."""
    with pytest.raises(j.ChainError):
        j.parse_line(base_line(kind="STAGE-INTENT", subject="stage/" + stage, detail="9" * 64))
    with pytest.raises(j.RequestError):
        j.stage_subject(stage)
    with pytest.raises(j.RequestError):
        j.validate_request(j.Request("STAGE-INTENT", "stage/" + stage, OP, ACTOR, detail="9" * 64))


def test_seal_subject_is_a_stage_subject_only():
    """A seal subject on a slot kind is rejected; a slot subject is never a seal stage."""
    with pytest.raises(j.ChainError):
        j.parse_line(base_line(subject="stage/seal/2026-11-02"))
    with pytest.raises(j.RequestError):
        j.validate_request(j.Request("SLOT-INTENT", "stage/seal/2026-11-02", OP, ACTOR))


@pytest.mark.parametrize("field", ["seq", "at", "slot", "seal"])
def test_non_ascii_digits_are_not_grammar_digits(field):
    """F0.2 bytes are ASCII: a Unicode digit (here ARABIC-INDIC DIGIT ONE, U+0661) is a deviation, never a digit."""
    one = "١"
    ln = {"seq": base_line().replace(" seq=1 ", f" seq=1{one} "),
          "at": base_line().replace(".000000+", f".00000{one}+"),
          "slot": base_line().replace(SLOT, SLOT.replace("214500Z", f"21450{one}Z")),
          "seal": base_line(kind="STAGE-INTENT", subject=f"stage/seal/2026-11-0{one}", detail="9" * 64)}[field]
    with pytest.raises(j.ChainError):
        j.parse_line(ln)


def test_mailbox_path_characters_cannot_change_the_file_or_mode(tmp_path):
    """A `#` or `%` in the mailbox path must not truncate the sqlite URI (which would drop mode=ro and open, or
    create, a different file)."""
    d = tmp_path / "a#b%41"
    d.mkdir()
    with pytest.raises(j.Outage):
        j.read_all(d / "mailbox.sqlite3")
    before = sorted(p.name for p in tmp_path.rglob("*"))
    mb = s1_mailbox_init(d)
    res = j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=lambda: T0)
    assert j.read_trial(TRIAL, GEN, mb) == [res.row]
    assert sorted(p.name for p in tmp_path.rglob("*")) == sorted(before + ["mailbox.sqlite3"])


def test_genesis_is_the_sha256_of_the_audit_ack_line(tmp_path):
    mb = s1_mailbox_init(tmp_path)
    assert j.genesis(AUDIT_LINE) == GEN == j.line_sha256(AUDIT_LINE)
    first = j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=lambda: T0)
    assert first.row.prev == GEN and first.row.sha == c.sha256_bytes(first.row.line.encode("utf-8"))


# ---------------------------------------------------------------- chain and readers
def chained(n, trial=TRIAL, gen=GEN):
    lines, prev = [], gen
    for i in range(1, n + 1):
        ln = base_line(trial_id=trial, seq=i, prev=prev, subject=f"slot/2026110{i}T214500Z", op=f"{i:032x}")
        lines.append(ln)
        prev = j.line_sha256(ln)
    return lines


def as_rows(lines):
    return [j.Row(**j.parse_line(ln), line=ln, mailbox_id=str(i), created=float(i)) for i, ln in enumerate(lines)]


def test_verify_chain_detects_gap_fork_duplicate_and_bad_prev():
    good = chained(3)
    assert [r.seq for r in j.verify_chain(as_rows(good), TRIAL, GEN)] == [1, 2, 3]
    with pytest.raises(j.ChainError, match="gap"):
        j.verify_chain(as_rows([good[0], good[2]]), TRIAL, GEN)
    fork = base_line(seq=2, prev=j.line_sha256(good[0]), subject="slot/20261109T214500Z", op="f" * 32)
    with pytest.raises(j.ChainError, match="duplicate seq"):
        j.verify_chain(as_rows(good + [fork]), TRIAL, GEN)
    bad_prev = base_line(seq=2, prev="0" * 64, subject="slot/20261108T214500Z", op="e" * 32)
    with pytest.raises(j.ChainError, match="prev"):
        j.verify_chain(as_rows([good[0], bad_prev]), TRIAL, GEN)
    with pytest.raises(j.ChainError, match="prev"):
        j.verify_chain(as_rows(good), TRIAL, "f" * 64)                  # seq 1 must chain to the genesis


def test_other_trials_rows_are_ignored_and_have_their_own_chain(tmp_path):
    other = "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"
    mb = s1_mailbox_init(tmp_path)
    for i, ln in enumerate(chained(2) + chained(1, trial=other, gen="e" * 64)):
        put(mb, f"m{i}", ln, created=float(i))
    assert [r.seq for r in j.read_trial(TRIAL, GEN, mb)] == [1, 2]
    assert [r.seq for r in j.read_trial(other, "e" * 64, mb)] == [1]


@pytest.mark.parametrize("sender,recipient,body", [("codex", "codex", None), ("s1", "claude", None),
                                                    ("s1", "codex", "not a journal line")])
def test_foreign_or_unparseable_row_under_the_journal_key_is_a_chain_failure(tmp_path, sender, recipient, body):
    """OQ-4: only s1->codex well-formed lines may sit under the journal key."""
    mb = s1_mailbox_init(tmp_path)
    put(mb, "m0", body or chained(1)[0], sender=sender, recipient=recipient)
    with pytest.raises(j.ChainError):
        j.read_all(mb)


def test_acknowledged_column_never_changes_the_journal(tmp_path):
    """Review Focus 2: mailbox.py `ack` (run by Codex on its inbox) UPDATEs `acknowledged` on rows addressed to codex."""
    mb = s1_mailbox_init(tmp_path)
    j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=lambda: T0)
    before = j.read_trial(TRIAL, GEN, mb)
    con = sqlite3.connect(mb)
    con.execute("UPDATE messages SET acknowledged=?", (T0.timestamp() + 5,))     # the test simulates Codex's ack
    con.commit()
    con.close()
    assert j.read_trial(TRIAL, GEN, mb) == before


def test_readers_are_mode_ro_and_never_create_the_mailbox(tmp_path):
    missing = tmp_path / "absent.sqlite3"
    with pytest.raises(j.Outage):
        j.read_all(missing)
    assert not missing.exists()
    mb = s1_mailbox_init(tmp_path)
    con = j._ro(mb)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO messages VALUES ('x','s1','codex','k','b',0,NULL)")
    finally:
        con.close()


# ---------------------------------------------------------------- F0.1 the one INSERT
def test_append_is_one_insert_inside_begin_immediate(tmp_path, monkeypatch):
    mb = s1_mailbox_init(tmp_path)
    seen = []
    real = j._connect_rw

    def traced(mailbox, timeout):
        con = real(mailbox, timeout)
        con.set_trace_callback(seen.append)
        return con
    monkeypatch.setattr(j, "_connect_rw", traced)
    res = j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=lambda: T0)
    assert res.outcome == "APPEND" and seen[0] == "BEGIN IMMEDIATE" and seen[-1] == "COMMIT"
    verbs = [s.split(None, 1)[0].upper() for s in seen]
    assert [v for v in verbs if v in ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")] == ["INSERT"]
    assert verbs.index("SELECT") < verbs.index("INSERT")                 # re-read inside the transaction
    assert stored(mb) == [("s1", "codex", "experiments-s1-journal", res.row.line, T0.timestamp(), None)]


def test_concurrent_append_is_serialized_and_a_busy_mailbox_is_an_outage(tmp_path):
    """F0.1 + Review Focus 1 + F8.3: a second writer while the first holds BEGIN IMMEDIATE is an Outage (no row), never
    a fork; the chain stays contiguous."""
    mb = s1_mailbox_init(tmp_path)
    inner = {}

    def ctx_outer(rows, con):
        try:
            j.append(TRIAL, GEN, intent(SLOT2, op="3" * 32), OPEN, mailbox=mb, clock=lambda: T0, timeout=0.2)
            inner["outcome"] = "appended"
        except j.Outage as e:
            inner["outcome"] = f"outage: {e}"
        return OPEN(rows, con)
    first = j.append(TRIAL, GEN, intent(), ctx_outer, mailbox=mb, clock=lambda: T0)
    assert inner["outcome"].startswith("outage") and first.row.seq == 1
    second = j.append(TRIAL, GEN, intent(SLOT2, op="3" * 32), OPEN, mailbox=mb, clock=lambda: T0 + timedelta(seconds=1))
    rows = j.read_trial(TRIAL, GEN, mb)
    assert [r.seq for r in rows] == [1, 2] and rows[1].prev == rows[0].sha and second.row == rows[1]


def test_at_is_the_in_transaction_clock_and_qualified_uses_r(tmp_path, monkeypatch):
    mb = s1_mailbox_init(tmp_path)
    seen = []
    real = j._connect_rw

    def traced(mailbox, timeout):
        con = real(mailbox, timeout)
        con.set_trace_callback(lambda s: seen.append(s.split(None, 1)[0].upper()))
        return con
    monkeypatch.setattr(j, "_connect_rw", traced)
    reads = []

    def clock():
        seen.append("CLOCK")
        reads.append(T0 + timedelta(seconds=len(reads)))
        return reads[-1]
    a = j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=clock)
    r_ = T0 + timedelta(minutes=1, microseconds=7)
    q = j.append(TRIAL, GEN, j.Request("SLOT-QUALIFIED", SLOT, OP, ACTOR, detail="9" * 64, r_at=r_), OPEN, mailbox=mb,
                 clock=clock)
    assert len(reads) == 2
    first = seen[:seen.index("COMMIT") + 1]
    assert first.index("BEGIN") < first.index("CLOCK") < first.index("INSERT")
    assert a.row.at == reads[0].isoformat(timespec="microseconds") and a.row.created == reads[0].timestamp()
    assert q.row.at == "2026-11-02T21:46:30.000007+00:00" and q.row.created == reads[1].timestamp()   # OQ-26


def test_detail_is_hashed_from_memory_not_reread_from_disk(tmp_path):
    obj = {"b": 1, "a": "x"}
    assert j.detail_of(obj) == c.sha256_bytes(c.canonical(obj)) == c.sha256_bytes(b'{"a":"x","b":1}')
    mb = s1_mailbox_init(tmp_path)
    got = []

    def fn(at):
        got.append(at)
        return j.detail_of({"cutoff": at.astimezone(c.NY).date().isoformat()})
    res = j.append(TRIAL, GEN, j.Request("STAGE-INTENT", "stage/audit", OP, ACTOR, detail_fn=fn), OPEN, mailbox=mb,
                   clock=lambda: T0)
    assert got == [T0] and res.row.detail == j.detail_of({"cutoff": "2026-11-02"})      # OQ-7


@pytest.mark.parametrize("state", ["no-file", "no-table"])
def test_missing_mailbox_or_table_is_an_outage_with_no_row(tmp_path, state):
    mb = tmp_path / "mb.sqlite3"
    if state == "no-table":
        sqlite3.connect(mb).close()
    with pytest.raises(j.Outage):
        j.append(TRIAL, GEN, intent(), OPEN, mailbox=mb, clock=lambda: T0)
    assert (state == "no-file") == (not mb.exists())


def test_journal_module_never_updates_deletes_or_imports_mailbox():
    tree = ast.parse((HERE / "s1_journal.py").read_text(encoding="utf-8"))
    sql = [n.value.strip().split(None, 1)[0].upper() for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.strip()
           and n.value.strip().split(None, 1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP",
                                                             "ALTER")]
    assert sql == ["INSERT"]
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "mailbox" not in imports


def test_default_mailbox_is_the_tmp_redirect(s1_tmp_mailbox):
    real = Path("C:/Users/gl450/.coordination/trading_app/mailbox.sqlite3")
    assert Path(c.MAILBOX) == s1_tmp_mailbox and Path(c.MAILBOX).resolve() != real.resolve()
    assert s1_tmp_mailbox.is_file()                                       # the redirect carries the real schema
