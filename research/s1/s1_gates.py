"""S1 shared gate verification (Task 12, controller-added; Addendum 1 A6, A7.4, A8). One implementation of the
checks that several commands repeat before any live capture, request, reservation or priced work:
- a collector attempt: COMPLETE manifest, every derived file AND every raw page re-verified against its hash (A7.4);
- the audit: plan binding (A8.1 plan_sha256), bundle, the AUDIT-ACK's identity/token/causal timing (A8.2) and the
  pinned provider calendar (A6, s1_seal.calendar_pin_problems);
- the RUN-ACK registration: identity, exact token rebuilt from the current artifacts, causal timing and the prereg
  bindings (A8.2).
Reads files and the read-only coordination mailbox only; no live state, prices or economics."""
import sqlite3
from pathlib import Path

import s1_common as c
import s1_receipt as rc
import s1_seal as z

AUDIT_FILES = ("calendar.json", "calendar_source.json", "corporate_actions.json", "ca_problems.json")


class Invalid(Exception):
    """A protocol/integrity failure: a refusal at a gate, ABORTED-INVALID at the score."""


def attempt(d: Path, names, out: Path) -> tuple:
    """A COMPLETE collector attempt whose named derived files AND every raw page listed under `pages` (paths
    relative to s1_out) match the manifest's hashes -> (manifest, {name: content}). A7.4."""
    d, out = Path(d), Path(out)
    mp = d / "manifest.json"
    if not mp.exists():
        raise Invalid(f"{d.name}: no manifest")
    try:
        m = c.load_json(mp)
    except (OSError, ValueError) as e:
        raise Invalid(f"{d.name}: manifest unreadable ({type(e).__name__})") from None
    if not isinstance(m, dict) or m.get("outcome") != "COMPLETE":
        raise Invalid(f"{d.name} attempt outcome is {m.get('outcome') if isinstance(m, dict) else None!r}, "
                      f"not COMPLETE")
    files, got = m.get("files") or {}, {}
    for n in names:
        p = d / n
        if n not in files or not p.is_file() or c.sha256_file(p) != files[n]:
            raise Invalid(f"{d.name}/{n} missing or differs from its manifest hash")
        got[n] = c.load_json(p)
    for rel, h in sorted((m.get("pages") or {}).items()):
        p = out / rel
        if not p.is_file() or c.sha256_file(p) != h:
            raise Invalid(f"{d.name}: raw page {rel} missing or differs from its manifest hash")
    return m, got


def verify_audit_ack(out: Path, m: dict, plan: dict, mailbox=None) -> dict:
    """A8.2: the audit's S1-AUDIT-ACK = a codex->claude experiments-prereg message carrying the audit token rebuilt
    from the CURRENT plan, collector and bundle; created after the plan and before the audit reservation, and
    recorded as such in the manifest."""
    a = m.get("ack") if isinstance(m.get("ack"), dict) else {}
    if not a.get("ack_id"):
        raise Invalid("audit manifest records no AUDIT-ACK")
    try:
        msg = c.mailbox_message(a["ack_id"], mailbox)
    except sqlite3.Error as e:
        raise Invalid(f"mailbox unreadable ({type(e).__name__})") from None
    except SystemExit as e:
        raise Invalid(str(e)) from None
    if c.audit_token(out) not in msg["lines"]:
        raise Invalid("the AUDIT-ACK does not carry the audit token of the current plan/collector/bundle")
    t = c.aware(msg["created_utc"])
    if a.get("created_utc") is None or c.aware(a["created_utc"]) != t:
        raise Invalid("the audit manifest's ACK time differs from the mailbox")
    if not t > c.aware(plan["created_utc"]):
        raise Invalid("the AUDIT-ACK is not after the plan it binds")
    reserved = c.aware(c.load_json(Path(out) / "audit" / "attempt.json")["reserved_utc"])
    if not t < reserved:
        raise Invalid("the AUDIT-ACK is not before the audit reservation")
    return {"ack_id": a["ack_id"], "created_utc": msg["created_utc"]}


def verified_audit(out: Path, mailbox=None) -> dict:
    """The audit every later stage builds on: COMPLETE with derived files and raw pages verified (A7.4), bound to
    the current plan (A8.1) and bundle (A3.1), under a verified AUDIT-ACK (A8.2), with a pinned provider calendar
    that passes the A6 completeness checks. Raises Invalid. Returns {manifest, files, calendar, plan, ack}."""
    out = Path(out)
    try:
        plan = c.load_json(out / "plan.json")
    except (OSError, ValueError) as e:
        raise Invalid(f"plan.json unreadable ({type(e).__name__})") from None
    m, files = attempt(out / "audit", AUDIT_FILES, out)
    if m.get("plan_sha256") != c.sha256_file(out / "plan.json"):
        raise Invalid("audit is not bound to the current plan (plan_sha256 differs): no reuse after a plan change")
    if m.get("bundle_sha256") != c.bundle_sha256():
        raise Invalid("audit manifest bundle differs from the S1 bundle")
    ack = verify_audit_ack(out, m, plan, mailbox)
    probs = z.calendar_pin_problems(out, m, files, plan) + z.calendar_problems(files["calendar.json"], plan)
    if probs:
        raise Invalid(f"pinned calendar refused: {probs}")
    return {"manifest": m, "files": files, "calendar": z.calendar_rows(files["calendar.json"]), "plan": plan,
            "ack": ack}


