import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import s1_collect as k
import s1_common

UTC = timezone.utc
START = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)   # Mon 09:30 EST open; >= now + 7 days (I-5)
FIXED_NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
KEYS = ("KEYID-dummy-123", "SECRET-dummy-456")


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    """Determinism: every clock read in s1_collect goes through s1_common.now_utc."""
    monkeypatch.setattr(s1_common, "now_utc", lambda: FIXED_NOW)


def mailbox(root, mid, body):
    con = sqlite3.connect(root / "mailbox.sqlite3")
    con.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT, sender TEXT, recipient TEXT, request_key TEXT, "
                "body TEXT, created REAL, acknowledged REAL)")
    con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,NULL)", (mid, "codex", "claude", "experiments-prereg",
                                                                  body, datetime(2026, 10, 20, tzinfo=UTC).timestamp()))
    con.commit(); con.close()


def weekdays(first, last):
    d, out = date.fromisoformat(first), []
    while d <= date.fromisoformat(last):
        if d.weekday() < 5:
            out.append({"date": d.isoformat(), "open": "09:30", "close": "16:00"})
        d += timedelta(days=1)
    return out


def full_calendar():
    """Synthetic NYSE-like calendar (weekdays) covering created date .. past deadline (2027-05-02) + 3 sessions."""
    return weekdays("2026-10-21", "2027-05-31")


def client(calls):
    def handler(req):
        calls.append(str(req.url))
        if "calendar" in str(req.url):
            return httpx.Response(200, json=full_calendar())
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    return httpx.Client(transport=httpx.MockTransport(handler))


def no_key_text_written(root):
    for f in Path(root).rglob("*"):
        if f.is_file() and f.name != "mailbox.sqlite3":
            txt = f.read_bytes().decode("utf-8", "ignore")
            assert KEYS[0] not in txt and KEYS[1] not in txt


def test_plan_is_written_once(tmp_path):
    k.write_plan(tmp_path, START, "2026-10-23", ["A", "B"], "2026-03-17")
    with pytest.raises(FileExistsError):
        k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")


def test_audit_refuses_without_exact_ack_and_makes_no_request(tmp_path):
    k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    mailbox(tmp_path, "m1", "approve, roughly")
    calls = []
    with pytest.raises(SystemExit):
        k.do_audit(tmp_path, "m1", client(calls), ("id", "secret"))
    assert calls == [] and not (tmp_path / "s1_out" / "audit").exists()


def test_audit_once_metadata_only(tmp_path):
    k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    mailbox(tmp_path, "m2", k.audit_token(tmp_path))
    calls = []
    m = k.do_audit(tmp_path, "m2", client(calls), ("id", "secret"))
    assert m["outcome"] == "COMPLETE" and not any("/bars" in u for u in calls)
    with pytest.raises(SystemExit):
        k.do_audit(tmp_path, "m2", client(calls), ("id", "secret"))
    assert "secret" not in json.dumps(m)


def test_final_plan_covers_carry_in_and_bridge_symbols(tmp_path):
    p = k.write_final_plan(tmp_path, "2027-01-20T21:00:00+00:00", ["A"], ["B", "NEW"], "2026-03-17")
    plan = json.loads(p.read_text(encoding="utf-8"))
    assert plan["bar_symbols"] == ["A", "B", "NEW"] and plan["ca_symbols_full_history"] == ["B", "NEW"]


# ---- additional tests required by the brief's Step 1 note and the controller rulings

def test_keys_never_written_and_manifest_has_hashes(tmp_path):
    k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    mailbox(tmp_path, "m3", k.audit_token(tmp_path))
    m = k.do_audit(tmp_path, "m3", client([]), KEYS)
    assert set(m["files"]) >= {"calendar.json", "corporate_actions.json", "ca_problems.json"}
    for name, h in m["files"].items():
        assert h == s1_common.sha256_file(tmp_path / "s1_out" / "audit" / name)
    assert m["pages"] and all((tmp_path / "s1_out" / p).exists() for p in m["pages"])
    no_key_text_written(tmp_path)


def test_audit_refuses_when_planned_start_has_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(s1_common, "now_utc", lambda: datetime(2026, 10, 1, 12, tzinfo=UTC))
    k.write_plan(tmp_path, datetime(2026, 10, 19, 13, 30, tzinfo=UTC), "2026-10-16", ["A"], "2026-03-17")
    monkeypatch.setattr(s1_common, "now_utc", lambda: FIXED_NOW)
    mailbox(tmp_path, "m4", k.audit_token(tmp_path))
    calls = []
    with pytest.raises(SystemExit):
        k.do_audit(tmp_path, "m4", client(calls), KEYS)
    assert calls == []


