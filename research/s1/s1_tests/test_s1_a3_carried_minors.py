"""A3 H5c carried minors (no map row): H1 M-1 (the five write_abort callers surface their own refusal or INVALID -
OutputRootGone never replaces it), H1 M-2 (record_refusal never creates s1_out: a vanished root refuses with no row,
I-3) and H5a-FIX concern 4 (Worker normalizes an aware non-UTC slot to UTC, so names() and the late/ paths are UTC
wall time). The root vanishes INSIDE the real publisher (the barrier wraps the real helper and forwards every
keyword), after every caller check. Behavioural RED against base 864ecc2 (s1_evidence/a3/h5c_red.txt)."""
import json
import re
import shutil
import types
from datetime import timedelta, timezone
from pathlib import Path

import pytest
import a3_h5a_helpers as h
import s1_checkpoint as ck
import s1_common as c
import s1_journal as j
import s1_slot as sl
import s1_trial as t
from conftest import _Clock

T = c.aware("2026-10-27T21:00:00+00:00")
GONE = "local abort not published: s1_out is gone"
JOURNAL_DOWN = ("violation (registration-artifact) observed but the journal could not be written (Outage): refused; "
                "local abort not published (s1_out is gone); F8.1 residual (lost detection if it never commits)")


def vanish_in_publisher(monkeypatch, out: Path, seen: list):
    """The root disappears inside the real publisher, after any caller's is_dir() check (row 468's barrier)."""
    real = c.publish_exclusive

    def vanish(path, data, **kw):
        if Path(path).name == "aborted.json" and out.exists():
            seen.append(kw.get("mkdir"))
            shutil.rmtree(out)
        return real(path, data, **kw)
    monkeypatch.setattr(c, "publish_exclusive", vanish)


def _gv(tmp_path, out):
    return types.SimpleNamespace(trial=object(), root=tmp_path, out=out, mailbox=None)


def _invalidate(outcome):
    """invalidate()'s two observable outcomes at these sites: the journal-failure Refusal, or a committed row."""
    def f(*a, **kw):
        if outcome == "journal-down":
            raise t.Refusal(JOURNAL_DOWN)
        return j.Result("APPEND", "", None, [])
    return f


SITES = ["qualified-violation-journal-down", "qualified-violation-committed", "worker-violation-journal-down",
         "worker-violation-committed", "opening-seal-conflict", "bundle-gate", "registration-gate",
         "registration-gate-no-refuse"]


