"""S1 runner (§11–15): lifecycle gates and ACKs, attestations, carry-in unit trust, per-lot paired exclusions,
economics from the pinned E1 core, verdict and report. Never touches the live app or trading.db."""
import json
import re
import sqlite3
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path

import s1_books as b
import s1_collect as k
import s1_common as c
import s1_gates as g
import s1_receipt as rc
import s1_seal as z
import s1_trial

START_STATEMENT = "I confirm the trading_app backend runs from the recorded checkout, started after the S1 receipt."
STOP_STATEMENT = ("I confirm that between START and the stop no MeanReversion code, config or package changed "
                  "(including changed and reverted) and no MeanReversion trade was placed or edited by hand.")
BPS = (0, 1, 5, 10)
GATE_BPS = (5, 10)
MIN_RETAINED = 30                     # §14 (= e1_sim.MIN_LOTS)
ABSENT = c.ABSENT                     # ACK-field placeholder for an artifact that does not exist
BLOCKING_TYPES = {"forward_splits", "reverse_splits", "unit_splits", "spin_offs", "rights_distributions",
                  "cash_mergers", "stock_mergers", "stock_and_cash_mergers", "stock_dividends", "redemptions",
                  "worthless_removals", "name_changes"}
SYMBOL_FIELDS = ("symbol", "old_symbol", "new_symbol", "alternate_symbol", "acquiree_symbol", "source_symbol")
DATE_FIELDS = ("ex_date", "effective_date")         # Task 12 (A7.3): process_date is never an effective date
# A7.3: the registered effective-date field per provider action type (the E1 CA_SCHEMA field names). No field - in
# particular process_date, a processing/publication date - is treated as an effective date without a pinned provider
# field contract; types without such a field (redemptions, name changes, worthless removals) have UNKNOWN timing.
EX_DATE_TYPES = {"forward_splits", "reverse_splits", "stock_dividends", "cash_dividends", "spin_offs",
                 "rights_distributions"}
EFFECTIVE_DATE_TYPES = {"unit_splits", "cash_mergers", "stock_mergers", "stock_and_cash_mergers"}
AUDIT_FILES = g.AUDIT_FILES          # Task 12 (A6): + calendar_source.json (the pinned calendar's source)
FINAL_FILES = ("bars.json", "bar_problems.json", "corporate_actions.json", "ca_problems.json")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


Invalid = g.Invalid                   # a protocol/integrity failure: a refusal at a gate, ABORTED-INVALID at score


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


def effective_date(a):
    """Task 12 (A7.3, A4.2): the action's effective date from its type's registered field (ex_date or
    effective_date), or None = unknown timing: an unregistered type or a type with no such field, a missing or
    invalid value, an ambiguous record (both fields valid and different), a record the provider identity
    reconciliation found conflicting (effective_conflict), or an incomplete/unclassifiable classification (whose
    E1-derived effective_date may be a process date). Unknown timing is handled conservatively, never as outside
    the date comparison."""
    if a.get("effective_conflict") or a.get("classification") in ("incomplete", "unclassifiable"):
        return None
    t = a.get("type")
    field = "ex_date" if t in EX_DATE_TYPES else "effective_date" if t in EFFECTIVE_DATE_TYPES else None
    if field is None or not _valid_date(a.get(field)):
        return None
    vals = {a[f] for f in DATE_FIELDS if _valid_date(a.get(f))}
    return a[field] if len(vals) == 1 else None


def _date(a):
    """Effective date of an action (Task 12: effective_date(); the Task 7 ex/effective/process fallback is gone)."""
    return effective_date(a)


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


def contaminated_symbols(rows, actions, start, stop_close, held_syms=()) -> dict:
    """Task 12 (A4.2; replaces the Task-7 C-2 fifo_untrusted ruling): the pre-registered contaminated-symbol rule.
    A unit/identity action on symbol S with any lot of S (cohort or carry-in; economic FIFO over the as-of rows, dust
    residuals included) open across its effective date contaminates S. An action with unknown effective timing
    (effective_date() is None) is never outside the date comparison: it contaminates S when S has any cohort lot
    (BUY with START <= stored time <= stop close) or is held at START (`held_syms`). Actions effective after the stop
    session are outside the trial. Returns {S: {"actions": [ids], "effective_dates": [...], "sells": [SELL ids of S
    stored on/after the effective date (unknown: any) and at or before the stop close]}}; a fully resolved event
    with no lot of S open across it does not contaminate S."""
    stop_day = _ny_day(stop_close)
    in_trial = [t for t in rows if c.aware(t["ts"]) <= stop_close]
    cohort_syms = {t["symbol"] for t in z.cohort(in_trial, start, stop_close)}
    named = cohort_syms | set(held_syms) | {t["symbol"] for t in in_trial}
    out = {}
    for a in actions:
        syms = sorted(sym for sym in named if unit_identity(a, sym))
        if not syms:
            continue
        d = effective_date(a)
        if d is None:
            hit = [s for s in syms if s in cohort_syms or s in set(held_syms)]
            since = None
        elif d <= stop_day:
            open_syms = {l["symbol"] for l in open_lots_before(in_trial, d)}
            hit = [s for s in syms if s in open_syms]
            since = datetime.combine(date.fromisoformat(d), datetime.min.time(), tzinfo=c.NY)
        else:
            continue
        for s in hit:
            info = out.setdefault(s, {"actions": [], "effective_dates": [], "sells": []})
            if a.get("id") not in info["actions"]:
                info["actions"].append(a.get("id"))
                info["effective_dates"].append(d)
            for t in in_trial:
                if t["symbol"] == s and t["action"] == "SELL" and (since is None or c.aware(t["ts"]) >= since) \
                        and t["id"] not in info["sells"]:
                    info["sells"].append(t["id"])
    for info in out.values():
        info["sells"].sort()
    return out


def exclusions(lots, actions, problems, stop_date, sessions, bars, bar_problems, *, untrusted=None) -> dict:
    """§11 paired exclusion window per lot: entry NY date EXCLUSIVE .. stop session INCLUSIVE (both arms); undated
    or problem records block every lot of the symbol; every required bar (post-entry sessions + the stop close)
    must exist and be unflagged. `untrusted` ({symbol: [reasons]}; Task 12: the A4.2c contaminated symbols)
    excludes every lot of the symbol."""
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
    """Why carry-in units are untrusted: a unit/identity action (or an undated one) on a symbol held at START, dated on/
    after the date its oldest open lot was bought (and, when `until` is given, no later than it), or a problem
    record blocking that symbol. Ruling I-3: when `open_across(sym, day)` is given, an action dated on/after
    `start_day` counts only if a carry-in lot of the symbol was still open across that date (a lot held at START
    and bought before a pre-START action date was necessarily held across it). Task 11 (controller-added), I-6
    (design §11): only unit/identity actions (unit_identity) count; a special cash dividend or a spin-off/rights
    source does not untrust carry-in units (cohort per-lot exclusions still use blocks())."""
    bad_syms = {s for p in problems for s in p.get("blocks_symbols", [])}
    out = []
    for sym in sorted(held_at_start):
        if not held_at_start[sym] > 0:
            continue
        if sym in bad_syms:
            out.append(f"carry-in {sym}: corporate-action problem record")
        since = held_since.get(sym)
        for a in actions:
            if not unit_identity(a, sym):
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


