"""E1 acquisition collector - Alpaca SIP raw daily bars, NYSE calendar and corporate actions for the frozen
roster-agent symbols (EXPERIMENTS_PREREG.md, E1-DATA). One attempt; everything verified before any request.

    python e1_fetch.py plan                 # write e1_inputs/plan.json (no network)
    python e1_fetch.py fetch <ACQUIRE_ACK>  # ONE acquisition attempt

Streams (frozen in the plan):
- calendar: GET https://paper-api.alpaca.markets/v2/calendar start=2026-03-17 end=2026-08-12 date_type=TRADING.
  The response must EQUAL the frozen expected schedule (published NYSE 2026 holidays inside the span: 04-03,
  05-25, 06-19, 07-03 observed; no early closes in the span, 2026 early closes are 11-27 and 12-24; source
  https://www.nyse.com/trade/hours-calendars, checked 2026-10-11). Times are New York local; any disagreement
  in dates, opens or closes aborts - the response never redefines the expected sessions.
- bars: GET https://data.alpaca.markets/v2/stocks/bars timeframe=1Day adjustment=raw feed=sip currency=USD
  sort=asc limit=10000 asof=2026-08-12, start=2026-03-17T04:00:00Z, end=2026-08-13T03:59:59.999999Z, batches
  of 50 symbols, next_page_token followed to null.
- corporate actions: GET https://data.alpaca.markets/v1/corporate-actions all types, process_date window
  2025-09-01..2026-10-11 (as of the acquisition), region=us, data_quality=all, sort=asc, limit=1000, batches of
  50 symbols, paginated. LIMITS: actions processed outside that window or published after the fetch are not
  covered; incomplete records are kept and flagged, never treated as "no action"; an empty result does not prove
  the absence of an action. Every record is classified against the per-type required fields of the alpaca-py
  models; incomplete, unclassifiable-type and conflicting-duplicate records are written to
  corporate_action_problems.json with the symbols they block (their own plus the whole request batch). The three
  verified splits are reconciled (found / missing / conflicting / not requested).
STRUCTURAL failures (HTTP != 200, transport, non-JSON, wrong root/field types, malformed tokens, repeated or
cyclic tokens, more than MAX_PAGES pages) ABORT the attempt; pages received are preserved; no manifest.
BAR-LEVEL data problems are recorded in problems.json (never silently dropped): missing session, duplicate
session, non-session date, non-positive or non-finite price, OHLC inconsistent. The E1 runner turns any problem
in a required path into INCONCLUSIVE for that agent. Unrequested symbols are listed and ignored.
Secrets are read from C:/Users/gl450/trading_app/.env at fetch time and sent only as headers.
"""
import hashlib
import json
import math
import re
import sqlite3
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROSTER = ("HistoricalTrendsAgent", "MeanReversionAgent", "XGBReasoningAgent")
CUTOFF = datetime(2026, 8, 12, 21, 0, 0, tzinfo=timezone.utc)
SPAN = ("2026-03-17", "2026-08-12")
CAL_URL = "https://paper-api.alpaca.markets/v2/calendar"
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
CA_URL = "https://data.alpaca.markets/v1/corporate-actions"
CAL_PARAMS = {"start": SPAN[0], "end": SPAN[1], "date_type": "TRADING"}
BAR_PARAMS = {"timeframe": "1Day", "start": "2026-03-17T04:00:00Z", "end": "2026-08-13T03:59:59.999999Z",
              "adjustment": "raw", "feed": "sip", "currency": "USD", "sort": "asc", "limit": 10000,
              "asof": "2026-08-12"}
CA_PARAMS = {"start": "2025-09-01", "end": "2026-10-11", "region": "us", "data_quality": "all", "sort": "asc",
             "limit": 1000}
NYSE_HOLIDAYS_IN_SPAN = ("2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03")
NYSE_EARLY_CLOSES_IN_SPAN = ()
NYSE_SOURCE = "https://www.nyse.com/trade/hours-calendars (checked 2026-10-11)"
VERIFIED_SPLITS = ({"symbol": "BKNG", "date": "2026-04-06", "ratio": 25.0},
                   {"symbol": "KLAC", "date": "2026-06-12", "ratio": 10.0},
                   {"symbol": "CRWD", "date": "2026-07-02", "ratio": 4.0})
