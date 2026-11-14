"""A3 H4 row 439 (Codex 799fc940 RM-1, controller-accepted): the arithmetic of the row-439 verdict - C = L + T per run,
READY only if max(C) <= 60 s over every declared healthy run with its success control completed. The rule is test
tooling (s1_evidence/a3/m4_workload/verdict_rule.py), loaded here by path; row 439 itself is a measurement gate, not
a unit-test PASS. Codex's examples: L=20/T=45 fails although T alone passes; equality; just over the cap; unknown
lateness; a fast refusal; a negative L."""
import importlib.util
from pathlib import Path

import pytest

_P = Path(__file__).resolve().parents[1] / "s1_evidence" / "a3" / "m4_workload" / "verdict_rule.py"
_spec = importlib.util.spec_from_file_location("m4_verdict_rule", _P)
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def run(L, T, ok=True, i="r"):
    return {"id": i, "L": L, "T": T, "control_ok": ok}


def test_l20_t45_fails_although_t_alone_passes():
    got = v.verdict([run(20.0, 45.0)])
    assert got["verdict"] == "NOT READY" and got["max_C"] == 65.0 and got["max_T"] == 45.0
    assert any("65.000 s > 60 s" in x for x in got["reasons"])


def test_equality_passes():
    assert v.verdict([run(15.0, 45.0)]) == {"verdict": "READY", "max_C": 60.0, "max_T": 45.0, "reasons": []}


def test_just_over_the_cap_fails():
    got = v.verdict([run(0.0, 60.001)])
    assert got["verdict"] == "NOT READY" and got["max_C"] == pytest.approx(60.001)


def test_unknown_lateness_is_not_ready():
    got = v.verdict([run(None, 10.0)])
    assert got["verdict"] == "NOT READY" and got["max_C"] is None
    assert got["reasons"] == ["run r: dispatch delay L unknown"]


def test_fast_refusal_is_not_a_pass():
    got = v.verdict([run(0.1, 0.4, ok=False, i="refused"), run(1.0, 20.0, i="ok")])
    assert got["verdict"] == "NOT READY"
    assert got["reasons"] == ["run refused: success control not completed (a fast refusal or skip is not a pass)"]


def test_negative_l_is_inconsistent_never_clamped():
    got = v.verdict([run(-0.5, 30.0)])
    assert got["verdict"] == "NOT READY" and got["max_C"] is None
    assert "negative" in got["reasons"][0] and "never clamped" in got["reasons"][0]


def test_max_over_all_runs_and_unresolved_workload():
    assert v.verdict([run(1.0, 30.0), run(2.0, 50.0)])["max_C"] == 52.0
    assert v.verdict([run(1.0, 30.0)], workloads_resolved=False)["verdict"] == "NOT READY"
    assert v.verdict([])["verdict"] == "NOT READY"


def test_b_conditional_labels():
    runs = [run(None, 40.0), run(None, 45.0)]
    assert v.b_conditional(runs, None)["label"] == "NOT READY"                  # B unknown: R-3 unresolved
    assert v.b_conditional(runs, None)["max_T"] == 45.0
    got = v.b_conditional(runs, 15.0, workloads_resolved=True, injected_resolved=True)  # (fix round 1, M-5: stated)
    assert got["label"] == "B-CONDITIONAL READY" and got["max_T_plus_B"] == 60.0       # equality passes
    assert v.b_conditional(runs, 15.5)["label"] == "B-CONDITIONAL NOT READY"
    assert v.b_conditional(runs + [run(None, 1.0, ok=False)], 1.0)["label"] == "B-CONDITIONAL NOT READY"
    assert v.b_conditional(runs, -1.0)["label"] == "NOT READY"


def test_b_conditional_requires_resolved_workloads_and_injected_cases():
    """H4 fix round 1 (review M-5): B-CONDITIONAL never reads READY while a declared workload bound or the injected
    cases are unresolved; both default to unresolved (fail closed)."""
    runs = [run(None, 40.0), run(None, 45.0)]
    got = v.b_conditional(runs, 15.0)                                         # max(T) + B = 60 s: within the cap
    assert got["label"] == "B-CONDITIONAL NOT READY", got
    assert any("workload" in r for r in got["reasons"]) and any("injected" in r for r in got["reasons"]), got
    assert v.b_conditional(runs, 15.0, workloads_resolved=True)["label"] == "B-CONDITIONAL NOT READY"
    assert v.b_conditional(runs, 15.0, injected_resolved=True)["label"] == "B-CONDITIONAL NOT READY"
    ok = v.b_conditional(runs, 15.0, workloads_resolved=True, injected_resolved=True)
    assert ok["label"] == "B-CONDITIONAL READY" and ok["reasons"] == [], ok
    nb = v.b_conditional(runs, None, workloads_resolved=False, injected_resolved=False)
    assert nb["label"] == "NOT READY" and any("workload" in r for r in nb["reasons"]), nb