@pytest.mark.parametrize("site", SITES)
def test_write_abort_callers_root_gone_keeps_the_original_outcome(tmp_path, monkeypatch, site):   # H1 M-1
    """Each of the five write_abort callers that let OutputRootGone escape (two of them from a `finally:` that masked
    the primary Refusal): the original refusal - or, after a committed INVALID, the site's INVALID refusal / return -
    is what surfaces; OutputRootGone never replaces it, and s1_out is never recreated (F6.6, I-3). The three non-
    `finally` sites append that the local abort was not published."""
    out = tmp_path / "s1_out"
    out.mkdir()
    seen = []
    vanish_in_publisher(monkeypatch, out, seen)
    if site.startswith("qualified-violation"):
        monkeypatch.setattr(t, "invalidate", _invalidate("journal-down" if site.endswith("down") else "committed"))
        want = (re.escape(JOURNAL_DOWN) if site.endswith("down") else
                r"^seal selection refused: slot/x: QUALIFIED tree differs \(F3\): INVALID \(registration-artifact\)$")
        with pytest.raises(BaseException, match=want) as ei:
            ck._qualified_violation(_gv(tmp_path, out), None, out, ValueError("slot/x: QUALIFIED tree differs (F3)"),
                                    lambda: T)
        assert isinstance(ei.value, SystemExit)
        assert isinstance(ei.value, t.Refusal) == site.endswith("down")
    elif site.startswith("worker-violation"):
        monkeypatch.setattr(t, "invalidate", _invalidate("journal-down" if site.endswith("down") else "committed"))
        w = sl.Worker.__new__(sl.Worker)
        w.gv, w.slot, w.subject, w.mailbox, w.now = _gv(tmp_path, out), T, j.slot_subject(T), None, lambda: T
        rep = {"close": T.isoformat(), "scheduled": T.isoformat(), "actual": T.isoformat(), "snapshot": None}
        if site.endswith("down"):
            with pytest.raises(BaseException, match=re.escape(JOURNAL_DOWN)) as ei:
                w.violation("receipt", "semantic receipt changed", rep, "a" * 64)
            assert isinstance(ei.value, t.Refusal)
        else:                                            # the INVALID committed: the caller's display path follows
            try:
                got = w.violation("receipt", "semantic receipt changed", rep, "a" * 64)
            except BaseException as e:                   # (B3: an assertion, never a traceback)
                pytest.fail(f"violation() raised {type(e).__name__}: {e} after a committed INVALID")
            assert got is None
    elif site == "opening-seal-conflict":
        monkeypatch.setattr(c, "_report_seals", lambda out_, rows=None, **kw: [
            ("seals/2026-10-23.json", out_ / "seals" / "2026-10-23.json", "a" * 64)])
        with pytest.raises(BaseException, match=r"^opening refused: seals/2026-10-23\.json: the selected opening seal "
                                                rf"b{{64}} differs .*persistent ABORTED-INVALID \(reason registration "
                                                rf"artifact\) \({GONE}\)$") as ei:
            ck._before_opening_seal(out, "2026-10-23", "b" * 64, T, rows=[])
        assert type(ei.value) is ck._OpeningSealConflict
    elif site == "bundle-gate":
        with pytest.raises(BaseException, match=r"^probe refused: S1 bundle [0-9a-f]{12} differs from the registered "
                                                rf"000000000000: persistent ABORTED-INVALID \(reason bundle\) "
                                                rf"\({GONE}\)$") as ei:
            c.bundle_gate(out, "0" * 64, registered=True, where="probe", now=lambda: T)
        assert type(ei.value) is SystemExit
    else:
        monkeypatch.setattr(c, "registration_problems", lambda *a, **kw: ["plan.json changed since opening"])
        committed = []
        monkeypatch.setattr(t, "invalidate_current", lambda *a, **kw: committed.append(a[1]))
        with pytest.raises(BaseException, match=r"^probe refused: registration artifact\(s\) missing or changed: "
                                                r"\['plan\.json changed since opening'\]: persistent ABORTED-INVALID "
                                                rf"\(reason registration artifact\) \({GONE}\)$") as ei:
            c.registration_gate(out, "probe", lambda: T, refuse=site == "registration-gate")
        assert type(ei.value) is SystemExit and committed == ["registration-artifact"]
    assert seen == [False]                                # the real helper ran, with mkdir=False, inside the barrier
    assert not out.exists()                               # never recreated (F6.6)


# ---------------------------------------------------------------- H1 M-2: record_refusal never creates s1_out
@pytest.mark.parametrize("case", ["root-missing-at-entry", "root-vanishes-after-the-caller-check"])
def test_record_refusal_never_creates_s1_out(tmp_path, monkeypatch, capsys, case):                # H1 M-2 (I-3)
    """B3.2's refusal record is written only INTO an existing s1_out; a root missing on entry, or vanishing between
    s1_trial._record's is_dir() check and the write (the race), is never recreated: the refusal still stands (no row,
    nothing written) and its text goes to stderr instead."""
    out = tmp_path / "s1_out"
    if case == "root-missing-at-entry":
        assert c.record_refusal(out, "probe", "the refusal text") is None
    else:
        out.mkdir()
        real = c.record_refusal

        def race(out_, *a, **kw):
            shutil.rmtree(out_)                                   # after the caller's check-then-act guard
            return real(out_, *a, **kw)
        monkeypatch.setattr(c, "record_refusal", race)
        with pytest.raises(t.Refusal, match=r"^probe refused: the refusal text$"):
            t._refuse(out, "probe", "the refusal text", lambda: T)
    assert not out.exists() and sorted(p.name for p in tmp_path.iterdir() if p.name == "s1_out") == []
    assert "S1 probe refusal not recorded (s1_out absent): the refusal text" in capsys.readouterr().err