# per-type required fields (alpaca-py data/models/corporate_actions.py): s=str, n=number, b=bool, d=date
CA_SCHEMA = {
    "forward_splits": {"symbol": "s", "cusip": "s", "new_rate": "n", "old_rate": "n", "process_date": "d",
                       "ex_date": "d"},
    "reverse_splits": {"symbol": "s", "old_cusip": "s", "new_cusip": "s", "new_rate": "n", "old_rate": "n",
                       "process_date": "d", "ex_date": "d"},
    "unit_splits": {"old_symbol": "s", "old_cusip": "s", "old_rate": "n", "new_symbol": "s", "new_cusip": "s",
                    "new_rate": "n", "alternate_symbol": "s", "alternate_cusip": "s", "alternate_rate": "n",
                    "process_date": "d", "effective_date": "d"},
    "stock_dividends": {"symbol": "s", "cusip": "s", "rate": "n", "process_date": "d", "ex_date": "d"},
    "cash_dividends": {"symbol": "s", "cusip": "s", "rate": "n", "special": "b", "foreign": "b",
                       "process_date": "d", "ex_date": "d"},
    "spin_offs": {"source_symbol": "s", "source_cusip": "s", "source_rate": "n", "new_symbol": "s",
                  "new_cusip": "s", "new_rate": "n", "process_date": "d", "ex_date": "d"},
    "cash_mergers": {"acquiree_symbol": "s", "acquiree_cusip": "s", "rate": "n", "process_date": "d",
                     "effective_date": "d"},
    "stock_mergers": {"acquirer_symbol": "s", "acquirer_cusip": "s", "acquirer_rate": "n", "acquiree_symbol": "s",
                      "acquiree_cusip": "s", "acquiree_rate": "n", "process_date": "d", "effective_date": "d"},
    "stock_and_cash_mergers": {"acquirer_symbol": "s", "acquirer_cusip": "s", "acquirer_rate": "n",
                               "acquiree_symbol": "s", "acquiree_cusip": "s", "acquiree_rate": "n",
                               "cash_rate": "n", "process_date": "d", "effective_date": "d"},
    "redemptions": {"symbol": "s", "cusip": "s", "rate": "n", "process_date": "d"},
    "name_changes": {"old_symbol": "s", "old_cusip": "s", "new_symbol": "s", "new_cusip": "s", "process_date": "d"},
    "worthless_removals": {"symbol": "s", "cusip": "s", "process_date": "d"},
    "rights_distributions": {"source_symbol": "s", "source_cusip": "s", "new_symbol": "s", "new_cusip": "s",
                             "rate": "n", "process_date": "d", "ex_date": "d"},
}
CA_SYMBOL_FIELDS = ("symbol", "old_symbol", "new_symbol", "alternate_symbol", "acquiree_symbol", "acquirer_symbol",
                    "source_symbol")
CA_EFFECTIVE_FIELDS = ("ex_date", "effective_date", "process_date")
BATCH, MAX_PAGES = 50, 20
OPEN_NY = "09:30"
ACK_TOKEN = "E1-ACQUIRE-ACK collector_sha256={collector} plan_sha256={plan}"
PINS = {"db": "411da6472eec35c98f5a727fd25cc2a89d4768f29745cfbf5de0a569971cb367"}
PATH_GLOBALS = ("ROOT", "OUT", "PLAN", "ATTEMPT", "PAGES", "BARS", "CALENDAR", "CORP", "CA_PROBLEMS", "PROBLEMS",
                "MANIFEST", "LOG", "DB", "T1_MANIFEST", "MAILBOX", "ENV_FILE")
COLLECTOR = Path(__file__).resolve()


class Structural(Exception):
    """Transport / HTTP / schema / pagination failure: aborts the attempt."""


def configure(root, env_file=None):
    g = globals()
    root = Path(root)
    out = root / "e1_inputs"
    g.update(ROOT=root, OUT=out, PLAN=out / "plan_rev2.json", ATTEMPT=out / "fetch.attempt", PAGES=out / "pages",
             BARS=out / "bars.json", CALENDAR=out / "calendar.json", CORP=out / "corporate_actions.json",
             CA_PROBLEMS=out / "corporate_action_problems.json",
             PROBLEMS=out / "problems.json", MANIFEST=out / "manifest.json", LOG=out / "attempts.jsonl",
             DB=root / "t1_inputs" / "trading_snapshot.db", T1_MANIFEST=root / "t1_inputs" / "manifest.json",
             MAILBOX=root / "mailbox.sqlite3",
             ENV_FILE=Path(env_file) if env_file else (root / "dummy.env" if root != HERE
                                                       else Path("C:/Users/gl450/trading_app/.env")))


