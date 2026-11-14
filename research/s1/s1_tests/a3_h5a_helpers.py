"""A3 H5a test helpers (Erratum 2 Clarifications 2, 3 and 4): the t11 registered fixture (START 2026-10-26T13:30Z,
deadline 2027-04-26T13:30Z, L = d129 2027-04-23, W_L = 2027-04-26T12:00Z, d130 = 2027-04-26, d131 = 2027-04-27), the
pinned refusal texts written out literally (never read from the product constants), spies over every claim, capture,
callback, finalizer, seal stage, stop decision and journal append, and a decision-level harness for the cases no
registered trial can realize (labelled where used). Test-only; never product code."""
import json
import re
import types
from datetime import timedelta
from pathlib import Path

import pytest
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_seal as z
import s1_slot as sl
import s1_stage as sg
import s1_trial as t
from conftest import S1_PROCESS, S1_RECEIPT, Spies, _Clock, s1_ack, s1_state

START = "2026-10-26T13:30:00+00:00"
D0, D1, D129, D130, D131 = "2026-10-26", "2026-10-27", "2027-04-23", "2027-04-26", "2027-04-27"
W_L = c.aware("2027-04-26T12:00:00+00:00")
D_L = W_L + timedelta(minutes=30)
US = timedelta(microseconds=1)


# ------------------------------------------------------------------ the pinned texts (literal, independent of product)
def c2_text(close_date: str) -> str:
    return f"close {close_date} is not an A5.1-eligible session (Clarification 2): no post-START capture"


def c3_text(close_date: str, q) -> str:
    return (f"close {close_date} has a committed QUALIFIED at an earlier registered slot {q.isoformat()}: no later "
            f"slot attempt (Clarification 3)")


def c4_text(s) -> str:
    return f"slot {s.isoformat()} requested before its scheduled instant: no claim (Clarification 4)"


def refused(s, reason: str) -> str:
    """The Worker's refusal text for a SLOT-INTENT refused with no row, as a regex (re.escape'd)."""
    return re.escape(f"{j.slot_subject(s)}: SLOT-INTENT refused with no row: {reason}")


PINNED = re.compile(r"\(Clarification [234]\)")


# ------------------------------------------------------------------ journal reads
def mb(root) -> Path:
    return Path(root) / "mailbox.sqlite3"


def rows(root) -> list:
    trs = t.trials(t.scan(mb(root)))
    (tid,) = [x for x, tr_ in trs.items() if tr_.closed is None]
    return j.read_trial(tid, trs[tid].genesis, mb(root))


def shas(root) -> list:
    return [x.sha for x in rows(root)]


def kinds(root, s) -> list:
    return [x.kind for x in j.subject_rows(rows(root), j.slot_subject(s))]


def invalids(root) -> list:
    return [x.subject for x in rows(root) if x.kind == "TRIAL-INVALID"]


# ------------------------------------------------------------------ fixtures
def registered(root, start=START, **kw):
    """A registered, PREREG-ACKed, ACTIVE trial (no cohort, no post-START seal): s1_state, the real do_prereg, then
    the PREREG-ACK (F7.4). `kw` goes to s1_state (e.g. score_ready / lots for a stop)."""
    if kw.get("score_ready"):
        return s1_state(root, start, stop=False, **kw)
    st_ = s1_state(root, start, **kw)
    with _Clock(st_["prereg_at"]):
        r.do_prereg(root, "run-ack", S1_RECEIPT)
    s1_ack(root, "prereg-ack", "S1-PREREG-ACK", st_["prereg_at"] + timedelta(minutes=1))
    return st_


def day(st_, date: str) -> dict:
    return next(d for d in st_["calendar"] if d["date"] == date)


def slot(st_, date: str, minutes: int = 45):
    return z.close_of(date, st_["calendar"]) + timedelta(minutes=minutes)


def run(root, st_, sch, at, *, receipt=None, process=None):
    """The real scheduled-mode checkpoint for slot `sch` on the fixed clock `at` (a clock callable returning it)."""
    rec = receipt or (lambda reference=None: json.loads(json.dumps(S1_RECEIPT)))
    proc = process or (lambda: dict(S1_PROCESS))
    with _Clock(at):
        return ck.run_checkpoint(root, st_["ledger"].path, sch, rec, proc, Path(root) / "crash.log",
                                 now=lambda: at, mailbox=mb(root))


def attempt(fn, *a, **kw):
    """("ok", result) or ("refused", the SystemExit text)."""
    try:
        return "ok", fn(*a, **kw)
    except SystemExit as e:
        return "refused", str(e)


def qualify(root, st_, sch, at=None):
    """A real capture of slot `sch` through run_checkpoint that must commit SLOT-QUALIFIED."""
    run(root, st_, sch, at or sch + timedelta(seconds=30))
    assert kinds(root, sch) == ["SLOT-INTENT", "SLOT-QUALIFIED"], kinds(root, sch)


