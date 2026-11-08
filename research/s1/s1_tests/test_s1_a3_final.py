"""Addendum 3 rev 5 F1 (no provider call before stop_attest and the ACQUIRE-ACK; the ACK no earlier than the lag),
F4.6/F4.9 final rows (raw/SIP bars, CA window, CA full history; empty families), consistency before valuation, C-a,
C-b, F8.5. Behavioural RED against the Task 12 stub (s1_evidence/a3/t12_red.txt). Injected MockTransport clients;
synthetic stopped trials; spies (requests and valuation)."""
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_run as r
import s1_stage as sg
import s1_trial as t
from conftest import Spies, _Clock, s1_ack, s1_state

START = "2026-10-26T13:30:00+00:00"
KEYS = ("KEYID-dummy-123", "SECRET-dummy-456")
# (Deviation: match= on every pytest.raises, inherited rule) the intended refusal of each refused case
# (Fix round 1, M-3: each pinned to the one reason that fires; an ACK before the attestation precedes the
# final_plan row it binds, so F6.1 refuses before do_final's own attestation-order check)
ACK_REFUSAL = {"before-attest": r"created not after the journal row it references \(F6\.1\)",
               "before-lag": r"the ACQUIRE-ACK precedes the acquisition lag \(F1 step 4\)",
               "wrong-stop-line": r"stop_line_sha256 is not the TRIAL-STOP line",
               "wrong-prev": r"prev 'audit-ack' is not the S1-PREREG-ACK"}


def mb(root):
    return Path(root) / "mailbox.sqlite3"


def jrows(root):
    """(Deviation: read without the open-trial refusal - a malformed ACK chain makes open_trial refuse, and the
    oracle must still read the rows; as conftest.s1_first_invalid does.)"""
    trs = t.trials(t.scan(mb(root)))
    (tid,) = [x for x, tr_ in trs.items() if tr_.closed is None]
    return j.read_trial(tid, trs[tid].genesis, mb(root))


class Provider:
    def __init__(self, bars_pages=1, empty=False, fail_url=None):
        self.bars_pages, self.fail_url, self.sent = bars_pages, fail_url, []

    def __call__(self, req):
        self.sent.append(req)
        url = str(req.url).split("?")[0]
        if url == self.fail_url:
            return httpx.Response(500)
        if url == k.BARS_URL:
            n = sum(1 for x in self.sent if str(x.url).split("?")[0] == k.BARS_URL) - 1
            tok = None if n + 1 >= self.bars_pages else f"b{n}"
            return httpx.Response(200, json={"bars": {}, "next_page_token": tok})
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": None})


def ready(tmp_path, **kw):
    """Stopped, attested, final plan written; ACQUIRE-ACK at the lag (OQ-22). Returns (state, acquire instant)."""
    st_ = s1_state(tmp_path, START, score_ready=True, final=False, **kw)
    plan_at = st_["stop_attested_at"] + timedelta(hours=1)
    with _Clock(plan_at):
        k.write_final_plan(tmp_path)
    fp = json.loads((tmp_path / "s1_out" / "final_plan.json").read_text(encoding="utf-8"))
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    # (Deviation: a TIMEOUT stop's lag runs from its last sealed close, long before the attestation; the ACK must also
    # follow the final_plan row it binds, F6.1/F7.1 - so the later of the lag and the final plan)
    at = max(k._earliest_acquire(pr["calendar"], fp["stop_date"]), plan_at)
    s1_ack(tmp_path, "acq-ack", "S1-ACQUIRE-ACK", at + timedelta(minutes=1))
    return st_, at + timedelta(minutes=2)


def final(tmp_path, monkeypatch, prov, at):
    sp = Spies(monkeypatch)
    with _Clock(at):
        m = k.do_final(tmp_path, "acq-ack", sp.client(prov), KEYS)
    return m, sp


