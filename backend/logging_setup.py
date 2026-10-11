"""Logging and crash-log setup.

Extracted from main.py for issue #67. This module sets up:
  - The crash log (raw file that survives logging failures)
  - A sys.excepthook that records unhandled exceptions
  - Suppression of noisy Windows asyncio messages
  - RotatingFileHandlers for error.log + errors_only.log
  - A helper to parse the structured error log back into JSON

main.py imports the public names from here so existing tests doing
`from main import _write_crash`, `patch("main._ERROR_LOG_PATH", ...)`, etc.
continue to work.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)


# ─── Crash Log ──────────────────────────────────────────────────────────────
# Written with open() so it works even if the RotatingFileHandler hasn't
# been initialised yet, and appears in the repo regardless of the launcher.

# Anchor the log dir to backend/ via the module file location (works
# regardless of where the backend was launched from).
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_CRASH_LOG_PATH = os.path.join(_BACKEND_DIR, "logs", "crash.log")


def _write_crash(msg: str) -> None:
    """Append msg to crash.log with a UTC timestamp. Never raises."""
    try:
        os.makedirs(os.path.dirname(_CRASH_LOG_PATH), exist_ok=True)
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8") as _f:
            _f.write(f"{ts} {_redact(msg)}\n")
    except Exception:
        pass


def _crash_excepthook(exc_type, exc_value, exc_tb) -> None:
    """sys.excepthook replacement — logs unhandled exceptions to crash.log."""
    import traceback
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _write_crash(f"[UNHANDLED EXCEPTION]\n{tb_str}")
    # Also log via standard logging so it still appears in error.log (redacted by _RedactSecrets)
    logger.critical(f"Unhandled exception: {exc_value}", exc_info=(exc_type, exc_value, exc_tb))
    # C-2: print the traceback ourselves, redacted, instead of sys.__excepthook__ (which writes it raw to
    # stderr / backend_stderr.log). The interpreter still exits after the hook returns.
    try:
        sys.stderr.write(_redact(tb_str))
        sys.stderr.flush()
    except Exception:
        pass


# ─── Secret redaction (finding C-2, 2026-10-11) ─────────────────────────────
# httpx logs every request URL at INFO. Massive (apiKey=) and FRED (api_key=) authenticate with query
# parameters, so their keys were written to live.log / backend_stderr.log in plain text. This filter rewrites
# the formatted message with secret query values masked. Attached to the httpx/httpcore loggers (so every
# handler sees the clean record) and to every root handler as a second layer.
# A query value runs to the next '&', whitespace or '#': every other character (incl. sub-delimiters such as
# ' ! $ ( ) * + , ; = and percent-escapes) belongs to the value and is redacted with it.
_SECRET_PARAM_RE = re.compile(r"(?i)(api_?key|access_token|token|secret)=([^&\s#]+)")


def _redact(text: str) -> str:
    return _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}=***", text)


class _RedactSecrets(logging.Filter):
    """Masks secret query values in the message, the exception traceback and stack_info of every record.
    Must run BEFORE any other filter that formats the record (e.g. _SuppressWin10054). A malformed record
    (format/args mismatch) is replaced by a safe, redacted description instead of reaching logging's raw
    error diagnostic. Never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception as e:
            msg = (f"<unformattable log record ({type(e).__name__}): msg={_redact(str(record.msg))} "
                   f"args={_redact(repr(record.args))}>")
            record.msg, record.args = msg, None
        redacted = _redact(msg)
        if redacted != msg:
            record.msg, record.args = redacted, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _redact(record.exc_text)
        if record.stack_info:
            record.stack_info = _redact(record.stack_info)
        return True


def _install_first(target, f) -> None:
    """Attach the redaction filter to a logger/handler exactly once, ahead of every other filter."""
    if not any(isinstance(x, _RedactSecrets) for x in target.filters):
        target.filters.insert(0, f)


# ─── Win10054 noise suppression ─────────────────────────────────────────────

