"""S1 runner (§11–15): lifecycle gates and ACKs, attestations, carry-in unit trust, per-lot paired exclusions,
economics from the pinned E1 core, verdict and report. Never touches the live app or trading.db."""
import json
import re
import sqlite3
from datetime import date
from fractions import Fraction
from pathlib import Path

import s1_books as b
import s1_collect as k
import s1_common as c
import s1_seal as z

RUN_ACK = ("S1-RUN-ACK runner_sha256={runner} plan_sha256={plan} audit_manifest_sha256={audit} "
           "attest_start_sha256={attest} start={start}")
SCORE_ACK = ("S1-SCORE-ACK runner_sha256={runner} final_manifest_sha256={final} stop_attest_sha256={attest} "
             "final_snapshot_sha256={snap}")
START_STATEMENT = "I confirm the trading_app backend runs from the recorded checkout, started after the S1 receipt."
STOP_STATEMENT = ("I confirm that between START and the stop no MeanReversion code, config or package changed "
                  "(including changed and reverted) and no MeanReversion trade was placed or edited by hand.")
BPS = (0, 1, 5, 10)
GATE_BPS = (5, 10)
MIN_RETAINED = 30                     # §14 (= e1_sim.MIN_LOTS)
TRIAL_ID = "S1"
ABSENT = "absent"                     # SCORE_ACK placeholder for an artifact that does not exist
BLOCKING_TYPES = {"forward_splits", "reverse_splits", "unit_splits", "spin_offs", "rights_distributions",
                  "cash_mergers", "stock_mergers", "stock_and_cash_mergers", "stock_dividends", "redemptions",
                  "worthless_removals", "name_changes"}
SYMBOL_FIELDS = ("symbol", "old_symbol", "new_symbol", "alternate_symbol", "acquiree_symbol", "source_symbol")
DATE_FIELDS = ("ex_date", "effective_date", "process_date")
AUDIT_FILES = ("calendar.json", "corporate_actions.json", "ca_problems.json")
FINAL_FILES = ("bars.json", "bar_problems.json", "corporate_actions.json", "ca_problems.json")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Invalid(Exception):
    """A protocol/integrity failure: a refusal at a gate, ABORTED-INVALID at the score."""


def runner_sha() -> str:
    return c.sha256_file(Path(__file__).resolve())


# ------------------------------------------------------------------ pure rules (§11, §14)
def _valid_date(v) -> bool:
    if not (isinstance(v, str) and _ISO_DATE.match(v)):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _date(a):
    """Effective date of an action: the first VALID date among ex/effective/process date; None = undated."""
    return next((a[f] for f in DATE_FIELDS if _valid_date(a.get(f))), None)


def blocks(a, sym) -> bool:
    """§11: any split kind (symbol/old/new/alternate), spin-off/rights SOURCE, ACQUIREE of any merger, stock dividend,
    redemption, worthless removal, identity change (old_symbol), special cash dividend. Acquirer side does not block.
    Unknown types naming the symbol (any symbol field, acquirer included) block."""
    t = a.get("type")
    if t == "cash_dividends":
        return a.get("symbol") == sym and a.get("special") is not False
    if t in ("spin_offs", "rights_distributions"):
        return a.get("source_symbol") == sym
    if t in ("cash_mergers", "stock_mergers", "stock_and_cash_mergers"):
        return a.get("acquiree_symbol") == sym
    if t == "name_changes":
        return a.get("old_symbol") == sym
    if t in BLOCKING_TYPES:
        return sym in {a.get(f) for f in ("symbol", "old_symbol", "new_symbol", "alternate_symbol")}
    named = {a.get(f) for f in SYMBOL_FIELDS + ("acquirer_symbol",)} | set(a.get("affected_symbols") or [])
    return sym in named


def required_sessions(entry_date, stop_date, sessions) -> list:
    req = [s for s in sessions if entry_date < s <= stop_date]
    return req if stop_date in req else req + [stop_date]


NOT_UNIT_IDENTITY = {"cash_dividends", "spin_offs", "rights_distributions"}     # ruling M-1: per-lot only


def unit_identity(a, sym) -> bool:
    """Ruling M-1: the FIFO-untrust triggers - forward/reverse/unit splits, stock dividends, name changes
    (old_symbol), acquiree-side mergers, redemptions, worthless removals, and unknown types naming the symbol.
    Special cash dividends and spin-off/rights sources are ordinary per-lot exclusions only."""
    return a.get("type") not in NOT_UNIT_IDENTITY and blocks(a, sym)


def open_lots_before(rows, day: str) -> list:
    """Economic-FIFO lots (dust residuals included) still open after replaying the rows whose stored-time NY date
    is strictly before `day`: the lots open across `day`."""
    sim = c.sim()
    before = [t for t in rows if sim.ny_date(c.aware(t["ts"])) < day]
    if not before:
        return []
    end = max(r_["ts"] for r_ in b.rows(before))
    return [l for l in b.economic_lots(before, end) if l["rem_qty"] > 0]


def fifo_untrusted(rows, actions, start_day: str, stop_date: str) -> dict:
    """Controller ruling (Task 7, C-2 / M-1): for every unit/identity action dated inside the trial window (START
    session .. stop session, inclusive) on a symbol with ANY economic-FIFO lot (cohort or carry-in, dust residual
    included) open across that date, FIFO attribution of that symbol's SELLs is untrusted: {symbol: [reasons]}."""
    out = {}
    for a in actions:
        d = _date(a)
        if d is None or not (start_day <= d <= stop_date):
            continue
        for l in open_lots_before(rows, d):
            if unit_identity(a, l["symbol"]):
                why = f"FIFO attribution untrusted after {a.get('id')} on {d}"
                if why not in out.setdefault(l["symbol"], []):
                    out[l["symbol"]].append(why)
    return out