def commitment(root):
    tr = t.open_trial(mb(root))
    p = sg.staging_dir(root, tr.trial_id, "final") / "prepared.json"
    assert p.is_file(), "no final PREPARED commitment in staging"          # (Deviation: an assertion, not an OSError)
    return json.loads(p.read_bytes())


def test_final_policy_is_exactly_the_f49_final_rows():
    fp = {"bar_symbols": ["A", "B"], "ca_symbols_window": ["A"], "ca_symbols_full_history": ["B"],
          "full_history_start": "2026-09-01", "stop_date": "2026-10-28"}
    pr = {"start": "2026-10-26T13:30:00+00:00"}
    fixed = {"region": "us", "data_quality": "all", "sort": "asc", "limit": 1000}
    assert k.final_policy(fp, pr, "2026-11-02") == {
        "redirects": False, "max_pages": 200, "cutoff": "2026-11-02", "families": [
            {"name": "bars", "url": "https://data.alpaca.markets/v2/stocks/bars", "scope": "final", "batches": None,
             "base_params": {"symbols": "A,B", "timeframe": "1Day", "start": "2026-10-26T04:00:00Z",
                             "end": "2026-10-29T03:59:59.999999Z", "adjustment": "raw", "feed": "sip",
                             "limit": 10000},
             "paged": True, "page_template": "final/pages/bars_page{n:03d}.json"},
            {"name": "corporate_actions", "url": "https://data.alpaca.markets/v1/corporate-actions", "scope": "window",
             "batches": [["A"]], "base_params": [dict(fixed, symbols="A", start="2026-10-26", end="2026-11-02")],
             "paged": True, "page_template": "final/pages/ca_{i:03d}_page{n:03d}.json"},
            {"name": "corporate_actions", "url": "https://data.alpaca.markets/v1/corporate-actions",
             "scope": "full_history", "batches": [["B"]],
             "base_params": [dict(fixed, symbols="B", start="2026-09-01", end="2026-11-02")],
             "paged": True, "page_template": "final/pages_full/ca_{i:03d}_page{n:03d}.json"}]}


