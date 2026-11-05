"""Addendum 3 rev 5 F4.6 (the deterministic request policy enforced in _get/_paged before sending, provenance,
provider anomaly), F4.9 audit rows (calendar + corporate_actions/audit), F9 (audit as a stage after the AUDIT-ACK),
C-a (manifest projection), C-b (cross-midnight cutoff), C-e (positive path isolated). Behavioural RED against the
Task 9 stub (s1_evidence/a3/t9_red.txt). Injected httpx.MockTransport clients only; tmp mailbox; spies.
Task 9 additions: the Task 7 carry-forward N1 (stray slot files with no slot row and no readable calendar, after the
AUDIT-ACK and before the audit calendar exists, are judged: TRIAL-INVALID (registration-artifact), F3/F4)."""
import itertools
import json
import random
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import s1_collect as k
import s1_common as c
import s1_journal as j
import s1_stage as sg
import s1_trial as t
from conftest import Spies, s1_mailbox

UTC = timezone.utc
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
START = datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
KEYS = ("KEYID-dummy-123", "SECRET-dummy-456")
CAL = [{"date": d.isoformat(), "open": "09:30", "close": "16:00"}
       for d in (date(2026, 10, 1) + timedelta(days=i) for i in range(300)) if d.weekday() < 5]


class Provider:
    """A synthetic Alpaca: calendar listing; corporate-action pages per batch, with optional tokens."""

    def __init__(self, pages_per_batch=None, tokens=None, status=None):
        self.pages_per_batch, self.tokens, self.status = pages_per_batch or {}, tokens, status or {}
        self.sent = []

    def __call__(self, req):
        self.sent.append(req)
        url = str(req.url).split("?")[0]
        if url in self.status:
            return httpx.Response(self.status[url], headers={"Location": "https://evil.example.com/x"})
        if url == k.CAL_URL:
            return httpx.Response(200, json=CAL)
        syms = req.url.params.get("symbols")
        n = sum(1 for r in self.sent if str(r.url).split("?")[0] == url and r.url.params.get("symbols") == syms) - 1
        last = n + 1 >= self.pages_per_batch.get(syms, 1)
        tok = None if last else (self.tokens(n) if self.tokens else f"t-{syms[:6]}-{n}")
        return httpx.Response(200, json={"corporate_actions": {}, "next_page_token": tok})


def setup(root, symbols=("A",), now=NOW, start=START, opening_close="2026-10-23"):
    with _clock(now - timedelta(hours=1)):
        k.write_plan(root, start, opening_close, list(symbols), "2026-03-17")
    s1_mailbox(root, "audit-ack", c.audit_token(Path(root) / "s1_out"), now - timedelta(minutes=30))


def audit(root, monkeypatch, provider, now=NOW, mailbox=None):
    sp = Spies(monkeypatch)
    with _clock(now):
        m = k.do_audit(root, "audit-ack", sp.client(provider), KEYS, mailbox=mailbox)
    return m, sp


def _staged(root, name):
    """A staging file of the audit stage; asserted present (B3: the RED is an assertion, never a FileNotFoundError)."""
    tr = t.open_trial(Path(root) / "mailbox.sqlite3")
    p = sg.staging_dir(root, tr.trial_id, "audit") / name
    assert p.is_file(), f"no staged {name} for the audit stage"
    return p


def commitment(root):
    return json.loads(_staged(root, "prepared.json").read_bytes())


def kinds(root):
    tr = t.open_trial(Path(root) / "mailbox.sqlite3")
    return [(r_.kind, r_.subject) for r_ in j.read_trial(tr.trial_id, tr.genesis, Path(root) / "mailbox.sqlite3")]


class _clock:
    def __init__(self, at):
        self.at = at

    def __enter__(self):
        self.old = c.now_utc
        c.now_utc = self.at if callable(self.at) else (lambda: self.at)

    def __exit__(self, *exc):
        c.now_utc = self.old