def test_ack_future_missing_or_embedded_token_is_refused(tmp_path, monkeypatch):
    k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    mailbox(tmp_path, "m5", k.audit_token(tmp_path))
    monkeypatch.setattr(s1_common, "now_utc", lambda: datetime(2026, 10, 19, tzinfo=UTC))
    with pytest.raises(SystemExit):
        k._ack(tmp_path, "m5", k.audit_token(tmp_path))
    monkeypatch.setattr(s1_common, "now_utc", lambda: FIXED_NOW)
    assert k._ack(tmp_path, "m5", k.audit_token(tmp_path))["ack_id"] == "m5"
    with pytest.raises(SystemExit):
        k._ack(tmp_path, "nope", k.audit_token(tmp_path))
    mailbox(tmp_path, "m6", "please " + k.audit_token(tmp_path) + " ok")
    with pytest.raises(SystemExit):
        k._ack(tmp_path, "m6", k.audit_token(tmp_path))


def test_audit_token_binds_start(tmp_path):
    k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    t = k.audit_token(tmp_path)
    assert "start=2026-11-02T14:30:00+00:00" in t and "plan_sha256=" in t and "collector_sha256=" in t


def bar(t, o, h, l, c):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": 1}


SESS = ["2026-10-26", "2026-10-27"]


def good_bars():
    return [bar("2026-10-26T04:00:00Z", 10, 11, 9, 10.5), bar("2026-10-27T04:00:00Z", 10, 11, 9, 10.5)]


def test_parse_bars_clean_and_flags():
    out, pr = k._parse_bars(["A"], [{"bars": {"A": good_bars()}}], SESS)
    assert pr == [] and set(out["A"]) == set(SESS)
    bad = [bar("2026-10-26T04:00:00Z", 10, 11, 10.2, 10.5), good_bars()[1]]          # l > min(o, c)
    _, pr = k._parse_bars(["A"], [{"bars": {"A": bad}}], SESS)
    assert any(p["session"] == "2026-10-26" for p in pr)
    dup = good_bars() + [good_bars()[0]]                                              # duplicate session
    _, pr = k._parse_bars(["A"], [{"bars": {"A": dup}}], SESS)
    assert any(p["session"] == "2026-10-26" for p in pr)
    off = good_bars() + [bar("2026-10-28T04:00:00Z", 10, 11, 9, 10)]                  # off-calendar
    _, pr = k._parse_bars(["A"], [{"bars": {"A": off}}], SESS)
    assert any(p["session"] == "2026-10-28" for p in pr)
    _, pr = k._parse_bars(["A"], [{"bars": {"A": good_bars()[:1]}}], SESS)            # missing session
    assert {"symbol": "A", "session": "2026-10-27", "problem": "missing session"} in pr
    _, pr = k._parse_bars(["A"], [{"bars": {"A": good_bars(), "Z": good_bars()}}], SESS)
    assert any(p["symbol"] == "Z" for p in pr)


def test_paged_refuses_repeated_token(tmp_path):
    def handler(req):
        return httpx.Response(200, json={"bars": {}, "next_page_token": "same"})
    cl = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(k.Structural, match="repeated"):
        k._paged(cl, "http://x/bars", {}, {}, tmp_path / "p", None, [])


def test_transport_error_message_has_no_key_text(tmp_path):
    def handler(req):
        raise httpx.ConnectError("boom " + KEYS[1] + " " + KEYS[0])
    cl = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(k.Structural) as e:
        k._get(cl, "http://x", {}, k._headers(KEYS), tmp_path / "pg.json", [])
    assert KEYS[0] not in str(e.value) and KEYS[1] not in str(e.value)


def test_get_http_error_and_non_json(tmp_path):
    cl = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="x")))
    with pytest.raises(k.Structural, match="HTTP 500"):
        k._get(cl, "http://x", {}, {}, tmp_path / "a.json", [])
    cl = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="not json")))
    with pytest.raises(k.Structural, match="not JSON"):
        k._get(cl, "http://x", {}, {}, tmp_path / "b.json", [])