def exclusions(lots, actions, problems, stop_date, sessions, bars, bar_problems, *, untrusted=None) -> dict:
    """§11 paired exclusion window per lot: entry NY date EXCLUSIVE .. stop session INCLUSIVE (both arms); undated
    or problem records block every lot of the symbol; every required bar (post-entry sessions + the stop close)
    must exist and be unflagged. `untrusted` ({symbol: [reasons]}, from fifo_untrusted) excludes every lot of the
    symbol."""
    sim = c.sim()
    blocked = {s for p in problems for s in p.get("blocks_symbols", [])}
    flagged = {(p.get("symbol"), p.get("session")) for p in bar_problems}
    out = {}
    for l in lots:
        s, ed, why = l["symbol"], sim.ny_date(l["entry_ts"]), []
        if s in blocked:
            why.append("corporate-action problem record")
        why += (untrusted or {}).get(s, [])
        for a in actions:
            if not blocks(a, s):
                continue
            d = _date(a)
            if d is None:
                why.append(f"undated {a.get('type')} {a.get('id')}")
            elif ed < d <= stop_date:
                why.append(f"{a.get('type')} {a.get('id')} on {d}")
        for d in required_sessions(ed, stop_date, sessions):
            if bars.get(s, {}).get(d) is None or (s, d) in flagged:
                why.append(f"missing or flagged bar {d}")
        if why:
            out[l["id"]] = why
    return out


def disposition(n: int, k_: int) -> str:
    """§14 order: N = 0 -> INSUFFICIENT; 10*K > N -> INCONCLUSIVE (exactly 10 % allowed); N - K < 30 ->
    INSUFFICIENT; else OK."""
    if n == 0:
        return "INSUFFICIENT"
    if 10 * k_ > n:
        return "INCONCLUSIVE"
    if n - k_ < MIN_RETAINED:
        return "INSUFFICIENT"
    return "OK"


def carry_in_reasons(held_at_start: dict, actions, held_since: dict, *, problems=(), until=None, start_day=None,
                     open_across=None) -> list:
    """Why carry-in units are untrusted: a blocking action (or an undated one) on a symbol held at START, dated on/
    after the date its oldest open lot was bought (and, when `until` is given, no later than it), or a problem
    record blocking that symbol. Ruling I-3: when `open_across(sym, day)` is given, an action dated on/after
    `start_day` counts only if a carry-in lot of the symbol was still open across that date (a lot held at START
    and bought before a pre-START action date was necessarily held across it)."""
    bad_syms = {s for p in problems for s in p.get("blocks_symbols", [])}
    out = []
    for sym in sorted(held_at_start):
        if not held_at_start[sym] > 0:
            continue
        if sym in bad_syms:
            out.append(f"carry-in {sym}: corporate-action problem record")
        since = held_since.get(sym)
        for a in actions:
            if not blocks(a, sym):
                continue
            d = _date(a)
            if d is None:
                out.append(f"carry-in {sym}: undated {a.get('type')} {a.get('id')}")
            elif (since is None or d >= since) and (until is None or d <= until) and not (
                    open_across is not None and start_day is not None and d >= start_day
                    and not open_across(sym, d)):
                out.append(f"carry-in {sym}: {a.get('type')} {a.get('id')} on {d} (held since {since})")
    return out


def carry_in_status(held_at_start: dict, actions, held_since: dict, phase: str, *, problems=(), until=None) -> str:
    if phase not in ("audit", "final"):
        raise ValueError(f"unknown phase {phase!r}")
    if carry_in_reasons(held_at_start, actions, held_since, problems=problems, until=until):
        return "BLOCKED" if phase == "audit" else "INCONCLUSIVE"
    return "OK"


def candidate_economics(lot, path, stop_date, bp) -> dict:
    sim = c.sim()
    r = sim.simulate_lot(entry_ts=lot["entry_ts"], entry_px=lot["entry_px"], qty=lot["qty"], bars=path, splits=[],
                         policy=c.p13(), endpoint_date=stop_date)
    kind = "terminal" if r["reason"] == "endpoint" else "exit"
    return dict(sim.lot_economics(entry_notional=lot["entry_notional"], exits=[(r["shares_x"], r["exit_px_x"], kind)],
                                  bp=bp), reason=r["reason"], exit_date=r["exit_date"],
                eligible_sessions=r["eligible_sessions"])


def final_verdict(numeric: str, attest_stop) -> dict:
    prov = "VERIFIED" if attest_stop and attest_stop.get("ok") else "UNVERIFIED-PROVENANCE"
    return {"verdict": numeric, "provenance": prov, "nomination": numeric == "SHADOW PASS" and prov == "VERIFIED"}


# ------------------------------------------------------------------ files, ACKs, shared readers
def _out(root) -> Path:
    return Path(root) / "s1_out"