def test_audit_policy_is_exactly_the_f49_audit_rows():
    syms = [f"S{i:03d}" for i in range(120)]
    plan = {"calendar_range": ["2026-10-13", "2027-05-10"], "ca_symbols": syms, "ca_range": ["2026-03-17", "2026-10-26"]}
    fixed = {"region": "us", "data_quality": "all", "sort": "asc", "limit": 1000}
    batches = [syms[0:50], syms[50:100], syms[100:120]]
    assert k.audit_policy(plan, "2026-10-13") == {
        "redirects": False, "max_pages": 200, "cutoff": "2026-10-13",
        "families": [
            {"name": "calendar", "url": "https://paper-api.alpaca.markets/v2/calendar", "scope": "audit",
             "batches": None, "base_params": {"start": "2026-10-13", "end": "2027-05-10", "date_type": "TRADING"},
             "paged": False, "page_template": "audit/pages/calendar.json"},
            {"name": "corporate_actions", "url": "https://data.alpaca.markets/v1/corporate-actions", "scope": "audit",
             "batches": batches,
             "base_params": [dict(fixed, symbols=",".join(b), start="2026-03-17", end="2026-10-13") for b in batches],
             "paged": True, "page_template": "audit/pages/ca_{i:03d}_page{n:03d}.json"}]}


def test_normal_audit_authorizes_calendar_and_ca_batches_and_commits_every_member(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(120)]
    setup(tmp_path, syms)
    prov = Provider(pages_per_batch={",".join(syms[0:50]): 2})
    m, sp = audit(tmp_path, monkeypatch, prov)
    com = commitment(tmp_path)
    pages = sorted(p["page_relpath"] for p in com["provenance"])
    assert pages == ["audit/pages/ca_000_page000.json", "audit/pages/ca_000_page001.json",
                     "audit/pages/ca_001_page000.json", "audit/pages/ca_002_page000.json", "audit/pages/calendar.json"]
    assert set(com["members"]) == set(sg.FIXED_TREE["audit"]) | set(pages)
    assert sp.n["request"] == len(com["provenance"]) == 5
    assert kinds(tmp_path) == [("STAGE-INTENT", "stage/audit"), ("STAGE-PREPARED", "stage/audit"),
                               ("STAGE-CREATED", "stage/audit")]


def test_unpredictable_tokens_and_page_counts_complete_with_full_provenance(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(140)]
    setup(tmp_path, syms)
    rnd = random.Random(20261103)
    per = {",".join(syms[i:i + 50]): rnd.randint(1, 4) for i in range(0, 140, 50)}
    prov = Provider(pages_per_batch=per, tokens=lambda n: f"{rnd.getrandbits(64):016x}")
    audit(tmp_path, monkeypatch, prov)
    pv = commitment(tmp_path)["provenance"]
    assert len(pv) == 1 + sum(per.values()) == len(prov.sent)
    for a, b in zip(pv, pv[1:]):
        if b["n"] > 0:
            assert b["page_token_from"] == a["page_relpath"] and "page_token" in b["params"]


CASES = ["repeated-token", "over-max-pages", "redirect", "other-host", "wrong-endpoint", "changed-base",
         "outside-batch", "other-paper-path"]


@pytest.mark.parametrize("case", CASES)
def test_structural_refusals_send_no_further_request_then_invalid(tmp_path, monkeypatch, case):
    syms = [f"S{i:03d}" for i in range(60)]
    setup(tmp_path, syms)
    frozen = k.audit_policy
    prov = Provider()
    if case == "repeated-token":
        prov = Provider(pages_per_batch={",".join(syms[:50]): 5}, tokens=lambda n: "same-token")
    elif case == "over-max-pages":
        prov = Provider(pages_per_batch={",".join(syms[:50]): 10_000})
    elif case == "redirect":
        prov = Provider(status={k.CA_URL: 302})
    else:                                                                 # the code deviates from the committed policy
        if case == "other-host":
            monkeypatch.setattr(k, "CA_URL", "https://evil.example.com/v1/corporate-actions")
        elif case == "wrong-endpoint":
            monkeypatch.setattr(k, "CA_URL", "https://data.alpaca.markets/v1beta1/corporate-actions")
        elif case == "changed-base":
            monkeypatch.setattr(k, "CA_FIXED", dict(k.CA_FIXED, limit=500))
        elif case == "outside-batch":
            monkeypatch.setattr(k, "CA_BATCH", 40)
        elif case == "other-paper-path":
            monkeypatch.setattr(k, "CAL_URL", "https://paper-api.alpaca.markets/v2/orders")
        monkeypatch.setattr(k, "audit_policy", lambda plan, cutoff, f=frozen: _policy_with_original_constants(
            f, plan, cutoff))
    with pytest.raises(SystemExit, match=r"INVALID \(provider-structural\)"):
        audit(tmp_path, monkeypatch, prov)
    aborted = json.loads(_staged(tmp_path, "ABORTED.json").read_bytes())
    assert len(prov.sent) == len(aborted["provenance"])                    # nothing sent beyond the provenance
    if case == "over-max-pages":
        assert len(prov.sent) == 1 + 200
    if case in ("other-host", "wrong-endpoint", "changed-base", "outside-batch", "other-paper-path"):
        assert {str(r.url).split("?")[0] for r in prov.sent} <= {"https://paper-api.alpaca.markets/v2/calendar"}
    assert [kd for kd, _ in kinds(tmp_path)] == ["STAGE-INTENT", "TRIAL-INVALID"]
    assert not (tmp_path / "s1_out" / "audit").exists()