def test_ca_pages_classified_and_problems_recorded(tmp_path):
    k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    mailbox(tmp_path, "m7", k.audit_token(tmp_path))
    split = {"id": "s1", "symbol": "A", "cusip": "c", "new_rate": 2.0, "old_rate": 1.0,
             "process_date": "2026-05-01", "ex_date": "2026-05-02"}

    def handler(req):
        if "calendar" in str(req.url):
            return httpx.Response(200, json=full_calendar())
        return httpx.Response(200, json={"corporate_actions": {"forward_splits": [split, {"id": "bad", "symbol": "A"}]},
                                         "next_page_token": None})
    cl = httpx.Client(transport=httpx.MockTransport(handler))
    k.do_audit(tmp_path, "m7", cl, KEYS)
    recs = json.loads((tmp_path / "s1_out" / "audit" / "corporate_actions.json").read_text())
    probs = json.loads((tmp_path / "s1_out" / "audit" / "ca_problems.json").read_text())
    assert {r["classification"] for r in recs} == {"valid", "incomplete"} and len(probs) == 1


ACQ_NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)       # after the close of the 3rd session after the stop (10-30)


def final_setup(tmp_path, monkeypatch, mid="f1", now=ACQ_NOW):
    """Input changes vs the brief draft: prereg calendar carries the close (I-2 lag), the ACK binds prereg (I-8),
    and the clock is moved past the registered acquisition lag."""
    monkeypatch.setattr(s1_common, "now_utc", lambda: now)
    out = tmp_path / "s1_out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "prereg.json").write_text(json.dumps({
        "start": "2026-10-26T13:30:00+00:00",
        "calendar": weekdays("2026-10-26", "2026-11-06")}), encoding="utf-8")
    k.write_final_plan(tmp_path, "2026-10-27T20:00:00+00:00", ["A"], ["B", "NEW"], "2026-03-17")
    mailbox(tmp_path, mid, k.ACQUIRE_ACK.format(collector=k.collector_sha(),
                                                plan=s1_common.sha256_file(out / "final_plan.json"),
                                                prereg=s1_common.sha256_file(out / "prereg.json")))


def test_final_requests_every_symbol_bars_and_full_history(tmp_path, monkeypatch):
    final_setup(tmp_path, monkeypatch)
    calls = []

    def handler(req):
        calls.append(req)
        if "/bars" in str(req.url):
            syms = req.url.params["symbols"].split(",")
            return httpx.Response(200, json={"bars": {s: good_bars() for s in syms}, "next_page_token": None})
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    cl = httpx.Client(transport=httpx.MockTransport(handler))
    m = k.do_final(tmp_path, "f1", cl, KEYS)
    assert m["outcome"] == "COMPLETE"
    bar_calls = [r for r in calls if "/bars" in str(r.url)]
    assert bar_calls[0].url.params["symbols"] == "A,B,NEW"
    ca = [r for r in calls if "corporate-actions" in str(r.url)]
    assert any(r.url.params["symbols"] == "B,NEW" and r.url.params["start"] == "2026-03-17" for r in ca)
    assert any(r.url.params["symbols"] == "A" and r.url.params["start"] == "2026-10-26" for r in ca)
    bars = json.loads((tmp_path / "s1_out" / "final" / "bars.json").read_text())
    assert set(bars) == {"A", "B", "NEW"} and set(bars["A"]) == set(SESS)
    assert json.loads((tmp_path / "s1_out" / "final" / "bar_problems.json").read_text()) == []
    n = len(calls)
    with pytest.raises(SystemExit):
        k.do_final(tmp_path, "f1", cl, KEYS)
    assert len(calls) == n
    no_key_text_written(tmp_path)


def test_final_refused_ack_makes_no_request(tmp_path, monkeypatch):
    final_setup(tmp_path, monkeypatch, "f2")
    mailbox(tmp_path, "f3", "nothing")
    calls = []
    with pytest.raises(SystemExit):
        k.do_final(tmp_path, "f3", client(calls), KEYS)
    assert calls == [] and not (tmp_path / "s1_out" / "final").exists()


# ======================= Task 6 review fix round 1 (all retrospective) =======================

def bars_handler(calls, mutate=None):
    def handler(req):
        calls.append(req)
        if "/bars" in str(req.url):
            syms = req.url.params["symbols"].split(",")
            page = {"bars": {s: good_bars() for s in syms}, "next_page_token": None}
            return httpx.Response(200, json=mutate(page) if mutate else page)
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    return handler