configure(HERE)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def log(event: str, **kw) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t_utc": now_utc().isoformat(), "event": event, "argv": sys.argv[1:], **kw},
                           default=str) + "\n")


def env_identity() -> dict:
    import httpx
    import tzdata
    return {"python": sys.version.split()[0], "httpx": getattr(httpx, "__version__", None),
            "tzdata": getattr(tzdata, "__version__", None), "executable": sys.executable}


# ---------------------------------------------------------------- plan
def roster_symbols() -> list:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT t.symbol, t.timestamp FROM trades t JOIN agents a ON a.id=t.agent_id WHERE a.name IN "
                           f"({','.join('?' * len(ROSTER))})", ROSTER).fetchall()
    finally:
        con.close()
    syms = set()
    for sym, ts in rows:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        if t <= CUTOFF:
            syms.add(sym)
    return sorted(syms)


def bound_inputs() -> dict:
    db = sha256(DB)
    if db != PINS["db"]:
        raise SystemExit("ledger snapshot differs from its approved hash")
    if json.loads(T1_MANIFEST.read_text(encoding="utf-8"))["trading_snapshot.db"] != db:
        raise SystemExit("ledger snapshot does not match its t1 manifest")
    return {"db_sha256": db, "t1_manifest_sha256": sha256(T1_MANIFEST)}


def expected_sessions() -> list:
    """Frozen expected schedule: every weekday in the span except the published NYSE holidays."""
    out, d, end = [], date.fromisoformat(SPAN[0]), date.fromisoformat(SPAN[1])
    while d <= end:
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in NYSE_HOLIDAYS_IN_SPAN:
            out.append({"date": iso, "open": OPEN_NY,
                        "close": "13:00" if iso in NYSE_EARLY_CLOSES_IN_SPAN else "16:00"})
        d = date.fromordinal(d.toordinal() + 1)
    return out


def contract() -> dict:
    return {"calendar": {"url": CAL_URL, "params": CAL_PARAMS, "expected_sessions": expected_sessions(),
                         "source": NYSE_SOURCE},
            "bars": {"url": BARS_URL, "params": BAR_PARAMS, "batch": BATCH},
            "corporate_actions": {"url": CA_URL, "params": CA_PARAMS, "batch": BATCH,
                                  "schema_types": sorted(CA_SCHEMA), "verified_splits": list(VERIFIED_SPLITS)},
            "max_pages_per_batch": MAX_PAGES, "retry_policy": "none", "span": list(SPAN)}


def do_plan() -> None:
    if PLAN.exists():
        raise SystemExit("plan.json exists - refusing to overwrite")
    syms = roster_symbols()
    plan = {"created_utc": now_utc().isoformat(), "collector_sha256": sha256(COLLECTOR), "symbols": syms,
            "n_symbols": len(syms), "symbols_sha256": sha256_bytes(json.dumps(syms).encode()),
            "bound_inputs": bound_inputs(), "contract": contract(), "env": env_identity()}
    OUT.mkdir(parents=True, exist_ok=True)
    with PLAN.open("x", encoding="utf-8") as f:
        f.write(json.dumps(plan, indent=1))
    log("PLAN", plan_sha256=sha256(PLAN), n_symbols=len(syms))
    print(json.dumps({"plan_sha256": sha256(PLAN), "collector_sha256": plan["collector_sha256"], "n": len(syms)}))


def verify_plan() -> dict:
    if not PLAN.exists():
        raise SystemExit("no plan.json")
    try:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            raise TypeError("plan must be an object")
    except (ValueError, TypeError) as e:
        raise SystemExit(f"malformed plan: {e}")
    if plan.get("collector_sha256") != sha256(COLLECTOR):
        raise SystemExit("collector changed since plan")
    if plan.get("contract") != contract():
        raise SystemExit("request contract differs from plan")
    if plan.get("env") != env_identity():
        raise SystemExit("environment differs from plan")
    if plan.get("bound_inputs") != bound_inputs():
        raise SystemExit("bound inputs changed since plan")
    syms = roster_symbols()
    if (plan.get("symbols") != syms or plan.get("n_symbols") != len(syms)
            or plan.get("symbols_sha256") != sha256_bytes(json.dumps(syms).encode())):
        raise SystemExit("symbol list differs from plan")
    return plan


