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
(R-3) is unresolved and the verdict is NOT READY."""

CAP = 60.0


def run_c(run: dict):
    """(C, problem) for one run: problem None when C is defined."""
    if not run.get("control_ok"):
        return None, "success control not completed (a fast refusal or skip is not a pass)"
    t = run.get("T")
    if t is None or t < 0:
        return None, f"invocation duration T unavailable or negative ({t!r})"
    lat = run.get("L")
    if lat is None:
        return None, "dispatch delay L unknown"
    if lat < 0:
        return None, f"dispatch delay L negative ({lat!r}): inconsistent (never clamped)"
    return lat + t, None


def verdict(runs: list, *, workloads_resolved: bool = True, cap: float = CAP) -> dict:
    """RM-1 verdict over the declared healthy runs: {"verdict": "READY"|"NOT READY", "max_C", "max_T", "reasons"}."""
    reasons, cs = [], []
    if not runs:
        reasons.append("no declared healthy run")
    for i, r in enumerate(runs):
        c, why = run_c(r)
        if why is not None:
            reasons.append(f"run {r.get('id', i)}: {why}")
        else:
            cs.append(c)
            if c > cap:
                reasons.append(f"run {r.get('id', i)}: C = L + T = {c:.3f} s > {cap:g} s")
    if not workloads_resolved:
        reasons.append("a declared workload bound is unresolved")
    ts = [r["T"] for r in runs if r.get("T") is not None]
    return {"verdict": "NOT READY" if reasons else "READY", "max_C": max(cs, default=None),
            "max_T": max(ts, default=None), "reasons": reasons}


def b_conditional(runs: list, b, *, workloads_resolved: bool = False, injected_resolved: bool = False,
                  cap: float = CAP) -> dict:
    """RM-1 B-CONDITIONAL report: max(T) + B over the declared healthy runs whose controls completed. `b` None (unknown
    or unjustified) leaves R-3 unresolved: NOT READY, with max(T) still reported.
    H4 fix round 1 (review M-5): the label is never READY while a declared workload bound (`workloads_resolved`) or
    the injected cases (`injected_resolved`) are unresolved. Both default to False (unresolved: fail closed), so a
    caller must state them explicitly to obtain "B-CONDITIONAL READY"."""
    ok = [r for r in runs if r.get("control_ok") and r.get("T") is not None]
    bad = [r.get("id", i) for i, r in enumerate(runs) if not (r.get("control_ok") and r.get("T") is not None)]
    max_t = max((r["T"] for r in ok), default=None)
    open_ = ([] if workloads_resolved else ["a declared workload bound is unresolved"]) + \
        ([] if injected_resolved else ["the injected cases are unresolved (not run or not passed)"])
    if b is None:
        return {"label": "NOT READY", "max_T": max_t, "B": None,
                "reasons": ["no predeclared, justified dispatch-lateness bound B: R-3 unresolved"]
                + [f"run {x}: success control not completed" for x in bad] + open_}
    if b < 0:
        return {"label": "NOT READY", "max_T": max_t, "B": b, "reasons": [f"B negative ({b!r}): inconsistent"] + open_}
    reasons = [f"run {x}: success control not completed" for x in bad]
    if max_t is None:
        reasons.append("no completed healthy run")
    elif max_t + b > cap:
        reasons.append(f"max(T) + B = {max_t + b:.3f} s > {cap:g} s")
    reasons += open_
    return {"label": "B-CONDITIONAL NOT READY" if reasons else "B-CONDITIONAL READY", "max_T": max_t, "B": b,
            "max_T_plus_B": None if max_t is None else max_t + b, "reasons": reasons}