def run_ack_problems(out: Path, pr: dict, mailbox=None) -> list:
    """A8.2: problems of the RUN-ACK registration (empty = verified): the codex message carries the RUN token
    rebuilt from the current artifacts; it was created after the START attestation, before planned START and no
    later than prereg; prereg's bindings equal the current files and bundle."""
    out = Path(out)
    probs = []
    try:
        a = pr["ack"]
        msg = c.mailbox_message(a["ack_id"], mailbox)
        if c.run_token(out) not in msg["lines"]:
            probs.append("the RUN-ACK does not carry the RUN token of the current artifacts")
        t = c.aware(msg["created_utc"])
        if c.aware(a["created_utc"]) != t:
            probs.append("prereg's RUN-ACK time differs from the mailbox")
        att = c.load_json(out / "attest_start.json")
        if not t > c.aware(att["recorded_utc"]):
            probs.append("the RUN-ACK is not after the START attestation")
        if not t < c.aware(pr["start"]):
            probs.append("the RUN-ACK is not before planned START")
        if not t <= c.aware(pr["recorded_utc"]):
            probs.append("prereg was recorded before its RUN-ACK")
        plan = c.load_json(out / "plan.json")
        want = {"plan_sha256": c.sha256_file(out / "plan.json"),
                "audit_manifest_sha256": c.sha256_file(out / "audit" / "manifest.json"),
                "attest_start_sha256": c.sha256_file(out / "attest_start.json"),
                "opening_seal_sha256": c.sha_or_absent(c.opening_seal_path(out, plan)),
                "opening_books_sha256": c.sha_or_absent(out / "opening_books.json"),
                "bundle_sha256": c.bundle_sha256(), "runner_sha256": c.sha256_file(c.HERE / "s1_run.py"),
                "start": plan["planned_start"]}
        probs += [f"prereg {k_} does not match" for k_, v in want.items() if pr.get(k_) != v]
        m = c.load_json(out / "audit" / "manifest.json")                    # bound by the RUN token's hash
        calp = out / "audit" / "calendar.json"
        if (m.get("files") or {}).get("calendar.json") != c.sha256_file(calp) or \
                pr.get("calendar") != z.calendar_rows(c.load_json(calp)):
            probs.append("prereg calendar is not the audit's pinned calendar")
        if c.receipt_sha256(pr.get("receipt")) != att.get("receipt_sha256"):
            probs.append("prereg receipt is not the attested opening receipt")
        seal = c.load_json(c.opening_seal_path(out, plan))                   # fix round 2 (B2.1): the reference
        pb = seal.get("process_binding") if isinstance(seal, dict) else None
        ref = pr.get("process_binding")
        if rc.binding_problem(ref) or pb != {"status": "REFERENCE", "binding": ref}:
            probs.append("prereg process binding is not the opening seal's registered reference")
        elif att.get("process_binding_sha256") != c.sha256_bytes(c.canonical(ref)):
            probs.append("the START attestation does not bind prereg's process binding")
    except SystemExit as e:
        probs.append(f"RUN-ACK unverifiable: {e}")
    except sqlite3.Error as e:
        probs.append(f"RUN-ACK unverifiable: mailbox unreadable ({type(e).__name__})")
    except (OSError, ValueError, KeyError, TypeError) as e:
        probs.append(f"RUN-ACK unverifiable: {type(e).__name__}")
    return probs


def verified_registration(out: Path, where: str, mailbox=None, now=None, *, gate_refuses=True) -> dict:
    """A3.2 then A8.2 for every post-prereg command: the bundle FIRST (against the RUN-ACK's), then the full RUN-ACK
    verification; any failure refuses (SystemExit) before protocol state is used. Returns prereg."""
    c.verify_bundle_first(out, where, mailbox=mailbox, now=now, need="prereg", gate_refuses=gate_refuses)
    pr = c.load_json(Path(out) / "prereg.json")
    probs = run_ack_problems(out, pr, mailbox)
    if probs:
        c.record_refusal(out, where, f"registration not verified: {probs}", now)       # fix round 2 (B3.2)
        raise SystemExit(f"{where} refused: registration not verified: {probs}")
    return pr