def _load(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _sha_or_absent(p: Path) -> str:
    return c.sha256_file(p) if p.exists() else ABSENT


def _receipt_sha(receipt) -> str:
    return c.sha256_bytes(c.canonical(receipt))


def _ack(root, ack_id: str, token: str) -> dict:
    """s1_collect._ack (codex->claude experiments-prereg, standalone exact line, not in the future); an unreadable
    mailbox is a refusal too."""
    try:
        return k._ack(root, ack_id, token)
    except sqlite3.Error as e:
        raise SystemExit(f"mailbox unreadable ({type(e).__name__}): refusing") from None


def run_token(root) -> str:
    out = _out(root)
    plan = _load(out / "plan.json")
    return RUN_ACK.format(runner=runner_sha(), plan=c.sha256_file(out / "plan.json"),
                          audit=c.sha256_file(out / "audit" / "manifest.json"),
                          attest=_sha_or_absent(out / "attest_start.json"), start=plan["planned_start"])


def score_token(root) -> str:
    out = _out(root)
    return SCORE_ACK.format(runner=runner_sha(), final=_sha_or_absent(out / "final" / "manifest.json"),
                            attest=_sha_or_absent(out / "attest_stop.json"),
                            snap=_sha_or_absent(out / "final_snapshot" / "report.json"))   # Task 7b ruling 1


def _attempt(d: Path, names) -> tuple:
    """A COMPLETE collector attempt whose named files match the manifest's hashes -> (manifest, {name: content})."""
    mp = d / "manifest.json"
    if not mp.exists():
        raise Invalid(f"{d.name}: no manifest")
    m = _load(mp)
    if m.get("outcome") != "COMPLETE":
        raise Invalid(f"{d.name} attempt outcome is {m.get('outcome')!r}, not COMPLETE")
    files, got = m.get("files") or {}, {}
    for n in names:
        p = d / n
        if n not in files or not p.exists() or c.sha256_file(p) != files[n]:
            raise Invalid(f"{d.name}/{n} missing or differs from its manifest hash")
        got[n] = _load(p)
    return m, got


def _calendar(raw) -> list:
    return [{"date": x["date"], "open": x["open"], "close": x["close"]} for x in raw]


def _ny_day(t) -> str:
    return t.astimezone(c.NY).date().isoformat()


def _opening_seal(out: Path, plan: dict, calendar) -> tuple:
    """§4/§6: the opening seal = the seal of the session immediately before planned START (plan opening_close)."""
    sd = _ny_day(c.aware(plan["planned_start"]))
    prior = sorted(d["date"] for d in calendar if d["date"] < sd)
    if not prior or prior[-1] != plan.get("opening_close"):
        raise Invalid("plan opening_close is not the session immediately before planned START")
    p = out / "seals" / f"{prior[-1]}.json"
    if not p.exists():
        raise Invalid(f"opening seal {prior[-1]} missing")
    seal = _load(p)
    if c.aware(seal["close"]) != z.close_of(prior[-1], calendar):
        raise Invalid("opening seal close is not the opening session's close")
    return p, seal


def _carry_in(rows_before_start, start) -> tuple:
    """Opening inventory at START from rows stored before START: symbols with an open economic-FIFO lot (dust
    residuals included) or an operational holding, and the NY date its oldest open lot was bought."""
    sim = c.sim()
    held, since = {}, {}
    for l in b.economic_lots(rows_before_start, start):
        if l["rem_qty"] > 0:
            s, d = l["symbol"], sim.ny_date(l["entry_ts"])
            held[s] = held.get(s, 0.0) + float(l["rem_qty"])
            since[s] = min(since.get(s, d), d)
    first = {}
    for r_ in b.rows(rows_before_start):
        first.setdefault(r_["symbol"], sim.ny_date(r_["ts"]))
    for s, q in b.operational_replay(rows_before_start)["qty"].items():
        if q > 0 and s not in held:
            held[s], since[s] = q, first[s]
    return held, since


def _coverage_reasons(held: dict, since: dict, covered, history_start: str) -> list:
    """Carry-in identity/units the corporate-action request did not cover (symbol absent, or window starting after
    the symbol's oldest open lot)."""
    out = []
    for s in sorted(held):
        if s not in covered:
            out.append(f"carry-in {s}: not covered by the corporate-action request")
        elif since.get(s) is not None and history_start > since[s]:
            out.append(f"carry-in {s}: request starts {history_start}, after its oldest open lot ({since[s]})")
    return out


def _write_once(path: Path, obj, what: str):
    try:
        k._write_once(path, obj)
    except FileExistsError:
        raise SystemExit(f"{what} already recorded: refusing") from None


def _opening_receipt(out: Path, opening_seal: dict) -> dict:
    """Task 7b: s1_out/opening_receipt.json, written by the opening checkpoint; it must hash to the opening seal's
    receipt_sha256."""
    p = out / "opening_receipt.json"
    if not p.exists():
        raise SystemExit("START attestation refused: no opening receipt (run s1_checkpoint.py --opening first)")
    rec = _load(p)
    if opening_seal.get("receipt_sha256") != _receipt_sha(rec):
        raise SystemExit("START attestation refused: the opening receipt does not match the opening seal's "
                         "receipt_sha256")
    return rec


# ------------------------------------------------------------------ gates (§12, §15)
def attest_start(root, statement: str, receipt) -> dict:
    """START attestation (§12): before RUN-ACK/prereg and strictly before planned START; binds trial ID, planned
    START, the semantic receipt, the plan, the COMPLETE audit and the opening seal."""
    if statement != START_STATEMENT:
        raise SystemExit("START attestation refused: the statement must be exactly START_STATEMENT")
    out = _out(root)
    plan = _load(out / "plan.json")
    if c.now_utc() >= c.aware(plan["planned_start"]):
        raise SystemExit("planned START has passed: re-register")
    if (out / "attest_start.json").exists():
        raise SystemExit("START attestation already recorded: refusing")
    try:
        _, files = _attempt(out / "audit", AUDIT_FILES)
        seal_p, seal = _opening_seal(out, plan, _calendar(files["calendar.json"]))
    except Invalid as e:
        raise SystemExit(f"START attestation refused: {e}") from None
    opening_receipt = _opening_receipt(out, seal)                     # Task 7b: the receipt the opening sealed with
    if receipt != opening_receipt:
        raise SystemExit("START attestation refused: the receipt differs from the opening receipt "
                         "(s1_out/opening_receipt.json)")
    rec = {"statement": statement, "trial_id": TRIAL_ID, "planned_start": plan["planned_start"],
           "receipt_sha256": _receipt_sha(opening_receipt), "plan_sha256": c.sha256_file(out / "plan.json"),
           "audit_manifest_sha256": c.sha256_file(out / "audit" / "manifest.json"),
           "opening_seal_sha256": c.sha256_file(seal_p), "recorded_utc": c.now_utc().isoformat()}
    _write_once(out / "attest_start.json", rec, "START attestation")
    return rec


def _start_attestation_problems(out: Path, att: dict, plan: dict, seal_p: Path, receipt) -> list:
    want = {"statement": START_STATEMENT, "trial_id": TRIAL_ID, "planned_start": plan["planned_start"],
            "plan_sha256": c.sha256_file(out / "plan.json"),
            "audit_manifest_sha256": c.sha256_file(out / "audit" / "manifest.json"),
            "opening_seal_sha256": c.sha256_file(seal_p), "receipt_sha256": _receipt_sha(receipt)}
    return [f"START attestation {key} does not match" for key, v in want.items() if att.get(key) != v]


def do_prereg(root, ack_id: str, receipt) -> dict:
    """Prereg (§4/§15): strictly before planned START, after a COMPLETE audit and the START attestation, never with
    a BLOCKED carry-in, under the exact RUN-ACK. Writes s1_out/prereg.json once (start, calendar, receipt + bindings)."""
    out = _out(root)
    plan = _load(out / "plan.json")
    start = c.aware(plan["planned_start"])
    if c.now_utc() >= start:
        raise SystemExit("planned START has passed: re-register")
    if (out / "prereg.json").exists():
        raise SystemExit("prereg already recorded: refusing")
    try:
        _, files = _attempt(out / "audit", AUDIT_FILES)
    except Invalid as e:
        raise SystemExit(f"prereg refused: audit not COMPLETE ({e})") from None
    ap = out / "attest_start.json"
    if not ap.exists():
        raise SystemExit("prereg refused: no START attestation recorded")
    cal = _calendar(files["calendar.json"])
    try:
        seal_p, seal = _opening_seal(out, plan, cal)
    except Invalid as e:
        raise SystemExit(f"prereg refused: {e}") from None
    bad = _start_attestation_problems(out, _load(ap), plan, seal_p, receipt)
    if bad:
        raise SystemExit(f"prereg refused: {bad} (receipt or bound artifacts changed since the START attestation)")
    try:
        held, since = _carry_in(z.split_bridge(seal["trades"], start)[0], start)
    except b.BookError as e:
        raise SystemExit(f"prereg refused: opening ledger unreadable ({e})") from None
    reasons = (_coverage_reasons(held, since, set(plan["ca_symbols"]), plan["ca_range"][0])
               + carry_in_reasons(held, files["corporate_actions.json"], since, problems=files["ca_problems.json"]))
    if reasons:
        try:
            k._write_once(out / "blocked.json", {"status": "BLOCKED", "reasons": reasons,
                                                 "recorded_utc": c.now_utc().isoformat()})
        except FileExistsError:
            pass
        raise SystemExit(f"S1 BLOCKED (pre-START units): {reasons}; re-register")
    ack = _ack(root, ack_id, run_token(root))
    if c.aware(ack["created_utc"]) <= c.aware(_load(ap)["recorded_utc"]):         # §12 causal order (ruling I-2)
        raise SystemExit("prereg refused: the RUN-ACK is not strictly after the START attestation")
    pr = {"trial_id": TRIAL_ID, "start": plan["planned_start"], "calendar": cal, "receipt": receipt,
          "runner_sha256": runner_sha(), "plan_sha256": c.sha256_file(out / "plan.json"),
          "audit_manifest_sha256": c.sha256_file(out / "audit" / "manifest.json"),
          "attest_start_sha256": c.sha256_file(ap), "ack": ack, "recorded_utc": c.now_utc().isoformat()}
    _write_once(out / "prereg.json", pr, "prereg")
    return pr


def _seals(out: Path) -> list:
    return [(p, _load(p)) for p in sorted((out / "seals").glob("*.json"))]


def attest_stop(root, statement: str) -> dict:
    """Stop attestations (§12): after a recorded stop (STOPPED/TIMEOUT from the seals), before the final acquisition
    and any score; binds the START attestation, the actual START and stop and the sealed final ledger (stop seal)."""
    if statement != STOP_STATEMENT:
        raise SystemExit("stop attestation refused: the statement must be exactly STOP_STATEMENT")
    out = _out(root)
    if not (out / "prereg.json").exists():
        raise SystemExit("stop attestation refused: no prereg (the trial never started)")
    if (out / "aborted.json").exists():
        raise SystemExit("stop attestation refused: the trial is ABORTED-INVALID")
    if (out / "final").exists() or (out / "score").exists():
        raise SystemExit("stop attestation refused: it must precede the final acquisition and the score")
    pr = _load(out / "prereg.json")
    try:
        stop = z.stop_decision([s for _, s in _seals(out)], c.aware(pr["start"]), pr["calendar"],
                               today=c.now_utc())
    except ValueError as e:
        raise SystemExit(f"stop attestation refused: bad seal record ({e})") from None
    if stop["status"] not in ("STOPPED", "TIMEOUT"):
        raise SystemExit(f"stop attestation refused: no stop recorded (status {stop['status']})")
    stop_p = out / "seals" / f"{_ny_day(c.aware(stop['stop_close']))}.json"
    rec = {"statement": statement, "trial_id": TRIAL_ID,
           "attest_start_sha256": c.sha256_file(out / "attest_start.json"), "start": pr["start"],
           "stop_close": stop["stop_close"], "stop_status": stop["status"],
           "sealed_final_ledger_sha256": c.sha256_file(stop_p), "recorded_utc": c.now_utc().isoformat()}
    _write_once(out / "attest_stop.json", rec, "stop attestation")
    return rec


# ------------------------------------------------------------------ score (§13–14)
def _clean(obj):
    """JSON-ready copy: '_'-prefixed (exact) keys dropped, keys as str, Fractions as floats, instants as ISO."""
    if isinstance(obj, dict):
        return {str(key): _clean(v) for key, v in obj.items() if not (isinstance(key, str) and key.startswith("_"))}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, Fraction):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def score(root, ack_id: str) -> dict:
    """One exclusive score (§15): exact SCORE-ACK, then the reservation (exclusive), then computation; the report
    s1_out/score/s1.json is written once. A refused ACK or a second attempt writes nothing."""
    out = _out(root)
    ack = _ack(root, ack_id, score_token(root))
    if not (out / "prereg.json").exists():
        raise SystemExit("no prereg: the trial never started; nothing to score")
    _pre_reserve_gate(out, ack)
    k._reserve(out / "score", ack)
    try:
        text = _serialise(_score(out))                    # ruling M-6: serialise before opening the output file
    except (Exception, SystemExit) as e:                  # one attempt: the failure itself is the preserved record
        rep = {"trial_id": TRIAL_ID, "outcome": "ABORTED", "verdict": "ABORTED-INVALID", "provenance": None,
               "nomination": False, "reasons": [f"score error: {type(e).__name__}: {e}"]}
        _write_text_once(out / "score" / "s1.json", _serialise(rep))
        raise SystemExit(f"score ABORTED ({type(e).__name__}); attempt preserved, see s1_out/score/s1.json") from None
    _write_text_once(out / "score" / "s1.json", text)
    return _load(out / "score" / "s1.json")


