"""S1 Task 9: targeted semantic mutants (structure copied from e1_evidence/e1_r2_mutants.py). Each mutant is applied
to an isolated copy of the S1 sources (s1_*.py + the pinned e1_sim.py / e1_fetch.py) and the FULL s1_tests suite
runs there with -x, in parallel; KILLED = a test fails. The real source files are never modified; every temp dir
is removed. Usage: python s1_evidence/s1_mutants.py [WORKERS] [NAME_FILTER[|NAME_FILTER...]]
(env S1M_TESTS='node ...' runs only those tests: an intent check, not the evidence run)"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = Path("C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe")
B, Z, K, R, RUN, COL = "s1_books.py", "s1_seal.py", "s1_checkpoint.py", "s1_receipt.py", "s1_run.py", "s1_collect.py"

M = {
    # ---------------------------------------------------------------- books (§7-8)
    "sold: strict < 0.001 -> <=": [(B, 'and l["rem_qty"] < limit and', 'and l["rem_qty"] <= limit and')],
    "write-off: strict < 0.001 -> <=": [(B, "        elif q < lt:\n", "        elif q <= lt:\n")],
    "sold event without requiring a SELL allocation": [
        (B, 'if n > prev_fills.get(l["id"], 0) and l["rem_qty"]', 'if l["rem_qty"]')],
    "sold event not absorbing (a later SELL re-dates it)": [
        (B, ' and l["id"] not in events:', ':')],
    "operational write-off at the end instead of at each SELL": [
        (B, "        elif q < lt:\n            if q > 0:\n                writeoffs.append({\"id\": r[\"id\"], \"symbol\": s, "
            "\"qty\": float(q)})\n            q = Fraction(0)\n        qty[s] = q\n",
         "        qty[s] = q\n    for s, q in list(qty.items()):\n        if 0 < q < lt:\n"
         "            writeoffs.append({\"id\": None, \"symbol\": s, \"qty\": float(q)})\n            qty[s] = Fraction(0)\n")],
    "oversell beyond OP_OVERSELL_TOL raises instead of recording an anomaly": [
        (B, '            anomalies.append({"id": r["id"], "symbol": s, "qty": float(q)})\n',
         '            raise BookError(f"oversell by trade {r[\'id\']}")\n')],
    # ---------------------------------------------------------------- consistency / seals (§6)
    "consistency on as-of rows instead of the full set": [
        (K, 'rep["consistent"] = b.consistency(proj["trades"], proj["portfolios"])["consistent"]',
         'rep["consistent"] = b.consistency([t for t in proj["trades"] if c.aware(t["ts"]) <= c.aware(rep["close"])], '
         'proj["portfolios"])["consistent"]')],
    "seal from a non-registered slot (slack 10 min -> 600 min)": [
        (Z, "SCHEDULE_SLACK = timedelta(minutes=10)", "SCHEDULE_SLACK = timedelta(minutes=600)")],
    "seal from a non-registered slot (choose_seal skips slot membership)": [
        (Z, "        if sch in slots and sch <= act", "        if sch <= act")],
    "seal from an inconsistent capture (choose_seal ignores consistent)": [
        (Z, ' and cap["ok"] and cap["consistent"]:', ' and cap["ok"]:')],
    "seal from an inconsistent capture (scheduled checkpoint gate)": [
        (K, '    if (already is None and proj is not None and rep["consistent"] and rep["receipt_match"]',
         '    if (already is None and proj is not None and rep["receipt_match"]')],
    "seal from an inconsistent capture (opening checkpoint gate)": [
        (K, '    if proj is not None and rep["consistent"] and not rep["fence_violations"]:',
         '    if proj is not None and not rep["fence_violations"]:')],
    "unsealed close allowed to stop (latest seal's rows used)": [
        (Z, '            continue\n        if count_sold(s["trades"], start, close) >= STOP_N:',
         '            s = by_close[max(by_close)] if by_close else None\n            if s is None:\n                continue\n'
         '        if count_sold(s["trades"], start, close) >= STOP_N:')],
    "stop_decision without the today check (seal after today accepted)": [
        (Z, "        if k > today:\n", "        if False:\n")],
    "backdated row ignored": [
        (Z, '            if str(i) not in fenced and c.aware(t["ts"]) <= c.aware(s["close"]):', "            if False:")],
    "deleted sealed row ignored": [(Z, '(f"sealed row {i} deleted" if i not in now', '(None if i not in now')],
    "bridge rows in the cohort": [
        (Z, 'if t["action"] == "BUY" and start <= c.aware(t["ts"]) <= close]',
         'if t["action"] == "BUY" and c.aware(t["ts"]) <= close]')],
    "bridge row classified with <= START": [
        (Z, 'if c.aware(t["ts"]) < start], [t for t in rs if c.aware(t["ts"]) >= start]',
         'if c.aware(t["ts"]) <= start], [t for t in rs if c.aware(t["ts"]) > start]')],
    "bridge hash not compared across seals": [
        (Z, '            for s in post[1:] if s["bridge"]["bridge_sha256"] != want]', "            for s in post[1:] if False]")],
    # ---------------------------------------------------------------- deadline (§9)
    "deadline = START + 180 days": [
        (Z, "    d = start.astimezone(c.NY).date()\n    m = d.month + 6\n",
         "    return (start.astimezone(c.NY) + timedelta(days=180)).date()\n    d = start.astimezone(c.NY).date()\n"
         "    m = d.month + 6\n")],
    "deadline without the month-end clamp (overflow into the next month)": [
        (Z, "    return date(y, m, min(d.day, pycal.monthrange(y, m)[1]))",
         "    return date(y, m, 1) + timedelta(days=d.day - 1)")],
    # ---------------------------------------------------------------- receipt / process (§12)
    "receipt includes secret keys": [(R, "    return sorted(k for k in keys if not SECRET.search(k))", "    return sorted(keys)")],
    "PID-change gap ignored": [(R, "    elif ppid is not None and opid != ppid and opid not in new_pids:", "    elif False:")],
    # ---------------------------------------------------------------- checkpoint (§10, Task 7b)
    "checkpoint emitting a price field": [
        (K, '    rep["snapshot"] = meta["projection_sha256"]\n',
         '    rep["snapshot"] = meta["projection_sha256"]\n'
         '    rep["last_price"] = proj["trades"][-1]["price"] if proj["trades"] else None\n')],
    "opening checkpoint accepts a non-opening slot": [
        (K, "    if scheduled not in slots:\n        raise SystemExit(f\"opening refused:",
         "    if False:\n        raise SystemExit(f\"opening refused:")],
    "opening checkpoint accepts a non-opening close": [
        (K, '    if not prior or prior[-1]["date"] != plan.get("opening_close"):', "    if not prior:")],
    "opening_receipt written after the seal": [
        (K, "            _try_seal(out, day, cal, close, rep, meta, cap_dir, proj, rec, proc, receipt_sha,\n"
            "                      before_seal=lambda: _store_opening_receipt(rp, receipt))",
         "            if _try_seal(out, day, cal, close, rep, meta, cap_dir, proj, rec, proc, receipt_sha):\n"
         "                _store_opening_receipt(rp, receipt)")],
    "final snapshot retried after an ok attempt": [
        (K, '    if (d / "report.json").exists() or ok_attempts(d):', '    if (d / "report.json").exists():')],
    # ---------------------------------------------------------------- runner rules (§11, §14)
    "exclusion window shortened to the actual exit": [
        (RUN, "            elif ed < d <= stop_date:", '            elif ed < d <= l.get("_exit_date", stop_date):'),
        (RUN, "    ex = exclusions(cohort, actions,",
         "    _sold = b.sold_events(asof)\n    for _l in cohort:\n        if _l[\"id\"] in _sold:\n"
         "            _l[\"_exit_date\"] = _ny_day(c.aware(_sold[_l[\"id\"]][\"sold_at\"]))\n"
         "    ex = exclusions(cohort, actions,")],
    "undated action ignored (per-lot exclusions)": [
        (RUN, "            if d is None:\n                why.append(f\"undated {a.get('type')} {a.get('id')}\")",
         "            if d is None:\n                pass")],
    "acquirer side blocking": [
        (RUN, '        return a.get("acquiree_symbol") == sym',
         '        return sym in (a.get("acquiree_symbol"), a.get("acquirer_symbol"))')],
    "stop close not required for endpoint-day entries": [
        (RUN, "    return req if stop_date in req else req + [stop_date]", "    return req")],
    "cap 10K > N -> >=": [(RUN, "    if 10 * k_ > n:", "    if 10 * k_ >= n:")],
    "INSUFFICIENT at N-K = 30": [(RUN, "    if n - k_ < MIN_RETAINED:", "    if n - k_ <= MIN_RETAINED:")],
    "UNVERIFIED-PROVENANCE pass nominated": [
        (RUN, '"nomination": numeric == "SHADOW PASS" and prov == "VERIFIED"}', '"nomination": numeric == "SHADOW PASS"}')],
    "NO-VALID-SEAL reported as FAIL": [(RUN, '        return done("NO-VALID-SEAL", attest)', '        return done("FAIL", attest)')],
    "prereg after START allowed": [(RUN, "    if c.now_utc() >= start:\n", "    if False:\n")],
    "duplicate score allowed": [
        (RUN, '    k._reserve(out / "score", ack)\n', '    (out / "score").mkdir(parents=True, exist_ok=True)\n'),
        (RUN, '    _write_text_once(out / "score" / "s1.json", text)\n',
         '    (out / "score" / "s1.json").write_text(text, encoding="utf-8")\n')],
    "reservation after computing": [
        (RUN, '    k._reserve(out / "score", ack)\n    try:\n', "    try:\n"),
        (RUN, '        _write_text_once(out / "score" / "s1.json", _serialise(rep))\n',
         '        k._reserve(out / "score", ack)\n        _write_text_once(out / "score" / "s1.json", _serialise(rep))\n'),
        (RUN, '    _write_text_once(out / "score" / "s1.json", text)\n    return',
         '    k._reserve(out / "score", ack)\n    _write_text_once(out / "score" / "s1.json", text)\n    return')],
    "score ignores a missing final-snapshot report while an ok attempt exists": [
        (RUN, '        return [f"final snapshot: report.json missing or unreadable',
         '        return [] and [f"final snapshot: report.json missing or unreadable')],
    "SCORE_ACK not binding final_snapshot_sha256": [
        (RUN, 'snap=_sha_or_absent(out / "final_snapshot" / "report.json"))', "snap=ABSENT)")],
    "score skips _bridge_problems": [
        (RUN, "    invalid += _bridge_problems(rep, [s for _, s in seals], asof, start, cal)",
         "    _bridge_problems(rep, [s for _, s in seals], asof, start, cal)")],
}

SOURCES = sorted(p.name for p in ROOT.glob("s1_*.py")) + ["e1_sim.py", "e1_fetch.py"]
ORIG = {f: (ROOT / f).read_text(encoding="utf-8") for f in SOURCES}
HASHES = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in SOURCES}


def mutate(name, edits) -> dict:
    out = {}
    for f, a, b in edits:
        cur = out.get(f, ORIG[f])
        assert cur.count(a) == 1, (name, f, cur.count(a), a[:70])
        out[f] = cur.replace(a, b)
    return out


def one(item):
    name, edits = item
    changed = mutate(name, edits)
    d = Path(tempfile.mkdtemp(prefix="s1m_"))
    try:
        for f in SOURCES:
            shutil.copy(ROOT / f, d / f)
        for f, text in changed.items():
            (d / f).write_text(text, encoding="utf-8")
        shutil.copytree(ROOT / "s1_tests", d / "s1_tests", ignore=shutil.ignore_patterns("__pycache__"))
        tests = os.environ.get("S1M_TESTS", "").split() or ["s1_tests"]        # diagnostic: intended test only
        r = subprocess.run([str(PY), "-m", "pytest", *tests, "-q", "-x", "-p", "no:cacheprovider"], cwd=d,
                           capture_output=True, text=True, timeout=1800)
        first = next((l.split(" ")[1] for l in r.stdout.splitlines() if l.startswith("FAILED")), "")
        tag = "KILLED" if r.returncode == 1 else "SURVIVED" if r.returncode == 0 else f"ERROR(rc={r.returncode})"
        return f"{tag}  {name}  {first}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    filt = sys.argv[2] if len(sys.argv) > 2 else ""
    items = [(n, e) for n, e in M.items() if any(f in n for f in filt.split("|"))]
    for n, e in items:                                        # every edit applies exactly once, before any run
        mutate(n, e)
    print("sources: " + ", ".join(f"{f} {HASHES[f][:12]}" for f in SOURCES))
    print("tests: " + ", ".join(f"{p.name} {hashlib.sha256(p.read_bytes()).hexdigest()[:12]}"
                                for p in sorted((ROOT / "s1_tests").glob("*.py"))))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, items))
    print("\n".join(res))
    print(f"{sum(r.startswith('KILLED') for r in res)}/{len(res)} killed")