def _trial_id_of(plan) -> str:
    """F6.2 (Task 4 review M2): the plan's trial_id; a plan without one is a refusal (never a KeyError, never None)."""
    tid = plan.get("trial_id") if isinstance(plan, dict) else None
    if not isinstance(tid, str) or not tid:
        raise s1_trial.Refusal("plan.json has no trial_id: refuse (F6.2)")
    return tid


def _plan_trial_id(out: Path) -> str:
    """F6.2: the trial_id recorded in s1_out/plan.json (an unreadable plan or one without a trial_id refuses)."""
    try:
        plan = _load(out / "plan.json")
    except (OSError, ValueError) as e:
        raise s1_trial.Refusal(f"plan.json unreadable ({type(e).__name__}): plan.json has no trial_id: refuse "
                               f"(F6.2)") from None
    return _trial_id_of(plan)


def _sha_or_absent(p: Path) -> str:
    return c.sha256_file(p) if p.exists() else ABSENT


def _receipt_sha(receipt) -> str:
    """Task 12 (A1): the validity hash = the receipt FINGERPRINT's (provenance is informational)."""
    return c.receipt_sha256(receipt)


def _ack(ack_id: str, token: str, mailbox=None) -> dict:
    """s1_collect._ack (codex->claude experiments-prereg, standalone exact line, not in the future; Task 11 I-5: from
    `mailbox`, default s1_common.MAILBOX); an unreadable mailbox is a refusal too."""
    try:
        return k._ack(ack_id, token, mailbox)
    except sqlite3.Error as e:
        raise SystemExit(f"mailbox unreadable ({type(e).__name__}): refusing") from None


def run_token(root, mailbox=None) -> str:
    """Task 12 (A8.1): binds the opening seal, the frozen opening books, the audit, the attestation and the bundle
    (s1_common.run_token); A3: the trial and journal fields from `mailbox` (s1_trial.token)."""
    return c.run_token(_out(root), mailbox)


def score_token(root, mailbox=None) -> str:
    """Task 12 (A2/A3): also binds the persisted stop (stop.json) and the bundle (s1_common.score_token); A3: the
    trial and journal fields from `mailbox` (s1_trial.token)."""
    return c.score_token(_out(root), mailbox)


def _attempt(d: Path, names) -> tuple:
    """A COMPLETE collector attempt: named derived files AND raw pages re-verified (s1_gates.attempt, A7.4)."""
    return g.attempt(d, names, Path(d).parent)


def _calendar(raw) -> list:
    return z.calendar_rows(raw)


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


def _binding_sha(binding) -> str:
    return c.sha256_bytes(c.canonical(binding))


def _opening_binding(seal: dict, where: str) -> dict:
    """Addendum 2 B2.1: the registered process-binding reference = the opening seal's observed binding (REFERENCE);
    an opening seal without a usable one fails closed."""
    pb = seal.get("process_binding") if isinstance(seal, dict) else None
    b_ = pb.get("binding") if isinstance(pb, dict) and pb.get("status") == "REFERENCE" else None
    if rc.binding_problem(b_) or (seal.get("process") or {}).get("binding") != b_:
        raise SystemExit(f"{where} refused: the opening seal carries no usable process-binding reference (B2.1)")
    return b_


# ------------------------------------------------------------------ gates (§12, §15)
def _books_record(seal_p: Path, seal: dict) -> dict:
    """Task 12 (A8.1, mapping 1.2): the frozen opening books = economic-FIFO open lots (exact quantities as text) and
    the operational replay over the opening seal's rows (quantities only), bound to the opening seal's hash."""
    rows = seal["trades"]
    end = c.aware(seal["close"])
    lots = [{"id": l["id"], "symbol": l["symbol"], "entry_ts": l["entry_ts"].isoformat(), "qty": str(l["qty"]),
             "rem_qty": str(l["rem_qty"])} for l in b.economic_lots(rows, end) if l["rem_qty"] > 0]
    return {"opening_seal_sha256": c.sha256_file(seal_p), "opening_close": seal["close"], "economic_lots": lots,
            "operational": b.operational_replay(rows)}


def _opening_books(out: Path, seal_p: Path, seal: dict) -> Path:
    """A3 Task 10 (OQ-15, KEEP SINGLE): opening_books.json is a deterministic derived input of the start_attest stage,
    published BEFORE its INTENT: recomputed from the committed opening seal (the exact bytes s1_collect._write_once
    publishes); published exclusively if absent; if present it must equal the recomputation byte for byte, otherwise
    the attestation refuses with no row. A change after CREATED is the envelope input check's stage-replaced."""
    try:
        data = c.text_bytes(k._json_text(_books_record(seal_p, seal)))
    except b.BookError as e:
        raise SystemExit(f"START attestation refused: opening ledger unreadable ({e})") from None
    p = out / "opening_books.json"
    try:
        c.publish_in_out(p, data, "START attestation")             # F6.6 (fix round 1, M5): never recreates s1_out
    except FileExistsError:
        if p.read_bytes() != data:
            raise SystemExit("START attestation refused: opening_books.json differs from its recomputation from the "
                             "committed opening seal (OQ-15)") from None
    return p