def fake_trial(*, prereg=True):
    """A trial stand-in for the decision-level harness: only `acks` is read by the slot gates."""
    return types.SimpleNamespace(acks={"S1-PREREG-ACK": object()} if prereg else {})


def gate_of(st_, *, start=START, prereg=True, trial=None):
    return sl.post_start_gate(trial or fake_trial(prereg=prereg), start=c.aware(start), cal=st_["calendar"])


def product_ctx(cal, slot_gate) -> j.Context:
    """The product's step-5/6 pieces for a decision-level harness: the real slot gate and the real registered slot
    timing (s1_slot.slot_times); CLOSED false (an open trial)."""
    return j.Context(closed=False, slot_times=sl.slot_times(cal), slot_gate=slot_gate)


# ------------------------------------------------------------------ spies
class Watch:
    """Spies over the live callbacks and captures (conftest.Spies), the post-terminal work (_after_terminal, the
    journal finalizer, the seal stage, decide_stop, the W_L route) and every journal append (kind, outcome)."""

    def __init__(self, monkeypatch):
        self.sp = Spies(monkeypatch)
        self.calls = []
        self.appends = []
        for mod, name in ((ck, "_after_terminal"), (ck, "_w_last_route"), (ck, "_finalize_others"),
                          (ck, "_finalize_last_if_due"), (sl, "finalize_close"), (sl, "run_seal_stage"),
                          (z, "decide_stop"), (sg, "run")):
            real = getattr(mod, name)
            monkeypatch.setattr(mod, name, self._wrap(name, real))
        real_append = j.append

        def append(trial_id, gen, req, ctx_fn, **kw):
            res = real_append(trial_id, gen, req, ctx_fn, **kw)
            self.appends.append((req.kind, res.outcome))
            return res
        monkeypatch.setattr(j, "append", append)

    def _wrap(self, name, real):
        def f(*a, **kw):
            self.calls.append(name)
            return real(*a, **kw)
        return f

    def receipt(self):
        return self.sp.receipt()

    def process(self):
        return self.sp.process()

    def written(self) -> list:
        """The appends that committed a row."""
        return [k for k, o in self.appends if o in ("APPEND", "INVALIDATE")]

    def assert_no_work(self):
        """No claim/capture/receipt/process/provider/valuation callback, no post-terminal work, no committed row."""
        self.sp.assert_zero()
        assert self.calls == [], self.calls
        assert self.written() == [], self.appends


def no_files(root, st_, sch) -> bool:
    """No claim, report, resolution or capture directory of slot `sch` exists."""
    d = sl.day_for(sch, st_["calendar"])["date"]
    return not any(p.exists() for p in sl.names(Path(root) / "s1_out", sch, d).values())


def refuse_no_row(root, st_, sch, at, reason, w=None):
    """run_checkpoint(sch) at `at` is refused with exactly the Worker's refusal for `reason`; no row, no file, no work."""
    before = shas(root)
    with pytest.raises(SystemExit, match=refused(sch, reason)):
        run(root, st_, sch, at, **({"receipt": w.receipt(), "process": w.process()} if w else {}))
    assert shas(root) == before
    assert no_files(root, st_, sch)
    if w is not None:
        w.assert_no_work()


# ------------------------------------------------------------------ synthetic rows and capture fixtures
TRIAL, GEN = "3f2b8c1e-5d4a-4b6c-9e7f-0a1b2c3d4e5f", "7" * 64


def synthetic_rows(specs) -> list:
    """Committed-looking rows for a decision-level harness: specs = [(kind, subject, at[, detail])], chained from GEN
    with the frozen F0.2 grammar (no mailbox)."""
    out, prev = [], GEN
    for i, spec in enumerate(specs, start=1):
        kind, subject, at = spec[:3]
        detail = spec[3] if len(spec) > 3 else ("1" * 64 if kind not in j.DETAIL_ABSENT else j.ABSENT)
        ln = j.format_line(trial_id=TRIAL, seq=i, prev=prev, kind=kind, subject=subject, detail=detail,
                           op=f"{i:032x}", actor=f"{i:032x}", at=j.fmt_at(at))
        out.append(j.Row(**j.parse_line(ln), line=ln, mailbox_id=str(i), created=float(i)))
        prev = out[-1].sha
    return out