def test_record_refusal_appends_into_an_existing_root(tmp_path):                                   # H1 M-2 (ctrl)
    out = tmp_path / "s1_out"
    out.mkdir()
    c.record_refusal(out, "probe", "first", lambda: T)
    c.record_refusal(out, "probe", "second", lambda: T)
    recs = [json.loads(x) for x in (out / "refusals.jsonl").read_text(encoding="utf-8").splitlines()]
    assert recs == [{"where": "probe", "refused": m, "utc": T.isoformat()} for m in ("first", "second")]
    assert sorted(p.name for p in out.iterdir()) == ["refusals.jsonl"]


# ---------------------------------------------------------------- H5a-FIX concern 4: names() from the UTC instant
NY4 = timezone(timedelta(hours=-4))


def _utc_name(s) -> str:
    return s.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def test_non_utc_slot_names_files_by_utc_wall_time(tmp_path, monkeypatch):                         # H5a-FIX c4
    """A direct caller past the early refusal passes the registered slot as an aware -04:00 instant: the Worker
    normalizes it to UTC (decision: normalize, never refuse - h5c_old_new.md), so every slot file is named by the UTC
    wall time and the QUALIFIED tree is the one the journal subject names. (Base: files named by local wall time.)"""
    st_ = h.registered(tmp_path)
    s45 = h.slot(st_, h.D0)
    local = s45.astimezone(NY4)
    assert local.isoformat().endswith("-04:00") and local == s45 and _utc_name(local) != local.strftime("%Y%m%dT%H%M%SZ")
    got = h.attempt(h.run, tmp_path, st_, local, s45 + timedelta(seconds=30))
    assert got[0] == "ok", got
    assert h.kinds(tmp_path, s45) == ["SLOT-INTENT", "SLOT-QUALIFIED"]
    d = tmp_path / "s1_out" / "captures" / h.D0
    utc, wall = _utc_name(s45), local.strftime("%Y%m%dT%H%M%SZ")
    n = sl.names(tmp_path / "s1_out", s45, h.D0)
    assert all(p.exists() for k_, p in n.items()), {k_: p.exists() for k_, p in n.items()}
    assert all(p.name.startswith(utc) for p in n.values())
    assert [p.name for p in d.iterdir() if p.name.startswith(wall)] == []          # no local-wall-time name
    assert json.loads(n["claim"].read_text(encoding="utf-8"))["scheduled"] == s45.isoformat()


def test_non_utc_slot_late_paths_use_utc_wall_time(tmp_path, monkeypatch):                          # H5a-FIX c4
    """The Worker's LOST-RACE path moves its own files to late/<day>/<UTC slot>/ (harness: the completion append is
    answered LOST-RACE; every other step is the real Worker)."""
    st_ = h.registered(tmp_path)
    s45 = h.slot(st_, h.D0)
    local = s45.astimezone(NY4)
    at = s45 + timedelta(seconds=30)
    with _Clock(at):
        gv = t.gate(tmp_path, "direct worker", defer_pending=True)
        with sl.Worker(gv, local, h.day(st_, h.D0), st_["calendar"],
                       slot_gate=sl.post_start_gate(gv.trial, start=c.aware(h.START), cal=st_["calendar"]),
                       mailbox=h.mb(tmp_path), now=lambda: at) as wk:
            assert wk.intent() is None
            real = wk._append
            wk._append = lambda req: (j.Result("LOST-RACE", "simulated", None, []) if req.kind == "SLOT-FAILED"
                                      else real(req))
            got = wk.complete({"scheduled": local.isoformat(), "close": None}, success=False)
    assert got["outcome"] == "LOST-RACE"
    late = tmp_path / "s1_out" / "late" / h.D0
    assert [p.name for p in late.iterdir()] == [_utc_name(s45)]
    moved = sorted(p.name for p in (late / _utc_name(s45)).iterdir())
    assert moved and all(x.startswith(_utc_name(s45)) for x in moved), moved