def run_final(tmp_path, monkeypatch, make_handler, mid="f1"):
    final_setup(tmp_path, monkeypatch, mid)
    calls = []
    return calls, httpx.Client(transport=httpx.MockTransport(make_handler(calls)))


def manifest_of(tmp_path, which):
    return json.loads((tmp_path / "s1_out" / which / "manifest.json").read_text(encoding="utf-8"))


def planned(tmp_path, start=START):
    k.write_plan(tmp_path, start, "2026-10-30", ["A"], "2026-03-17")
    mailbox(tmp_path, "a1", k.audit_token(tmp_path))


def audit_with_calendar(tmp_path, cal):
    planned(tmp_path)

    def handler(req):
        if "calendar" in str(req.url):
            return httpx.Response(200, json=cal)
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_write_plan_requires_aware_start_a_week_ahead_and_records_deadline(tmp_path):
    """Retrospective (Task 6 review fix round 1): I-5."""
    with pytest.raises(ValueError):
        k.write_plan(tmp_path, datetime(2026, 11, 2, 14, 30), "2026-10-30", ["A"], "2026-03-17")
    with pytest.raises(ValueError):
        k.write_plan(tmp_path, FIXED_NOW + timedelta(days=6, hours=23), "2026-10-30", ["A"], "2026-03-17")
    assert not (tmp_path / "s1_out" / "plan.json").exists()
    p = json.loads(k.write_plan(tmp_path, FIXED_NOW + timedelta(days=7), "2026-10-30", ["A"],
                                "2026-03-17").read_text())
    assert p["created_utc"] == FIXED_NOW.isoformat() and p["deadline"] == "2027-04-28"


@pytest.mark.parametrize("mutate,why", [
    (lambda cal: [], "empty"),
    (lambda cal: [x for x in cal if x["date"] != "2026-11-02"], "START not a session"),
    (lambda cal: [dict(x, open="10:30") if x["date"] == "2026-11-02" else x for x in cal], "START not the open"),
    (lambda cal: [x for x in cal if not ("2026-10-21" <= x["date"] <= "2026-10-27")], "fewer than 5 sessions"),
    (lambda cal: [x for x in cal if x["date"] <= "2027-04-30"], "short of deadline + 3 sessions"),
    (lambda cal: {"not": "a list"}, "wrong shape"),
])
def test_audit_aborts_on_bad_calendar(tmp_path, mutate, why):
    """Retrospective (Task 6 review fix round 1): I-5 + I-1 (ABORTED manifest, pages kept)."""
    cl = audit_with_calendar(tmp_path, mutate(full_calendar()))
    with pytest.raises(SystemExit):
        k.do_audit(tmp_path, "a1", cl, KEYS)
    m = manifest_of(tmp_path, "audit")
    assert m["outcome"] == "ABORTED" and m["error_type"] == "Structural" and m["pages"], why
    with pytest.raises(SystemExit):                                   # still one attempt
        k.do_audit(tmp_path, "a1", cl, KEYS)
    no_key_text_written(tmp_path)


def test_audit_accepts_calendar_at_exact_boundaries(tmp_path):
    """Retrospective (Task 6 review fix round 1): I-5 boundary - exactly 5 sessions before START (Oct 26-30),
    exactly deadline (2027-05-02, Sunday) + 3 sessions present (May 3, 4, 5)."""
    cal = [x for x in full_calendar() if "2026-10-26" <= x["date"] <= "2027-05-05"]
    cl = audit_with_calendar(tmp_path, cal)
    assert k.do_audit(tmp_path, "a1", cl, KEYS)["outcome"] == "COMPLETE"


def test_audit_midrun_http_failure_writes_aborted_manifest(tmp_path):
    """Retrospective (Task 6 review fix round 1): I-1."""
    planned(tmp_path)

    def handler(req):
        if "calendar" in str(req.url):
            return httpx.Response(200, json=full_calendar())
        return httpx.Response(429, text="slow down " + KEYS[1])
    with pytest.raises(SystemExit):
        k.do_audit(tmp_path, "a1", httpx.Client(transport=httpx.MockTransport(handler)), KEYS)
    m = manifest_of(tmp_path, "audit")
    assert m["outcome"] == "ABORTED" and m["error_type"] == "Structural" and "HTTP 429" in m["error"]
    assert all(len(h) == 64 for h in m["pages"].values()) and len(m["pages"]) == 2
    # the raw 429 body is preserved verbatim as a page (vendor text), but key text must be in no file
    # except the raw page the vendor echoed; this mock echoes the key, so only check non-page files:
    for f in (tmp_path / "s1_out").rglob("*.json"):
        if "pages" not in f.parts:
            assert KEYS[1] not in f.read_text(encoding="utf-8")


