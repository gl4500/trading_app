# CI/CD Pipeline — AI Trading App

## Stack
- **Backend:** FastAPI + Python 3.12 + asyncio, port 8000
- **Frontend:** React + Vite + TypeScript + Tailwind CSS, port 5173
- **Tests:** Python `unittest` via `run_tests.py` (no pytest — self-contained runtime)
- **SAST:** Bandit (installed at `site-packages/bandit`)
- **VCS:** GitHub (`gl4500/trading_app`)
- **CI platform:** GitHub Actions

---

## Pipeline Overview

```
push / PR to any branch
        │
        ├── 1. Secret scan          ← Gitleaks full-history scan
        ├── 2. Backend tests        ← 160+ unittest tests (run_tests.py -v)
        ├── 3. Bandit SAST          ← medium+/medium+, excludes tests/
        ├── 4. Frontend type-check  ← tsc --noEmit
        ├── 5. Frontend build       ← vite build
        └── 6. Tag release          ← main branch only, date-stamp tag
```

Stages 2, 3, and 4 run in parallel after stage 1 passes.
Stage 5 runs after stage 4. Stage 6 runs only on `main` push after 2+3+5 all pass.

---

## Stage Details

### 1. Secret Scan
- **Tool:** `gitleaks/gitleaks-action@v2`
- **Scope:** Full git history (`fetch-depth: 0`) — catches keys committed then "deleted"
- **Blocks:** Everything downstream. A leaked key fails the pipeline immediately.

### 2. Backend Tests
- **Runner:** `python run_tests.py -v` from `backend/`
- **Python:** 3.12, installed via `actions/setup-python@v5`
- **Key packages installed in CI:** `fastapi uvicorn aiosqlite httpx pandas numpy pyarrow alpaca-py yfinance anthropic openai google-genai pyportfolioopt`
- **PyTorch:** NOT installed in CI. All torch-dependent tests are decorated `@unittest.skipUnless(HAS_TORCH, "torch not installed")` and auto-skip cleanly.
- **API calls:** None. All external services (Alpaca, Anthropic, yfinance, Ollama) are mocked in the test suite.
- **No `.env` secrets needed** in CI environment.

### 3. Bandit SAST
- **Severity/confidence threshold:** medium+ / medium+
- **Excludes:** `./tests/` directory
- **Output:** JSON report uploaded as artifact on every run (even clean)
- **Exit behavior:** `--exit-zero` + manual Python parse → real exit code based on findings count
- **Known-safe suppressions:** use `# nosec BXXX - reason` on the flagged line

### 4. Frontend Type-Check
- **Command:** `npx tsc --noEmit` from `frontend/`
- **Node:** 22 LTS
- **Purpose:** Catch TypeScript errors without running a full bundle build (fast)

### 5. Frontend Build
- **Command:** `npm run build` (Vite) from `frontend/`
- **Artifact:** `frontend/dist/` uploaded, retained 7 days
- **Note:** `NODE_TLS_REJECT_UNAUTHORIZED=0` set in CI — no `certs/` directory present in CI environment (self-signed certs are local-only)

### 6. Tag Release (main only)
- **Trigger:** push to `main` branch only
- **Format:** Date-stamped tag `YYYY.MM.DD.HHMM` (e.g. `2026.04.18.0700`)
- **Requires:** stages 2 (tests) + 3 (SAST) + 5 (build) all green

---

## Branch Protection Rules (recommended for GitHub)

Configure under **Settings → Branches → main**:

| Rule | Setting |
|---|---|
| Require status checks before merging | ✅ |
| Required checks | `Secret scan`, `Backend tests`, `Bandit SAST`, `Frontend build` |
| Require branches to be up to date | ✅ |
| Require pull request reviews | 1 approval |
| Restrict pushes to matching branches | ✅ (block direct pushes to main) |

---

## Workflow File Location

```
trading_app/
└── .github/
    └── workflows/
        └── ci.yml
```

---

## ci.yml

