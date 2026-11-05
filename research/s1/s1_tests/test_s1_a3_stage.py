"""Addendum 3 rev 5 F4.1-F4.5, F4.7, the F4 stage-state table, F1 graph and failure cases, F5 for stages, R2-1/R2-2,
FINAL-2, C-a projection. Behavioural RED against the Task 8 stub (s1_evidence/a3/t8_red.txt). Fake stage works over
real staging and the real journal; child processes for crashes and live owners; spies."""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import a3_helpers as h
import s1_common as c
import s1_journal as j
import s1_locks as L
import s1_stage as sg
import s1_trial as t
from conftest import Spies, s1_jappend, s1_mailbox_init

UTC = timezone.utc
START = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
AT = START - timedelta(days=12)
HELPERS = Path(__file__).resolve().parent / "a3_helpers.py"
SEAL = "seal/2026-10-27"
SEAL_OK = {"extra_gate": lambda rows: None, "stage_check": lambda rows, s, inputs: None}   # fake seal-side callables


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    tr = t.open_trial(mb(root))
    return j.read_trial(tr.trial_id, tr.genesis, mb(root))


def stage_kinds(root, stage):
    return [r_.kind for r_ in j.subject_rows(jrows(root), j.stage_subject(stage))]


def drive(root, stage, work, monkeypatch, inputs=None, clock=None, **kw):
    monkeypatch.setattr(sg, "ENFORCED", frozenset({stage}))
    if stage != "audit":
        h.relax(monkeypatch, stage)
    gv = t.gate(root, "engine")
    return sg.run(gv, stage, inputs=inputs if inputs is not None else
                  {"plan.json": c.sha256_file(Path(root) / "s1_out" / "plan.json")}, acks={}, work=work,
                  mailbox=mb(root), clock=clock or (lambda: AT), **kw)


def child(root, stage, mode, wait=True):
    p = subprocess.Popen([sys.executable, "-I", str(HELPERS), str(root), stage, mode, AT.isoformat()],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if mode.startswith("hold"):
        assert p.stdout.readline().strip() == "held", p.stderr.read()
        return p
    p.wait(timeout=120)
    return p


@pytest.fixture
def trial(tmp_path):
    return h.plan_only(tmp_path, START)


def test_intent_precedes_any_work_and_the_envelope_is_exact(tmp_path, trial, monkeypatch):
    seen = {}

    def work(sw):
        seen["kinds"] = stage_kinds(tmp_path, "audit")
        return h.fake_audit(sw)
    drive(tmp_path, "audit", work, monkeypatch)
    assert seen["kinds"] == ["STAGE-INTENT"]
    intent = j.first(j.subject_rows(jrows(tmp_path), "stage/audit"), "STAGE-INTENT")
    env = sg.envelope(trial.trial.trial_id, "audit", {"plan.json": c.sha256_file(tmp_path / "s1_out" / "plan.json")},
                      {}, None)
    assert intent.detail == j.detail_of(env) == j.detail_of(json.loads(
        (sg.staging_dir(tmp_path, trial.trial.trial_id, "audit") / "intent.json").read_bytes()))


def test_work_writes_only_to_staging_outside_s1_out(tmp_path, trial, monkeypatch):
    seen = {}

    def work(sw):
        prov = h.fake_audit(sw)
        seen["in_out"] = sorted(p.relative_to(tmp_path / "s1_out").as_posix()
                                for p in (tmp_path / "s1_out").rglob("*") if p.is_file())
        seen["staging"] = sw.staging.dir
        return prov
    drive(tmp_path, "audit", work, monkeypatch)
    assert seen["in_out"] == ["plan.json"]
    assert seen["staging"] == tmp_path / "s1_staging" / trial.trial.trial_id / "audit"
    assert (tmp_path / "s1_out") not in seen["staging"].parents


@pytest.mark.parametrize("case", ["single", "tree", "single-with-two-members-refused"])
def test_prepared_commitment_format(tmp_path, trial, monkeypatch, case):
    if case == "tree":
        com = drive(tmp_path, "audit", h.fake_audit, monkeypatch)
        assert com["kind"] == "tree" and set(sg.FIXED_TREE["audit"]) <= set(com["members"])
        assert {p["page_relpath"] for p in com["provenance"]} == set(com["members"]) - set(sg.FIXED_TREE["audit"])
    elif case == "single":
        com = drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
        assert (com["kind"], list(com["members"]), com["provenance"]) == ("single", ["final_plan.json"], [])
    else:
        def two(sw):
            h.fake_single(sw)
            sw.put_json("extra.json", {})
            return []
        with pytest.raises(SystemExit, match="exactly one member"):
            drive(tmp_path, "final_plan", two, monkeypatch)
        assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT"]
        return
    assert set(com) == {"trial_id", "stage", "op", "kind", "members", "provenance"}   # no seals_checked (E2.7 r3)
    prepared = j.first(j.subject_rows(jrows(tmp_path), j.stage_subject(com["stage"])), "STAGE-PREPARED")
    assert prepared is not None and prepared.detail == j.detail_of(com)


def test_prepared_json_is_written_before_prepared_and_never_trusted_alone(tmp_path, trial, monkeypatch):
    seen = {}
    real = j.append

    def spy(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-PREPARED":
            seen["exists"] = (sg.staging_dir(tmp_path, trial_id, "audit") / "prepared.json").is_file()
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", spy)
    drive(tmp_path, "audit", h.fake_audit, monkeypatch)
    assert seen.get("exists") is True


def test_publication_is_exclusive_then_created_repeats_the_prepared_detail(tmp_path, trial, monkeypatch):
    order = []
    real_pub, real_app = c.publish_exclusive, j.append
    monkeypatch.setattr(c, "publish_exclusive", lambda p, d: order.append(("publish", Path(p).name))
                        or real_pub(p, d))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(("append", a[2].kind)) or real_app(*a, **kw))
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    names_ = [x for x in order if x[0] == "append" or x[1] == "final_plan.json"]
    assert names_ == [("append", "STAGE-INTENT"), ("publish", "final_plan.json"), ("append", "STAGE-PREPARED"),
                      ("publish", "final_plan.json"), ("append", "STAGE-CREATED")]
    rows = j.subject_rows(jrows(tmp_path), "stage/final_plan")
    assert rows[2].detail == rows[1].detail


def test_intent_at_field_equals_the_intent_row(tmp_path, trial, monkeypatch):          # row 89 (schema placement)
    ticks = []

    def clock():                                              # every in-transaction reading is a distinct instant
        ticks.append(AT + timedelta(seconds=len(ticks)))
        return ticks[-1]
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch, clock=clock)
    rows = j.subject_rows(jrows(tmp_path), "stage/final_plan")
    assert len({r_.at for r_ in rows}) == 3
    body = (tmp_path / "s1_out" / "final_plan.json").read_text(encoding="utf-8")
    assert json.loads(body)["intent_at"] == rows[0].at