class _SuppressWin10054(logging.Filter):
    """Suppress the Windows-specific 'connection forcibly closed' asyncio noise.

    This fires whenever a browser tab closes/refreshes mid-connection and is harmless.
    """
    _NOISE = ("WinError 10054", "ConnectionResetError", "ConnectionAbortedError",
              "_call_connection_lost", "RemoteProtocolError")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(n in msg for n in self._NOISE)


# ─── Persistent Error Log File ──────────────────────────────────────────────

_LOG_DIR = os.path.join(_BACKEND_DIR, "logs")
_ERROR_LOG_PATH       = os.path.join(_LOG_DIR, "error.log")        # WARNING+
_ERRORS_ONLY_LOG_PATH = os.path.join(_LOG_DIR, "errors_only.log")  # ERROR+ only
_LIVE_LOG_PATH        = os.path.join(_LOG_DIR, "live.log")         # INFO+ (added 2026-05-23 for W3 blend observability)

_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\] ([^:]+): (.+)$"
)


def _add_log_handler(
    path: str,
    level: int,
    win10054_filter: "_SuppressWin10054 | None" = None,
) -> None:
    """Add a RotatingFileHandler at `path` for `level`+, guarded against duplicates."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=5 * 1024 * 1024,   # 5 MB per file
            backupCount=10,
            encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        handler.addFilter(_RedactSecrets())             # first: every later filter sees a safe record
        if win10054_filter is not None:
            handler.addFilter(win10054_filter)
        already_added = any(
            isinstance(h, RotatingFileHandler)
            and os.path.abspath(getattr(h, "baseFilename", "")) == os.path.abspath(path)
            for h in logging.root.handlers
        )
        if not already_added:
            logging.root.addHandler(handler)
        else:
            handler.close()
    except OSError:
        pass  # Non-fatal


def _parse_error_log(limit: int = 100, errors_only: bool = True) -> list:
    """Read and parse the log file, returning entries newest-first.

    errors_only=True  → reads errors_only.log (ERROR/CRITICAL, never polluted by warnings)
    errors_only=False → reads error.log       (WARNING/ERROR/CRITICAL, full log)

    Looks up the log paths through `main` so tests that patch
    `main._ERRORS_ONLY_LOG_PATH` / `main._ERROR_LOG_PATH` intercept correctly.
    """
    import main
    path = main._ERRORS_ONLY_LOG_PATH if errors_only else main._ERROR_LOG_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    entries = []
    for line in reversed(lines):
        m = _LOG_LINE_RE.match(line.rstrip())
        if m:
            entries.append({
                "timestamp": m.group(1),
                "level":     m.group(2),
                "logger":    m.group(3).strip(),
                "message":   m.group(4),
            })
        if len(entries) >= limit:
            break
    return entries


def install_logging() -> "_SuppressWin10054":
    """Wire up the Win10054 filter on root + asyncio + uvicorn loggers,
    install the crash excepthook, register both rotating file handlers, and
    write a PROCESS START stamp. Returns the filter so callers can also
    apply it elsewhere if needed.
    """
    win10054 = _SuppressWin10054()
    logging.getLogger("asyncio").addFilter(win10054)
    logging.getLogger("uvicorn.error").addFilter(win10054)
    logging.getLogger("uvicorn.access").addFilter(win10054)
    logging.root.addFilter(win10054)

    sys.excepthook = _crash_excepthook
    # Stamp the start of each process run so separate crashes are easy to distinguish
    _write_crash(f"[PROCESS START] pid={os.getpid()}")

    _add_log_handler(_ERROR_LOG_PATH,       logging.WARNING, win10054)
    _add_log_handler(_ERRORS_ONLY_LOG_PATH, logging.ERROR,   win10054)
    _add_log_handler(_LIVE_LOG_PATH,        logging.INFO,    win10054)

    # C-2: redact secret query parameters at the source loggers and on every root handler (incl. the
    # basicConfig console stream that feeds backend_stderr.log).
    redact = _RedactSecrets()
    for name in ("httpx", "httpcore", "asyncio", "uvicorn.error", "uvicorn.access"):
        _install_first(logging.getLogger(name), redact)
    _install_first(logging.root, redact)
    for h in logging.root.handlers:
        _install_first(h, redact)

    return win10054