def attest_start(root, statement: str, receipt, *, mailbox=None) -> dict:
    """START attestation (§12): before RUN-ACK/prereg and strictly before planned START; binds trial ID, planned
    START, the semantic receipt, the plan, the COMPLETE audit and the opening seal. Task 12: the bundle is verified
    FIRST (A3.2; from the opening seal on a mismatch is the persistent "bundle" abort, R-1); the audit is the
    verified one (A8.2); the attestation follows the opening seal's capture (A8.1); it writes and binds the frozen
    opening books (A8.1) and binds the bundle.
    A3 Task 10: the stage `start_attest` (F4.8; OQ-15: SINGLE member attest_start.json; opening_books.json a
    deterministic hash-bound derived input published before the INTENT): after the legacy checks, the OPENING-ACK is
    verified against the journal (s1_trial.verify_opening_ack: F7.2/F7.4, E5.3, E5.5); envelope inputs plan, audit
    manifest, opening seal, opening receipt and opening books, acks the OPENING-ACK line; attest_start.json records
    intent_at (F4.5); the legacy registry records are published inside the stage publication (stage.lock)."""
    import s1_stage
    gv = s1_trial.gate(root, "START attestation", mailbox=mailbox)      # A3 F0.6: open trial, state, bundle first
    if statement != START_STATEMENT:
        raise SystemExit("START attestation refused: the statement must be exactly START_STATEMENT")
    out = _out(root)
    c.verify_bundle_first(out, "START attestation", mailbox=mailbox, need="audit")
    if c.load_abort(out) is not None:                                 # Task 12 (A3.3): persistent, never resumed
        raise SystemExit("START attestation refused: the registration is ABORTED-INVALID (aborted.json)")
    plan = _load(out / "plan.json")
    if c.now_utc() >= c.aware(plan["planned_start"]):
        raise SystemExit("planned START has passed: re-register")
    if (out / "attest_start.json").exists():
        raise SystemExit("START attestation already recorded: refusing")
    try:
        aud = g.verified_audit(out, mailbox)
        seal_p, seal = _opening_seal(out, plan, aud["calendar"])
    except Invalid as e:
        raise SystemExit(f"START attestation refused: {e}") from None
    if seal.get("bundle_sha256") != c.bundle_sha256():
        raise SystemExit("START attestation refused: the opening seal was not written by the registered bundle")
    cap = seal.get("capture") or {}
    if c.now_utc() <= c.aware(cap.get("capture_end") or cap.get("actual")):
        raise SystemExit("START attestation refused: it must follow the opening seal's capture")
    binding = _opening_binding(seal, "START attestation")           # fix round 2 (B2.1): the bound reference
    opening_receipt = _opening_receipt(out, seal)                     # Task 7b: the receipt the opening sealed with
    if c.receipt_sha256(receipt) != _receipt_sha(opening_receipt):    # Task 12 (A1): fingerprints compared
        raise SystemExit("START attestation refused: the receipt differs from the opening receipt "
                         "(s1_out/opening_receipt.json)")
    a = s1_trial.verify_opening_ack(gv, aud["calendar"])            # A3 Task 10: F7.2/F7.4, E5.3, E5.5
    books_p = _opening_books(out, seal_p, seal)                       # OQ-15: write once / verify, before the INTENT
    seal_rel = seal_p.relative_to(out).as_posix()
    rec = {"statement": statement, "trial_id": _trial_id_of(plan), "planned_start": plan["planned_start"],
           "receipt_sha256": _receipt_sha(opening_receipt), "plan_sha256": c.sha256_file(out / "plan.json"),
           "audit_manifest_sha256": c.sha256_file(out / "audit" / "manifest.json"),
           "opening_seal_sha256": c.sha256_file(seal_p), "opening_books_sha256": c.sha256_file(books_p),
           "process_binding_sha256": _binding_sha(binding),                         # fix round 2 (B2.1)
           "bundle_sha256": c.bundle_sha256(), "recorded_utc": c.now_utc().isoformat()}

    def work(sw):
        sw.put_json("attest_start.json", dict(rec, intent_at=sw.intent_at))      # F4.5
        return []

    inputs = {"plan.json": rec["plan_sha256"], "audit/manifest.json": rec["audit_manifest_sha256"],
              seal_rel: rec["opening_seal_sha256"],
              "opening_receipt.json": c.sha256_file(out / "opening_receipt.json"),
              "opening_books.json": rec["opening_books_sha256"]}
    ctx, before = start_attest_publish_hooks(gv, inputs)             # (the same hooks F4.7 recovery uses)
    s1_stage.run(gv, "start_attest", inputs=inputs, acks={"S1-OPENING-ACK": a.sha}, work=work, mailbox=mailbox,
                 publish_ctx=ctx, before_publish=before)
    return _load(out / "attest_start.json")


def start_attest_publish_hooks(gv, inputs, clock=None) -> tuple:
    """The start_attest stage's publication hooks (s1_stage.PUBLISH_HOOKS; the stage run and F4.7 recovery alike, A3
    Task 10 fix round 1, review I1): inside stage.lock (fix rounds 3/4, M-2/C-2/m-1), BOTH legacy registration records
    BEFORE the artifact (B3.1): attest_start.json's committed sha256 and the bound opening_books.json input."""
    out = Path(gv.out)

    def before(com):
        c.register_stage(out, "attest_start", {"attest_start.json": com["members"]["attest_start.json"],
                                               "opening_books.json": inputs["opening_books.json"]})
    return (lambda: c.stage_publication(out, "attest_start")), before


def prereg_publish_hooks(gv, inputs, clock=None) -> tuple:
    """The prereg stage's publication hooks (s1_stage.PUBLISH_HOOKS; the stage run and F4.7 recovery alike): inside
    stage.lock, BOTH legacy registration records of prereg.json's committed sha256 BEFORE the artifact (B3.1)."""
    out = Path(gv.out)

    def before(com):
        c.register_stage(out, "prereg", {"prereg.json": com["members"]["prereg.json"]})
    return (lambda: c.stage_publication(out, "prereg")), before


def _start_attestation_problems(out: Path, att: dict, plan: dict, seal_p: Path, receipt) -> list:
    want = {"statement": START_STATEMENT, "trial_id": _trial_id_of(plan), "planned_start": plan["planned_start"],
            "plan_sha256": c.sha256_file(out / "plan.json"),
            "audit_manifest_sha256": c.sha256_file(out / "audit" / "manifest.json"),
            "opening_seal_sha256": c.sha256_file(seal_p), "receipt_sha256": _receipt_sha(receipt),
            "opening_books_sha256": c.sha_or_absent(out / "opening_books.json"),
            "bundle_sha256": c.bundle_sha256()}
    bad = [f"START attestation {key} does not match" for key, v in want.items() if att.get(key) != v]
    try:                                                                         # fix round 2 (B2.1)
        if att.get("process_binding_sha256") != _binding_sha(_opening_binding(_load(seal_p), "attestation check")):
            bad.append("START attestation process_binding_sha256 does not match")
    except (SystemExit, OSError, ValueError) as e:
        bad.append(f"START attestation process binding unverifiable ({e})")
    return bad