def _member_bytes_with(root, monkeypatch, gaps):
    """Drive final_plan with the INTENT at AT and PREPARED/CREATED at AT + gaps (seconds); return member bytes."""
    seq = iter([AT] + [AT + timedelta(seconds=g) for g in gaps])
    last = [AT]

    def clock():
        last[0] = next(seq, last[0])
        return last[0]
    drive(root, "final_plan", h.fake_single, monkeypatch, clock=clock)
    return (root / "s1_out" / "final_plan.json").read_bytes(), j.subject_rows(jrows(root), "stage/final_plan")


def _own_mailbox(root, monkeypatch):
    """Two independent trials in one test: each root gets its own tmp mailbox (under the test's tmp_path), and the
    gates' default mailbox (s1_common.MAILBOX) is pointed at it while that root is driven (B4: never the real one)."""
    root.mkdir(parents=True, exist_ok=True)
    s1_mailbox_init(root)
    monkeypatch.setattr(c, "MAILBOX", mb(root))


@pytest.mark.parametrize("case", ["distinct-ticks", "same-tick"])
def test_member_bytes_do_not_depend_on_the_prepared_or_created_clock(tmp_path, monkeypatch, case):
    """Rows 15, 89 (coverage 15/89): a DATA-INDEPENDENCE oracle, not substring inequality. Two runs with the same
    INTENT instant and different PREPARED/CREATED instants give byte-identical members; the same-tick run (all three
    rows at one instant, where a substring test would be vacuous or false) is accepted."""
    a, b = tmp_path / "a", tmp_path / "b"
    gaps_b = [7, 13] if case == "distinct-ticks" else [0, 0]
    _own_mailbox(a, monkeypatch)
    ta = h.plan_only(a, START)
    bytes_a, rows_a = _member_bytes_with(a, monkeypatch, [1, 2])
    _own_mailbox(b, monkeypatch)
    h.plan_only(b, START)
    bytes_b, rows_b = _member_bytes_with(b, monkeypatch, gaps_b)
    strip = lambda x: json.loads(x) | {"trial_id": None, "op": None}           # noqa: E731 (per-trial identity)
    assert strip(bytes_a) == strip(bytes_b)
    prepared = json.loads((sg.staging_dir(a, ta.trial.trial_id, "final_plan") / "prepared.json").read_bytes())
    assert "at" not in prepared and "prepared_at" not in prepared              # the commitment has no clock field
    assert len({r_.at for r_ in rows_a}) == 3
    if case == "same-tick":
        assert len({r_.at for r_ in rows_b}) == 1


@pytest.mark.parametrize("case", ["created", "gate-refuses", "selection-invalid"])
def test_seal_stage_family_in_the_engine(tmp_path, trial, monkeypatch, case):          # row 331 (E2.1/E2.2 r3)
    """The engine side of a `seal/<close>` stage, with fake inputs (the slot side is Task 7's): kind single, member
    seals/<close>.json, policy null; the extra_gate refuses with no row; a stage_check INVALIDATE is committed."""
    stage = SEAL
    assert sg.spec(stage)["kind"] == "single" and sg.single_member(tmp_path / "s1_out", stage) == \
        "seals/2026-10-27.json"
    with pytest.raises(KeyError):
        sg.spec("seal/../x")                                                 # unknown names fail closed

    def work(sw):
        sw.put("seals/2026-10-27.json", b'{"seal": "fake"}')
        return []
    kw = dict(SEAL_OK, inputs={"qualified_line": "1" * 64, "tree_manifest": "2" * 64})
    if case == "gate-refuses":
        kw["extra_gate"] = lambda rows: "close not determined (E2.2)"
    if case == "selection-invalid":
        kw["stage_check"] = lambda rows, s, inputs: j.Decision("INVALIDATE", "contradictory-stage")
    if case == "created":
        com = drive(tmp_path, stage, work, monkeypatch, **kw)
        assert com["kind"] == "single" and list(com["members"]) == ["seals/2026-10-27.json"]
        assert stage_kinds(tmp_path, stage) == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]
        env = json.loads((sg.staging_dir(tmp_path, trial.trial.trial_id, stage) / "intent.json").read_bytes())
        assert env["request_policy"] is None
        return
    with pytest.raises(SystemExit):
        drive(tmp_path, stage, work, monkeypatch, **kw)
    if case == "gate-refuses":
        assert stage_kinds(tmp_path, stage) == [] and not (tmp_path / "s1_out" / "seals").exists()
    else:
        assert jrows(tmp_path)[-1].subject == "reason/contradictory-stage"