ORIGINAL = {"CAL_URL": "https://paper-api.alpaca.markets/v2/calendar",
            "CA_URL": "https://data.alpaca.markets/v1/corporate-actions",
            "CA_FIXED": {"region": "us", "data_quality": "all", "sort": "asc", "limit": 1000}, "CA_BATCH": 50}


def _policy_with_original_constants(f, plan, cutoff):
    """The policy the INTENT commits is built from the registered constants; the test then makes the request path
    deviate (the constants the code sends from were changed after import)."""
    saved = {n: getattr(k, n) for n in ORIGINAL}
    try:
        for n, v in ORIGINAL.items():
            setattr(k, n, v)
        return f(plan, cutoff)
    finally:
        for n, v in saved.items():
            setattr(k, n, v)


def test_authorizer_refuses_a_second_calendar_request_and_an_unlisted_family():
    plan = {"calendar_range": ["2026-10-13", "2027-05-10"], "ca_symbols": [], "ca_range": ["2026-03-17", "2026-10-26"]}
    pol = k.audit_policy(plan, "2026-10-13")
    assert pol.get("families"), "the policy has no families"
    auth = k._Authorizer(pol)
    base = pol["families"][0]["base_params"]
    assert auth.authorize("calendar", "audit", k.CAL_URL, base) == (0, "audit/pages/calendar.json")
    auth.record("calendar", "audit", 0, k.CAL_URL, base, NOW.isoformat(), 200, "audit/pages/calendar.json", "0" * 64)
    assert auth.page_done(CAL) is None
    with pytest.raises(k.Structural, match="no family"):
        auth.authorize("calendar", "audit", k.CAL_URL, base)                # a second calendar request
    auth2 = k._Authorizer(pol)
    with pytest.raises(k.Structural, match="not the next family"):
        auth2.authorize("bars", "final", k.BARS_URL, {})


def test_every_sent_request_is_in_provenance(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(55)]
    setup(tmp_path, syms)
    prov = Provider(pages_per_batch={",".join(syms[:50]): 3})
    audit(tmp_path, monkeypatch, prov)
    pv = commitment(tmp_path)["provenance"]
    assert [(str(r.url).split("?")[0], dict(r.url.params)) for r in prov.sent] == [
        (p["url"], {n: str(v) for n, v in p["params"].items()}) for p in pv]
    for f in tmp_path.rglob("*"):
        if f.is_file() and f.name != "mailbox.sqlite3":
            txt = f.read_bytes().decode("utf-8", "ignore")
            assert KEYS[0] not in txt and KEYS[1] not in txt


def test_retrieved_utc_is_the_actual_observation_instant(tmp_path, monkeypatch):
    setup(tmp_path)
    ticks = itertools.count()
    clock = lambda: NOW + timedelta(seconds=next(ticks))                   # noqa: E731
    sp = Spies(monkeypatch)
    prov = Provider()
    seen = []

    def handler(req):
        seen.append(clock())                                              # the provider's own clock reading
        return prov(req)
    with _clock(clock):
        k.do_audit(tmp_path, "audit-ack", sp.client(handler), KEYS)
    src = json.loads((tmp_path / "s1_out" / "audit" / "calendar_source.json").read_bytes())
    pv = commitment(tmp_path)["provenance"]
    assert c.aware(src["retrieved_utc"]) > seen[0] and src["retrieved_utc"] == pv[0]["retrieved_utc"]