def test_foreign_exception_records_type_name_only(tmp_path, monkeypatch):
    """Retrospective (Task 6 review fix round 1): I-1 - non-Structural error text is never recorded."""
    planned(tmp_path)

    def boom(*a, **kw):
        raise RuntimeError(KEYS[1])
    monkeypatch.setattr(k, "_corporate_actions", boom)
    with pytest.raises(SystemExit) as e:
        k.do_audit(tmp_path, "a1", client([]), KEYS)
    assert KEYS[1] not in str(e.value) and e.value.__cause__ is None and e.value.__suppress_context__
    m = manifest_of(tmp_path, "audit")
    assert m["error_type"] == "RuntimeError" and m["error"] == "RuntimeError"
    no_key_text_written(tmp_path)


def test_e1_structural_from_ca_validation_is_recorded(tmp_path):
    """Retrospective (Task 6 review fix round 1): I-1/M-2 - the pinned collector's Structural is caught too."""
    planned(tmp_path)

    def handler(req):
        if "calendar" in str(req.url):
            return httpx.Response(200, json=full_calendar())
        return httpx.Response(200, json={"corporate_actions": []})
    with pytest.raises(SystemExit):
        k.do_audit(tmp_path, "a1", httpx.Client(transport=httpx.MockTransport(handler)), KEYS)
    m = manifest_of(tmp_path, "audit")
    assert m["outcome"] == "ABORTED" and "corporate-actions root malformed" in m["error"]


def test_audit_manifest_hashes_pages_coverage_limits_and_params(tmp_path):
    """Retrospective (Task 6 review fix round 1): I-4, I-7."""
    planned(tmp_path)
    reqs = []

    def handler(req):
        reqs.append(req)
        if "calendar" in str(req.url):
            return httpx.Response(200, json=full_calendar())
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})
    m = k.do_audit(tmp_path, "a1", httpx.Client(transport=httpx.MockTransport(handler)), KEYS)
    out = tmp_path / "s1_out"
    assert set(m["pages"]) == {"audit/pages/calendar.json", "audit/pages/ca_000_page000.json"}
    for rel, h in m["pages"].items():
        assert h == s1_common.sha256_file(out / rel) and ":" not in rel and "\\" not in rel
    assert m["limits"].startswith("Vendor coverage and publication lags are not guaranteed complete")
    assert m["coverage"]["ca_records"] == 0 and m["coverage"]["ca_problems"] == 0
    assert m["coverage"]["calendar_sessions"] == len(full_calendar())
    ca = [r for r in reqs if "corporate-actions" in str(r.url)][0].url.params
    assert (ca["region"], ca["data_quality"], ca["sort"]) == ("us", "all", "asc")
    assert ca["start"] == "2026-03-17" and ca["end"] == "2026-10-21"          # audit date (NY), not START
    assert m["publication_cutoff"] == "2026-10-21"


def test_final_lag_refused_before_reserving(tmp_path, monkeypatch):
    """Retrospective (Task 6 review fix round 1): I-2 - 3rd session after the stop closes 2026-10-30 20:00Z."""
    final_setup(tmp_path, monkeypatch, now=datetime(2026, 10, 30, 19, 59, tzinfo=UTC))
    calls = []
    with pytest.raises(SystemExit):
        k.do_final(tmp_path, "f1", client(calls), KEYS)
    assert calls == [] and not (tmp_path / "s1_out" / "final").exists()
    monkeypatch.setattr(s1_common, "now_utc", lambda: datetime(2026, 10, 30, 20, 0, tzinfo=UTC))   # exactly the close
    cl = httpx.Client(transport=httpx.MockTransport(bars_handler(calls)))
    m = k.do_final(tmp_path, "f1", cl, KEYS)
    assert m["outcome"] == "COMPLETE" and m["earliest_acquire_utc"] == "2026-10-30T20:00:00+00:00"


