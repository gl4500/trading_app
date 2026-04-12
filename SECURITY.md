# Security Architecture

This document describes the security controls in place for the AI Trading App,
covering the pre-commit gate, static analysis, runtime hardening, and test coverage.

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