def synthetic_tree(root, s, day_iso: str, op: str, actor: str) -> str:
    """A synthetic capture fixture of slot `s` (claim, resolution, report and the capture's raw files, each JSON record
    carrying op/actor, OQ-10) and the QUALIFIED detail its tree manifest gives (F3). Test-only."""
    out = Path(root) / "s1_out"
    n = sl.names(out, s, day_iso)
    n["capture"].mkdir(parents=True, exist_ok=True)
    proj = c.canonical({"agent_id": 2, "trades": [], "portfolios": {}, "schema": {}})
    (n["capture"] / "projection.json").write_bytes(proj)
    (n["capture"] / "backup.sqlite3").write_bytes(b"")
    at = (s + timedelta(seconds=30)).isoformat()
    (n["capture"] / "meta.json").write_text(json.dumps({"ok": True, "capture_start": at, "capture_end": at}),
                                            encoding="utf-8")
    who = {"op": op, "actor": actor}
    n["claim"].write_text(json.dumps(dict(who, scheduled=s.isoformat(),
                                          capture_dir=n["capture"].relative_to(out).as_posix())), encoding="utf-8")
    n["resolution"].write_text(json.dumps(dict(who, outcome="SUCCESS", slot=s.isoformat())), encoding="utf-8")
    n["report"].write_text(json.dumps(dict(who, scheduled=s.isoformat(), actual=at)), encoding="utf-8")
    return j.detail_of(sl.qualified_tree(out, s, day_iso))


def qualified_count(root, close_day: dict, cal) -> int:
    """Q(C): the committed SLOT-QUALIFIED rows of the slots of close `close_day`."""
    subs = {j.slot_subject(x) for x in z.schedule(close_day, cal)}
    return sum(1 for x in rows(root) if x.kind == "SLOT-QUALIFIED" and x.subject in subs)


# ------------------------------------------------------------------ Codex b4304771 probes, integrated (rows 524, 547)
def _qualify_synthetic(root, st_, tr, ctx, s, intent, r_):
    """slot `s` (claimed by `intent`) resumes and QUALIFIES with R = `r_` (inside its window, R < D) through the real
    F0.5 arbitration: a synthetic capture fixture, then s1_journal.append with the product Context."""
    cal, d0 = st_["calendar"], day(st_, D0)
    det = synthetic_tree(root, s, D0, intent.op, intent.actor)
    assert r_ < z.resolution_deadline(s, d0, cal) and r_ < z.eligible_until(s, d0, cal)
    res = j.append(tr.trial_id, tr.genesis, j.Request("SLOT-QUALIFIED", j.slot_subject(s), intent.op, intent.actor,
                                                      detail=det, r_at=r_), ctx, mailbox=mb(root), clock=lambda: r_)
    assert res.outcome == "APPEND", res


def probe1_staged_q(root, st_) -> int:
    """Probe 1 as a HISTORICAL (pre-C4) STAGED S1-ONLY fixture: slots C+45 .. C+120 committed INTENT at C+40 (staged
    legacy rows - no production entry point can write them under Clarification 4), each resumes and QUALIFIES at
    s + 30 s through the real arbitration. Returns Q(C)."""
    cal, d0 = st_["calendar"], day(st_, D0)
    cl = z.close_of(D0, cal)
    tr = t.open_trial(mb(root))
    ctx = t.product_context(tr, cal, slot_gate=gate_of(st_, trial=tr))
    from conftest import s1_jstage
    slots_ = [cl + timedelta(minutes=m) for m in (45, 47, 49, 51, 53, 55, 60, 120)]
    intents = [s1_jstage(root, "SLOT-INTENT", j.slot_subject(x), at=cl + timedelta(minutes=40)) for x in slots_]
    for x, i_ in zip(slots_, intents):
        _qualify_synthetic(root, st_, tr, ctx, x, i_, x + timedelta(seconds=30))
    return qualified_count(root, d0, cal)


def probe2_q(root, st_) -> int:
    """Probe 2 through the production Worker (post-START gate, real step-6 timing): q0 = slot C+55, claimed at its s
    and QUALIFIED at C+55m30s (the only claim before it); at C+55m36s slots C+47, 49, 51 and 53 claim (each earlier than
    q0 and before its own E) and all QUALIFY. Returns Q(C)."""
    cal, d0 = st_["calendar"], day(st_, D0)
    cl = z.close_of(D0, cal)
    tr = t.open_trial(mb(root))
    ctx = t.product_context(tr, cal, slot_gate=gate_of(st_, trial=tr))

    def claim(s, at):
        with _Clock(at):
            gv = t.gate(root, f"probe2 claim {s.isoformat()}", defer_pending=True)
            with sl.Worker(gv, s, d0, cal, slot_gate=gate_of(st_, trial=gv.trial), mailbox=mb(root),
                           now=lambda: at) as wk:
                assert wk.intent() is None
                return wk.intent_row
    s55 = cl + timedelta(minutes=55)
    _qualify_synthetic(root, st_, tr, ctx, s55, claim(s55, s55), s55 + timedelta(seconds=30))
    at = s55 + timedelta(seconds=36)
    claims = [(s, claim(s, at)) for s in (cl + timedelta(minutes=m) for m in (47, 49, 51, 53))]
    for s, i_ in claims:
        _qualify_synthetic(root, st_, tr, ctx, s, i_, at + timedelta(seconds=20))
    return qualified_count(root, d0, cal)