def test_normal_final_commits_every_member(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    m, sp = final(tmp_path, monkeypatch, Provider(bars_pages=2), at)
    cm = commitment(tmp_path)
    assert set(sg.FIXED_TREE["final"]) <= set(cm["members"])
    assert {p["scope"] for p in cm["provenance"]} >= {"final", "window"} and sp.n["request"] == len(cm["provenance"])


def test_final_members_are_the_fixed_names_plus_one_page_per_request(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    final(tmp_path, monkeypatch, Provider(bars_pages=3), at)
    cm = commitment(tmp_path)
    pages = [p["page_relpath"] for p in cm["provenance"]]
    assert len(pages) == len(set(pages)) and set(cm["members"]) == set(sg.FIXED_TREE["final"]) | set(pages)


def test_final_manifest_projection_equals_the_members(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    m, _ = final(tmp_path, monkeypatch, Provider(), at)
    cm = commitment(tmp_path)
    assert sg.manifest_projection("final", m) == {r_: h for r_, h in cm["members"].items()
                                                  if r_ != "final/manifest.json"}


def test_final_envelope_inputs_and_members(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    final(tmp_path, monkeypatch, Provider(), at)
    tr = t.open_trial(mb(tmp_path))
    ip = sg.staging_dir(tmp_path, tr.trial_id, "final") / "intent.json"
    assert ip.is_file(), "no final INTENT envelope in staging"            # (Deviation: an assertion, not an OSError)
    e = json.loads(ip.read_bytes())
    assert set(e["inputs"]) == {"final_plan.json", "prereg.json", "attest_stop.json"}
    assert e["acks"] == {"S1-ACQUIRE-ACK": tr.acks["S1-ACQUIRE-ACK"].sha}


@pytest.mark.parametrize("case", ["ok", "before-attest", "before-lag", "wrong-stop-line", "wrong-prev"])
def test_acquire_ack_binds_prev_stop_line_and_is_not_before_the_lag(tmp_path, monkeypatch, case):
    st_ = s1_state(tmp_path, START, score_ready=True, final=False)
    with _Clock(st_["stop_attested_at"] + timedelta(hours=1)):
        k.write_final_plan(tmp_path)
    fp = json.loads((tmp_path / "s1_out" / "final_plan.json").read_text(encoding="utf-8"))
    pr = json.loads((tmp_path / "s1_out" / "prereg.json").read_text(encoding="utf-8"))
    lag = k._earliest_acquire(pr["calendar"], fp["stop_date"])
    att = c.aware(json.loads((tmp_path / "s1_out" / "attest_stop.json").read_text(encoding="utf-8"))["recorded_utc"])
    when = {"ok": lag + timedelta(minutes=1), "before-attest": att - timedelta(seconds=1),
            "before-lag": lag - timedelta(minutes=1)}.get(case, lag + timedelta(minutes=1))
    over = {"wrong-stop-line": {"stop_line_sha256": "0" * 64},
            "wrong-prev": {"prev": t.open_trial(mb(tmp_path)).audit.mailbox_id}}.get(case, {})
    s1_ack(tmp_path, "acq-ack", "S1-ACQUIRE-ACK", when, **over)
    prov = Provider()
    if case == "ok":
        final(tmp_path, monkeypatch, prov, lag + timedelta(minutes=2))
        kinds = [x.kind for x in j.subject_rows(jrows(tmp_path), "stage/final")]
        assert kinds and kinds[-1] == "STAGE-CREATED", kinds                 # (Deviation: no IndexError on the stub)
        return
    with pytest.raises(SystemExit, match=ACK_REFUSAL[case]):
        final(tmp_path, monkeypatch, prov, lag + timedelta(minutes=2))
    assert prov.sent == [] and j.subject_rows(jrows(tmp_path), "stage/final") == []


def test_no_provider_request_before_stop_attest_and_acquire_ack(tmp_path, monkeypatch):
    st_ = s1_state(tmp_path, START, score_ready=True, stop_attest=False, final=False)
    prov = Provider()
    with pytest.raises(SystemExit, match=r"no final plan \(final_plan comes first, F1\)"):
        final(tmp_path, monkeypatch, prov, st_["now"])
    assert prov.sent == []


@pytest.mark.parametrize("empty", ["window", "full_history", "both"])
def test_empty_ca_family_sends_no_request_and_final_completes(tmp_path, monkeypatch, empty):
    """A3-R3C-1 (retrospective): ca_symbols_window is the cohort (empty: no post-START BUY - a TIMEOUT stop on a
    day-0 seal); ca_symbols_full_history is the carry-in/bridge symbols (empty: no carry-in)."""
    kw = {}
    if empty in ("window", "both"):
        kw.update(lots=[], seal_days=[0])
    if empty in ("full_history", "both"):
        kw.update(carry_in=())
    st_, at = ready(tmp_path, **kw)
    prov = Provider()
    m, _ = final(tmp_path, monkeypatch, prov, at)
    scopes = [p["scope"] for p in commitment(tmp_path)["provenance"]]
    assert m["outcome"] == "COMPLETE"
    assert ("window" in scopes) == (empty not in ("window", "both"))
    assert ("full_history" in scopes) == (empty not in ("full_history", "both"))


def test_both_ca_families_are_requested_and_reconciled(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    m, _ = final(tmp_path, monkeypatch, Provider(), at)
    scopes = {p["scope"] for p in commitment(tmp_path)["provenance"]}
    assert {"window", "full_history"} <= scopes and m["coverage"]["ca_conflicts"] == 0


def test_final_request_order_is_the_collector_order(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    prov = Provider()
    final(tmp_path, monkeypatch, prov, at)
    fams = [p["scope"] for p in commitment(tmp_path)["provenance"]]
    assert fams == sorted(fams, key=["final", "window", "full_history"].index)


def test_cutoff_is_the_intent_new_york_date_across_midnight(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    pre = datetime.combine(at.astimezone(c.NY).date(), time(23, 59, 59, 999999), tzinfo=c.NY).astimezone(timezone.utc)
    post = pre + timedelta(microseconds=2)
    now = [pre - timedelta(seconds=5)]
    real = j.append

    def at_intent(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-INTENT" and req.subject == "stage/final":
            kw["clock"] = lambda: pre
            res = real(trial_id, gen, req, ctx_fn, **kw)
            now[0] = post                                         # reservation and requests after New York midnight
            return res
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", at_intent)
    monkeypatch.setattr(c, "now_utc", lambda: now[0])
    prov, sp = Provider(), Spies(monkeypatch)
    m = k.do_final(tmp_path, "acq-ack", sp.client(prov), KEYS)
    want = pre.astimezone(c.NY).date().isoformat()
    reserved = json.loads((tmp_path / "s1_out" / "final" / "attempt.json").read_bytes())["reserved_utc"]
    assert m["publication_cutoff"] == want != c.aware(reserved).astimezone(c.NY).date().isoformat()
    assert all(r_.url.params.get("end") == want for r_ in prov.sent if "corporate-actions" in str(r_.url))


@pytest.mark.parametrize("victim", ["final/bars.json", "final/bar_problems.json", "final/corporate_actions.json",
                                    "final/ca_problems.json", "final/manifest.json", "final/pages/bars_page000.json",
                                    "final/pages/ca_000_page000.json", "final/pages_full/ca_000_page000.json"])
@pytest.mark.parametrize("damage", ["changed", "deleted"])
def test_damaged_final_member_is_invalid_before_valuation_with_zero_valuation_calls(tmp_path, monkeypatch, victim,
                                                                                    damage):
    st_, at = ready(tmp_path)
    final(tmp_path, monkeypatch, Provider(), at)
    s1_ack(tmp_path, "score-ack", "S1-SCORE-ACK", at + timedelta(days=1))
    p = tmp_path / "s1_out" / victim
    if damage == "deleted":
        p.unlink()
    else:
        p.write_bytes(p.read_bytes() + b" ")
    sp = Spies(monkeypatch)
    with _Clock(at + timedelta(days=2)), pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        r.score(tmp_path, "score-ack")
    assert sp.n["valuation"] == 0 and not (tmp_path / "s1_out" / "score").exists()


@pytest.mark.parametrize("case", ["extra-page", "missing-page", "extra-full-page"])
def test_final_extra_page_or_orphan_provenance_is_invalid(tmp_path, monkeypatch, case):
    st_, at = ready(tmp_path)
    final(tmp_path, monkeypatch, Provider(), at)
    out = tmp_path / "s1_out"
    if case == "extra-page":
        (out / "final" / "pages" / "bars_page009.json").write_text("{}", encoding="utf-8")
    elif case == "extra-full-page":
        (out / "final" / "pages_full" / "ca_009_page000.json").write_text("{}", encoding="utf-8")
    else:
        (out / "final" / "pages" / "bars_page000.json").unlink()
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "orphan")


def test_final_provider_anomaly_after_the_stop_is_invalid_with_no_retry(tmp_path, monkeypatch):
    st_, at = ready(tmp_path)
    with pytest.raises(SystemExit, match=r"INVALID \(provider-structural\)"):
        final(tmp_path, monkeypatch, Provider(fail_url=k.CA_URL), at)
    # Fix round 1, M-4 (F4.6, F8.5): the ABORTED record stays in staging with the provenance of every request sent
    # (the failing one last), no PREPARED, nothing of the stage under s1_out, and no credential in any file
    tr = t.trials(t.scan(mb(tmp_path)))
    (tid,) = list(tr)
    d = sg.staging_dir(tmp_path, tid, "final")
    ab = json.loads((d / "ABORTED.json").read_bytes())
    assert (ab["outcome"], ab["error_type"], ab["reason"]) == ("ABORTED", "Structural", "provider-structural")
    assert "HTTP 500" in ab["error"] and ab["provenance"] and ab["provenance"][-1]["status"] == 500
    assert not (d / "prepared.json").exists() and not (tmp_path / "s1_out" / "final").exists()
    leaked = [p for p in tmp_path.rglob("*") if p.is_file() and any(x.encode() in p.read_bytes() for x in KEYS)]
    assert leaked == []
    prov = Provider()
    with pytest.raises(SystemExit, match="INVALID"):
        final(tmp_path, monkeypatch, prov, at + timedelta(minutes=1))
    assert prov.sent == []


# ====================================================================== Task 12 fix round 1 (review I-1, M-1, M-4)
def _flaky_staging(monkeypatch, needle):
    """A transient local I/O fault: the first staging write whose relpath ends with `needle` raises PermissionError
    (a sharing violation), later writes are real."""
    real, hit = sg._Staging.put, []

    def put(self, rel, data):
        if rel.endswith(needle) and not hit:
            hit.append(rel)
            raise PermissionError(13, "transient sharing violation (test)")
        return real(self, rel, data)
    monkeypatch.setattr(sg._Staging, "put", put)
    return hit


LOCAL_IO = r"stage final: local I/O error after the INTENT \(PermissionError\).*refused with no row"


@pytest.mark.parametrize("needle", ["final/pages/bars_page000.json", "final/bars.json"])
def test_transient_local_oserror_after_the_intent_refuses_with_no_row_then_the_table_decides(tmp_path, monkeypatch,
                                                                                               needle):
    """Fix round 1, I-1 (ruling T12 concern 4, corrected): a local OSError inside the work (a staged page write
    inside the request loop, or a derived file after it) is not a provider anomaly - a refusal with no row and no
    ABORTED.json; re-entry is the F4 table's INTENT-without-PREPARED row: INVALID (stage-incomplete), no refetch."""
    st_, at = ready(tmp_path)
    hit = _flaky_staging(monkeypatch, needle)
    prov = Provider()
    with pytest.raises(BaseException, match=LOCAL_IO) as ei:          # (the old code raised a bare OSError for one)
        final(tmp_path, monkeypatch, prov, at)
    assert type(ei.value) is SystemExit and hit == [needle]
    assert "TRIAL-INVALID" not in [x.kind for x in jrows(tmp_path)]
    assert [x.kind for x in j.subject_rows(jrows(tmp_path), "stage/final")] == ["STAGE-INTENT"]
    assert list((tmp_path / "s1_staging").rglob("ABORTED.json")) == []
    n = len(prov.sent)
    with pytest.raises(SystemExit, match=r"stage final: INVALID \(stage-incomplete\)"):
        final(tmp_path, monkeypatch, prov, at + timedelta(minutes=1))
    assert len(prov.sent) == n


def test_a_sent_request_is_recorded_in_provenance_before_its_page_write(tmp_path):
    """Fix round 1, M-1 (F4.6: every request sent is recorded in provenance): the record precedes the page write, so a
    page-write failure never drops a sent request."""
    pol = k.final_policy({"bar_symbols": ["A"], "ca_symbols_window": [], "ca_symbols_full_history": [],
                          "full_history_start": "2026-10-26", "stop_date": "2026-10-27"}, {"start": START},
                         "2026-11-02")
    auth = k._Authorizer(pol)
    body = b'{"bars": {}, "next_page_token": null}'

    class FailingStage:
        files = {}

        def put(self, rel, data):
            raise PermissionError(13, "page write fails (test)")
    cl = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=body)),
                      follow_redirects=False)
    with pytest.raises(PermissionError, match="page write fails"):
        k._get(cl, auth, "bars", "final", k.BARS_URL, pol["families"][0]["base_params"], k._headers(KEYS),
               FailingStage())
    assert [(p["status"], p["page_relpath"], p["page_sha256"]) for p in auth.provenance] == \
        [(200, "final/pages/bars_page000.json", c.sha256_bytes(body))]