def verify_ack(ack_id: str, plan: dict, plan_sha: str) -> dict:
    con = sqlite3.connect(f"file:{MAILBOX}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT sender, recipient, request_key, body, created FROM messages WHERE id=?",
                          (ack_id,)).fetchone()
    finally:
        con.close()
    if row is None or (row[0], row[1], row[2]) != ("codex", "claude", "experiments-prereg"):
        raise SystemExit(f"{ack_id!r} is not a codex->claude experiments-prereg message")
    token = ACK_TOKEN.format(collector=plan["collector_sha256"], plan=plan_sha)
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in (row[3] or "").split("\n")]
    if token not in lines:
        raise SystemExit(f"ack lacks the standalone line: {token}")
    ack_t = datetime.fromtimestamp(row[4], tz=timezone.utc)
    plan_t = datetime.fromisoformat(plan["created_utc"])
    if plan_t.tzinfo is None or not (plan_t <= ack_t <= now_utc()):
        raise SystemExit("ack time out of order")
    return {"ack_id": ack_id, "created_utc": ack_t.isoformat()}


def read_keys() -> tuple:
    keys = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip().strip('"').strip("'")
    return keys["ALPACA_API_KEY"], keys["ALPACA_SECRET_KEY"]


# ---------------------------------------------------------------- schema validation
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM = re.compile(r"^\d{2}:\d{2}$")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _aware(t, where):
    if not isinstance(t, str):
        raise Structural(f"{where}: timestamp not a string")
    try:
        d = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        raise Structural(f"{where}: unparseable timestamp {t!r}")
    if d.tzinfo is None or d.utcoffset() is None:
        raise Structural(f"{where}: naive timestamp {t!r}")
    return d


def validate_calendar(data, expected) -> list:
    """The response must equal the frozen expected schedule exactly (dates, NY open and close)."""
    if not isinstance(data, list) or not data:
        raise Structural("calendar: root must be a non-empty list")
    got = []
    for c in data:
        if not isinstance(c, dict) or any(k not in c for k in ("date", "open", "close")):
            raise Structural("calendar: malformed entry")
        if not (isinstance(c["date"], str) and _DATE.match(c["date"])):
            raise Structural(f"calendar: bad date {c.get('date')!r}")
        try:
            date.fromisoformat(c["date"])
        except ValueError:
            raise Structural(f"calendar: nonexistent date {c['date']!r}")
        if not (isinstance(c["open"], str) and _HHMM.match(c["open"]) and isinstance(c["close"], str)
                and _HHMM.match(c["close"])):
            raise Structural("calendar: bad open/close format")
        got.append({"date": c["date"], "open": c["open"], "close": c["close"]})
    if got != list(expected):
        missing = sorted({e["date"] for e in expected} - {g["date"] for g in got})
        extra = sorted({g["date"] for g in got} - {e["date"] for e in expected})
        raise Structural(f"calendar disagrees with the frozen schedule: missing {missing[:5]} extra {extra[:5]}")
    return got


def validate_token(tok, where):
    if tok is not None and not (isinstance(tok, str) and tok):
        raise Structural(f"{where}: malformed next_page_token {tok!r}")


def validate_bars_page(data, where) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("bars"), dict):
        raise Structural(f"{where}: 'bars' missing or not an object")
    if "next_page_token" not in data:
        raise Structural(f"{where}: next_page_token key missing (explicit null required on the last page)")
    for sym, rows in data["bars"].items():
        if not isinstance(rows, list):
            raise Structural(f"{where}: bars[{sym!r}] not a list")
        for b in rows:
            if not isinstance(b, dict) or any(k not in b for k in ("t", "o", "h", "l", "c")):
                raise Structural(f"{where}: malformed bar for {sym!r}")
            if not all(_num(b[k]) for k in ("o", "h", "l", "c")):
                raise Structural(f"{where}: non-numeric OHLC for {sym!r}")
            _aware(b["t"], f"{where}/{sym}")
    validate_token(data.get("next_page_token"), where)