def test_final_lag_refused_when_calendar_lacks_three_later_sessions(tmp_path, monkeypatch):
    """Retrospective (Task 6 review fix round 1): I-2."""
    final_setup(tmp_path, monkeypatch)
    pr = tmp_path / "s1_out" / "prereg.json"
    pr.write_text(json.dumps({"start": "2026-10-26T13:30:00+00:00", "calendar": weekdays("2026-10-26", "2026-10-29")}))
    mailbox(tmp_path, "f9", k.ACQUIRE_ACK.format(collector=k.collector_sha(),
                                                 plan=s1_common.sha256_file(tmp_path / "s1_out" / "final_plan.json"),
                                                 prereg=s1_common.sha256_file(pr)))
    calls = []
    with pytest.raises(SystemExit):
        k.do_final(tmp_path, "f9", client(calls), KEYS)
    assert calls == [] and not (tmp_path / "s1_out" / "final").exists()


def test_final_request_params_windows_and_manifest(tmp_path, monkeypatch):
    """Retrospective (Task 6 review fix round 1): I-3, I-4, I-7, I-8."""
    calls, cl = run_final(tmp_path, monkeypatch, bars_handler)
    m = k.do_final(tmp_path, "f1", cl, KEYS)
    b = [r for r in calls if "/bars" in str(r.url)][0].url.params
    assert b["start"] == "2026-10-26T04:00:00Z"                               # NY midnight of START's session (EDT)
    assert b["end"] == "2026-10-28T03:59:59.999999Z"                          # NY midnight after the stop session
    cas = [r for r in calls if "corporate-actions" in str(r.url)]
    assert cas
    for r in cas:
        p = r.url.params
        assert (p["region"], p["data_quality"], p["sort"]) == ("us", "all", "asc") and p["end"] == "2026-10-31"
    out = tmp_path / "s1_out"
    assert m["prereg_sha256"] == s1_common.sha256_file(out / "prereg.json")
    assert m["publication_cutoff"] == "2026-10-31"
    assert "final/pages/bars_page000.json" in m["pages"]
    assert all(h == s1_common.sha256_file(out / rel) for rel, h in m["pages"].items())
    assert m["coverage"]["bars"]["A"] == {"present": 2, "missing": 0}
    assert "ca_records" in m["coverage"] and m["limits"].endswith("are not known.")
    no_key_text_written(tmp_path)


def test_final_ack_binds_prereg(tmp_path, monkeypatch):
    """Retrospective (Task 6 review fix round 1): I-8 - a prereg changed after the ACK is refused, no request."""
    final_setup(tmp_path, monkeypatch)
    pr = tmp_path / "s1_out" / "prereg.json"
    pr.write_text(pr.read_text() + " ")
    calls = []
    with pytest.raises(SystemExit):
        k.do_final(tmp_path, "f1", client(calls), KEYS)
    assert calls == [] and not (tmp_path / "s1_out" / "final").exists()


@pytest.mark.parametrize("mutate", [
    lambda page: {"bars": page["bars"]},                                          # next_page_token missing
    lambda page: dict(page, next_page_token=""),                                  # malformed token
    lambda page: {"bars": None, "next_page_token": None},
    lambda page: {"bars": {"A": [{"o": 1, "h": 1, "l": 1, "c": 1}]}, "next_page_token": None},      # no t
    lambda page: {"bars": {"A": [dict(good_bars()[0], c=True)]}, "next_page_token": None},          # bool price
])
def test_final_aborts_on_structurally_bad_bars_page(tmp_path, monkeypatch, mutate):
    """Retrospective (Task 6 review fix round 1): I-6 + I-1."""
    calls, cl = run_final(tmp_path, monkeypatch, lambda calls: bars_handler(calls, mutate))
    with pytest.raises(SystemExit):
        k.do_final(tmp_path, "f1", cl, KEYS)
    assert manifest_of(tmp_path, "final")["outcome"] == "ABORTED"


def test_parse_bars_flags_non_midnight_and_bool_prices():
    """Retrospective (Task 6 review fix round 1): I-6."""
    rows = [bar("2026-10-26T13:30:00Z", 10, 11, 9, 10.5), good_bars()[1]]
    out, pr = k._parse_bars(["A"], [{"bars": {"A": rows}}], SESS)
    assert any(p["session"] == "2026-10-26" for p in pr) and "2026-10-26" not in out["A"]
    rows = [bar("2026-10-26T04:00:00Z", True, 11, 9, 10.5), good_bars()[1]]
    _, pr = k._parse_bars(["A"], [{"bars": {"A": rows}}], SESS)
    assert any(p["session"] == "2026-10-26" for p in pr)