@pytest.mark.parametrize("pre,date_,start,oc", [
    (datetime(2026, 10, 13, 3, 59, 59, 999999, tzinfo=UTC), "2026-10-12", START, "2026-10-23"),
    (datetime(2026, 11, 1, 3, 59, 59, 999999, tzinfo=UTC), "2026-10-31", datetime(2026, 11, 16, 14, 30, tzinfo=UTC),
     "2026-11-13")], ids=["midnight", "dst-fall-back"])
def test_cutoff_is_the_intent_new_york_date_across_midnight(tmp_path, monkeypatch, pre, date_, start, oc):
    setup(tmp_path, ("A",), now=pre - timedelta(minutes=1), start=start, opening_close=oc)
    post = pre + timedelta(microseconds=2)
    now = [pre - timedelta(seconds=10)]
    real = j.append

    def at_intent(trial_id, gen, req, ctx_fn, **kw):
        if req.kind == "STAGE-INTENT":
            kw["clock"] = lambda: pre
            res = real(trial_id, gen, req, ctx_fn, **kw)
            now[0] = post                                                 # reservation and requests after midnight
            return res
        return real(trial_id, gen, req, ctx_fn, **kw)
    monkeypatch.setattr(j, "append", at_intent)
    prov = Provider()
    sp = Spies(monkeypatch)
    with _clock(lambda: now[0]):
        m = k.do_audit(tmp_path, "audit-ack", sp.client(prov), KEYS)
    reserved = json.loads((tmp_path / "s1_out" / "audit" / "attempt.json").read_bytes())["reserved_utc"]
    assert m["publication_cutoff"] == date_ != c.aware(reserved).astimezone(c.NY).date().isoformat()
    assert all(r.url.params.get("end") == date_ for r in prov.sent if "corporate-actions" in str(r.url))


def test_cutoff_same_day_positive_path(tmp_path, monkeypatch):
    setup(tmp_path)
    m, sp = audit(tmp_path, monkeypatch, Provider())
    assert m["outcome"] == "COMPLETE" and m["publication_cutoff"] == NOW.astimezone(c.NY).date().isoformat()


LEGACY_MANIFEST_KEYS = {"publication_cutoff", "ca_window", "plan_sha256", "bundle_sha256", "outcome", "ack", "files",
                        "pages", "coverage", "limits"}


def test_manifest_shape_is_preserved_and_its_projection_equals_the_members(tmp_path, monkeypatch):
    setup(tmp_path, ("A", "B"))
    m, _ = audit(tmp_path, monkeypatch, Provider())
    assert set(m) == LEGACY_MANIFEST_KEYS
    assert set(m["files"]) == {"attempt.json", "calendar_source.json", "calendar.json", "corporate_actions.json",
                               "ca_problems.json"}
    com = commitment(tmp_path)
    want = {r: h for r, h in com["members"].items() if r != "audit/manifest.json"}
    assert sg.manifest_projection("audit", m) == want


def test_empty_ca_symbols_send_no_ca_request_and_the_audit_completes(tmp_path, monkeypatch):
    setup(tmp_path, ())
    prov = Provider()
    m, _ = audit(tmp_path, monkeypatch, prov)
    assert m["outcome"] == "COMPLETE" and [str(r.url).split("?")[0] for r in prov.sent] == [k.CAL_URL]


def test_request_order_is_the_collector_order(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(110)]
    setup(tmp_path, syms)
    prov = Provider()
    audit(tmp_path, monkeypatch, prov)
    order = [(str(r.url).split("?")[0], r.url.params.get("symbols", "")[:4]) for r in prov.sent]
    assert order == [(k.CAL_URL, ""), (k.CA_URL, "S000"), (k.CA_URL, "S050"), (k.CA_URL, "S100")]


