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


# --------------------------------------------------------------------- A3 H4-CX (Codex H4-CX-1 / P2): numeric validation
# T, L and B count only as real, non-bool, finite, >= 0 numbers; the cap must be finite and > 0. Anything else is NOT
# READY with a reason naming the run and the field - never READY, never an unhandled exception. max_T / max_C are over
# valid values only. Each call is wrapped (B3: a RED is an assertion, never an escaping TypeError).
import math  # noqa: E402


def call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:                                     # noqa: BLE001 - asserted to be absent below
        return e


def not_ready(got, *needles):
    assert isinstance(got, dict), f"raised instead of reporting: {got!r}"
    label = got.get("verdict", got.get("label"))
    assert label in ("NOT READY", "B-CONDITIONAL NOT READY"), got
    for n in needles:
        assert any(n in x for x in got["reasons"]), (n, got["reasons"])
    return got


@pytest.mark.parametrize("field,value", [("T", float("nan")), ("L", float("nan")), ("T", float("inf")),
                                         ("T", True), ("T", "5"), ("L", float("-inf")), ("L", False)],
                         ids=["nan-T", "nan-L", "inf-T", "bool-T", "string-T", "neg-inf-L", "bool-L"])
def test_verdict_invalid_observation_is_not_ready(field, value):
    r = run(0.0, 1.0, i="bad")
    r[field] = value
    got = not_ready(call(v.verdict, [r, run(0.0, 2.0, i="good")]), "run bad", f"{field} ")
    assert got["max_T"] == 2.0 and got["max_C"] == 2.0, got                 # over the valid values only
    assert all(isinstance(x, float) and math.isfinite(x) for x in (got["max_T"], got["max_C"]) if x is not None)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "5", -1.0],
                         ids=["nan-T", "inf-T", "bool-T", "string-T", "negative-T"])
def test_b_conditional_invalid_t_is_not_ready(value):
    got = not_ready(call(v.b_conditional, [run(None, value, i="bad"), run(None, 10.0, i="good")], 0.0,
                         workloads_resolved=True, injected_resolved=True), "run bad", "T ")
    assert got["max_T"] == 10.0, got
    alone = not_ready(call(v.b_conditional, [run(None, value, i="bad")], 0.0, workloads_resolved=True,
                           injected_resolved=True), "run bad", "T ")
    assert alone["max_T"] is None and alone.get("max_T_plus_B") is None, alone      # never computed from it


@pytest.mark.parametrize("b", [float("nan"), float("inf"), -1.0, True, "1"],
                         ids=["nan-B", "inf-B", "negative-B", "bool-B", "string-B"])
def test_b_conditional_invalid_b_is_not_ready(b):
    not_ready(call(v.b_conditional, [run(None, 1.0)], b, workloads_resolved=True, injected_resolved=True), "B ")


@pytest.mark.parametrize("cap", [float("nan"), float("inf"), 0.0, -60.0, True],
                         ids=["nan-cap", "inf-cap", "zero-cap", "negative-cap", "bool-cap"])
def test_invalid_cap_is_not_ready_in_both_routes(cap):
    not_ready(call(v.verdict, [run(0.0, 1.0)], cap=cap), "cap")
    not_ready(call(v.b_conditional, [run(None, 1.0)], 0.0, workloads_resolved=True, injected_resolved=True,
                   cap=cap), "cap")


def test_cap_boundary_exact_and_next_float():
    assert call(v.verdict, [run(0.0, 60.0)])["verdict"] == "READY"
    not_ready(call(v.verdict, [run(0.0, math.nextafter(60.0, math.inf))]), "> 60 s")
    ok = call(v.b_conditional, [run(None, 60.0)], 0.0, workloads_resolved=True, injected_resolved=True)
    assert ok["label"] == "B-CONDITIONAL READY", ok
    not_ready(call(v.b_conditional, [run(None, math.nextafter(60.0, math.inf))], 0.0, workloads_resolved=True,
                   injected_resolved=True), "> 60 s")
