"""
AI Trading Competition — GUI Launcher
Dark-themed control panel for starting/stopping the backend and frontend.
Run with:  runtime/python/python.exe launcher_gui.pyw
"""
# ── Frozen-exe Tcl/Tk fix (must run before `import tkinter`) ─────────────────
# When PyInstaller bundles the app, tcl8.6 / tk8.6 dirs are extracted to
# sys._MEIPASS.  Without these env vars tkinter can't find its script files.
import sys as _sys, os as _os
if getattr(_sys, "frozen", False):
    _base = _sys._MEIPASS
    _os.environ.setdefault("TCL_LIBRARY", _os.path.join(_base, "tcl8.6"))
    _os.environ.setdefault("TK_LIBRARY",  _os.path.join(_base, "tk8.6"))
# ─────────────────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import font as tkfont
import subprocess
import threading
import os
import sys
import ssl
import time
import webbrowser
import urllib.request
import urllib.error
import queue

# ── Paths ─────────────────────────────────────────────────────────────────────
# When frozen by PyInstaller, __file__ is inside sys._MEIPASS (temp dir).
# sys.executable is always the real exe path, so use that when frozen.
if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON      = os.path.join(ROOT, "runtime", "python", "python.exe")
NPM         = os.path.join(ROOT, "runtime", "node", "npm.cmd")
SITE_PKG    = os.path.join(ROOT, "site-packages")
BACKEND_DIR = os.path.join(ROOT, "backend")
FRONTEND_DIR= os.path.join(ROOT, "frontend")
CERT        = os.path.join(ROOT, "certs", "cert.pem")
PROTOCOL    = "https" if os.path.exists(CERT) else "http"
BACKEND_URL = f"{PROTOCOL}://localhost:8000/api/auth/check"
FRONTEND_URL= f"{PROTOCOL}://localhost:5173"

# ── Colours ───────────────────────────────────────────────────────────────────

C_BG      = "#0f1117"   # window background
C_PANEL   = "#1a1d27"   # card background
C_BORDER  = "#2d3148"   # card border
C_TEXT    = "#e2e8f0"   # primary text
C_MUTED   = "#64748b"   # secondary text
C_GREEN   = "#4ade80"   # running / success
C_RED     = "#f87171"   # stopped / error
C_YELLOW  = "#fbbf24"   # starting
C_BLUE    = "#60a5fa"   # button accent
C_BTN_BG  = "#1e2235"   # button background
C_BTN_HOV = "#2d3557"   # button hover
C_LOG_BG  = "#0a0c12"   # log background
C_LOG_TXT = "#94a3b8"   # log text


# ── Shared env ────────────────────────────────────────────────────────────────

_env = os.environ.copy()
_env["PATH"] = os.path.join(ROOT, "runtime", "node") + os.pathsep + _env.get("PATH", "")
_env["PYTHONPATH"] = SITE_PKG
_env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"


# ── Kill port helper ──────────────────────────────────────────────────────────

def _kill_port(port: int) -> None:
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid.isdigit() and int(pid) != os.getpid():
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True)
    except Exception:
        pass


# ── Backend health check ──────────────────────────────────────────────────────

def _backend_is_up() -> bool:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        urllib.request.urlopen(BACKEND_URL, context=ctx, timeout=2)
        return True
    except urllib.error.HTTPError as e:
        return e.code in (401, 403)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Main App
# ══════════════════════════════════════════════════════════════════════════════

class LauncherApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AI Trading Competition — Launcher")
        self.root.configure(bg=C_BG)
        self.root.resizable(False, False)

        # Process handles
        self._backend_proc  = None
        self._frontend_proc = None

        # Log queue — subprocess threads push lines here; UI polls it
        self._log_q: queue.Queue = queue.Queue()

        # State flags
        self._backend_status  = "stopped"   # stopped | starting | running
        self._frontend_status = "stopped"

        self._build_ui()
        self._center_window(520, 600)
        self._poll_log()
        self._poll_status()

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        pad = dict(padx=16, pady=8)

        # ── Header ──
        hdr = tk.Frame(self.root, bg="#141828", pady=14)
        hdr.pack(fill=tk.X)

        tk.Label(hdr, text="🤖  AI Trading Competition",
                 bg="#141828", fg=C_TEXT,
                 font=("Segoe UI", 14, "bold")).pack()
        tk.Label(hdr, text="Control Panel",
                 bg="#141828", fg=C_MUTED,
                 font=("Segoe UI", 9)).pack()

        # ── Status Cards ──
        cards = tk.Frame(self.root, bg=C_BG)
        cards.pack(fill=tk.X, padx=16, pady=(12, 0))

        self._backend_card  = self._status_card(cards, "Backend",  "Port 8000", 0)
        self._frontend_card = self._status_card(cards, "Frontend", "Port 5173", 1)
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

        # ── Control Buttons ──
        btns = tk.Frame(self.root, bg=C_BG)
        btns.pack(fill=tk.X, padx=16, pady=10)

        self._btn_start = self._button(btns, "▶  Start All",   self._start_all,  C_GREEN)
        self._btn_stop  = self._button(btns, "⏹  Stop All",    self._stop_all,   C_RED)
        self._btn_open  = self._button(btns, "🌐  Open Dashboard", self._open_browser, C_BLUE)

        self._btn_start.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        self._btn_stop .pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        self._btn_open .pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ── URL bar ──
        url_frame = tk.Frame(self.root, bg=C_PANEL, bd=0,
                             highlightthickness=1,
                             highlightbackground=C_BORDER)
        url_frame.pack(fill=tk.X, padx=16, pady=(0, 8))

        tk.Label(url_frame, text="  URL  ", bg=C_PANEL,
                 fg=C_MUTED, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        tk.Label(url_frame, text=FRONTEND_URL, bg=C_PANEL,
                 fg=C_BLUE, font=("Consolas", 9),
                 cursor="hand2").pack(side=tk.LEFT, pady=6)

        # ── Log window ──
        log_frame = tk.Frame(self.root, bg=C_BG)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        tk.Label(log_frame, text="Backend Log",
                 bg=C_BG, fg=C_MUTED,
                 font=("Segoe UI", 8)).pack(anchor=tk.W)

        self._log = tk.Text(
            log_frame,
            bg=C_LOG_BG, fg=C_LOG_TXT,
            font=("Consolas", 8),
            bd=0, relief=tk.FLAT,
            wrap=tk.WORD,
            state=tk.DISABLED,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            height=14,
        )
        self._log.pack(fill=tk.BOTH, expand=True)

        scroll = tk.Scrollbar(self._log, command=self._log.yview,
                              bg=C_PANEL, troughcolor=C_BG,
                              activebackground=C_BORDER)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._log.configure(yscrollcommand=scroll.set)

        # colour tags for log
        self._log.tag_config("INFO",    foreground="#60a5fa")
        self._log.tag_config("WARNING", foreground="#fbbf24")
        self._log.tag_config("ERROR",   foreground="#f87171")
        self._log.tag_config("plain",   foreground=C_LOG_TXT)

        # ── Footer ──
        footer = tk.Frame(self.root, bg=C_BG)
        footer.pack(fill=tk.X, padx=16, pady=(0, 10))
        self._status_label = tk.Label(
            footer, text="Ready", bg=C_BG,
            fg=C_MUTED, font=("Segoe UI", 8), anchor=tk.W
        )
        self._status_label.pack(side=tk.LEFT)

    def _status_card(self, parent, title, subtitle, col):
        """Return a dict of widgets for one status card."""
        frame = tk.Frame(parent, bg=C_PANEL,
                         highlightthickness=1,
                         highlightbackground=C_BORDER)
        frame.grid(row=0, column=col,
                   padx=(0, 8) if col == 0 else (0, 0),
                   sticky=tk.EW, ipady=8, ipadx=10)

        top = tk.Frame(frame, bg=C_PANEL)
        top.pack(fill=tk.X, padx=10, pady=(8, 2))

        dot = tk.Label(top, text="●", bg=C_PANEL,
                       fg=C_RED, font=("Segoe UI", 11))
        dot.pack(side=tk.LEFT)

        tk.Label(top, text=f"  {title}", bg=C_PANEL,
                 fg=C_TEXT, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)

        lbl = tk.Label(frame, text="Stopped",
                       bg=C_PANEL, fg=C_RED,
                       font=("Segoe UI", 8))
        lbl.pack(anchor=tk.W, padx=10)

        tk.Label(frame, text=subtitle, bg=C_PANEL,
                 fg=C_MUTED, font=("Segoe UI", 7)).pack(anchor=tk.W, padx=10, pady=(0, 6))

        return {"dot": dot, "label": lbl}

    def _button(self, parent, text, cmd, color):
        btn = tk.Label(
            parent, text=text,
            bg=C_BTN_BG, fg=color,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2", padx=8, pady=7,
            relief=tk.FLAT,
        )
        btn.bind("<Button-1>",  lambda e: cmd())
        btn.bind("<Enter>",     lambda e: btn.configure(bg=C_BTN_HOV))
        btn.bind("<Leave>",     lambda e: btn.configure(bg=C_BTN_BG))
        return btn

    def _center_window(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ── Status Updates ────────────────────────────────────────────────────────

    def _set_card(self, card: dict, status: str):
        if status == "running":
            card["dot"]  .configure(fg=C_GREEN)
            card["label"].configure(text="Running", fg=C_GREEN)
        elif status == "starting":
            card["dot"]  .configure(fg=C_YELLOW)
            card["label"].configure(text="Starting…", fg=C_YELLOW)
        else:
            card["dot"]  .configure(fg=C_RED)
            card["label"].configure(text="Stopped", fg=C_RED)

    def _set_status(self, msg: str):
        self._status_label.configure(text=msg)

    # ── Log ───────────────────────────────────────────────────────────────────

    def _append_log(self, line: str):
        self._log.configure(state=tk.NORMAL)
        tag = "plain"
        if "[INFO]" in line or "INFO:" in line:
            tag = "INFO"
        elif "[WARNING]" in line or "WARNING:" in line:
            tag = "WARNING"
        elif "[ERROR]" in line or "ERROR:" in line:
            tag = "ERROR"
        self._log.insert(tk.END, line + "\n", tag)
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def _poll_log(self):
        try:
            while True:
                line = self._log_q.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def _stream_output(self, proc):
        """Read subprocess stdout line-by-line and push to log queue."""
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    self._log_q.put(line)
        except Exception:
            pass

    # ── Poll process status every 2 s ─────────────────────────────────────────

    def _poll_status(self):
        # Backend
        if self._backend_proc is not None:
            ret = self._backend_proc.poll()
            if ret is not None:
                # Process exited
                self._backend_status = "stopped"
                self._backend_proc = None
                self._log_q.put("[WARNING] Backend process exited unexpectedly.")
        if self._backend_status == "running":
            self._set_card(self._backend_card, "running")
        elif self._backend_status == "starting":
            self._set_card(self._backend_card, "starting")
        else:
            self._set_card(self._backend_card, "stopped")

        # Frontend
        if self._frontend_proc is not None:
            ret = self._frontend_proc.poll()
            if ret is not None:
                self._frontend_status = "stopped"
                self._frontend_proc = None
                self._log_q.put("[WARNING] Frontend process exited unexpectedly.")
        if self._frontend_status == "running":
            self._set_card(self._frontend_card, "running")
        elif self._frontend_status == "starting":
            self._set_card(self._frontend_card, "starting")
        else:
            self._set_card(self._frontend_card, "stopped")

        self.root.after(2000, self._poll_status)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _start_all(self):
        if self._backend_status != "stopped" or self._frontend_status != "stopped":
            self._set_status("Already running — stop first.")
            return
        threading.Thread(target=self._start_sequence, daemon=True).start()

    def _start_sequence(self):
        # 1. Start backend
        self._backend_status = "starting"
        self._set_status("Starting backend…")
        self._log_q.put("[INFO] Starting backend...")

        _kill_port(8000)
        time.sleep(0.3)

        try:
            proc = subprocess.Popen(
                [PYTHON, "main.py"],
                cwd=BACKEND_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=_env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._backend_proc = proc
            threading.Thread(target=self._stream_output,
                             args=(proc,), daemon=True).start()
        except Exception as e:
            self._log_q.put(f"[ERROR] Failed to start backend: {e}")
            self._backend_status = "stopped"
            return

        # 2. Wait for backend to be ready
        self._log_q.put("[INFO] Waiting for backend to respond...")
        deadline = time.time() + 60
        while time.time() < deadline:
            if _backend_is_up():
                break
            if self._backend_proc and self._backend_proc.poll() is not None:
                self._log_q.put("[ERROR] Backend exited during startup.")
                self._backend_status = "stopped"
                return
            time.sleep(0.5)
        else:
            self._log_q.put("[WARNING] Backend slow to start — continuing anyway.")

        self._backend_status = "running"
        self._log_q.put("[INFO] Backend is ready.")

        # 3. Start frontend
        self._frontend_status = "starting"
        self._set_status("Starting frontend…")
        self._log_q.put("[INFO] Starting frontend...")

        _kill_port(5173)
        time.sleep(0.5)

        try:
            self._frontend_proc = subprocess.Popen(
                ["cmd", "/c", NPM, "run", "dev"],
                cwd=FRONTEND_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            self._log_q.put(f"[ERROR] Failed to start frontend: {e}")
            self._frontend_status = "stopped"
            return

        # 4. Wait for Vite (fixed 4 s)
        time.sleep(4)
        if self._frontend_proc.poll() is None:
            self._frontend_status = "running"
            self._log_q.put(f"[INFO] Frontend ready at {FRONTEND_URL}")
            self.root.after(0, lambda: self._set_status("All systems running"))
            webbrowser.open(FRONTEND_URL)
        else:
            self._frontend_status = "stopped"
            self._log_q.put("[ERROR] Frontend failed to start.")

    def _stop_all(self):
        threading.Thread(target=self._stop_sequence, daemon=True).start()

    def _stop_sequence(self):
        self._set_status("Stopping…")
        self._log_q.put("[INFO] Stopping all processes...")

        for proc, name in [(self._frontend_proc, "frontend"),
                           (self._backend_proc,  "backend")]:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                    self._log_q.put(f"[INFO] {name.capitalize()} stopped.")
                except Exception:
                    proc.kill()

        self._backend_proc    = None
        self._frontend_proc   = None
        self._backend_status  = "stopped"
        self._frontend_status = "stopped"
        self.root.after(0, lambda: self._set_status("Stopped"))

    def _open_browser(self):
        webbrowser.open(FRONTEND_URL)

    def on_close(self):
        self._stop_sequence()
        self.root.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = LauncherApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