def do_prereg(root, ack_id: str, receipt, *, mailbox=None) -> dict:
    """Prereg (§4/§15): strictly before planned START, after a COMPLETE audit and the START attestation, never with
    a BLOCKED carry-in, under the exact RUN-ACK. Writes s1_out/prereg.json once (start, calendar, receipt + bindings).
    Task 12: the bundle first (A3.2/A3.3, R-1); the verified audit (A8.2); the carry-in audit bounded to actions
    effective before START (A4.1); prereg records the bundle, opening seal and opening books (A8.1).
    A3 Task 10: the stage `prereg` (F4.8: single member prereg.json; envelope inputs attest_start.json and the
    receipt, acks the RUN-ACK line, F7.4); BLOCKED is the E3 pre-INTENT refusal record (_blocked_refusal: no journal
    row, never INVALID), evaluated at the same place as before, after the gates and before the INTENT."""
    import s1_stage
    gv = s1_trial.gate(root, "prereg", mailbox=mailbox)                 # A3 F0.6: open trial, state, bundle first
    out = _out(root)
    c.verify_bundle_first(out, "prereg", mailbox=mailbox, need="audit")
    if c.load_abort(out) is not None:                                 # Task 12 (A3.3): persistent, never resumed
        raise SystemExit("prereg refused: the registration is ABORTED-INVALID (aborted.json)")
    plan = _load(out / "plan.json")
    start = c.aware(plan["planned_start"])
    if c.now_utc() >= start:
        raise SystemExit("planned START has passed: re-register")
    if (out / "prereg.json").exists():
        raise SystemExit("prereg already recorded: refusing")
    try:
        aud = g.verified_audit(out, mailbox)
    except Invalid as e:
        raise SystemExit(f"prereg refused: audit not COMPLETE ({e})") from None
    ap = out / "attest_start.json"
    if not ap.exists():
        raise SystemExit("prereg refused: no START attestation recorded")
    cal = aud["calendar"]
    try:
        seal_p, seal = _opening_seal(out, plan, cal)
    except Invalid as e:
        raise SystemExit(f"prereg refused: {e}") from None
    bad = _start_attestation_problems(out, _load(ap), plan, seal_p, receipt)
    if bad:
        raise SystemExit(f"prereg refused: {bad} (receipt or bound artifacts changed since the START attestation)")
    _blocked_refusal(out, cal)                                        # E3: before the INTENT, no journal row
    a = s1_trial.verify_ack(gv.trial, gv.rows, "S1-RUN-ACK", ack_id,    # A3: field by field (F6.1, F6.5, F7.1)
                            dict(s1_trial.artifact_fields("S1-RUN-ACK", out), trial_id=_trial_id_of(plan),
                                 bundle_sha256=c.bundle_sha256()))
    ack = s1_trial.ack_record(a)
    if c.aware(ack["created_utc"]) <= c.aware(_load(ap)["recorded_utc"]):         # §12 causal order (ruling I-2)
        raise SystemExit("prereg refused: the RUN-ACK is not strictly after the START attestation")
    pr = {"trial_id": _trial_id_of(plan), "start": plan["planned_start"], "calendar": cal, "receipt": receipt,
          "runner_sha256": runner_sha(), "bundle_sha256": c.bundle_sha256(),           # Task 12 (A3.1)
          "plan_sha256": c.sha256_file(out / "plan.json"),
          "audit_manifest_sha256": c.sha256_file(out / "audit" / "manifest.json"),
          "attest_start_sha256": c.sha256_file(ap), "opening_seal_sha256": c.sha256_file(seal_p),   # A8.1
          "opening_books_sha256": c.sha_or_absent(out / "opening_books.json"),
          "process_binding": _opening_binding(seal, "prereg"),                     # fix round 2 (B2.1)
          "ack": ack, "recorded_utc": c.now_utc().isoformat()}

    def work(sw):
        sw.put_json("prereg.json", dict(pr, intent_at=sw.intent_at))             # F4.5
        return []
    inputs = {"attest_start.json": c.sha256_file(ap), "receipt": c.receipt_sha256(receipt)}
    ctx, before = prereg_publish_hooks(gv, inputs)                   # (the same hooks F4.7 recovery uses)
    s1_stage.run(gv, "prereg", inputs=inputs, acks={"S1-RUN-ACK": a.sha}, work=work, mailbox=mailbox,
                 publish_ctx=ctx, before_publish=before)
    return _load(out / "prereg.json")


def blocked_reasons_record(out, cal) -> dict:
    """E3.1 (adopted Erratum 1, de008b1): the BLOCKED reasons as a pure function of committed inputs only - the
    CREATED audit tree (calendar `cal`, audit/corporate_actions.json, audit/ca_problems.json), the CREATED opening
    seal (its rows: the carry-in at START) and plan.json - with the existing predicate (_blocked_reasons, unchanged).
    Every re-run gives the same record (E3.2, E3.6b). Returns {"trial_id", "reasons"}."""
    out = Path(out)
    plan = _load(out / "plan.json")
    cal = z.calendar_rows(cal)
    start = c.aware(plan["planned_start"])
    _, seal = _opening_seal(out, plan, cal)
    held, since = _carry_in(z.split_bridge(seal["trades"], start)[0], start)
    reasons = _blocked_reasons(plan, held, since, _load(out / "audit" / "corporate_actions.json"),
                               _load(out / "audit" / "ca_problems.json"), start)
    return {"trial_id": _trial_id_of(plan), "reasons": reasons}


def _blocked_refusal(out, cal) -> None:
    """E3.2: after the prereg gates and before the prereg STAGE-INTENT. With reasons: publish s1_out/blocked.json
    exclusively ({status, trial_id (E5.4), reasons, recorded_utc = this observation's time}), or keep an existing one
    whose reasons equal the recomputation (else refuse and escalate), and refuse with NO journal row and no INTENT.
    blocked.json is a declared pre-INTENT refusal record (never a stage member); the state stays ACTIVE and BLOCKED is
    never INVALID (E3.3): Codex closes the trial with reason=BLOCKED (E3.4)."""
    try:
        rec = blocked_reasons_record(out, cal)
    except b.BookError as e:
        raise SystemExit(f"prereg refused: opening ledger unreadable ({e})") from None
    if not rec["reasons"]:
        return
    p = Path(out) / "blocked.json"
    body = {"status": "BLOCKED", "trial_id": rec["trial_id"], "reasons": rec["reasons"],
            "recorded_utc": c.now_utc().isoformat()}
    try:
        c.publish_in_out(p, c.text_bytes(k._json_text(body)), "prereg")   # F6.6 (fix round 1, M5)
    except FileExistsError:
        try:
            same = _load(p).get("reasons") == rec["reasons"]
        except (OSError, ValueError, AttributeError):
            same = False
        if not same:
            raise SystemExit("prereg refused: blocked.json differs from the recomputed BLOCKED reasons: escalate "
                             "(E3.2)") from None
    raise SystemExit(f"S1 BLOCKED (pre-START units): {rec['reasons']}; re-register (prereg refused with no journal "
                     f"row, E3; Codex closes the trial with reason=BLOCKED)")