@pytest.mark.parametrize("missing", ["extra_gate", "stage_check"])
def test_a_seal_stage_without_its_gate_or_selection_check_fails_closed(tmp_path, trial, monkeypatch, missing):
    """Task 2/5 carry-forward (decide step 5 fail-closed): the seal side's callables (s1_slot.seal_gate, the E2.2
    selection check) are never defaulted to 'no check' for a seal stage: omitting either refuses with no row."""
    kw = dict(SEAL_OK, inputs={"qualified_line": "1" * 64, "tree_manifest": "2" * 64})
    del kw[missing]
    with pytest.raises(SystemExit, match=r"fail closed"):
        drive(tmp_path, SEAL, lambda sw: sw.put("seals/2026-10-27.json", b"{}") and [], monkeypatch, **kw)
    assert stage_kinds(tmp_path, SEAL) == [] and not (tmp_path / "s1_out" / "seals").exists()


def test_every_stage_append_hands_real_gate_callables_to_the_context(tmp_path, trial, monkeypatch):
    """Task 5 carry-forward: the engine never relies on None meaning 'no check' (decide refuses that at step 5); the
    Context built inside each stage transaction carries callable stage_gate and stage_check."""
    seen = []
    real = j.append

    def spy(trial_id, gen, req, ctx_fn, **kw):
        def ctx_spy(rows, con):
            ctx = ctx_fn(rows, con)
            seen.append((req.kind, callable(ctx.stage_gate), callable(ctx.stage_check)))
            return ctx
        return real(trial_id, gen, req, ctx_spy, **kw)
    monkeypatch.setattr(j, "append", spy)
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    assert seen == [("STAGE-INTENT", True, True), ("STAGE-PREPARED", True, True), ("STAGE-CREATED", True, True)]


def test_stage_kinds_are_the_frozen_f48_kinds():                                       # row 85 (OQ-15)
    assert {g: v["kind"] for g, v in sg.TABLE.items()} == {
        "audit": "tree", "opening": "single", "start_attest": "single", "prereg": "single", "stop_attest": "single",
        "final_plan": "single", "final": "tree", "score": "tree"}


@pytest.mark.parametrize("case", ["intent-deleted", "prepared-changed"])
def test_intent_or_prepared_json_lost_after_created_is_invalid(tmp_path, trial, monkeypatch, case):   # row 317
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    st_dir = sg.staging_dir(tmp_path, trial.trial.trial_id, "final_plan")
    assert (st_dir / "intent.json").is_file() and (st_dir / "prepared.json").is_file()      # kept (OQ-35)
    if case == "intent-deleted":
        (st_dir / "intent.json").unlink()
    else:
        (st_dir / "prepared.json").write_bytes((st_dir / "prepared.json").read_bytes() + b" ")
    with pytest.raises(SystemExit, match="stage-replaced"):
        t.gate(tmp_path, "staging evidence")


def test_committed_commitment_is_verified_against_its_prepared_row(tmp_path, trial, monkeypatch):
    """committed_commitment (used by s1_slot.required_seals and s1_trial.evidence_manifest later): the staging
    prepared.json only when it hashes to its PREPARED row's detail; ValueError otherwise (no PREPARED, or changed)."""
    tid = trial.trial.trial_id
    with pytest.raises(ValueError):
        sg.committed_commitment(tmp_path, tid, "final_plan", jrows(tmp_path))        # no PREPARED row
    com = drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    assert sg.committed_commitment(tmp_path, tid, "final_plan", jrows(tmp_path)) == com
    p = sg.staging_dir(tmp_path, tid, "final_plan") / "prepared.json"
    p.write_bytes(p.read_bytes().replace(b'"single"', b'"tree"'))
    with pytest.raises(ValueError):
        sg.committed_commitment(tmp_path, tid, "final_plan", jrows(tmp_path))


def test_prepared_detail_comes_from_memory_even_if_prepared_json_is_altered(tmp_path, trial, monkeypatch):
    real = c.publish_exclusive

    def tamper(p, data):
        real(p, data)
        if Path(p).name == "prepared.json":
            Path(p).write_bytes(data.replace(b'"single"', b'"tree"'))      # the TEST alters its staging copy
    monkeypatch.setattr(c, "publish_exclusive", tamper)
    real_app = j.append

    def stop_before_created(*a, **kw):
        if a[2].kind == "STAGE-CREATED":
            raise KeyboardInterrupt                                       # simulate a crash before CREATED
        return real_app(*a, **kw)
    monkeypatch.setattr(j, "append", stop_before_created)
    with pytest.raises(KeyboardInterrupt):
        drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    monkeypatch.setattr(j, "append", real_app)
    monkeypatch.setattr(c, "publish_exclusive", real)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "recovery")


