"""Task 12 fix round 2, controller ruling on fix-round-1 concern 1 (I-1 completion, Addendum 1 A1.1 "membership AND
sha256 of every file"): the bound receipt's closure members are compared by raw sha256 BEFORE any parse; a changed
file is a semantic change (terminal). Written BEFORE the fix (RED: s1_evidence/t12_fix2_I1_red.txt). Synthetic
repos only (tmp_path)."""
from datetime import datetime, timedelta, timezone

import pytest

import s1_checkpoint as ck
import s1_receipt as rc
from conftest import S1_PROCESS, _Clock
from test_s1_t12_a1 import ROOTS, contract, repo
from test_s1_t12_fix1 import START_DT, _reg

UTC = timezone.utc
MON = datetime(2026, 10, 26, 20, 0, tzinfo=UTC)


class ParseSpy:
    def __init__(self, monkeypatch):
        self.n = 0
        real = rc._parse

        def spy(f):
            self.n += 1
            return real(f)
        monkeypatch.setattr(rc, "_parse", spy)


def _rec(root, **kw):
    return rc.semantic_receipt(root, root / ".env", None, roots=ROOTS, contract=contract(), **kw)


def test_i1_an_unchanged_closure_against_the_bound_reference_gives_the_same_fingerprint(tmp_path):
    """A1.1: with the bound reference passed, an unchanged repo yields the identical fingerprint."""
    root = repo(tmp_path)
    ref = _rec(root)
    assert _rec(root, reference=ref)["fingerprint"] == ref["fingerprint"]


@pytest.mark.parametrize("change", ["edited", "merge-conflict", "deleted"])
def test_i1_a_changed_closure_member_is_terminal_before_any_parse(tmp_path, monkeypatch, change):
    """A1.1 (controller ruling): membership + raw sha256 of every bound member are compared BEFORE any parse: an
    edited (still valid), merge-conflicted or deleted member is a terminal semantic change and nothing is parsed."""
    root = repo(tmp_path)
    ref = _rec(root)
    mr = root / "backend" / "agents" / "mean_reversion_agent.py"
    if change == "edited":
        mr.write_text(mr.read_text() + "# a valid edit\n")
    elif change == "merge-conflict":
        mr.write_text("<<<<<<< HEAD\nx = 1\n=======\n")
    else:
        mr.unlink()
    spy = ParseSpy(monkeypatch)
    with pytest.raises(rc.ReceiptError) as e:
        _rec(root, reference=ref)
    assert e.value.terminal is True and "agents/mean_reversion_agent.py" in str(e.value)
    assert spy.n == 0, "a closure file was parsed before the raw membership/sha256 comparison"


def test_i1_the_checkpoint_passes_the_bound_reference_and_a_valid_edit_aborts(tmp_path, monkeypatch):
    """A1.1/A9.2: mid-trial the checkpoint hands the registered receipt to the receipt function; a valid edit of an
    MR file is a terminal change -> ABORTED-INVALID without parsing the changed file."""
    root = repo(tmp_path / "live")
    seen = {}

    def receipt(reference=None):
        seen["reference"] = reference
        return _rec(root, reference=reference)
    ref = _rec(root)
    st_ = _reg(tmp_path, ref)
    mr = root / "backend" / "agents" / "mean_reversion_agent.py"
    mr.write_text(mr.read_text() + "# a valid edit\n")
    spy = ParseSpy(monkeypatch)
    sch = MON + timedelta(minutes=45)
    act = sch + timedelta(seconds=30)
    with _Clock(act):
        rep = ck.run_checkpoint(tmp_path, st_["ledger"].path, sch, receipt, lambda: dict(S1_PROCESS),
                                tmp_path / "crash.log", now=lambda: act)
    assert seen["reference"] is not None and seen["reference"]["fingerprint"] == ref["fingerprint"]
    assert rep["stop"]["status"] == "ABORTED-INVALID" and rep["seal"]["written"] is False
    assert spy.n == 0
