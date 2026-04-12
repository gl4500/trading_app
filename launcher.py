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
BACKEND_STATUS_URL = f"{PROTOCOL}://localhost:8000/api/auth/check"
FRONTEND_URL = f"{PROTOCOL}://localhost:5173"

# ── Shared env ────────────────────────────────────────────────────────────────

env = os.environ.copy()
env["PATH"] = os.path.join(ROOT, "runtime", "node") + os.pathsep + env.get("PATH", "")
env["PYTHONPATH"] = SITE_PACKAGES

# Allow Node.js to connect to the self-signed backend cert when proxying
env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"

# ── Helper: poll backend until ready ─────────────────────────────────────────

def wait_for_backend(timeout: int = 60) -> bool:
    """Poll /api/auth/check until the backend responds or timeout expires.
    Uses auth/check (always public) so a 200 or 401 both count as 'backend is up'."""
    import urllib.error
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(BACKEND_STATUS_URL, context=ctx, timeout=2)
            return True   # 200 — auth disabled
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return True   # backend is up, auth is just enabled
        except Exception:
            pass
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

# ── 3. Free port 5173 then start frontend ────────────────────────────────────

import socket as _socket

def _kill_port(port: int) -> None:
    """Kill any process listening on the given port."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid.isdigit() and int(pid) != os.getpid():
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True)
                    print(f"[INFO] Freed port {port} (killed PID {pid})")
    except Exception:
        pass

_kill_port(5173)
time.sleep(0.5)

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