def test_crash_after_prepared_recovery_by_b_appends_created_without_recompute(tmp_path, trial, monkeypatch):
    p = child(tmp_path, "final_plan", "die-after-prepared")
    assert p.returncode == 9, p.stderr.read()
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED"]
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    called = []
    monkeypatch.setattr(h, "fake_single", lambda sw: called.append(1))
    t.gate(tmp_path, "B recovers")
    rows = j.subject_rows(jrows(tmp_path), "stage/final_plan")
    assert [r_.kind for r_ in rows] == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"] and called == []
    assert rows[2].op == rows[0].op and rows[2].actor != rows[0].actor and rows[2].detail == rows[1].detail
    assert all(r_.kind != "TRIAL-INVALID" for r_ in jrows(tmp_path))


def test_recovery_appends_created_with_a_op_and_b_actor_under_the_lock(tmp_path, trial, monkeypatch):
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    order = []
    real_acq, real_read, real_app = L.OwnershipLock.acquire, j.read_trial, j.append
    monkeypatch.setattr(L.OwnershipLock, "acquire", lambda self: order.append("lock") or real_acq(self))
    monkeypatch.setattr(j, "read_trial", lambda *a, **kw: order.append("read") or real_read(*a, **kw))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(a[2].kind) or real_app(*a, **kw))
    t.gate(tmp_path, "B recovers")
    assert "STAGE-CREATED" in order, order
    before = order[:order.index("STAGE-CREATED")][::-1]
    assert "lock" in before and before.index("read") < before.index("lock")   # re-read after the lock, then CREATED
    rows = j.subject_rows(jrows(tmp_path), "stage/final_plan")
    assert rows[2].op == rows[0].op and rows[2].actor not in (rows[0].actor, rows[1].actor)


@pytest.mark.parametrize("case", ["member-absent", "member-changed", "prepared-json-mismatch", "foreign-op",
                                  "missing-prepared"])
def test_recovery_failures_are_invalid(tmp_path, trial, monkeypatch, case):
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    tid = trial.trial.trial_id
    staging = sg.staging_dir(tmp_path, tid, "final_plan")
    if case in ("foreign-op", "missing-prepared"):
        row = s1_jappend(tmp_path, "STAGE-INTENT", "stage/final_plan", at=AT, detail="1" * 64)
        if case == "foreign-op":
            s1_jappend(tmp_path, "STAGE-PREPARED", "stage/final_plan", at=AT, detail="2" * 64, op=row.op,
                       actor=row.actor)
        tr = t.open_trial(mb(tmp_path))
        res = j.append(tid, tr.genesis, j.Request("STAGE-CREATED", "stage/final_plan",
                                                  j.new_nonce() if case == "foreign-op" else row.op, j.new_nonce(),
                                                  detail="2" * 64),
                       t.product_context(tr), mailbox=mb(tmp_path), clock=lambda: AT)
        assert (res.outcome, res.reason) == ("INVALIDATE", "contradictory-stage")
        return
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    if case == "member-absent":
        (staging / "final_plan.json").unlink()
    elif case == "member-changed":
        (staging / "final_plan.json").write_bytes(b"{}")
    else:
        (staging / "prepared.json").write_bytes(b"{}")
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "recovery")


def test_recovery_never_appends_prepared_for_another_actors_op(tmp_path, trial):
    row = s1_jappend(tmp_path, "STAGE-INTENT", "stage/final_plan", at=AT, detail="1" * 64)
    tr = t.open_trial(mb(tmp_path))
    res = j.append(tr.trial_id, tr.genesis, j.Request("STAGE-PREPARED", "stage/final_plan", row.op, j.new_nonce(),
                                                      detail="2" * 64),
                   t.product_context(tr), mailbox=mb(tmp_path), clock=lambda: AT)
    assert (res.outcome, res.reason) == ("INVALIDATE", "contradictory-stage")
    import inspect
    assert "STAGE-PREPARED" not in inspect.getsource(sg.recover)


def test_recovery_publishes_only_missing_members_and_never_overwrites(tmp_path, trial, monkeypatch):
    assert child(tmp_path, "audit", "die-after-prepared").returncode == 9
    staging = sg.staging_dir(tmp_path, trial.trial.trial_id, "audit")
    first = "audit/attempt.json"
    (tmp_path / "s1_out" / first).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(staging / first, tmp_path / "s1_out" / first)          # partially published before the crash
    before = (tmp_path / "s1_out" / first).stat().st_mtime_ns
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"audit"}))
    t.gate(tmp_path, "recovery")
    assert (tmp_path / "s1_out" / first).stat().st_mtime_ns == before
    assert stage_kinds(tmp_path, "audit")[-1] == "STAGE-CREATED"


def test_recovery_unexpected_error_appends_nothing(tmp_path, trial, monkeypatch):
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    monkeypatch.setattr(c, "publish_exclusive", lambda p, d: (_ for _ in ()).throw(RuntimeError("disk")))
    with pytest.raises(SystemExit, match="refused with no row"):
        t.gate(tmp_path, "recovery")
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED"]


