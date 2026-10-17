# Security Architecture

This document describes the security controls in place for the AI Trading App,
covering the pre-commit gate, static analysis, runtime hardening, and test coverage.

## Temporary Transformers exception: SNYK-PYTHON-TRANSFORMERS-19500670

**Requirement:** REQ-TRANSFORMERS-19500670. Recorded 2026-10-17. Implementer:
Codex; reviewer: Claude. Follow-up owners: **Claude/Codex**, review due
**2026-11-09**. The exception expires **2026-11-16 at 00:00 UTC**; renewal
requires a new advisory/reachability assessment and peer review.

This is a time-limited risk acceptance, **not a dependency upgrade or a fix to
Transformers**. There is no dependency, pin, runtime or application-behavior
change. The live runtime's **5.6.2 is affected and remains installed**. This
policy/document change requires **no package installation or backend restart**.

### Advisory evidence and decision

- [Snyk advisory](https://security.snyk.io/vuln/SNYK-PYTHON-TRANSFORMERS-19500670),
  checked 2026-10-17: affected versions **>=4.49.0**, with **no fixed version**
  reported. Thus both live 5.6.2 and the reported CI resolution 5.20.1 are in
  Snyk's affected range.
- [CERT/CC VU#456290](https://kb.cert.org/vuls/id/456290), revised 2026-09-22:
  discusses versions 4.49.0 through 5.8.1 and reports no vendor patch. That
  narrower documented range does not establish that later versions are fixed;
  the Snyk range governs this Snyk exception.
- The vulnerable custom-generation loader caches remote Python before checking
  consent. Declining remote-code trust is therefore not, by itself, a remedy
  for the unauthorized file write. Cached code execution still requires an
  execution path; this exception does not assert that the library is safe for
  arbitrary repositories or other applications sharing its cache.

The sole production Transformers import is
`backend/data/finbert_scorer.py`. Its pipeline is `text-classification`, with
the constant model name `ProsusAI/finbert`, CPU inference and no caller-supplied
repository. `backend/data/signal_aggregator.py` uses its headline scores and
falls back to keyword scoring when unavailable. The reviewed application does
not invoke `load_custom_generate` or request a custom-generation repository.
This is the bounded basis for accepting this advisory temporarily, not proof
against every transitive or future library path.

FinBERT loads **third-party pretrained weights**; it is not one of the app's
locally trained XGB/W3 models. Older Transformers exceptions in `backend/.snyk`
contain a broader locally-trained-model rationale. Their correction and
individual reassessment are a **Claude/Codex follow-up**, not silently covered
by this new exception. Their existing entries and expiry dates are unchanged.

Downgrading below 4.49.0 would avoid this advisory's listed range but is not a
validated compatible or generally secure upgrade. Removing Transformers would
change live headline signals to their fallback. Neither is part of this
behavior-preserving policy change. Reassess the decision when a supported
fixed version becomes available, when the model/repository/task changes, or
when evidence changes about reachability. Review cached-module hygiene with
the operator if needed; this change does not inspect or clear the live cache.

### Scope and acceptance examples

CI invokes `snyk test` from `backend/`, which reads `backend/.snyk`. Only the
new advisory ID receives an exception. The existing high-severity threshold,
other advisory entries/expiries, Bandit gate and frontend scan remain intact.
`backend/requirements.txt` and the offline wheel cache `backend/packages/`
are unchanged; no replacement wheels are needed for this policy change.

- Given the current backend dependency graph, when Snyk scans it before expiry,
  this advisory is accepted under the documented policy; other unaccepted high
  findings still fail the scan.
- Given the expiry has passed, when Snyk evaluates this policy, this exception
  no longer suppresses the finding. A green scan now is not a permanent waiver.
- Given the policy before this change, when comparing it with this change,
  exactly one advisory is added and every prior entry and expiry is identical.
- Given the existing scoring and mocked HTTP workflows, when the targeted
  FinBERT, signal-aggregator and backend security tests run in isolation,
  their behavior remains unchanged. Passing tests do not prove the upstream
  vulnerability fixed or make all model-loading paths safe.

Validation records accompany the PR: policy/YAML consistency, targeted test
output, CI-equivalent Bandit output, environment/source hashes and the PR's
own Snyk outcome. No new Python behavior is introduced, so behavioral
RED/GREEN, Hypothesis and Cosmic Ray are not applicable to this policy/document
edit. No source code, live database, runtime packages or live configuration
is modified during validation; model inference and external services are mocked.

---

## Pre-commit Security Gate

Every `git commit` runs `.git/hooks/pre-commit` (4 steps, automatic):

```
Step 1  Block staged .env files
         → git diff --cached detects .env before it reaches GitHub

Step 2  Secret pattern scan (staged files only)
         → Rejects Anthropic (sk-ant-*), OpenAI (sk-*), Google (AIzaSy*),
           AWS (AKIA*), Alpaca key patterns in .py/.ts/.js/.json/.yaml files

Step 3  Bandit SAST — medium+/medium+ severity, excludes tests/
         → Scans backend/ Python source for injection, XXE, bind-all,
           hardcoded passwords, insecure deserialization, and more
```

Total pre-commit time: < 10 seconds.

**Security test suite — run on-demand before every merge to main:**
```bat
run_security_tests.bat
```
`test_security.py` (25 tests) is intentionally excluded from the per-commit hook
because it loads PyTorch + the full FastAPI app (~1.2 GB, ~2-3 min startup time).

To bypass pre-commit in a genuine emergency only:
```bash
git commit --no-verify -m "emergency: ..."
```
Never use `--no-verify` for routine commits.

---

## SAST — Bandit

**Version:** 1.9.4 (installed in `site-packages/`)

**Findings resolved:**

| Rule | Description | Resolution |
|---|---|---|
| B104 | Bind to all interfaces (`0.0.0.0`) | Changed `config.py` HOST default to `127.0.0.1` |
| B314 | Unsafe XML parsing (XXE risk) | Replaced `xml.etree.ElementTree.fromstring` with `defusedxml` in `sentinel_sources.py` |
| B608 | SQL injection via f-string | Added `# nosec B608` on two lines in `database.py` where `where_clause` and `set_clause` are built from whitelisted literals, never user input |

**Suppressing a known-safe finding:**
```python
# nosec comment must be on the FLAGGED LINE (the f-string or call site, not the line above)
result = f"SELECT * FROM t {where_clause} LIMIT ?"  # nosec B608 - where_clause from literals only
```

**Run manually:**
```bash
cd backend
PYTHONPATH=../site-packages ../runtime/python/python.exe -m bandit \
    -r . -x ./tests/ --severity-level medium --confidence-level medium
```

---

## XXE Protection — defusedxml

`data/sentinel_sources.py` parses RSS/XML feeds from external sources (SEC EDGAR, CNBC).
All XML parsing uses `defusedxml.ElementTree.fromstring` to prevent:
- XML External Entity (XXE) injection
- Billion laughs / entity expansion DoS

**Version:** defusedxml 0.7.1 (installed in `site-packages/`)

Fallback path (if defusedxml is somehow missing):
```python
from xml.etree.ElementTree import fromstring as _xml_fromstring  # nosec B314
```

---

## Authentication

Session-based authentication is enforced when `APP_PASSWORD` and `SESSION_SECRET` are set in `.env`.

| Control | Detail |
|---|---|
| Password hashing | PBKDF2-HMAC-SHA256, 200,000 iterations, session secret as salt |
| Session cookies | httpOnly, SameSite=Lax; `Secure` flag set automatically when HTTPS certs are present |
| Session TTL | 24 hours; server-side revocation on logout |
| Rate limiting | 5 login attempts per IP per 5 minutes; HTTP 429 with `Retry-After` on breach |
| Timing attack prevention | `hmac.compare_digest` for constant-time password comparison |
| WebSocket auth | Session cookie validated before `accept()` — unauthenticated connections receive HTTP 403 |
| Exempt endpoints | `/api/login`, `/api/logout`, `/api/auth/check`, `/docs`, `/openapi.json`, `/redoc` |

To enable: add `APP_PASSWORD` and `SESSION_SECRET` to `.env`. Leave either blank to run without authentication (development/local use only).

Generate a session secret:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## Runtime Security Hardening

### API Server binding
- Default host: `127.0.0.1` (localhost only)
- To expose on LAN: set `HOST=0.0.0.0` in `.env` explicitly — never as a default

### HTTP Security Headers (applied by middleware in `main.py`)
| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Content-Security-Policy` | Applied on API routes; excluded from `/docs`, `/openapi.json` |

### CORS
- Only explicitly allowed origins are accepted
- Credentials (`withCredentials`) are not permitted
- Disallowed origins are not echoed in responses

### Error responses
- No tracebacks in API responses (never expose internal paths or stack frames)
- No API key patterns in status endpoints
- Generic 404 messages for unknown agent names

### SQL injection prevention
- All user-controlled values passed as parameterised query parameters
- `where_clause` and `set_clause` in `database.py` built from whitelisted field names only (never raw user input)
- Unknown filter field names are rejected with HTTP 400 before reaching the database

### Rate limiting
- In-memory rate limiter on API endpoints
- HTTP 429 returned when limit exceeded

---

## Secret Management

### Never committed
- `.env` is in `.gitignore` — contains all API keys (Alpaca, Anthropic, OpenAI, Gemini, Finnhub)
- Pre-commit hook blocks `.env` from being staged
- Pre-commit hook scans for real key patterns in all staged source files

### In code
- All keys loaded via `os.getenv()` in `config.py` — never hardcoded
- Placeholder strings (`"your-key-here"`, `""`) are used as defaults

---

## Dependency Security

### Recommended: monthly pip-audit scan
```bash
cd backend
PYTHONPATH=../site-packages ../runtime/python/python.exe -m pip_audit \
    --requirement requirements.txt
```
Install: `pip install pip-audit` into `site-packages/`

---

## DAST — OWASP ZAP (recommended pre-release)

For pre-release validation, run OWASP ZAP against the running backend:

1. Start backend: `start_backend.bat`
2. Run ZAP baseline scan:
   ```bash
   docker run --network host -t owasp/zap2docker-stable zap-baseline.py \
       -t http://127.0.0.1:8000 -r zap_report.html
   ```
3. Review `zap_report.html` for medium/high findings before merging to main

This is not automated in CI yet — run manually before significant releases.

---

## Security Test Coverage

`backend/tests/test_security.py` — 25 tests, runs in the pre-commit hook.

| Class | Coverage |
|---|---|
| `TestSecurityHeaders` | All 5 security headers, CSP scoping, 404 response headers |
| `TestCORSEnforcement` | Allowed/disallowed origins, credentials, methods |
| `TestErrorSanitization` | No traceback/path/key leaks in error responses |
| `TestSQLHardening` | Field whitelist, parameterisation, no raw SQL in signatures |
| `TestRateLimiting` | 429 enforcement, normal request pass-through |
| `TestSecretPatterns` | No hardcoded secrets in source, .env in .gitignore |