def _serialise(rep) -> str:
    return json.dumps(_clean(rep), indent=1, sort_keys=True)


def _write_text_once(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as f:
        f.write(text)


def _trial_end(out: Path, pr: dict):
    """(end instant, final manifest required): the instant the trial ended, or None when it cannot be placed
    (malformed records: the attempt then records ABORTED-INVALID, ruling m-1); STOPPED/TIMEOUT require the final
    manifest (ruling R-1). Raises SystemExit while RUNNING (ruling I-1)."""
    if (out / "aborted.json").exists():
        try:
            return c.aware(_load(out / "aborted.json")["actual"]), False   # the aborting capture's recorded time
        except (ValueError, KeyError, TypeError):
            return None, False
    start, cal = c.aware(pr["start"]), pr["calendar"]
    try:
        st_ = z.stop_decision([s for _, s in _seals(out)], start, cal, today=c.now_utc())
        if st_["status"] == "RUNNING":
            raise SystemExit("score refused: the trial is still RUNNING (no stop yet); nothing written")
        if st_["status"] in ("STOPPED", "TIMEOUT"):
            return c.aware(st_["stop_close"]), True
        dl = z.deadline(start).isoformat()                                   # NO-VALID-SEAL
        last = [d for d in z._sorted_calendar(cal) if z.open_instant(d) >= start and d["date"] <= dl][-1]
        return z.window_end(last, cal), False
    except (ValueError, b.BookError, KeyError, TypeError, IndexError):
        return None, False


def _pre_reserve_gate(out: Path, ack: dict) -> None:
    """Rulings I-1 / R-1 / m-1: an early SCORE-ACK never consumes the one score. Refuse (no output) while RUNNING,
    for STOPPED/TIMEOUT without a final manifest, and unless the ACK was created strictly after the trial's end
    instant (stop close; aborted.json's recorded capture time; NO-VALID-SEAL: the last eligible seal window end)."""
    end, need_final = _trial_end(out, _load(out / "prereg.json"))
    if end is not None and c.aware(ack["created_utc"]) <= end:
        raise SystemExit(f"score refused: the SCORE-ACK ({ack['created_utc']}) is not strictly after the trial's end "
                         f"({end.isoformat()}); nothing written")
    if need_final and not (out / "final" / "manifest.json").exists():
        raise SystemExit("score refused: no final acquisition manifest yet (COMPLETE or ABORTED); nothing written")
    d = out / "final_snapshot"                                              # Task 7b (§6); fix round 1 (I-1):
    if not (d / "report.json").exists() and not _ok_attempts(d):          # an ok attempt is scored (INVALID)
        raise SystemExit("score refused: no final snapshot (run s1_checkpoint.py --final-snapshot after the "
                         "stop); nothing written")


def _ok_attempts(d: Path) -> list:
    """final_snapshot/attempt-NN names whose meta.json records ok=True (fix round 1, I-1: success is decided by the
    attempts, not by report.json). Kept here, not imported from s1_checkpoint, so runner_sha covers it."""
    found = []
    for p in sorted(d.glob("attempt-*")):
        try:
            if json.loads((p / "meta.json").read_text(encoding="utf-8")).get("ok") is True:
                found.append(p.name)
        except (OSError, ValueError, AttributeError):
            pass
    return found


def _final_snapshot_problems(out: Path, seals) -> list:
    """Task 7b (§6): the acquisition-time snapshot must have been captured, still hash to its recorded projection,
    and hold every sealed slice's fence (the recorded check AND an offline re-check against the current seals)."""
    d = out / "final_snapshot"
    oks = _ok_attempts(d)
    try:
        rep = _load(d / "report.json")
        if not isinstance(rep, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as e:                      # fix round 1 (I-1): lost report, ok attempt on disk
        return [f"final snapshot: report.json missing or unreadable ({type(e).__name__}) while successful "
                f"attempt(s) exist: {', '.join(oks) or 'none'}"]
    attempt = str(rep.get("attempt", ""))                   # Task 7b ruling 2: the successful attempt's capture
    others = [x for x in oks if x != attempt]
    if others:                                              # fix round 1 (I-1): one successful capture only
        return [f"final snapshot: successful attempt(s) other than the reported {attempt!r}: {', '.join(others)}"]
    if rep.get("capture_ok") is not True or rep.get("fence_checked") is not True:
        return [f"final snapshot capture failed: {rep.get('capture_error')}"]
    bad = [f"final snapshot: {v}" for v in rep.get("fence_violations") or []]
    if not re.fullmatch(r"attempt-\d{2,}", attempt):
        return bad + [f"final snapshot: report names no valid attempt ({attempt!r})"]
    proj_p = d / attempt / "projection.json"
    if not proj_p.is_file() or c.sha256_file(proj_p) != rep.get("projection_sha256"):
        return bad + ["final snapshot: projection differs from its recorded hash"]
    try:
        again = z.check_fences([s for _, s in seals], _load(proj_p))
    except (ValueError, KeyError, TypeError) as e:
        again = [f"bad seal record: {type(e).__name__}: {e}"]
    return bad + [f"final snapshot: {v}" for v in again if f"final snapshot: {v}" not in bad]


def _seal_chain_problems(out: Path, seals, receipt_sha: str) -> list:
    """Re-verify every seal offline: file date = its close's session; its fence = its own rows; receipt identical;
    rows = the preserved capture projection; and the row fences of every earlier seal hold (§6)."""
    bad = []
    ordered = sorted(seals, key=lambda ps: c.aware(ps[1]["close"]))
    for p, s in ordered:
        name = p.stem
        if _ny_day(c.aware(s["close"])) != name:
            bad.append(f"seal {name}: close {s['close']} is not that session")
        if {str(i): h for i, h in z.fence({"trades": s["trades"]}).items()} != {str(i): h for i, h in
                                                                                s["fence"].items()}:
            bad.append(f"seal {name}: fence does not match its rows")
        if s.get("receipt_match") is not True or s.get("receipt_sha256") != receipt_sha:
            bad.append(f"seal {name}: semantic receipt differs from prereg")
        cap = s.get("capture") or {}
        proj = out / "captures" / name / re.split(r"[\\/]", str(cap.get("dir", "")))[-1] / "projection.json"
        if not proj.is_file() or c.sha256_file(proj) != cap.get("projection_sha256") or \
                _load(proj).get("trades") != s["trades"]:
            bad.append(f"seal {name}: rows differ from the preserved capture projection")
    for i, (p, s) in enumerate(ordered):
        bad += [f"seal {p.stem}: {v}" for v in z.check_fences([x for _, x in ordered[:i]], {"trades": s["trades"]})]
    return bad


def _stop_attestation(out: Path, pr: dict, stop, stop_p, final_reserved) -> dict:
    p = out / "attest_stop.json"
    if not p.exists():
        return {"ok": False, "present": False, "problems": ["no stop attestation recorded"]}
    a = _load(p)
    probs = []
    if a.get("statement") != STOP_STATEMENT:
        probs.append("statement differs")
    if a.get("attest_start_sha256") != c.sha256_file(out / "attest_start.json"):
        probs.append("START attestation hash differs")
    if a.get("start") != pr["start"]:
        probs.append("START differs")
    if stop is None or stop.get("stop_close") is None or a.get("stop_close") is None or \
            c.aware(a["stop_close"]) != c.aware(stop["stop_close"]):
        probs.append("stop close differs")
    if stop_p is None or a.get("sealed_final_ledger_sha256") != c.sha256_file(stop_p):
        probs.append("sealed final ledger hash differs")
    try:
        t = c.aware(a.get("recorded_utc"))
        if stop and stop.get("stop_close") and t <= c.aware(stop["stop_close"]):
            probs.append("recorded before the stop")
        if final_reserved is not None and t >= final_reserved:
            probs.append("recorded after the final acquisition began")
    except ValueError:
        probs.append("recorded_utc unreadable")
    return {"ok": not probs, "present": True, "problems": probs}


def _restarts(opening: dict, stop_seal: dict, out: Path) -> dict:
    seen = {(x["ts"], x["pid"]) for x in (opening.get("restart_record") or {}).get("starts", [])}
    starts = [x for x in (stop_seal.get("restart_record") or {}).get("starts", []) if (x["ts"], x["pid"]) not in seen]
    gaps = []
    for p in sorted((out / "captures").glob("*/*.report.json")):
        rep = _load(p)
        gaps += [{"scheduled": rep.get("scheduled"), "gap": g} for g in rep.get("restart_gaps", [])]
    return {"observed_in_crash_log_minimum": starts, "observation_gaps": gaps}


def _median(xs):
    s = sorted(xs)
    return None if not s else (s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2)


def _score(out: Path) -> dict:
    sim = c.sim()
    pr, plan = _load(out / "prereg.json"), _load(out / "plan.json")
    start, cal = c.aware(pr["start"]), pr["calendar"]
    rep = {"trial_id": TRIAL_ID, "outcome": "SCORED", "runner_sha256": runner_sha(), "start": pr["start"],
           "reasons": [], "protocol_notes": [], "scored_utc": c.now_utc().isoformat()}
    invalid = rep["reasons"]

    def done(verdict: str, attest) -> dict:
        rep.update(final_verdict(verdict, attest))
        rep["stop_attestation"] = attest
        if verdict == "SHADOW PASS" and not rep["nomination"]:
            rep["note"] = "numeric pass with UNVERIFIED-PROVENANCE: flagged exploratory result, not a nomination"
        return rep

    # 1. ABORTED-INVALID: recorded abort, broken bindings, seal/receipt/fence failures, bad stop record
    if (out / "aborted.json").exists():
        invalid.append(f"checkpoint recorded ABORTED-INVALID: {_load(out / 'aborted.json').get('reason')}")
    if pr.get("runner_sha256") != runner_sha():          # controller ruling (Task 7): invalid, not a note
        invalid.append("runner changed since prereg")
    audit, opening_p, opening = {}, None, None
    try:
        _, audit = _attempt(out / "audit", AUDIT_FILES)
        if pr.get("plan_sha256") != c.sha256_file(out / "plan.json") or \
                pr.get("audit_manifest_sha256") != c.sha256_file(out / "audit" / "manifest.json") or \
                pr.get("attest_start_sha256") != c.sha256_file(out / "attest_start.json"):
            invalid.append("prereg bindings (plan / audit manifest / START attestation) changed")
        if pr["start"] != plan["planned_start"] or cal != _calendar(audit["calendar.json"]):
            invalid.append("prereg START or calendar differs from the plan/audit")
        opening_p, opening = _opening_seal(out, plan, cal)
        invalid += _start_attestation_problems(out, _load(out / "attest_start.json"), plan, opening_p, pr["receipt"])
    except (Invalid, FileNotFoundError, KeyError) as e:
        invalid.append(f"{type(e).__name__}: {e}")
    seals = _seals(out)
    invalid += _seal_chain_problems(out, seals, _receipt_sha(pr["receipt"]))
    invalid += _final_snapshot_problems(out, seals)
    stop = None
    try:
        stop = z.stop_decision([s for _, s in seals], start, cal, today=c.now_utc())
    except (ValueError, b.BookError) as e:
        invalid.append(f"bad seal record: {type(e).__name__}: {e}")
    rep["stop"] = stop
    rep["missed_seals"] = stop["missed"] if stop is not None else None
    stopped = stop is not None and stop["status"] in ("STOPPED", "TIMEOUT")
    if stop is not None and stop["status"] == "RUNNING":
        invalid.append("scored before the trial stopped")
    stop_p = stop_seal = final = fplan = None
    final_reserved = None
    if (out / "final" / "attempt.json").exists():
        final_reserved = c.aware(_load(out / "final" / "attempt.json")["reserved_utc"])
    if stopped:
        stop_dt = c.aware(stop["stop_close"])
        stop_p = out / "seals" / f"{_ny_day(stop_dt)}.json"
        stop_seal = _load(stop_p) if stop_p.exists() else None
        try:
            fm, final = _attempt(out / "final", FINAL_FILES)
            fplan = _load(out / "final_plan.json")
            if fm.get("prereg_sha256") != c.sha256_file(out / "prereg.json"):
                invalid.append("final acquisition is not bound to this prereg")
            if c.aware(fplan["stop_close"]) != stop_dt:
                invalid.append(f"final plan stop {fplan['stop_close']} is not the stop {stop['stop_close']}")
        except (Invalid, FileNotFoundError) as e:
            invalid.append(f"final acquisition unusable: {e}")
    attest = _stop_attestation(out, pr, stop, stop_p, final_reserved)
    held0 = since0 = asof = held = since = lots = None
    if opening is not None:                                # ruling M-2: ledger errors are ABORTED-INVALID first
        try:
            held0, since0 = _carry_in(z.split_bridge(opening["trades"], start)[0], start)
        except b.BookError as e:
            invalid.append(f"opening ledger unreadable: {e}")
    if stopped and stop_seal is None:
        invalid.append("stop seal file missing")
    elif stopped:
        stop_dt = c.aware(stop["stop_close"])
        asof = [t for t in stop_seal["trades"] if c.aware(t["ts"]) <= stop_dt]
        try:
            held, since = _carry_in(z.split_bridge(asof, start)[0], start)
            lots = b.economic_lots(asof, stop_dt)
            rep["quantity_bridge"] = b.bridge(asof, stop_dt)
        except b.BookError as e:
            invalid.append(f"final ledger unreadable: {e}")
    if invalid:
        return done("ABORTED-INVALID", attest)

    # 2. BLOCKED: pre-START units known to the audit (re-checked; prereg should have refused)
    blocked = (_coverage_reasons(held0, since0, set(plan["ca_symbols"]), plan["ca_range"][0])
               + carry_in_reasons(held0, audit["corporate_actions.json"], since0, problems=audit["ca_problems.json"]))
    if blocked:
        rep["reasons"] += blocked
        return done("BLOCKED", attest)

    # 3. NO-VALID-SEAL
    if stop["status"] == "NO-VALID-SEAL":
        return done("NO-VALID-SEAL", attest)

    # 4. untrusted carry-in inventory (bridge book from the frozen final ledger) -> INCONCLUSIVE before pricing
    stop_dt = c.aware(stop["stop_close"])
    stop_date = _ny_day(stop_dt)
    bridge_rows = z.split_bridge(asof, start)[0]
    actions = audit["corporate_actions.json"] + final["corporate_actions.json"]
    problems = audit["ca_problems.json"] + final["ca_problems.json"]
    rep["carry_in"] = {"held_at_start": held, "held_since": since,
                       "bridge_rows": [t["id"] for t in bridge_rows if c.aware(t["ts"]) > c.aware(opening["close"])]}
    untrusted = (_coverage_reasons(held, since, set(fplan["ca_symbols_full_history"]), fplan["full_history_start"])
                 + carry_in_reasons(held, actions, since, problems=problems, until=stop_date,
                                    start_day=_ny_day(start), open_across=lambda sym, d: any(
                                        l["symbol"] == sym and l["entry_ts"] < start
                                        for l in open_lots_before(asof, d))))
    rep["restarts"] = _restarts(opening, stop_seal, out)
    if untrusted:
        rep["reasons"] += untrusted
        return done("INCONCLUSIVE", attest)

    # 5. cohort, paired exclusions, cap / minimum (no prices used yet)
    ids = {t["id"] for t in z.cohort(asof, start, stop_dt)}
    cohort = [l for l in lots if l["id"] in ids]
    sessions = [d["date"] for d in cal]
    covered = set(fplan["ca_symbols_window"]) | set(fplan["ca_symbols_full_history"])
    problems = problems + [{"problem": "symbol not covered by the final corporate-action request",
                            "blocks_symbols": [s]} for s in sorted({l["symbol"] for l in cohort} - covered)]
    untrusted = fifo_untrusted(asof, actions, _ny_day(start), stop_date)
    ex = exclusions(cohort, actions, problems, stop_date, sessions, final["bars.json"], final["bar_problems.json"],
                    untrusted=untrusted)
    n, kk = len(cohort), len(ex)
    total_notional = sum((l["entry_notional"] for l in cohort), Fraction(0))
    ex_notional = sum((l["entry_notional"] for l in cohort if l["id"] in ex), Fraction(0))
    rep.update(n=n, k=kk, retained=n - kk, excluded={l_id: why for l_id, why in sorted(ex.items())},
               excluded_notional_share=float(ex_notional / total_notional) if total_notional else 0.0)
    disp = disposition(n, kk)
    if disp != "OK":
        rep["reasons"].append(f"{n} cohort lots, {kk} excluded: {disp}")
        return done(disp, attest)

    # 6. paired economics on the retained lots (pinned E1 core, exact decisions)
    bars = final["bars.json"]
    paired = []
    for l in (x for x in cohort if x["id"] not in ex):
        sb = bars[l["symbol"]]
        path = [sb[d] for d in required_sessions(sim.ny_date(l["entry_ts"]), stop_date, sessions)]
        close = sb[stop_date]["c"]
        paired.append({"id": l["id"], "symbol": l["symbol"], "entry_ts": l["entry_ts"],
                       "entry_notional": l["entry_notional"], "sessions_to_stop": len(path) - (
                           1 if sim.ny_date(l["entry_ts"]) == stop_date else 0),
                       "base": {bp: sim.baseline_economics(l, close, bp) for bp in BPS},
                       "cand": {bp: {c.POLICY_ID: candidate_economics(l, path, stop_date, bp)} for bp in BPS}})
    levels = {bp: sim.compare(paired, c.POLICY_ID, bp) for bp in BPS}
    numeric = "SHADOW PASS" if all(levels[bp]["improves"] for bp in GATE_BPS) else "FAIL"
    syms = {}
    for l in paired:
        syms[l["symbol"]] = syms.get(l["symbol"], 0) + 1
    ages = [l["sessions_to_stop"] for l in paired]
    rep.update(levels=levels, lots=paired,
               bootstrap={bp: sim.paired_bootstrap(paired, c.POLICY_ID, bp) for bp in GATE_BPS},
               zero_eligible=[l["id"] for l in paired if l["cand"][5][c.POLICY_ID]["eligible_sessions"] == 0],
               concentration={"lots_per_symbol": syms, "top_symbol_share": max(syms.values()) / len(paired)},
               holding_age_sessions={"min": min(ages), "median": _median(ages), "max": max(ages)})
    return done(numeric, attest)