def test_concurrent_recovery_appends_exactly_one_created(tmp_path, trial):
    """Row 136 (fix round 1, M1): a real race with a pipe barrier. Recoverer 1 holds the stage lock after its re-read,
    just before its CREATED request; recoverer 2 runs while it is held and refuses "pending" (exit 1, no row); on
    release recoverer 1 appends the one CREATED (exit 0); a third run finds it CREATED and does nothing (exit 0)."""
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    first = child(tmp_path, "final_plan", "hold-recover")
    try:
        second = child(tmp_path, "final_plan", "recover")
        err2 = second.stderr.read()
        assert second.returncode == 1 and "pending" in err2, (second.returncode, err2)
        assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED"]
        first.stdin.write("go\n")
        first.stdin.flush()
        assert first.wait(timeout=120) == 0, first.stderr.read()
    finally:
        if first.poll() is None:
            first.stdin.close()
            first.wait(timeout=60)
    third = child(tmp_path, "final_plan", "recover")
    assert third.returncode == 0, third.stderr.read()
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED", "STAGE-CREATED"]


@pytest.mark.parametrize("case", ["no-intent-artifact-after-audit-ack", "no-intent-artifact-before-audit-ack",
                                  "intent-lock-held", "intent-lock-free", "prepared-lock-held", "prepared-lock-free"])
def test_stage_state_table(tmp_path, monkeypatch, case):
    if case == "no-intent-artifact-before-audit-ack":
        import s1_collect as k
        from conftest import _Clock
        with _Clock(START - timedelta(days=14)):
            k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
        (tmp_path / "s1_out" / "final_plan.json").write_text("{}", encoding="utf-8")
        with pytest.raises(SystemExit, match="zero open trials"):
            t.gate(tmp_path, "table")
        return
    h.plan_only(tmp_path, START)
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    sp = Spies(monkeypatch)
    if case == "no-intent-artifact-after-audit-ack":
        (tmp_path / "s1_out" / "final_plan.json").write_text("{}", encoding="utf-8")
        with pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
            t.gate(tmp_path, "table")
    elif case.endswith("lock-held"):
        p = child(tmp_path, "final_plan", "hold-after-intent" if case.startswith("intent") else "hold-after-prepared")
        try:
            with pytest.raises(SystemExit, match="pending"):
                t.gate(tmp_path, "table")
            assert all(r_.kind != "TRIAL-INVALID" for r_ in jrows(tmp_path))
        finally:
            p.stdin.close()
            p.wait(timeout=60)
    elif case == "intent-lock-free":
        assert child(tmp_path, "final_plan", "die-after-intent").returncode == 9
        with pytest.raises(SystemExit, match=r"INVALID \(stage-incomplete\)"):
            t.gate(tmp_path, "table")
    else:
        assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
        t.gate(tmp_path, "table")
        assert stage_kinds(tmp_path, "final_plan")[-1] == "STAGE-CREATED"
    sp.assert_zero()


@pytest.mark.parametrize("damage", ["missing", "changed", "unparseable"])
def test_created_member_missing_changed_or_unparseable_is_invalid(tmp_path, trial, monkeypatch, damage):
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    p = tmp_path / "s1_out" / "final_plan.json"
    if damage == "missing":
        p.unlink()
    else:
        p.write_text("{}" if damage == "changed" else "{not JSON", encoding="utf-8")
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "created check")
    sp.assert_zero()


def test_pre_intent_outage_makes_no_request_and_no_artifact(tmp_path, trial, monkeypatch):
    sp = Spies(monkeypatch)
    real = j.append

    def outage(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-INTENT":
            raise j.Outage("mailbox busy")
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", outage)
    with pytest.raises(SystemExit, match="outage"):
        drive(tmp_path, "audit", lambda sw: sp.client().get("https://data.alpaca.markets/x"), monkeypatch)
    sp.assert_zero()
    assert not (tmp_path / "s1_staging").exists() and stage_kinds(tmp_path, "audit") == []


def test_completion_append_failure_keeps_evidence_and_no_next_stage_runs(tmp_path, trial, monkeypatch):
    real = j.append

    def fail_created(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-CREATED":
            raise j.Outage("mailbox busy")
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", fail_created)
    with pytest.raises(SystemExit, match="outage"):
        drive(tmp_path, "audit", h.fake_audit, monkeypatch)
    staging = sg.staging_dir(tmp_path, trial.trial.trial_id, "audit")
    assert (staging / "prepared.json").is_file() and stage_kinds(tmp_path, "audit") == ["STAGE-INTENT",
                                                                                        "STAGE-PREPARED"]
    assert "not CREATED" in (sg.permitted(trial.trial, jrows(tmp_path), "opening") or "")


@pytest.mark.parametrize("stage", list(sg.TABLE))
def test_stage_intent_refused_until_predecessor_created_and_ack(tmp_path, trial, stage):
    rows = jrows(tmp_path)
    why = sg.permitted(trial.trial, rows, stage)
    assert (why is None) == (stage == "audit"), (stage, why)


def test_repeat_stage_intent_is_invalid(tmp_path, trial):
    s1_jappend(tmp_path, "STAGE-INTENT", "stage/audit", at=AT, detail="1" * 64)
    tr = t.open_trial(mb(tmp_path))
    res = j.append(tr.trial_id, tr.genesis, j.Request("STAGE-INTENT", "stage/audit", j.new_nonce(), j.new_nonce(),
                                                      detail="2" * 64),
                   t.product_context(tr, stage_gate=lambda r_, g: None), mailbox=mb(tmp_path), clock=lambda: AT)
    assert (res.outcome, res.reason) == ("INVALIDATE", "repeat-stage")


def test_commit_delete_detect_restore_is_still_invalid_with_zero_callbacks(tmp_path, trial, monkeypatch):
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    p = tmp_path / "s1_out" / "final_plan.json"
    keep = p.read_bytes()
    p.unlink()
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "detect")
    p.write_bytes(keep)
    for w in ("aborted.json", "refusals.jsonl"):
        (tmp_path / "s1_out" / w).unlink(missing_ok=True)
    shutil.rmtree(tmp_path / "s1_out" / "invalid", ignore_errors=True)
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match="INVALID"):
        t.gate(tmp_path, "restart")
    sp.assert_zero()


