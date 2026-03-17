import subprocess
import os
import sys
import time
import ssl
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
PYTHON = os.path.join(ROOT, "runtime", "python", "python.exe")
NPM = os.path.join(ROOT, "runtime", "node", "npm.cmd")
SITE_PACKAGES = os.path.join(ROOT, "site-packages")
BACKEND_DIR = os.path.join(ROOT, "backend")
FRONTEND_DIR = os.path.join(ROOT, "frontend")
CERT = os.path.join(ROOT, "certs", "cert.pem")

PROTOCOL = "https" if os.path.exists(CERT) else "http"
BACKEND_STATUS_URL = f"{PROTOCOL}://localhost:8000/api/status"
FRONTEND_URL = f"{PROTOCOL}://localhost:5173"

# ── Shared env ────────────────────────────────────────────────────────────────

env = os.environ.copy()
env["PATH"] = os.path.join(ROOT, "runtime", "node") + os.pathsep + env.get("PATH", "")
env["PYTHONPATH"] = SITE_PACKAGES

# Allow Node.js to connect to the self-signed backend cert when proxying
env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"

# ── Helper: poll backend until ready ─────────────────────────────────────────

def wait_for_backend(timeout: int = 60) -> bool:
    """Poll /api/status until the backend responds or timeout expires."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(BACKEND_STATUS_URL, context=ctx, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False

# ── 1. Start backend ──────────────────────────────────────────────────────────

print(f"[INFO] Starting backend ({PROTOCOL})...")
subprocess.Popen(
    [PYTHON, "main.py"],
    cwd=BACKEND_DIR,
    creationflags=subprocess.CREATE_NEW_CONSOLE,
    env=env,
)

# ── 2. Wait until backend is actually serving ─────────────────────────────────

print("[INFO] Waiting for backend to be ready...")
if wait_for_backend(timeout=60):
    print("[INFO] Backend is ready.")
else:
    print("[WARN] Backend did not respond within 60 s — starting frontend anyway.")

# ── 3. Start frontend ─────────────────────────────────────────────────────────

print("[INFO] Starting frontend...")
subprocess.Popen(
    ["cmd", "/c", NPM, "run", "dev"],
    cwd=FRONTEND_DIR,
    creationflags=subprocess.CREATE_NEW_CONSOLE,
    env=env,
)

# ── 4. Wait for Vite to be ready, then open browser ──────────────────────────

print("[INFO] Waiting for Vite to be ready...")
time.sleep(4)  # Vite typically starts in 1-2 s; 4 s is safe

print(f"[INFO] Opening browser at {FRONTEND_URL}")
webbrowser.open(FRONTEND_URL)