def blocked_close_evidence(out) -> str:
    """E3.4 (Erratum 1 r3): the BLOCKED CLOSE evidence h = sha256(c.canonical({"trial_id", "reasons"})) of the
    deterministic recomputation from THIS trial's committed inputs (never the blocked.json bytes, which carry
    recorded_utc) - s1_trial.close_evidence("BLOCKED", ...). It is the helper Codex uses at issuance, against the
    trial's own root. S1 never calls it when reading a CLOSE: closure is decided from the mailbox alone."""
    out = Path(out)
    rec = blocked_reasons_record(out, c.load_json(out / "audit" / "calendar.json"))
    return s1_trial.close_evidence("BLOCKED", blocked_record=rec)


def _blocked_reasons(plan: dict, held: dict, since: dict, actions, problems, start) -> list:
    """§11/A4.1: the opening audit's BLOCKED reasons (prereg and the score's re-check): coverage, and unit/identity
    actions on symbols held at START, effective before START (the explicit pre-START bound)."""
    return (_coverage_reasons(held, since, set(plan["ca_symbols"]), plan["ca_range"][0])
            + carry_in_reasons(held, actions, since, problems=problems, until=_pre_start_day(start)))


def _pre_start_day(start) -> str:
    """Task 12 (A4.1): the explicit pre-START effective-date bound of the opening audit = the day before START's
    New York date."""
    from datetime import timedelta
    return (start.astimezone(c.NY).date() - timedelta(days=1)).isoformat()


def _seals(out: Path) -> list:
    return [(p, _load(p)) for p in sorted((out / "seals").glob("*.json"))]


def attest_stop(root, statement: str, *, mailbox=None) -> dict:
    """Stop attestations (§12): after a recorded stop (STOPPED/TIMEOUT from the seals), before the final acquisition
    and any score; binds the START attestation, the actual START and stop and the sealed final ledger (stop seal)."""
    gv = s1_trial.gate(root, "stop attestation", mailbox=mailbox)       # A3 F0.6: open trial, state, bundle first
    if statement != STOP_STATEMENT:
        raise SystemExit("stop attestation refused: the statement must be exactly STOP_STATEMENT")
    out = _out(root)
    c.verify_bundle_first(out, "stop attestation", mailbox=mailbox)    # fix round 2 (B3): gate first
    if not (out / "prereg.json").exists():
        raise SystemExit("stop attestation refused: no prereg (the trial never started)")
    g.verified_registration(out, "stop attestation", mailbox)          # Task 12: A3.2 bundle first, then A8.2
    if c.load_abort(out) is not None:
        raise SystemExit("stop attestation refused: the trial is ABORTED-INVALID")
    if (out / "final").exists() or (out / "score").exists():
        raise SystemExit("stop attestation refused: it must precede the final acquisition and the score")
    pr = _load(out / "prereg.json")
    try:                                                   # Task 12 (A2.1): the persisted stop (stop.json)
        import s1_checkpoint                               # fix round 3 (I-1): finalize BEFORE freezing the stop
        s1_checkpoint.finalize_pending(out, pr["calendar"], c.aware(pr["start"]), c.now_utc(), mailbox=mailbox)
        stop = z.current_stop(out, c.aware(pr["start"]), pr["calendar"], c.now_utc(), "stop attestation")
    except (ValueError, KeyError, TypeError) as e:
        raise SystemExit(f"stop attestation refused: bad seal record ({e})") from None
    if stop["status"] not in ("STOPPED", "TIMEOUT"):
        raise SystemExit(f"stop attestation refused: no stop recorded (status {stop['status']})")
    probs = z.stop_problems(out, c.aware(pr["start"]), pr["calendar"], recheck=False)
    if probs:
        raise SystemExit(f"stop attestation refused: the persisted stop does not verify ({probs})")
    stop_p = out / z.load_stop(out)["stop_seal"]
    rec = {"statement": statement, "trial_id": _plan_trial_id(out),
           "attest_start_sha256": c.sha256_file(out / "attest_start.json"), "start": pr["start"],
           "stop_close": stop["stop_close"], "stop_status": stop["status"],
           "sealed_final_ledger_sha256": c.sha256_file(stop_p),
           "stop_sha256": c.sha256_file(out / "stop.json"),                       # Task 12 (A2.1/A7.1)
           "recorded_utc": c.now_utc().isoformat()}
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


def score(root, ack_id: str, *, mailbox=None) -> dict:
    """One exclusive score (§15): exact SCORE-ACK, then the reservation (exclusive), then computation; the report
    s1_out/score/s1.json is written once. A refused ACK or a second attempt writes nothing."""
    gv = s1_trial.gate(root, "score", mailbox=mailbox)                  # A3 F0.6: open trial, state, bundle first
    out = _out(root)
    c.verify_bundle_first(out, "score", mailbox=mailbox, gate_refuses=False)   # fix round 2 (B3): gate first;
    if not (out / "prereg.json").exists():                                     # the score records (A2.3)
        raise SystemExit("no prereg: the trial never started; nothing to score")
    c.verify_bundle_first(out, "score", mailbox=mailbox, need="prereg",           # Task 12: A3.2 bundle first
                          gate_refuses=False)
    gv = s1_trial.gate(root, "score", mailbox=mailbox)     # A3 (F1, F8.1, OQ-19): a violation the legacy detector
    #                                                        just committed refuses here: no score, no record
    ack = s1_trial.verify_current(gv, "S1-SCORE-ACK", ack_id)          # A3: field by field (F6.1, F6.5, F7.1)
    _pre_reserve_gate(out, ack)
    k._reserve(out / "score", ack)
    try:
        text = _serialise(_score(out, mailbox))           # ruling M-6: serialise before opening the output file
    except (Exception, SystemExit) as e:                  # one attempt: the failure itself is the preserved record
        rep = {"trial_id": gv.trial.trial_id, "outcome": "ABORTED", "verdict": "ABORTED-INVALID", "provenance": None,
               "nomination": False, "reasons": [f"score error: {type(e).__name__}: {e}"]}
        _write_text_once(out / "score" / "s1.json", _serialise(rep))
        raise SystemExit(f"score ABORTED ({type(e).__name__}); attempt preserved, see s1_out/score/s1.json") from None
    _write_text_once(out / "score" / "s1.json", text)
    return _load(out / "score" / "s1.json")


def _serialise(rep) -> str:
    return json.dumps(_clean(rep), indent=1, sort_keys=True)


def _write_text_once(path: Path, text: str) -> None:
    c.publish_text_exclusive(path, text)                  # fix round 3 (C-1): atomic, exclusive