```yaml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:

  secret-scan:
    name: Secret scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Gitleaks
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  backend-tests:
    name: Backend tests
    runs-on: ubuntu-latest
    needs: secret-scan
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install backend dependencies
        run: |
          pip install --quiet \
            fastapi uvicorn aiosqlite httpx \
            pandas numpy pyarrow \
            alpaca-py yfinance \
            anthropic openai google-genai \
            pyportfolioopt
      - name: Run test suite
        working-directory: backend
        run: python run_tests.py -v

  sast:
    name: Bandit SAST
    runs-on: ubuntu-latest
    needs: secret-scan
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install Bandit
        run: pip install --quiet bandit
      - name: Run Bandit
        working-directory: backend
        run: |
          bandit -r . \
            -x ./tests/ \
            --severity-level medium \
            --confidence-level medium \
            --exit-zero \
            -f json -o bandit-report.json
          python -c "
          import json, sys
          r = json.load(open('bandit-report.json'))
          issues = r.get('results', [])
          if issues:
              for i in issues:
                  print(f\"[{i['issue_severity']}/{i['issue_confidence']}] {i['filename']}:{i['line_number']} — {i['issue_text']}\")
              sys.exit(1)
          print('Bandit: no findings')
          "
      - name: Upload Bandit report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: bandit-report
          path: backend/bandit-report.json

  frontend-typecheck:
    name: Frontend type-check
    runs-on: ubuntu-latest
    needs: secret-scan
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - name: Install frontend dependencies
        working-directory: frontend
        run: npm ci
      - name: TypeScript type-check
        working-directory: frontend
        run: npx tsc --noEmit

  frontend-build:
    name: Frontend build
    runs-on: ubuntu-latest
    needs: frontend-typecheck
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - name: Install frontend dependencies
        working-directory: frontend
        run: npm ci
      - name: Vite build
        working-directory: frontend
        run: npm run build
        env:
          NODE_TLS_REJECT_UNAUTHORIZED: "0"
      - name: Upload dist artifact
        uses: actions/upload-artifact@v4
        with:
          name: frontend-dist
          path: frontend/dist/
          retention-days: 7

  tag-release:
    name: Tag release
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    needs: [backend-tests, sast, frontend-build]
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Compute next version
        id: version
        run: echo "tag=$(date -u +'%Y.%m.%d.%H%M')" >> "$GITHUB_OUTPUT"
      - name: Create release tag
        uses: actions/github-script@v7
        with:
          script: |
            await github.rest.git.createRef({
              owner: context.repo.owner,
              repo:  context.repo.repo,
              ref:   `refs/tags/${{ steps.version.outputs.tag }}`,
              sha:   context.sha,
            });
            core.info(`Tagged ${{ steps.version.outputs.tag }}`);
```

---

## To Activate

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions CI pipeline"
git push
```

Then visit: `https://github.com/gl4500/trading_app/actions`

---

## Find-List-Fix Rule — Required Whenever Issues Are Found

Whenever bugs, test failures, stale assertions, or refactors are discovered during any task:

1. **Stop** — do not fix inline without listing first
2. **Write a numbered task list** of every issue found (all of them)
3. **Fix each item in order**, marking it complete as you go
4. **Commit after each fix** — do not batch unrelated fixes into one commit

No fix is made silently. Every issue gets listed before it gets fixed.

```
Example:
Found issues:
1. [ ] test_scanner_tokens assertion uses stale count (expected 25000, got 35000)
2. [ ] _hourly_call_limit hardcoded in __init__ — should be in config.py
3. [ ] CORRELATION_LIMIT not exposed as config env var

→ Fix 1 → commit. Fix 2 → commit. Fix 3 → commit.
```

---

## Standard Change Workflow — Required for Every Code Change

Follow these steps in order for every feature, fix, or refactor:

### 1. Write the failing test (TDD)
```bash
# Edit backend/tests/test_<module>.py — add failing tests first
cd backend
PYTHONPATH="C:/Users/gl450/trading_app/site-packages;C:/Users/gl450/trading_app/backend" \
  ../runtime/python/python.exe -m unittest tests.test_<module> -v
# Confirm: tests FAIL before implementation
```

### 2. Implement the change
Edit the source file(s) under `backend/` or `frontend/`.

### 3. Run tests — confirm green
```bash
PYTHONPATH="C:/Users/gl450/trading_app/site-packages;C:/Users/gl450/trading_app/backend" \
  ../runtime/python/python.exe -m unittest tests.test_<module> -v
# Confirm: all tests PASS
```

### 4. Update associated files

| What changed | Files to update |
|---|---|
| Architecture (new file, agent, endpoint, signal) | `memory/trading_app_architecture.md` |
| Bug found and fixed | `memory/trading_app_bugs_fixed.md` — append session entry |
| New rule or workflow | `CLAUDE.md` + matching `memory/*.md` file |
| New test module | `CLAUDE.md` → Current Test Coverage table |
| Agent threshold changed | `memory/trading_app_thresholds.md` |

```bash
# After updating files, verify CLAUDE.md and memory are in sync
```

### 5. Stage and commit
```bash
# Stage only the files you intentionally changed — never use git add -A
git add backend/<changed_file>.py \
        backend/tests/test_<module>.py \
        CLAUDE.md                        # if updated

git commit -m "feat|fix|test|docs|refactor: short description

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Commit message prefixes:
- `feat:` — new feature
- `fix:` — bug fix
- `test:` — tests only
- `docs:` — documentation / CLAUDE.md / memory
- `refactor:` — internal cleanup, no behavior change
- `security:` — SAST fixes, secret scanning

### 6. Push to main
```bash
git push origin main
```

The CI pipeline runs automatically on push. Monitor at:
`https://github.com/gl4500/trading_app/actions`

---

## Key Constraints to Communicate to Any Agent Working on This Repo

1. **Python runtime:** `C:\Users\gl450\trading_app\runtime\python\python.exe` — never use system Python or radioconda
2. **Test runner:** `python run_tests.py` from `backend/` — pytest is NOT installed in the self-contained runtime
3. **PYTHONPATH:** must include `C:\Users\gl450\trading_app\site-packages` when running tests directly
4. **No PyTorch in CI:** torch tests skip automatically via `HAS_TORCH` guard
5. **Scope:** only modify files inside `C:\Users\gl450\trading_app\` — never touch radioconda or other projects
6. **TDD required:** write failing test → implement → confirm green → commit (no exceptions)
7. **No `.env` in git:** pre-commit hook blocks it; secrets go in GitHub Actions secrets if needed
8. **Portfolio access:** `portfolio.positions[sym].shares` — there is NO `get_position()` method
