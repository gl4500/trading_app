"""A3 H4 row 439 (Erratum 2 r4 G3.7, O10; Codex 799fc940 RM-1): the readiness verdict over measured runs. Test tooling,
never product. Pure functions: no clock, no file, no network.

Per run (RM-1):
- L = launch - due (dispatch delay, seconds, from wall-clock instants). None = unknown; a negative L is INCONSISTENT
  and is reported as such - never clamped to zero.
- T = launch -> required completion (seconds, monotonic clock).
- C = L + T.
Verdict: READY only if every declared healthy run completed its success control (a fast refusal or a skip is not a
pass), has a known, non-negative L, and C <= CAP (60 s; equality passes), and every declared workload bound is resolved.
Otherwise NOT READY. Per-gate timings are diagnostics only (no per-gate cap; nothing nested is summed).
B-CONDITIONAL (RM-1): when the driver cannot observe scheduler dispatch, a PREDECLARED conservative lateness bound B
(seconds) may be used only to report max(T) + B under that label; with B unknown or unjustified the dispatch bound
(R-3) is unresolved and the verdict is NOT READY.

A3 H4-CX (Codex H4-CX-1 / P2): in both routes T, L and B count only as a real number that is not a bool, finite and
>= 0 (`valid`); the cap must be finite and > 0 (`cap_problem`). An invalid observation is NOT READY with a reason
naming the run and the field - never READY and never an unhandled exception; an invalid cap is NOT READY with a
reason. max_T / max_C are computed over valid values only (an invalid one is listed in the reasons instead)."""
import math
import numbers

CAP = 60.0


def _real(x) -> bool:
    """A finite real number that is not a bool (the sign is checked by the caller). H4-CX fix round 1 (review M-1):
    an int beyond the float range (math.isfinite raises OverflowError) is no usable value either."""
    try:
        return isinstance(x, numbers.Real) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:
        return False


def valid(x) -> bool:
    """A3 H4-CX: a usable timing value - real, not bool, finite and >= 0."""
    return _real(x) and x >= 0


def cap_problem(cap):
    """None for a usable cap (real, not bool, finite, > 0); else the NOT READY reason."""
    return None if _real(cap) and cap > 0 else f"cap invalid ({cap!r}): not a finite real number > 0"


def _t_problem(t):
    """None for a valid T; else why (missing/negative keep their wording; anything else is an invalid value)."""
    if valid(t):
        return None
    if t is None or (_real(t) and t < 0):
        return f"invocation duration T unavailable or negative ({t!r})"
    return f"invocation duration T invalid ({t!r}): not a finite real number"


def run_c(run: dict):
    """(C, problem) for one run: problem None when C is defined. A3 H4-CX: T and L are validated first (an invalid
    value is named even for a run whose control did not complete), then the control, then T, then L."""
    t, lat = run.get("T"), run.get("L")
    if t is not None and not _real(t):
        return None, _t_problem(t)
    if lat is not None and not _real(lat):
        return None, f"dispatch delay L invalid ({lat!r}): not a finite real number"
    if not run.get("control_ok"):
        return None, "success control not completed (a fast refusal or skip is not a pass)"
    if _t_problem(t) is not None:
        return None, _t_problem(t)
    if lat is None:
        return None, "dispatch delay L unknown"
    if lat < 0:
        return None, f"dispatch delay L negative ({lat!r}): inconsistent (never clamped)"
    c = lat + t
    if not math.isfinite(c):
        return None, f"C = L + T not finite ({c!r})"
    return c, None


def verdict(runs: list, *, workloads_resolved: bool = True, cap: float = CAP) -> dict:
    """RM-1 verdict over the declared healthy runs: {"verdict": "READY"|"NOT READY", "max_C", "max_T", "reasons"}."""
    reasons, cs = [], []
    bad_cap = cap_problem(cap)                              # A3 H4-CX: never compared against an invalid cap
    if bad_cap is not None:
        reasons.append(bad_cap)
    if not runs:
        reasons.append("no declared healthy run")
    for i, r in enumerate(runs):
        c, why = run_c(r)
        if why is not None:
            reasons.append(f"run {r.get('id', i)}: {why}")
        else:
            cs.append(c)
            if bad_cap is None and c > cap:
                reasons.append(f"run {r.get('id', i)}: C = L + T = {c:.3f} s > {cap:g} s")
    if not workloads_resolved:
        reasons.append("a declared workload bound is unresolved")
    ts = [r["T"] for r in runs if valid(r.get("T"))]        # A3 H4-CX: valid values only
    return {"verdict": "NOT READY" if reasons else "READY", "max_C": max(cs, default=None),
            "max_T": max(ts, default=None), "reasons": reasons}


def b_conditional(runs: list, b, *, workloads_resolved: bool = False, injected_resolved: bool = False,
                  cap: float = CAP) -> dict:
    """RM-1 B-CONDITIONAL report: max(T) + B over the declared healthy runs whose controls completed. `b` None (unknown
    or unjustified) leaves R-3 unresolved: NOT READY, with max(T) still reported.
    H4 fix round 1 (review M-5): the label is never READY while a declared workload bound (`workloads_resolved`) or
    the injected cases (`injected_resolved`) are unresolved. Both default to False (unresolved: fail closed), so a
    caller must state them explicitly to obtain "B-CONDITIONAL READY"."""
    invalid = [f"run {r.get('id', i)}: {_t_problem(r.get('T'))}" for i, r in enumerate(runs)    # A3 H4-CX: an
               if r.get("T") is not None and not valid(r.get("T"))]                                 # invalid T named
    ok = [r for r in runs if r.get("control_ok") and valid(r.get("T"))]                             # valid T only
    bad = [r.get("id", i) for i, r in enumerate(runs) if not (r.get("control_ok") and r.get("T") is not None)]
    max_t = max((r["T"] for r in ok), default=None)
    bad_cap = [] if cap_problem(cap) is None else [cap_problem(cap)]
    open_ = ([] if workloads_resolved else ["a declared workload bound is unresolved"]) + \
        ([] if injected_resolved else ["the injected cases are unresolved (not run or not passed)"])
    if b is None:
        return {"label": "NOT READY", "max_T": max_t, "B": None,
                "reasons": ["no predeclared, justified dispatch-lateness bound B: R-3 unresolved"]
                + [f"run {x}: success control not completed" for x in bad] + invalid + bad_cap + open_}
    if not _real(b):                                         # A3 H4-CX: NaN / inf / bool / non-number B
        return {"label": "NOT READY", "max_T": max_t, "B": b,
                "reasons": [f"B invalid ({b!r}): not a finite real number"] + invalid + bad_cap + open_}
    if b < 0:
        return {"label": "NOT READY", "max_T": max_t, "B": b, "reasons": [f"B negative ({b!r}): inconsistent"]
                + invalid + bad_cap + open_}
    if bad_cap:                                              # A3 H4-CX: never compared against an invalid cap
        return {"label": "NOT READY", "max_T": max_t, "B": b, "reasons": bad_cap + invalid + open_}
    reasons = [f"run {x}: success control not completed" for x in bad] + invalid
    if max_t is None:
        reasons.append("no completed healthy run")
    elif max_t + b > cap:
        reasons.append(f"max(T) + B = {max_t + b:.3f} s > {cap:g} s")
    reasons += open_
    return {"label": "B-CONDITIONAL NOT READY" if reasons else "B-CONDITIONAL READY", "max_T": max_t, "B": b,
            "max_T_plus_B": None if max_t is None else max_t + b, "reasons": reasons}