def _trial_end(out: Path, pr: dict):
    """(end instant, final manifest required): the instant the trial ended, or None when it cannot be placed
    (malformed records: the attempt then records ABORTED-INVALID, ruling m-1); STOPPED/TIMEOUT require the final
    manifest (ruling R-1). Raises SystemExit while RUNNING (ruling I-1)."""
    ab = c.load_abort(out)                                 # fix round 2 (B3.4): a corrupt one fails closed
    if ab is not None:
        try:                                               # the aborting capture's recorded time (a registration-
            return c.aware(ab["actual"]), False             # artifact abort has none: no end constraint, fix round 3
        except (ValueError, KeyError, TypeError):           # M-3 - its verdict is ABORTED-INVALID at any ACK time)
            return None, False
    start, cal = c.aware(pr["start"]), pr["calendar"]
    try:
        st_ = z.current_stop(out, start, cal, c.now_utc(), "score")          # Task 12 (A2.1): the persisted stop
        if st_.get("persisted") and z.stop_problems(out, start, cal, recheck=False):
            return (c.aware(st_["stop_close"]) if st_["stop_close"] else None), False    # A2.3: recorded INVALID
        if st_["status"] == "RUNNING":
            raise SystemExit("score refused: the trial is still RUNNING (no stop yet); nothing written")
        if st_["status"] in ("STOPPED", "TIMEOUT"):
            return c.aware(st_["stop_close"]), True
        last = z.eligible_sessions(start, cal)[-1]           # NO-VALID-SEAL (Task 12 A5.1: close instants)
        return z.window_end(last, cal), False
    except (ValueError, b.BookError, KeyError, TypeError, IndexError):
        return None, False


def _pre_reserve_gate(out: Path, ack: dict) -> None:
    """Rulings I-1 / R-1 / m-1: an early SCORE-ACK never consumes the one score. Refuse (no output) while RUNNING,
    for STOPPED/TIMEOUT without a final manifest, and unless the ACK was created strictly after the trial's end
    instant (stop close; aborted.json's recorded capture time; NO-VALID-SEAL: the last eligible seal window end)."""
    c.sim(), c.fetch()                    # Task 7 m-2: a pinned-core hash failure refuses before the reservation
    end, need_final = _trial_end(out, _load(out / "prereg.json"))
    if end is not None and c.aware(ack["created_utc"]) <= end:
        raise SystemExit(f"score refused: the SCORE-ACK ({ack['created_utc']}) is not strictly after the trial's end "
                         f"({end.isoformat()}); nothing written")
    if need_final and not (out / "final" / "manifest.json").exists():
        raise SystemExit("score refused: no final acquisition manifest yet (COMPLETE or ABORTED); nothing written")
    d = out / "final_snapshot"                                              # Task 7b (§6); fix round 1 (I-1):
    if c.load_abort(out) is not None:     # fix round 3 (M-3): a persistent abort is terminal - the one score records
        return                            # ABORTED-INVALID without a final snapshot (no priced path is reachable)
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


def _final_snapshot_problems(out: Path, seals, stop=None, bundle=None) -> list:
    """Task 7b (§6): the acquisition-time snapshot must have been captured, still hash to its recorded projection,
    and hold every sealed slice's fence (the recorded check AND an offline re-check against the current seals).
    Task 11 (controller-added), C-1: with a stop (STOPPED/TIMEOUT), only the seals of closes <= the stop close."""
    if stop is not None and stop.get("status") in ("STOPPED", "TIMEOUT"):
        seals = [(p, s) for p, s in seals if c.aware(s["close"]) <= c.aware(stop["stop_close"])]
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
    if bundle is not None and rep.get("bundle_sha256") != bundle:                    # Task 12 (A3.4)
        bad.append("final snapshot: bundle differs from prereg")
    if not re.fullmatch(r"attempt-\d{2,}", attempt):
        return bad + [f"final snapshot: report names no valid attempt ({attempt!r})"]
    proj_p = d / attempt / "projection.json"
    if not proj_p.is_file() or c.sha256_file(proj_p) != rep.get("projection_sha256"):
        return bad + ["final snapshot: projection differs from its recorded hash"]
    try:
        snap = _load(proj_p)
        again = z.check_fences([s for _, s in seals], snap)
        again += z.check_bridge([s for _, s in seals], snap["trades"],                       # Task 8b
                                c.aware(_load(out / "prereg.json")["start"]))
    except (ValueError, KeyError, TypeError) as e:
        again = [f"bad seal record: {type(e).__name__}: {e}"]
    return bad + [f"final snapshot: {v}" for v in again if f"final snapshot: {v}" not in bad]


def _seal_chain_problems(out: Path, seals, receipt_sha: str, bundle: str) -> list:
    """Re-verify every seal offline: file date = its close's session; its fence = its own rows; receipt identical;
    rows = the preserved capture projection; and the row fences of every earlier seal hold (§6). Task 12 (A3.4):
    every seal's bundle equals prereg's `bundle`."""
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
        if s.get("bundle_sha256") != bundle:
            bad.append(f"seal {name}: bundle differs from prereg")
        cap = s.get("capture") or {}
        proj = out / "captures" / name / re.split(r"[\\/]", str(cap.get("dir", "")))[-1] / "projection.json"
        if not proj.is_file() or c.sha256_file(proj) != cap.get("projection_sha256") or \
                _load(proj).get("trades") != s["trades"]:
            bad.append(f"seal {name}: rows differ from the preserved capture projection")
    for i, (p, s) in enumerate(ordered):
        bad += [f"seal {p.stem}: {v}" for v in z.check_fences([x for _, x in ordered[:i]], {"trades": s["trades"]})]
    return bad


def _capture_seal_problems(out: Path, rows=None, cal=None) -> list:
    """Task 11 (controller-added), m-2, rewritten in A3 Task 6 (OQ-11 ruling, E5.2; Erratum 1 E2.6 r3): every
    REQUIRED seal - a CREATED `seal/<close>` stage of the trial's journal and (A3 Task 10) the CREATED `opening` stage's
    seals/<opening close>.json (s1_slot.required_seals) - must exist with its committed sha256; a deleted or replaced one (stop shopping) is INVALID (stage-replaced, never
    recreated). It never opens a capture report or any <slot>.after.json (display only). `rows`: the caller's
    verified journal rows (None = the open trial's rows, s1_common._report_seals); `cal`: the plan calendar (the
    plan's signature; unused)."""
    bad = []
    for rel, sp, h in c._report_seals(out, rows, cal):
        if not sp.is_file() or c.sha256_file(sp) != h:
            bad.append(f"seal missing: {rel} is a CREATED seal stage's member {str(h)[:12]}, no seal file with that "
                       f"hash (stage-replaced, E2.6)")
    return bad