def test_pause_after_intent_with_a_live_owner_is_pending(tmp_path, trial, monkeypatch):
    p = child(tmp_path, "final_plan", "hold-after-intent")
    try:
        monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
        h.relax(monkeypatch, "final_plan")
        sp = Spies(monkeypatch)
        with pytest.raises(SystemExit, match="pending"):
            t.gate(tmp_path, "concurrent gate")
        sp.assert_zero()
    finally:
        p.stdin.close()
        p.wait(timeout=60)


def test_created_failure_then_restart_recovers_without_recreation(tmp_path, trial, monkeypatch):
    real = j.append
    monkeypatch.setattr(j, "append", lambda *a, **kw: (_ for _ in ()).throw(j.Outage("busy"))
                        if a[2].kind == "STAGE-CREATED" else real(*a, **kw))
    with pytest.raises(SystemExit):
        drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    monkeypatch.setattr(j, "append", real)
    calls = []
    monkeypatch.setattr(h, "fake_single", lambda sw: calls.append(1))
    t.gate(tmp_path, "restart")
    assert stage_kinds(tmp_path, "final_plan")[-1] == "STAGE-CREATED" and calls == []


def test_lock_io_error_refuses_with_no_row_and_no_liveness_verdict(tmp_path, trial, monkeypatch):
    """F5.5 + Task 3 carry-forward: a lock path that is a directory gives ERROR_ACCESS_DENIED (Windows error 5) from
    CreateFileW - LockError, so the gate refuses with no row: never INVALID, never 'pending', never a crash."""
    assert child(tmp_path, "final_plan", "die-after-intent").returncode == 9
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    lp = L.lock_path(tmp_path, trial.trial.trial_id, "stage-final_plan")
    lp.unlink(missing_ok=True)
    lp.mkdir(parents=True)                                     # an I/O error, not a sharing violation
    with pytest.raises(SystemExit, match=r"lock error .*Windows error 5\b.*refused with no row"):
        t.gate(tmp_path, "lock error")
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT"]
    assert all(r_.kind != "TRIAL-INVALID" for r_ in jrows(tmp_path))


def test_stage_lock_is_taken_before_the_journal_read(tmp_path, trial, monkeypatch):
    order = []
    real_acq, real_read, real_app = L.OwnershipLock.acquire, j.read_trial, j.append
    monkeypatch.setattr(L.OwnershipLock, "acquire", lambda self: order.append(("lock", self.path.name))
                        or real_acq(self))
    monkeypatch.setattr(j, "read_trial", lambda *a, **kw: order.append(("read",)) or real_read(*a, **kw))
    monkeypatch.setattr(j, "append", lambda *a, **kw: order.append(("append", a[2].kind)) or real_app(*a, **kw))
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    assert ("lock", "stage-final_plan.lock") in order and ("append", "STAGE-INTENT") in order, order
    i_lock = order.index(("lock", "stage-final_plan.lock"))
    i_intent = order.index(("append", "STAGE-INTENT"))
    assert i_lock < i_intent and ("read",) in order[i_lock:i_intent]      # the stage state is read under the lock


def test_manifest_projection_rule():
    m = {"files": {"attempt.json": "a", "calendar.json": "b"}, "pages": {"audit/pages/calendar.json": "c"}}
    assert sg.manifest_projection("audit", m) == {"audit/attempt.json": "a", "audit/calendar.json": "b",
                                                  "audit/pages/calendar.json": "c"}
    m2 = {"files": {"bars.json": "d"}, "pages": {"final/pages_full/ca_000_page000.json": "e"}}
    assert sg.manifest_projection("final", m2) == {"final/bars.json": "d", "final/pages_full/ca_000_page000.json": "e"}


def test_every_stage_artifact_records_and_is_validated_against_the_trial_id(tmp_path, trial, monkeypatch):
    def wrong(sw):
        sw.put_json("final_plan.json", {"trial_id": "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d", "intent_at": sw.intent_at})
        return []
    drive(tmp_path, "final_plan", wrong, monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "trial id")


# ------------------------------------------------- seal stages in the stage-state table (E2.4/E2.6 r3, row 331)
def test_a_seal_file_with_no_prepared_row_is_a_registration_artifact(tmp_path, trial, monkeypatch):
    """E2.4 r3: a post-START seal file with no INTENT/PREPARED is a violation in every state (seal evaluation on)."""
    monkeypatch.setattr(sg, "SEALS_ENFORCED", True)
    (tmp_path / "s1_out" / "seals").mkdir()
    (tmp_path / "s1_out" / "seals" / "2026-10-27.json").write_text("{}", encoding="utf-8")
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
        t.gate(tmp_path, "seal artifact")
    assert jrows(tmp_path)[-1].subject == "reason/registration-artifact"
    sp.assert_zero()