def validate_ca_page(data, where) -> None:
    if not isinstance(data, dict) or "corporate_actions" not in data or "next_page_token" not in data:
        raise Structural(f"{where}: corporate-actions root malformed")
    ca = data["corporate_actions"]
    if not isinstance(ca, dict):
        raise Structural(f"{where}: corporate_actions not an object")
    for kind, items in ca.items():
        if not isinstance(items, list):
            raise Structural(f"{where}: {kind} not a list")
        for it in items:
            if not isinstance(it, dict):
                raise Structural(f"{where}: {kind} item is not an object")
    validate_token(data["next_page_token"], where)


# ---------------------------------------------------------------- acquisition
def write_exclusive(path: Path, data: bytes, created: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(data)
    created.append(path)


def get(client, url, params, headers, name, created):
    try:
        resp = client.get(url, params=params, headers=headers)
    except Exception as e:
        raise Structural(f"{name}: transport error {type(e).__name__}")
    write_exclusive(PAGES / name, resp.content, created)
    if resp.status_code != 200:
        raise Structural(f"{name}: HTTP {resp.status_code}")
    try:
        return json.loads(resp.content)
    except ValueError:
        raise Structural(f"{name}: body is not JSON")


def paged(client, url, base, headers, prefix, validate, created) -> list:
    pages, token, seen, n = [], None, set(), 0
    while True:
        if n >= MAX_PAGES:
            raise Structural(f"{prefix}: more than {MAX_PAGES} pages")
        params = dict(base)
        if token:
            params["page_token"] = token
        name = f"{prefix}_page{n:03d}.json"
        data = get(client, url, params, headers, name, created)
        validate(data, name)
        pages.append(data)
        token, n = data.get("next_page_token"), n + 1
        if not token:
            return pages
        if token in seen:
            raise Structural(f"{name}: repeated/cyclic next_page_token")
        seen.add(token)


def parse_bars(symbols, pages, sessions):
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    requested, sess = set(symbols), set(sessions)
    out, problems, unexpected = {s: [] for s in symbols}, [], set()
    last_t = {}
    lo = datetime.fromisoformat(BAR_PARAMS["start"].replace("Z", "+00:00"))
    hi = datetime.fromisoformat(BAR_PARAMS["end"].replace("Z", "+00:00"))
    for page in pages:
        for sym, rows in page["bars"].items():
            if sym not in requested:
                unexpected.add(sym)
                continue
            for b in rows:
                t = _aware(b["t"], sym)
                local = t.astimezone(ny)
                d = local.date().isoformat()
                if (local.hour, local.minute, local.second, local.microsecond) != (0, 0, 0, 0):
                    problems.append({"symbol": sym, "session": d, "problem": "bar start not New York midnight"})
                if not (lo <= t <= hi):
                    problems.append({"symbol": sym, "session": d, "problem": "outside requested interval"})
                if sym in last_t and t <= last_t[sym]:
                    problems.append({"symbol": sym, "session": d, "problem": "out of order"})
                last_t[sym] = t
                out[sym].append({"t": b["t"], "session_date_ny": d, "o": b["o"], "h": b["h"], "l": b["l"],
                                 "c": b["c"], "v": b.get("v")})
    for sym in symbols:
        seen = set()
        for b in out[sym]:
            vals = [b[k] for k in ("o", "h", "l", "c")]
            if not all(math.isfinite(v) and v > 0 for v in vals):
                problems.append({"symbol": sym, "session": b["session_date_ny"],
                                 "problem": "non-positive or non-finite price"})
            elif not (b["l"] <= min(b["o"], b["c"]) <= max(b["o"], b["c"]) <= b["h"]):
                problems.append({"symbol": sym, "session": b["session_date_ny"], "problem": "ohlc inconsistent"})
            if b["session_date_ny"] not in sess:
                problems.append({"symbol": sym, "session": b["session_date_ny"], "problem": "not a trading session"})
            if b["session_date_ny"] in seen:
                problems.append({"symbol": sym, "session": b["session_date_ny"], "problem": "duplicate session"})
            seen.add(b["session_date_ny"])
        if out[sym]:
            for s in sessions:
                if s not in seen:
                    problems.append({"symbol": sym, "session": s, "problem": "missing session"})
        else:
            problems.append({"symbol": sym, "session": None, "problem": "no bars"})
    return out, problems, sorted(unexpected)


def _field_ok(v, kind) -> bool:
    if kind == "s":
        return isinstance(v, str) and v != ""
    if kind == "n":
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    if kind == "b":
        return isinstance(v, bool)
    if not (isinstance(v, str) and _DATE.match(v)):
        return False
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


def _comparable(rec):
    return {k: v for k, v in rec.items() if k != "request_batch"}


def classify_ca(batched_pages):
    """batched_pages: [(batch_symbols, page)]. Returns (records, problems). Identical duplicates are dropped;
    conflicting duplicates are kept and flagged; incomplete / unclassifiable records are kept and flagged with
    the symbols they block (their own symbols plus the whole request batch)."""
    records, problems, seen = [], [], {}
    for batch, page in batched_pages:
        for kind, items in page["corporate_actions"].items():
            for it in items:
                syms = sorted({it[f] for f in CA_SYMBOL_FIELDS if isinstance(it.get(f), str) and it[f]})
                rid = it.get("id")
                rec = dict(it, type=kind, affected_symbols=syms, request_batch=list(batch))
                if kind not in CA_SCHEMA:
                    rec["classification"] = "unclassifiable"
                    problems.append({"problem": "unclassifiable type", "type": kind, "id": rid,
                                     "blocks_symbols": sorted(set(syms) | set(batch))})
                else:
                    ok = isinstance(rid, str) and rid != "" and all(_field_ok(it.get(f), k)
                                                                    for f, k in CA_SCHEMA[kind].items())
                    rec["classification"] = "valid" if ok else "incomplete"
                    if not ok:
                        problems.append({"problem": "incomplete record", "type": kind, "id": rid,
                                         "blocks_symbols": sorted(set(syms) | set(batch))})
                    rec["effective_date"] = next((it[f] for f in CA_EFFECTIVE_FIELDS if _field_ok(it.get(f), "d")),
                                                 None)
                    if kind == "cash_dividends" and ok:
                        rec["dividend_kind"] = "special" if it["special"] else "ordinary"
                key = (kind, rid) if isinstance(rid, str) and rid else None
                if key is not None and key in seen:
                    prior = seen[key]
                    if _comparable(prior) == _comparable(rec):
                        continue                                   # identical duplicate
                    problems.append({"problem": "conflicting duplicate id", "type": kind, "id": rid,
                                     "blocks_symbols": sorted(set(syms) | set(prior["affected_symbols"]) | set(batch))})
                if key is not None:
                    seen[key] = rec
                records.append(rec)
    return records, problems


def reconcile_verified_splits(records, requested) -> list:
    out = []
    for v in VERIFIED_SPLITS:
        if v["symbol"] not in requested:
            out.append(dict(v, status="not requested"))
            continue
        cand = [r for r in records if r.get("type") == "forward_splits" and r.get("classification") == "valid"
                and r.get("symbol") == v["symbol"]]
        match = [r for r in cand if r.get("ex_date") == v["date"] and r["new_rate"] / r["old_rate"] == v["ratio"]]
        status = "found" if match else ("conflicting" if cand else "missing")
        out.append(dict(v, status=status, records=[r.get("id") for r in cand]))
    return out


def refuse_existing_evidence() -> None:
    clash = [p.name for p in (ATTEMPT, BARS, CALENDAR, CORP, CA_PROBLEMS, PROBLEMS, MANIFEST) if p.exists()]
    if PAGES.exists():
        clash.append("pages/")
    if clash:
        raise SystemExit(f"existing collection artifacts - refusing: {clash}")


def do_fetch(ack_id: str) -> None:
    import httpx
    try:
        plan = verify_plan()
        plan_sha = sha256(PLAN)
        ack = verify_ack(ack_id, plan, plan_sha)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
        raise SystemExit(f"preflight failed before reservation: {type(e).__name__}: {e}")
    refuse_existing_evidence()
    key, secret = read_keys()
    with ATTEMPT.open("x", encoding="utf-8") as f:
        f.write(json.dumps({"reserved_utc": now_utc().isoformat(), "ack": ack, "plan_sha256": plan_sha}))
    PAGES.mkdir()
    created, started, headers = [], now_utc().isoformat(), {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    syms = plan["symbols"]
    try:
        with httpx.Client(timeout=60.0) as client:
            cal = validate_calendar(get(client, CAL_URL, CAL_PARAMS, headers, "calendar.json", created),
                                    plan["contract"]["calendar"]["expected_sessions"])
            bar_pages, ca_pages = [], []
            for bi in range(0, len(syms), BATCH):
                batch = ",".join(syms[bi:bi + BATCH])
                bar_pages += paged(client, BARS_URL, dict(BAR_PARAMS, symbols=batch), headers,
                                   f"bars_b{bi // BATCH:02d}", validate_bars_page, created)
            for bi in range(0, len(syms), BATCH):
                batch = syms[bi:bi + BATCH]
                for pg in paged(client, CA_URL, dict(CA_PARAMS, symbols=",".join(batch)), headers,
                                f"ca_b{bi // BATCH:02d}", validate_ca_page, created):
                    ca_pages.append((batch, pg))
        sessions = [c["date"] for c in cal]
        bars, problems, unexpected = parse_bars(syms, bar_pages, sessions)
        ca_records, ca_problems = classify_ca(ca_pages)
        split_rec = reconcile_verified_splits(ca_records, set(syms))
    except (Structural, OSError) as e:
        log("ABORTED", reason=f"{type(e).__name__}: {e}", pages_preserved=[p.name for p in created])
        raise SystemExit(f"acquisition aborted: {type(e).__name__}: {e}")
    write_exclusive(CALENDAR, json.dumps(cal, indent=1).encode(), created)
    write_exclusive(BARS, json.dumps(bars).encode(), created)
    write_exclusive(CORP, json.dumps(ca_records, indent=1).encode(), created)
    write_exclusive(CA_PROBLEMS, json.dumps(ca_problems, indent=1).encode(), created)
    write_exclusive(PROBLEMS, json.dumps(problems, indent=1).encode(), created)
    manifest = {"created_utc": now_utc().isoformat(), "fetch_started_utc": started, "plan_sha256": plan_sha,
                "collector_sha256": plan["collector_sha256"], "ack": ack, "env": plan["env"],
                "files": {str(p.relative_to(OUT)).replace("\\", "/"): sha256(p) for p in created},
                "n_sessions": len(sessions), "n_symbols_with_bars": sum(1 for s in syms if bars[s]),
                "n_problems": len(problems), "unexpected_symbols": unexpected, "outcome": "COMPLETE",
                "n_corporate_actions": len(ca_records), "n_corporate_action_problems": len(ca_problems),
                "verified_split_reconciliation": split_rec,
                "corporate_action_coverage": {
                    "process_date_window": [CA_PARAMS["start"], CA_PARAMS["end"]], "as_of_utc": started,
                    "data_quality": CA_PARAMS["data_quality"],
                    "limits": "actions processed outside the window or published after the fetch are not covered; "
                              "incomplete records are flagged, not ignored; an empty result does not prove absence"},
                "label": "Alpaca SIP raw daily bars + calendar + corporate actions; vendor data, not official auction prices"}
    write_exclusive(MANIFEST, json.dumps(manifest, indent=1).encode(), [])
    log("COMPLETE", manifest_sha256=sha256(MANIFEST), n_problems=len(problems))
    print(json.dumps({"manifest_sha256": sha256(MANIFEST), "n_sessions": len(sessions),
                      "n_symbols_with_bars": manifest["n_symbols_with_bars"], "n_problems": len(problems),
                      "n_corporate_actions": len(ca_records), "n_ca_problems": len(ca_problems),
                      "unexpected": unexpected}))


def main() -> None:
    args = sys.argv[1:]
    log("STARTED")
    try:
        if args == ["plan"]:
            do_plan()
        elif len(args) == 2 and args[0] == "fetch":
            do_fetch(args[1])
        else:
            raise SystemExit("usage: e1_fetch.py plan | fetch <ACQUIRE_ACK_ID>")
        log("COMPLETE")
    except SystemExit as e:
        log("ABORTED", reason=str(e))
        raise
    except Exception:
        log("ABORTED", reason=traceback.format_exc()[-2000:])
        raise


if __name__ == "__main__":
    main()