def _bridge_problems(rep: dict, seals, asof, start, cal) -> list:
    """Task 8b (§6/§11 Bootstrap): every post-START seal carries a bridge record that matches its own rows and the
    FIRST post-START seal's hash; the bridge recomputed from the frozen final ledger (`asof`, the stop seal's rows
    through the stop) must hash the same. Records the bridge hash and row counts in rep["bridge_provenance"]."""
    post = z.post_start_seals(seals, start)
    if not post:
        return []
    try:
        oc = z.opening_close_of(start, cal)
        bad = [f"post-START seal {s['close']}: bridge record does not match its rows" for s in post
               if isinstance(s.get("bridge"), dict) and s["bridge"] != z.bridge_record(s["trades"], start, oc)]
        bad += z.check_bridge(seals, asof if asof is not None else post[0]["trades"], start)
        if asof is not None:
            rec = z.bridge_record(asof, start, oc)
            rep["bridge_provenance"] = {"bridge_sha256": rec["bridge_sha256"],
                                        "bridge_row_count": len(rec["bridge_row_ids"]),
                                        "post_opening_row_count": len(rec["post_opening_row_ids"]),
                                        "first_post_start_seal": post[0]["close"]}
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        bad = [f"bridge check failed: {type(e).__name__}: {e}"]
    return bad


def _seal_binding_problems(rep: dict, seals, pr: dict, opening_p, stop) -> list:
    """Addendum 2 B2.3/B2.4: the score independently rechecks the process binding of every seal from the opening
    through the frozen stop (all seals while there is no stop close) against the registered reference (prereg's,
    which must be the opening seal's REFERENCE): MATCH with that binding, or an explicit GAP (reported in
    rep["seal_binding_gaps"], never equality, never a change by itself). A missing or malformed disposition, or an
    observed different binding, is INVALID."""
    rep["seal_binding_gaps"] = []
    ref = pr.get("process_binding")
    if rc.binding_problem(ref):
        return [f"process binding: prereg's registered reference missing or malformed ({rc.binding_problem(ref)})"]
    bad = []
    sc = c.aware(stop["stop_close"]) if stop is not None and stop.get("stop_close") else None
    for p, s in sorted(seals, key=lambda ps: str(ps[0])):
        try:
            if sc is not None and c.aware(s["close"]) > sc:
                continue
            pb = s.get("process_binding")
            if opening_p is not None and Path(p) == Path(opening_p):
                if pb != {"status": "REFERENCE", "binding": ref} or (s.get("process") or {}).get("binding") != ref:
                    bad.append(f"seal {Path(p).stem}: process binding is not the registered opening reference")
                continue
            if isinstance(pb, dict) and pb.get("status") == "MATCH" and pb.get("binding") == ref:
                continue
            if isinstance(pb, dict) and pb.get("status") == "GAP" and pb.get("binding") is None \
                    and isinstance(pb.get("reason"), str):
                rep["seal_binding_gaps"].append({"seal": Path(p).stem, "gap": pb["reason"]})
                continue
            bad.append(f"seal {Path(p).stem}: process binding missing, malformed or different from the opening "
                       f"reference")
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            bad.append(f"seal {Path(p).stem}: process binding unverifiable ({type(e).__name__})")
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
    if a.get("stop_sha256") != c.sha_or_absent(out / "stop.json"):                # Task 12 (A2.1)
        probs.append("persisted stop (stop.json) hash differs")
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


def _capture_notes(out: Path, seals) -> dict:
    """Task 12 (final-review R-6, A1.2): report-only - every refused capture attempt (clock, bridge, seal refusal)
    and the receipt PROVENANCE observed at the seals (HEAD values, dirty/transient lists): changes are reported, never
    compared."""
    refused, binding = [], []
    for p in sorted((out / "captures").glob("*/*.report.json")):
        try:
            rep = _load(p)
        except (OSError, ValueError):
            continue
        if rep.get("refused"):
            refused.append({"scheduled": rep.get("scheduled"), "refused": rep["refused"]})
        binding += [{"scheduled": rep.get("scheduled"), "gap": g}            # A9.3: process-binding gaps, reported
                    for g in rep.get("observation_gaps", [])]
    prov = [s.get("receipt_provenance") or {} for _, s in seals]
    return {"refused_captures": refused, "binding_gaps": binding,
            "receipt_provenance": {"heads": sorted({str(x.get("head")) for x in prov if x.get("head") is not None}),
                                   "dirty": sorted({d for x in prov for d in (x.get("dirty") or [])}),
                                   "transient": sorted({d for x in prov for d in (x.get("transient") or [])})}}


def _report_restarts_and_bridge(rep: dict, opening, stop_seal, seals, out: Path) -> None:
    """Task 11 (controller-added), m-7: every report kind carries the observed restarts and the quantity bridge
    (design §14 Report). Restarts run from the opening seal to the stop seal (no stop: the latest seal); the bridge is
    the frozen final ledger's (None, with a note, when there is no readable stop-seal ledger)."""
    end = stop_seal
    if end is None and seals:
        try:
            end = max(seals, key=lambda ps: c.aware(ps[1]["close"]))[1]
        except (ValueError, KeyError, TypeError):
            end = None
    rep["restarts"] = _restarts(opening or {}, end or {}, out)   # malformed records still fail the attempt, as before
    rep.update(_capture_notes(out, seals))                       # Task 12 (R-6, A1.2): report-only
    if "quantity_bridge" not in rep:
        rep["quantity_bridge"] = None
        rep["quantity_bridge_note"] = "not available: no readable frozen final ledger (stop seal)"


def _median(xs):
    s = sorted(xs)
    return None if not s else (s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2)