def test_provider_anomaly_keeps_aborted_staging_no_prepared_and_invalidates(tmp_path, monkeypatch):
    syms = [f"S{i:03d}" for i in range(60)]
    setup(tmp_path, syms)
    prov = Provider()
    real = prov.__call__

    def flaky(req):
        if req.url.params.get("symbols", "").startswith("S050"):
            prov.sent.append(req)
            return httpx.Response(500, content=b"server error")
        return real(req)
    with pytest.raises(SystemExit, match=r"INVALID \(provider-structural\)"):
        audit(tmp_path, monkeypatch, flaky)
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    staging = sg.staging_dir(tmp_path, tr.trial_id, "audit")
    assert (staging / "ABORTED.json").is_file() and (staging / "audit" / "pages" / "ca_001_page000.json").is_file()
    assert not (staging / "prepared.json").exists()
    assert [kd for kd, _ in kinds(tmp_path)] == ["STAGE-INTENT", "TRIAL-INVALID"]
    with pytest.raises(SystemExit, match="INVALID"):                                    # F8.5: no retry
        audit(tmp_path, monkeypatch, Provider())


def test_audit_runs_as_a_stage_only_after_the_audit_ack(tmp_path, monkeypatch):
    with _clock(NOW - timedelta(hours=1)):
        k.write_plan(tmp_path, START, "2026-10-23", ["A"], "2026-03-17")
    prov = Provider()
    with pytest.raises(SystemExit, match="zero open trials"):
        audit(tmp_path, monkeypatch, prov)
    assert prov.sent == []
    s1_mailbox(tmp_path, "audit-ack", c.audit_token(tmp_path / "s1_out"), NOW - timedelta(minutes=30))
    audit(tmp_path, monkeypatch, prov)
    intent = j.first(j.subject_rows(j.read_trial(*_tg(tmp_path)), "stage/audit"), "STAGE-INTENT")
    assert intent is not None, "no STAGE-INTENT row for the audit"
    env = json.loads(_staged(tmp_path, "intent.json").read_bytes())
    assert intent.detail == j.detail_of(env) and env["request_policy"]["families"][0]["name"] == "calendar"


def _tg(root):
    tr = t.open_trial(Path(root) / "mailbox.sqlite3")
    return tr.trial_id, tr.genesis, Path(root) / "mailbox.sqlite3"


def test_audit_envelope_inputs_and_members(tmp_path, monkeypatch):
    setup(tmp_path)
    audit(tmp_path, monkeypatch, Provider())
    tr = t.open_trial(tmp_path / "mailbox.sqlite3")
    env = json.loads(_staged(tmp_path, "intent.json").read_bytes())
    assert env["inputs"] == {"bundle": c.bundle_sha256(), "plan.json": c.sha256_file(tmp_path / "s1_out" / "plan.json")}
    assert env["acks"] == {"S1-AUDIT-ACK": tr.audit.sha} and env["stage"] == "audit" and env["trial_id"] == tr.trial_id


def test_members_are_the_fixed_names_plus_one_page_per_request(tmp_path, monkeypatch):
    setup(tmp_path, ("A",))
    audit(tmp_path, monkeypatch, Provider(pages_per_batch={"A": 3}))
    com = commitment(tmp_path)
    pages = [p["page_relpath"] for p in com["provenance"]]
    assert len(pages) == len(set(pages)) == 4 and set(com["members"]) == set(sg.FIXED_TREE["audit"]) | set(pages)


@pytest.mark.parametrize("victim", ["audit/calendar.json", "audit/pages/calendar.json", "audit/manifest.json",
                                    "audit/pages/ca_000_page000.json"])
@pytest.mark.parametrize("damage", ["changed", "deleted"])
def test_damaged_audit_member_is_invalid_before_use(tmp_path, monkeypatch, victim, damage):
    setup(tmp_path, ("A",))
    audit(tmp_path, monkeypatch, Provider())
    p = tmp_path / "s1_out" / victim
    if damage == "deleted":
        p.unlink()
    else:
        p.write_bytes(p.read_bytes() + b" ")
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "use of the audit")
    sp.assert_zero()


@pytest.mark.parametrize("case", ["extra-page", "missing-page"])
def test_extra_page_or_orphan_provenance_is_invalid(tmp_path, monkeypatch, case):
    setup(tmp_path, ("A",))
    audit(tmp_path, monkeypatch, Provider())
    if case == "extra-page":
        (tmp_path / "s1_out" / "audit" / "pages" / "ca_000_page001.json").write_text("{}", encoding="utf-8")
    else:
        (tmp_path / "s1_out" / "audit" / "pages" / "ca_000_page000.json").unlink()
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(tmp_path, "orphan")