def test_a_created_seal_deleted_is_stage_replaced_and_never_recreated(tmp_path, trial, monkeypatch):
    """E2.6 r3: a CREATED seal stage's member missing is INVALID (stage-replaced); the gate never recreates it."""
    drive(tmp_path, SEAL, lambda sw: sw.put("seals/2026-10-27.json", b'{"seal": "fake"}') and [], monkeypatch,
          inputs={"qualified_line": "1" * 64, "tree_manifest": "2" * 64}, **SEAL_OK)
    seal = tmp_path / "s1_out" / "seals" / "2026-10-27.json"
    t.gate(tmp_path, "intact")                                         # positive control: CREATED and intact
    seal.unlink()
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "seal deleted")
    assert not seal.exists()


def test_seal_files_on_disk_are_not_evaluated_while_the_seal_family_is_not_enforced(tmp_path, trial):
    """Transitional (Task 8): the existing post-START seal writers have no seal stage yet (Task 7 adds it), so a seal
    file with no rows is not evaluated until SEALS_ENFORCED is set; ENFORCED (the TABLE stages) is empty too."""
    assert sg.ENFORCED == frozenset() and sg.SEALS_ENFORCED is False
    (tmp_path / "s1_out" / "seals").mkdir()
    (tmp_path / "s1_out" / "seals" / "2026-10-27.json").write_text("{}", encoding="utf-8")
    t.gate(tmp_path, "transitional")