def _score(out: Path, mailbox=None) -> dict:
    tid = _plan_trial_id(out)                              # F6.2 (M2): refuse first, never a silent None
    sim = c.sim()
    pr, plan = _load(out / "prereg.json"), _load(out / "plan.json")
    start, cal = c.aware(pr["start"]), pr["calendar"]
    rep = {"trial_id": tid, "outcome": "SCORED", "runner_sha256": runner_sha(), "start": pr["start"],
           "bundle_sha256": c.bundle_sha256(), "reasons": [], "protocol_notes": [],
           "scored_utc": c.now_utc().isoformat()}
    invalid = rep["reasons"]

    def done(verdict: str, attest) -> dict:
        rep.update(final_verdict(verdict, attest))
        rep["stop_attestation"] = attest
        if verdict == "SHADOW PASS" and not rep["nomination"]:
            rep["note"] = "numeric pass with UNVERIFIED-PROVENANCE: flagged exploratory result, not a nomination"
        return rep

    # 1. ABORTED-INVALID: recorded abort, broken bindings, seal/receipt/fence failures, bad stop record
    ab = c.load_abort(out)                                 # fix round 2 (B3.4): a corrupt one fails closed
    if ab is not None:
        invalid.append(f"checkpoint recorded ABORTED-INVALID: {ab.get('reason')}")
    if pr.get("runner_sha256") != runner_sha():          # controller ruling (Task 7): invalid, not a note
        invalid.append("runner changed since prereg")
    if pr.get("bundle_sha256") != c.bundle_sha256():                           # Task 12 (A3.4)
        invalid.append("bundle changed since prereg")
    invalid += [f"registration not verified: {x}" for x in g.run_ack_problems(out, pr, mailbox)]   # A8.2
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
    try:
        seals = _seals(out)
    except (OSError, ValueError) as e:                     # fix round 1 (I-4b): corrupt sealed evidence
        invalid.append(f"bad seal record: seal file unreadable ({type(e).__name__})")
        seals = []
    invalid += _seal_chain_problems(out, seals, _receipt_sha(pr["receipt"]), pr.get("bundle_sha256"))
    invalid += _capture_seal_problems(out)                                   # Task 11 (controller-added), m-2
    stop, stop_err = None, None
    try:                                                   # Task 12 (A2.1): the persisted stop, never recomputed
        if ab is not None and z.load_stop(out) is None:    # terminal: nothing is persisted now
            stop = dict(z.stop_decision([s for _, s in seals], start, cal, today=c.now_utc()), persisted=False)
        else:
            stop = z.current_stop(out, start, cal, c.now_utc(), "score")
        if stop.get("persisted"):
            invalid += z.stop_problems(out, start, cal)    # A2.3: integrity through the persisted stop
            sj = c.sha256_file(out / "stop.json")
            if (out / "attest_stop.json").exists() and _load(out / "attest_stop.json").get("stop_sha256") != sj:
                invalid.append("persisted stop (stop.json) changed after the stop attestation")
            fmp = out / "final" / "manifest.json"
            if fmp.exists() and _load(fmp).get("stop_sha256") not in (None, sj):
                invalid.append("persisted stop (stop.json) differs from the one the final acquisition bound")
            fsp = out / "final_snapshot" / "report.json"
            if fsp.exists() and _load(fsp).get("stop_sha256") not in (None, sj):
                invalid.append("persisted stop (stop.json) differs from the one the final snapshot bound")
        stop = {k_: stop[k_] for k_ in ("status", "stop_close", "missed")}
    except (ValueError, b.BookError, KeyError, TypeError) as e:
        stop_err = f"bad seal record: {type(e).__name__}: {e}"
    invalid += _final_snapshot_problems(out, seals, stop, pr.get("bundle_sha256"))   # C-1; A3.4 bundle
    if stop_err is not None:
        invalid.append(stop_err)
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
            if fm.get("final_plan_sha256") != c.sha256_file(out / "final_plan.json"):     # Task 11 (controller-
                invalid.append("final plan differs from the one the final acquisition used")  # added), m-1
            if fm.get("bundle_sha256") != pr.get("bundle_sha256"):                        # Task 12 (A3.4)
                invalid.append("final acquisition manifest bundle differs from prereg")
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
    invalid += _bridge_problems(rep, [s for _, s in seals], asof, start, cal)
    invalid += _seal_binding_problems(rep, seals, pr, opening_p, stop)      # fix round 2 (B2.3)
    _report_restarts_and_bridge(rep, opening, stop_seal, seals, out)        # Task 11 (controller-added), m-7
    if invalid:
        return done("ABORTED-INVALID", attest)

    # 2. BLOCKED: pre-START units known to the audit (re-checked; prereg should have refused)
    blocked = _blocked_reasons(plan, held0, since0, audit["corporate_actions.json"], audit["ca_problems.json"],
                               start)
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
    actions, conflicts = k.reconcile_actions(audit["corporate_actions.json"], final["corporate_actions.json"])
    problems = audit["ca_problems.json"] + final["ca_problems.json"] + conflicts     # A7.2: global, by identity
    rep["ca_conflicts"] = conflicts
    rep["carry_in"] = {"held_at_start": held, "held_since": since,
                       "bridge_rows": [t["id"] for t in bridge_rows if c.aware(t["ts"]) > c.aware(opening["close"])]}
    untrusted = (_coverage_reasons(held, since, set(fplan["ca_symbols_full_history"]), fplan["full_history_start"])
                 + carry_in_reasons(held, actions, since, problems=problems, until=stop_date,
                                    start_day=_ny_day(start), open_across=lambda sym, d: any(
                                        l["symbol"] == sym and l["entry_ts"] < start
                                        for l in open_lots_before(asof, d))))
    if untrusted:
        rep["reasons"] += untrusted
        return done("INCONCLUSIVE", attest)

    # 4b. Task 12 (A4.2): contaminated symbols. 2a (carry-in) was decided above; 2b: any SELL of a contaminated
    # symbol on/after the action's effective date through the stop -> whole-trial INCONCLUSIVE; 2c: otherwise every
    # cohort lot of the symbol is excluded in both arms (below), from action metadata only.
    contam = contaminated_symbols(asof, actions, start, stop_dt, held_syms=set(held))
    rep["contamination"] = {s: dict(info, rule="2b" if info["sells"] else "2c") for s, info in sorted(contam.items())}
    twob = {s: info for s, info in contam.items() if info["sells"]}
    if twob:
        rep["reasons"] += [f"unit event may affect stop/cohort attribution: {s} (actions {info['actions']}, "
                           f"effective {info['effective_dates']}; SELL(s) {info['sells']} on/after it, at or before "
                           f"the stop close)" for s, info in sorted(twob.items())]
        return done("INCONCLUSIVE", attest)

    # 5. cohort, paired exclusions, cap / minimum (no prices used yet)
    ids = {t["id"] for t in z.cohort(asof, start, stop_dt)}
    cohort = [l for l in lots if l["id"] in ids]
    sessions = [d["date"] for d in cal]
    covered = set(fplan["ca_symbols_window"]) | set(fplan["ca_symbols_full_history"])
    problems = problems + [{"problem": "symbol not covered by the final corporate-action request",
                            "blocks_symbols": [s]} for s in sorted({l["symbol"] for l in cohort} - covered)]
    untrusted = {s: [f"contaminated symbol {s}: unit/identity action(s) {info['actions']} with a lot open across "
                     f"(A4.2c, action metadata only)"] for s, info in contam.items()}
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