@pytest.mark.parametrize("case", ["commitment", "attempt", "page"])
def test_cross_trial_substitution_is_invalid(tmp_path_factory, monkeypatch, case):    # row 312 (OQ-36, E5.4)
    mine, other = tmp_path_factory.mktemp("mine"), tmp_path_factory.mktemp("other")
    mb = {r: Path(r) / "mailbox.sqlite3" for r in (mine, other)}            # each root's own tmp mailbox (B4)
    setup(mine, ("A",))
    setup(other, ("A",))
    audit(mine, monkeypatch, Provider(), mailbox=mb[mine])
    audit(other, monkeypatch, Provider(pages_per_batch={"A": 2}), mailbox=mb[other])   # different page bytes
    tm, to = (t.open_trial(mb[r]).trial_id for r in (mine, other))
    assert tm != to
    if case == "commitment":
        src = sg.staging_dir(other, to, "audit") / "prepared.json"
        dst = sg.staging_dir(mine, tm, "audit") / "prepared.json"
        assert src.is_file() and dst.is_file(), "no staged commitment to substitute"
    elif case == "attempt":
        src, dst = other / "s1_out" / "audit" / "attempt.json", mine / "s1_out" / "audit" / "attempt.json"
    else:
        src = other / "s1_out" / "audit" / "pages" / "ca_000_page000.json"
        dst = mine / "s1_out" / "audit" / "pages" / "ca_000_page000.json"
        assert src.read_bytes() != dst.read_bytes()
    shutil.copyfile(src, dst)                                               # the TEST substitutes tmp files
    with pytest.raises(SystemExit, match=r"INVALID \(stage-replaced\)"):
        t.gate(mine, "cross-trial substitution", mailbox=mb[mine])


@pytest.mark.parametrize("case", ["multi-page", "empty-families"])
def test_valid_pagination_and_empty_families_are_not_anomalous(tmp_path, monkeypatch, case):   # row 319 (P-4)
    syms = ("A", "B") if case == "multi-page" else ()
    setup(tmp_path, syms)
    prov = Provider(pages_per_batch={"A,B": 3}) if case == "multi-page" else Provider()
    audit(tmp_path, monkeypatch, prov)
    assert kinds(tmp_path)[-1:] == [("STAGE-CREATED", "stage/audit")]
    assert all(k_ != "TRIAL-INVALID" for k_, _ in kinds(tmp_path))
    t.gate(tmp_path, "valid audit is usable")                              # no refusal, no INVALID


# ---------------------------------------------------------------- Task 7 carry-forward N1 (F3 "no row", F4 table)
@pytest.mark.parametrize("stray", ["claim", "report", "opening-seal"])
def test_stray_slot_files_before_the_audit_calendar_are_judged_invalid(tmp_path, monkeypatch, stray):
    """After the AUDIT-ACK and before any audit calendar exists, a claim/report of a slot with no slot row, or an
    opening-close seal file, is a violation (F3 'no row: any claim, capture, report or resolution'; F4 'no INTENT:
    any artifact is a violation after the AUDIT-ACK'): TRIAL-INVALID (registration-artifact), zero callbacks."""
    setup(tmp_path, ("A",))
    out = tmp_path / "s1_out"
    t.gate(tmp_path, "N1 control: no stray file")                          # control: nothing to judge, passes
    if stray == "opening-seal":
        p = out / "seals" / "2026-10-23.json"
    else:
        p = out / "captures" / "2026-10-23" / f"20261023T204500Z.{'attempt' if stray == 'claim' else 'report'}.json"
    p.parent.mkdir(parents=True)
    p.write_text("{}", encoding="utf-8")
    sp = Spies(monkeypatch)
    with pytest.raises(SystemExit, match=r"INVALID \(registration-artifact\)"):
        t.gate(tmp_path, "N1 stray file")
    sp.assert_zero()
    inv = [x for x in j.read_trial(*_tg(tmp_path)) if x.kind == "TRIAL-INVALID"]
    assert [x.subject for x in inv] == ["reason/registration-artifact"]
    with pytest.raises(SystemExit, match=r"trial INVALID"):              # persistent: the next command refuses
        t.gate(tmp_path, "N1 after")