def test_a_foreign_root_is_refused_by_the_plan_check_before_the_stage_table(tmp_path, trial, monkeypatch):
    """Hook placement (Deviation): evaluate() runs after the F6.2 plan check, so a root whose plan.json names another
    trial is refused and its files are never judged as the open trial's stage artifacts (no TRIAL-INVALID)."""
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    other = tmp_path / "other_root"
    plan = json.loads((tmp_path / "s1_out" / "plan.json").read_text(encoding="utf-8"))
    (other / "s1_out").mkdir(parents=True)
    (other / "s1_out" / "plan.json").write_text(json.dumps(dict(plan, trial_id="9a1b2c3d-4e5f-4a6b-8c7d-"
                                                                             "0e1f2a3b4c5d")), encoding="utf-8")
    (other / "s1_out" / "final_plan.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"plan\.json trial_id .* differs from the AUDIT-ACK"):
        t.gate(other, "foreign root")
    assert all(r_.kind != "TRIAL-INVALID" for r_ in jrows(tmp_path))


# ------------------------------------------- fix round 1: decisions on the absence of a row are made under the lock
def _stale(gv, rows):
    """The gate's Gate with an older row snapshot (what a gate read before a concurrent stage committed rows)."""
    return t.Gate(gv.root, gv.out, gv.trial, list(rows), gv.state, gv.mailbox)


def _evaluate_passes(gv):
    """B3: a refusal or INVALID from evaluate() fails the test by assertion (pytest.fail), not by an escaping exit."""
    try:
        sg.evaluate(gv)
    except SystemExit as e:
        pytest.fail(f"evaluate on the stale snapshot refused: {e}")


def _no_invalid(root):
    assert all(r_.kind != "TRIAL-INVALID" for r_ in jrows(root)), [r_.subject for r_ in jrows(root)]


def test_no_intent_in_a_stale_snapshot_is_re_read_under_the_lock_before_invalid(tmp_path, trial, monkeypatch):
    """I1 (F5.1, F4 table "no INTENT"): a gate's snapshot shows no final_plan row; the stage then runs to CREATED;
    evaluate on the stale snapshot must take the stage lock, re-read, find CREATED and pass - never commit
    registration-artifact for a healthy stage."""
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    stale = t.gate(tmp_path, "snapshot")
    assert sg.stage_rows(stale.rows, "final_plan")["intent"] is None
    drive(tmp_path, "final_plan", h.fake_single, monkeypatch)
    assert (tmp_path / "s1_out" / "final_plan.json").is_file()
    _evaluate_passes(stale)
    _no_invalid(tmp_path)


def test_no_intent_in_a_stale_snapshot_with_a_live_owner_is_pending(tmp_path, trial, monkeypatch):
    """I1: the owner has published final_plan.json and holds the stage lock before CREATED (pipe barrier); a stale
    snapshot without its rows gives "pending" (refusal, no row), never INVALID."""
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    before = len(jrows(tmp_path))
    p = child(tmp_path, "final_plan", "hold-before-created")
    try:
        assert (tmp_path / "s1_out" / "final_plan.json").is_file()
        stale = _stale(trial, jrows(tmp_path)[:before])
        with pytest.raises(SystemExit, match="pending"):
            sg.evaluate(stale)
        _no_invalid(tmp_path)
    finally:
        p.stdin.close()
        p.wait(timeout=60)


def test_seal_intent_without_prepared_in_a_stale_snapshot_is_re_read_under_the_lock(tmp_path, trial, monkeypatch):
    """I1 (E2.4 "no PREPARED row" means in the journal): the snapshot is taken while the seal stage works (INTENT
    only); the stage then completes; evaluate on that snapshot re-reads under the lock, finds CREATED, passes."""
    seen = {}

    def work(sw):
        seen["rows"] = jrows(tmp_path)                                   # INTENT committed, no PREPARED yet
        return h.fake_seal(sw)
    drive(tmp_path, SEAL, work, monkeypatch, inputs=h.SEAL_INPUTS, **h.SEAL_FAKES)
    stale = _stale(trial, seen["rows"])
    m = sg.stage_rows(stale.rows, SEAL)
    assert m["intent"] is not None and m["prepared"] is None
    assert (tmp_path / "s1_out" / "seals" / "2026-10-27.json").is_file()
    _evaluate_passes(stale)
    _no_invalid(tmp_path)


def test_seal_intent_without_prepared_in_a_stale_snapshot_with_a_live_owner_is_pending(tmp_path, trial):
    """I1: the seal owner has PREPARED and published seals/<c>.json and holds the lock before CREATED; a snapshot
    without the PREPARED row gives "pending", never registration-artifact."""
    p = child(tmp_path, SEAL, "hold-before-created")
    try:
        rows = jrows(tmp_path)
        assert [r_.kind for r_ in rows][-2:] == ["STAGE-INTENT", "STAGE-PREPARED"]
        assert (tmp_path / "s1_out" / "seals" / "2026-10-27.json").is_file()
        with pytest.raises(SystemExit, match="pending"):
            sg.evaluate(_stale(trial, rows[:-1]))
        _no_invalid(tmp_path)
    finally:
        p.stdin.close()
        p.wait(timeout=60)


def test_a_seal_completed_after_a_rowless_snapshot_is_not_an_artifact(tmp_path, trial, monkeypatch):
    """I1 with SEALS_ENFORCED (as after Task 7): the snapshot has no seal row, the seal stage then completes; the
    on-disk seal file is re-read under the lock and found CREATED, not registration-artifact."""
    monkeypatch.setattr(sg, "SEALS_ENFORCED", True)
    stale = t.gate(tmp_path, "snapshot")
    drive(tmp_path, SEAL, h.fake_seal, monkeypatch, inputs=h.SEAL_INPUTS, **h.SEAL_FAKES)
    _evaluate_passes(stale)
    _no_invalid(tmp_path)


def test_recovery_never_creates_s1_out(tmp_path, trial, monkeypatch):
    """M3 (F6.6): s1_out disappears after the gate's total-loss check, while recovery holds the lock; recovery
    refuses with no row and never recreates s1_out (its absence is the total-loss evidence)."""
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    monkeypatch.setattr(sg, "ENFORCED", frozenset({"final_plan"}))
    h.relax(monkeypatch, "final_plan")
    real_acq = L.OwnershipLock.acquire

    def acquire_then_lose(self):
        res = real_acq(self)
        shutil.rmtree(tmp_path / "s1_out")                              # mid-recovery total loss
        return res
    monkeypatch.setattr(L.OwnershipLock, "acquire", acquire_then_lose)
    with pytest.raises(SystemExit, match=r"s1_out .*refused with no row"):
        t.gate(tmp_path, "recovery")
    assert not (tmp_path / "s1_out").exists()
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED"]


def test_run_never_creates_s1_out(tmp_path, trial, monkeypatch):
    """M3 (F6.6) on the run() path: s1_out disappears after PREPARED, before publication: no member is published,
    s1_out is not recreated, no CREATED (evidence kept; the stage table resolves it later)."""
    def lose(com):
        shutil.rmtree(tmp_path / "s1_out")
    with pytest.raises(SystemExit, match=r"s1_out .*refused with no row"):
        drive(tmp_path, "final_plan", h.fake_single, monkeypatch, before_publish=lose)
    assert not (tmp_path / "s1_out").exists()
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED"]


@pytest.mark.parametrize("case", ["other-bytes-refused", "same-bytes-accepted"])
def test_run_publication_never_overwrites_an_existing_member(tmp_path, trial, monkeypatch, case):
    """Row 88 (M4) on the run() path: a member already in s1_out with other bytes is never overwritten (refusal, no
    CREATED); the same bytes (an earlier partial publication) are accepted and CREATED follows."""
    def pre_create(com):
        dst = tmp_path / "s1_out" / "final_plan.json"
        st = sg.staging_dir(tmp_path, trial.trial.trial_id, "final_plan") / "final_plan.json"
        dst.write_bytes(b'{"other": true}' if case == "other-bytes-refused" else st.read_bytes())
    if case == "other-bytes-refused":
        with pytest.raises(SystemExit, match="never overwritten"):
            drive(tmp_path, "final_plan", h.fake_single, monkeypatch, before_publish=pre_create)
        assert (tmp_path / "s1_out" / "final_plan.json").read_bytes() == b'{"other": true}'
        assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED"]
    else:
        drive(tmp_path, "final_plan", h.fake_single, monkeypatch, before_publish=pre_create)
        assert stage_kinds(tmp_path, "final_plan")[-1] == "STAGE-CREATED"


def test_recover_refuses_unless_this_process_holds_the_stage_lock(tmp_path, trial, monkeypatch):
    """M7: recover() is only valid under the stage lock (F4.7, F5.1); called without it, it refuses with no row."""
    assert child(tmp_path, "final_plan", "die-after-prepared").returncode == 9
    h.relax(monkeypatch, "final_plan")
    m = sg.stage_rows(jrows(tmp_path), "final_plan")
    with pytest.raises(SystemExit, match="stage lock .*not held"):
        sg.recover(trial, "final_plan", m, mailbox=mb(tmp_path))
    assert stage_kinds(tmp_path, "final_plan") == ["STAGE-INTENT", "STAGE-PREPARED"]
    assert not (tmp_path / "s1_out" / "final_plan.json").exists()
