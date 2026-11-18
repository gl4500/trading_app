"""A3 Task 15c-P2: the import probe of the import-invalid-candidate diagnosis (Codex PROVENANCE_P_RULING, design P;
amendments A1-A4 as disposed in Codex P_AMENDMENTS_RESPONSE). Run BY PATH (never -c, never stdin) inside a contained
child (cr_guard.run_contained, 60 s deadline, verified cleanup) by cr_calibrate.py; never imported by it. One run
writes ONE structured JSON record (write-once, atomically: a temp file renamed into place), then exits 0.

Modes, identical except for the one mutation step:
  control  validate the pinned source identity, then import the UNMUTATED target (P1).
  mutated  validate the pinned source identity, apply the item's exact MutationSpec through Cosmic Ray's own pinned
           API (cosmic_ray.plugins.get_operator(operator)(**operator_args), cosmic_ray.mutating.apply_mutation(path,
           operator, occurrence)), record the original + mutated hashes and the diff, VALIDATE exactly one localized
           change inside the item's span (validate_mutation), persist that pre-import record, and ONLY THEN import
           the target (A3 as amended). Any failure writes a structured refusal record and exits WITHOUT importing.

Scope (A1 as accepted): the probe context MATCHES the selected import-path / environment facts of the guard's pytest
child - the conftest's module-level sys.path inserts (s1_tests, then research/s1, at the front), the copy root as cwd,
the bound child env (PYTHONPATH, S1_HYPOTHESIS_ROOT) - and pre-imports no S1 module. It is NOT identical pytest
initialization: no pytest, no plugins, no conftest pytest_configure (Hypothesis home), no fixtures, no original
test-module import order. Fix round 4 (m4): the probe also loads sqlite3, ctypes and ctypes.wintypes (plus Cosmic
Ray, stevedore and parso) before the target, in both modes, so the set of modules already in sys.modules when the
target is imported differs from collection. Control and mutated share exactly this context (modules_before_import is
checked equal).

Bootstrap window (A2): before anything else the probe hides every sys.path entry under the copy root, loads its own
stdlib modules and Cosmic Ray (whose stevedore cache write needs an unguarded filesystem), records the modules from
the copy loaded so far (must be none: refused otherwise), restores the entries and installs the barrier. The barrier
is in place BEFORE the mutation and BEFORE any target import, identically in both modes.

Barrier (A2 as amended): a COOPERATIVE CHILD-LOCAL Python audit hook (sys.addaudithook; it cannot be removed) - NOT
an OS sandbox and no claim of full isolation: native code can bypass audit events. It refuses
  * every write / create / delete / rename / link / mkdir / rmdir / chmod / utime / truncate / copy / move / rmtree
    whose path (BOTH source and destination for two-path operations) is not inside the resolved scratch roots;
  * any read of a protected path (--protected: the real mailbox, HMAC key and live trading DB from the driver's
    constants; tests pass synthetic fixtures), its SQLite sidecars (-wal, -shm, -journal) included, through open,
    _winapi.CreateFile or sqlite3.connect (plain path or file: URI; in-memory ONLY for the plain ":memory:", a
    "file::memory:" URI or an exact, single mode=memory URI parameter - fix round 2, review I1);
  * _winapi.CreateFile by access and creation disposition (any write access, a disposition other than
    OPEN_EXISTING or FILE_FLAG_DELETE_ON_CLOSE is a write);
  * whole families (REFUSED_PREFIXES): process and THREAD creation, network, ctypes / msvcrt / every other _winapi
    call (CreateJunction, CreateNamedPipe ...), registry writes, SQLite extension loading; mmap of a file descriptor;
  * any access it cannot parse (an integer fd opened for writing, a non-path object, an undecodable path);
  * FAIL CLOSED (fix round 2, review I2): an audit event that is neither handled nor on the reviewed SAFE list may
    proceed only if every path-like argument (str / bytes / PathLike) resolves inside the scratch roots and is not
    protected, and it has no int argument (a possible fd).
  The re-entrancy guard is per thread (review M2).
  Fix round 3: every new SQLite connection gets an authorizer (sqlite3.connect/handle) that denies ATTACH - which
  VACUUM INTO also asks for - unless the file is in-memory or inside scratch and not protected; a connection whose
  authorizer cannot be installed is refused (cooperative: the target could replace the authorizer). Unlisted events
  are checked inside tuple / list arguments. CTYPES_ALLOWED (the narrow declaration binding, accepted as amended
  by Codex's exact-head review of 3e80738): exactly the ctypes events of importing ctypes / wintypes / msvcrt and a
  kernel32 WinDLL with the CreateFileW / CloseHandle prototypes (recorded from a synthetic toy of the
  s1_locks.py:12,34-43 shape). Fix round 5 (R-N2, declarations allowed, calls refused): a call is refused on the
  guarded resolution path (every allowed symbol - GetLastError, CreateFileW, CloseHandle - is wrapped) and on the
  enumerated pre-hook aliases (ctypes.GetLastError, every pointer cached on the loaded loader / CDLL instances, every
  module-level _CFuncPtr in sys.modules at guard install, all replaced by refusing wrappers and recorded). A raw
  pointer obtained another way (closure or gc introspection, native code) is a disclosed limit of this cooperative
  barrier, not an OS sandbox.
  Fix round 6 (re-review 4): the guarded __getitem__ wraps EVERY pointer resolved in its window, labelled from the
  names the hook validated (no TOCTOU), and allows exactly one dlsym per window. The hook never runs target code
  (a pre-existing hole, now closed: a target _name property / __fspath__ used to run inside the hook, where its own
  audit events went unchecked): dlopen / dlsym need ctypes' own loader class by exact type, _name from the genuine
  instance __dict__ as an exact str and an exact-str symbol; path arguments must be an exact str / bytes, an
  os.DirEntry or a stdlib pathlib object of exact type with builtin-only state (a str / bytes subclass or any other
  PathLike is refused, never converted); containers are walked with the builtin types' own iterators; and an event
  raised while the hook is busy is REFUSED. Disclosed: target code that rebinds the stdlib functions, ctypes or
  probe internals the hook relies on (os.path.realpath, pathlib methods, the probe module's globals) is outside
  this cooperative guarantee.
Paths are resolved first (extended \\\\?\\ prefix stripped, relative to cwd, '..' collapsed, symlinks followed, case
folded). A refusal is recorded with its own reason (event, reason, the path - never file contents) and raised from the
hook, so the innermost frame is this probe, never the target; the driver then HALTS.

Evidence (P3): the exception's class (module + qualname) and, for EVERY traceback frame, the canonical filename
(realpath; relative to the copy root when under it), that file's sha256, co_name, co_qualname, co_firstlineno, co_flags,
tb_lineno, tb_lasti and the (lineno, end_lineno, col, end_col) of co_positions() at index tb_lasti // 2 (Python 3.12:
one position per 2-byte code unit, inline CACHE entries included). ``positions_agree`` compares it with dis's
instruction at offset tb_lasti, but in 3.12 dis reads the SAME co_positions table, so it is a consistency re-read and
not an independent check (review M1); the verification of the tb_lasti // 2 mapping is the toy tests with hand-derived spans
(an instruction after CALL / BINARY_SUBSCR inline caches included). Rendered traceback text is SECONDARY only. On
success: imported true and the imported file's identity.
A4: the mutated bytes are RE-APPLIED under the probe context; Cosmic Ray never persisted the original attempt's mutated
bytes, so no byte-for-byte comparison with the original attempt is possible or claimed.

usage: cr_import_probe.py --mode control|mutated --copy-root C --module-rel R --target T --spec SPEC.json
                          --scratch D --out RECORD.json --pin SHA256 [--prefix REL ...] [--protected PATH ...]
"""
import os
import sys


def _argv_value(flag: str):
    for i, a in enumerate(sys.argv[:-1]):
        if a == flag:
            return sys.argv[i + 1]
    return None


# ---- bootstrap window: hide the copy from sys.path while the probe's own modules and Cosmic Ray load ------------
_COPY = _argv_value("--copy-root")
_COPY_REAL = os.path.normcase(os.path.realpath(_COPY)) if _COPY else None
_SAVED_PATH = list(sys.path)


def _in_copy(p) -> bool:
    try:
        rp = os.path.normcase(os.path.realpath(p or "."))
    except (OSError, ValueError, TypeError):
        return True                                      # unknown: treat as the copy (hidden), fail closed
    return bool(_COPY_REAL) and (rp == _COPY_REAL or rp.startswith(_COPY_REAL.rstrip("\\/") + os.sep))


_HIDDEN = [p for p in sys.path if _in_copy(p)]
sys.path[:] = [p for p in sys.path if not _in_copy(p)]

import argparse        # noqa: E402 - deliberately after the copy entries are hidden
import difflib         # noqa: E402
import dis             # noqa: E402
import hashlib         # noqa: E402
import importlib       # noqa: E402
import json            # noqa: E402
import re              # noqa: E402
import threading       # noqa: E402
import traceback       # noqa: E402
import urllib.parse    # noqa: E402
from importlib import metadata   # noqa: E402
from pathlib import Path         # noqa: E402

import cosmic_ray.mutating as cr_mutating   # noqa: E402 - stevedore writes its cache here (unguarded, no S1 code)
import cosmic_ray.plugins as cr_plugins     # noqa: E402
from cosmic_ray.util import read_python_source   # noqa: E402
import sqlite3                                   # noqa: E402 - stdlib, loaded in the bootstrap window: the guards
import ctypes                                    # noqa: E402   below patch them before the hook-guarded import
if sys.platform == "win32":
    from ctypes import wintypes                  # noqa: E402,F401

import pathlib                                   # noqa: E402

# ---- fix round 6 (re-review 4, finding 3): references captured in the bootstrap window, BEFORE any target code, so
# the hook classifies arguments by exact type identity and reads attributes through these original descriptors -
# never through the target's own __class__ / __eq__ / __hash__ / __fspath__ / __str__ / __index__ / properties.
_TYPE_MRO = type.__dict__["__mro__"]             # getset descriptors of `type` itself: no metaclass lookup
_TYPE_DICT = type.__dict__["__dict__"]
_TYPE_NAME = type.__dict__["__name__"]
_TYPE_BASES = type.__dict__["__bases__"]
_STD_PATH_TYPES = tuple(getattr(pathlib, n) for n in ("PurePath", "PurePosixPath", "PureWindowsPath", "Path",
                                                      "PosixPath", "WindowsPath"))
_PATH_SLOTS = tuple(pathlib.PurePath.__dict__[n] for n in getattr(pathlib.PurePath, "__slots__", ())
                    if n in pathlib.PurePath.__dict__)
_DIRENTRY = os.DirEntry
_CTYPES_LIB_CLASSES = tuple(c for c in (ctypes.CDLL, ctypes.PyDLL, getattr(ctypes, "WinDLL", None),
                                        getattr(ctypes, "OleDLL", None)) if c is not None)
_CDLL_DICT = ctypes.CDLL.__dict__["__dict__"]    # the genuine instance-__dict__ descriptor of ctypes' loaders
_CFUNCPTR = ctypes._CFuncPtr
_FUNCPTR_META = type(ctypes._CFuncPtr)
_FUNCPTR_CLASS_KEYS = frozenset({"__module__", "__qualname__", "__doc__", "_flags_", "_restype_", "__dict__",
                                 "__weakref__"})


def _is(t, types) -> bool:
    """Exact type identity (never hash / __eq__ / isinstance on a target object)."""
    return any(t is k for k in types)


def _tname(v) -> str:
    """The type name of ``v`` as an exact str (str.__str__ copies a str subclass without calling its methods)."""
    try:
        return str.__str__(_TYPE_NAME.__get__(type(v)))
    except Exception:                                    # noqa: BLE001
        return "?"


def _exact_key(d, key: str):
    """d[key] for a real dict, matching only EXACT-str keys (a str-subclass key's __eq__ is never called)."""
    if type(d) is not dict:
        return None
    for k, v in dict.items(d):
        if type(k) is str and k == key:
            return v
    return None


def _defines_fspath(t) -> bool:
    """Whether a class (or a base) defines __fspath__, read through type's own descriptors (no metaclass code)."""
    try:
        for k in _TYPE_MRO.__get__(t):
            for key in _TYPE_DICT.__get__(k):
                if type(key) is not str or key == "__fspath__":
                    return True
    except Exception:                                    # noqa: BLE001 - unreadable: treat as path-like (refused)
        return True
    return False


def _exact_state(v, depth=0) -> bool:
    if v is None or _is(type(v), (str, int, bool)):
        return True
    if _is(type(v), (list, tuple)) and depth < 2:
        return all(_exact_state(x, depth + 1) for x in (list.__iter__(v) if type(v) is list else tuple.__iter__(v)))
    return False


def _plain_path(v) -> str:
    """Fix round 6 (finding 3): a path argument as an EXACT str, or ValueError (the caller refuses). Accepted: an
    exact str, exact bytes (strict UTF-8), an os.DirEntry, or a stdlib pathlib object of an exact stdlib type whose
    every set slot holds only exact builtin values (so pathlib's own __fspath__ runs on builtin data only). A str /
    bytes subclass or any other PathLike is never converted: its methods would be target code inside the hook."""
    t = type(v)
    if t is str:
        p = v
    elif t is bytes:
        p = v.decode("utf-8")                                 # strict: undecodable -> unparseable
    elif t is _DIRENTRY:
        p = v.path
    elif _is(t, _STD_PATH_TYPES):
        for d in _PATH_SLOTS:
            try:
                s = d.__get__(v)
            except AttributeError:
                continue
            if not _exact_state(s):
                raise ValueError("stdlib path with non-builtin state")
        p = os.fspath(v)
    else:
        raise ValueError(f"unparseable path {_tname(v)}")
    if type(p) is bytes:
        p = p.decode("utf-8")
    if type(p) is not str:
        raise ValueError("unparseable path")
    return p


SCHEMA = "a3-t15cp2-probe/2"
# ---- the barrier's event policy (fix round 2, review I2: FAIL CLOSED). Every audit event is one of:
#   REFUSED families (prefix): process / thread creation, network, native-code and Windows-handle APIs, registry writes;
#   MUTATING / READING events: their path arguments are checked (writes inside scratch, reads never protected);
#   explicitly handled: open, sqlite3.connect, _winapi.CreateFile, mmap.__new__;
#   SAFE: reviewed events with no filesystem effect (Python 3.12 audit-events table);
#   ANYTHING ELSE: every path-like argument (str / bytes / PathLike) must resolve inside the scratch roots and must
#   not be protected, and an int argument (a possible fd) is refused.
REFUSED_PREFIXES = (
    # processes and threads (review M2: no thread may race the hook)
    "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile", "os.fork", "os.kill",
    "os.killpg", "pty.", "_posixsubprocess.", "signal.pthread_kill", "_thread.start_new_thread", "ensurepip.",
    "webbrowser.",
    # network
    "socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto", "socket.sendmsg", "socket.gethostbyname",
    "socket.gethostbyaddr", "socket.getnameinfo", "socket.getservbyname", "socket.getservbyport", "socket.sethostname",
    "socket.listen", "http.client.", "urllib.Request", "ftplib.", "smtplib.", "poplib.", "imaplib.", "nntplib.",
    "telnetlib.",
    # native code, Windows handles, the console (reviewed: fail closed during the import)
    "ctypes.", "msvcrt.", "_winapi.CreateJunction", "_winapi.CreateNamedPipe", "_winapi.CreatePipe",
    "_winapi.CreateProcess", "_winapi.OpenProcess", "_winapi.TerminateProcess", "_winapi.",
    # registry writes / remote registry / hive files
    "winreg.CreateKey", "winreg.DeleteKey", "winreg.DeleteValue", "winreg.SetValue", "winreg.LoadKey",
    "winreg.SaveKey", "winreg.ConnectRegistry", "winreg.DisableReflectionKey", "winreg.EnableReflectionKey",
    # SQLite extension loading (native code)
    "sqlite3.enable_load_extension", "sqlite3.load_extension",
)
# event -> argument indexes that are paths WRITTEN / changed (all must be inside the scratch roots)
MUTATING = {"os.remove": (0,), "os.unlink": (0,), "os.rmdir": (0,), "os.rename": (0, 1), "os.replace": (0, 1),
            "os.link": (0, 1), "os.symlink": (1,), "os.mkdir": (0,), "os.makedirs": (0,), "os.chmod": (0,),
            "os.lchmod": (0,), "os.chown": (0,), "os.lchown": (0,), "os.chflags": (0,), "os.lchflags": (0,),
            "os.utime": (0,), "os.truncate": (0,), "os.setxattr": (0,), "os.removexattr": (0,), "os.lockf": (0,),
            "shutil.rmtree": (0,), "shutil.copyfile": (1,), "shutil.copymode": (1,), "shutil.copystat": (1,),
            "shutil.copytree": (1,), "shutil.move": (0, 1), "shutil.chown": (0,), "shutil.make_archive": (0,),
            "shutil.unpack_archive": (1,), "tempfile.mkstemp": (0,), "tempfile.mkdtemp": (0,)}
# event -> argument indexes that are paths READ (must not be protected; anything else may be read)
READING = {"shutil.copyfile": (0,), "shutil.copytree": (0,), "shutil.move": (0,), "shutil.copymode": (0,),
           "shutil.copystat": (0,), "shutil.unpack_archive": (0,), "os.link": (0,), "os.symlink": (0,),
           "os.rename": (0,), "os.replace": (0,), "os.listdir": (0,), "os.scandir": (0,), "os.walk": (0,),
           "os.fwalk": (0,), "os.chdir": (0,), "os.getxattr": (0,), "os.listxattr": (0,), "os.listdrives": (),
           "os.listmounts": (0,), "os.listvolumes": (), "os.add_dll_directory": (0,), "glob.glob": (0,),
           "glob.glob/2": (0, 2), "pathlib.Path.glob": (), "pathlib.Path.rglob": (), "zipimport.zipimporter": (0,)}
# reviewed events with no filesystem effect (their arguments are not paths)
SAFE = frozenset({
    "import", "exec", "compile", "builtins.id", "builtins.input", "builtins.input/result", "builtins.breakpoint",
    "code.__new__", "function.__new__", "object.__getattr__", "object.__setattr__", "object.__delattr__",
    "sys._getframe", "sys._getframemodulename", "sys._current_frames", "sys._current_exceptions", "sys.settrace",
    "sys.setprofile", "sys.addaudithook", "sys.excepthook", "sys.unraisablehook", "sys.set_asyncgen_hooks_firstiter",
    "sys.set_asyncgen_hooks_finalizer", "sys.monitoring.register_callback", "cpython.PyInterpreterState_New",
    "cpython.PyInterpreterState_Clear", "cpython._PySys_ClearAuditHooks", "cpython.run_command", "cpython.run_file",
    "cpython.run_interactivehook", "cpython.run_module", "cpython.run_startup", "cpython.run_stdin", "array.__new__",
    "gc.get_objects", "gc.get_referrers", "gc.get_referents", "marshal.dumps", "marshal.load", "marshal.loads",
    "pickle.find_class", "os.putenv", "os.unsetenv", "time.sleep", "resource.setrlimit", "resource.prlimit",
    "pdb.Pdb", "socket.__new__", "socket.gethostname", "winreg.OpenKey",
    "winreg.OpenKey/result", "winreg.QueryValue", "winreg.QueryInfoKey", "winreg.EnumKey", "winreg.EnumValue",
    "winreg.ExpandEnvironmentStrings", "winreg.PyHKEY.Detach", "locale.setlocale", "os.set_blocking"})
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# _winapi.CreateFile (audit args: file_name, desired_access, share_mode, creation_disposition, flags_and_attributes)
_GENERIC_WRITE, _GENERIC_ALL = 0x40000000, 0x10000000
_WRITE_ACCESS = (_GENERIC_WRITE | _GENERIC_ALL | 0x00000002 | 0x00000004 | 0x00000010 | 0x00000100 | 0x00010000
                 | 0x00040000 | 0x00080000 | 0x02000000)  # + FILE_WRITE_DATA/APPEND/EA/ATTRIBUTES, DELETE, WRITE_DAC,
#                                                           WRITE_OWNER, MAXIMUM_ALLOWED
_OPEN_EXISTING, _FLAG_DELETE_ON_CLOSE = 3, 0x04000000
_SQLITE_OK, _SQLITE_DENY, _SQLITE_ATTACH = 0, 1, 24
# fix round 3 N2 - the narrow kernel32 library / symbol / prototype DECLARATION binding, accepted as amended in Codex's
# exact-head review of 3e80738 (fix round 5, R-N2: declarations allowed, calls refused): exactly the ctypes events
# recorded from a SYNTHETIC toy with the import-time shape of s1_locks.py:12,34-43 (`import ctypes`: dlopen kernel32 +
# dlsym GetLastError; `from ctypes import wintypes` and `import msvcrt`: none; `ctypes.WinDLL("kernel32")`: dlopen
# kernel32; the CreateFileW / CloseHandle prototypes: dlsym of those two names). Every other ctypes / msvcrt / _winapi
# event - call_function, cdata, addressof, string_at, set_last_error, dlsym/handle, any other library or symbol - is
# refused.
CTYPES_ALLOWED = frozenset({("ctypes.dlopen", "kernel32"), ("ctypes.dlsym", "kernel32", "GetLastError"),
                            ("ctypes.dlsym", "kernel32", "CreateFileW"), ("ctypes.dlsym", "kernel32", "CloseHandle")})
# fix round 5 (R-N2): EVERY allowed symbol comes back wrapped on the resolution path - derived, never restated
CTYPES_WRAPPED = tuple(sorted((k[1], k[2]) for k in CTYPES_ALLOWED if k[0] == "ctypes.dlsym"))
_SIDECARS = ("", "-wal", "-shm", "-journal")
CLAIM = ("a cooperative child-local Python audit-hook barrier, not an OS sandbox: no claim of full isolation "
         "(native code can bypass audit events); ctypes foreign-function calls are refused on the guarded resolution "
         "path (CDLL.__getitem__, every allowed kernel32 symbol wrapped) and on the enumerated pre-hook aliases "
         "(ctypes.GetLastError, pointers cached on loaded loader / CDLL instances, module-level _CFuncPtr objects in "
         "sys.modules at guard install); the hook classifies arguments by exact type and never calls a target "
         "object's methods, and an event raised while it is busy is refused; disclosed limits of this cooperative "
         "barrier: a raw pointer obtained another way (closure or gc introspection, native code) and target code "
         "that rebinds the stdlib / ctypes / probe internals the hook itself relies on; process containment alone "
         "does not block data access")
DEFAULT_PREFIX = ("research/s1/s1_tests", "research/s1", ".")     # final sys.path front order (A1)


class BarrierRefusal(RuntimeError):
    """An A2 barrier refused an operation before or during the mutation or the target import."""


class Refusal(Exception):
    """A pre-import refusal: written as a structured record; the target is never imported."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_file(p) -> str | None:
    try:
        return _sha_bytes(Path(p).read_bytes())
    except OSError:
        return None


# ------------------------------------------------------------------------------------------ path resolution
def resolve(p) -> str:
    """Canonical form for descendant checks: fsdecode, strip the extended-length prefix, absolute against cwd,
    '..' collapsed, symlinks followed, case folded. Raises on anything unparseable. Fix round 6 (finding 3): the
    argument is first reduced to an exact str by _plain_path, so no target method runs here."""
    p = _plain_path(p)
    if not p or "\x00" in p:
        raise ValueError("unparseable path str")
    p = p.replace("/", "\\")
    if p.startswith("\\\\?\\UNC\\"):
        p = "\\\\" + p[8:]
    elif p.startswith(("\\\\?\\", "\\??\\")):
        p = p[4:]
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def _inside(rp: str, roots) -> bool:
    return any(rp == r or rp.startswith(r.rstrip("\\") + "\\") for r in roots)


def _sqlite_target(db):
    """(kind, path) of a sqlite3.connect database argument: ("memory", None), ("path", p) or ("uri", p)."""
    db = _plain_path(db)                                     # fix round 6: exact str only, no target method
    if db == ":memory:":
        return "memory", None
    if db.startswith("file:"):
        rest = db[5:].partition("#")[0]                      # a URI fragment is not part of the file name
        path, _, query = rest.partition("?")
        try:                                                 # review I1: the parsed parameters, never a substring
            params = urllib.parse.parse_qs(query, keep_blank_values=True, strict_parsing=bool(query),
                                           errors="strict")
        except (ValueError, UnicodeDecodeError):
            raise ValueError("unparseable sqlite URI query") from None
        if path == ":memory:" or params.get("mode") == ["memory"]:
            return "memory", None
        path = urllib.parse.unquote(path, errors="strict")
        if path.startswith("///"):
            path = path[3:]
        elif path.startswith("//localhost/"):
            path = path[12:]
        if len(path) > 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return "uri", path
    return "path", db


def make_barrier(scratch_roots, refusals: list, protected=()):
    """The A2 audit hook. ``scratch_roots`` may hold writes; ``protected`` (+ SQLite sidecars) may not even be read.
    Every refusal is appended to ``refusals`` (event, reason, path - never contents) and raised."""
    roots = [resolve(r) for r in scratch_roots]
    prot = {resolve(str(p) + s) for p in protected for s in _SIDECARS}
    local = threading.local()                                # review M2: a per-thread re-entrancy flag

    def refuse(event, reason, detail=""):
        refusals.append({"event": event, "reason": reason, "detail": str(detail)[:300]})
        raise BarrierRefusal(f"A2 barrier refused {event}: {reason} {str(detail)[:200]}")

    def check_read(event, p):
        try:
            rp = resolve(p)
        except Exception:                                  # noqa: BLE001 - unknown access fails closed
            refuse(event, "unparseable_path", _tname(p))
        if rp in prot:
            refuse(event, "protected_read", rp)

    def check_write(event, p):
        try:
            rp = resolve(p)
        except Exception:                                  # noqa: BLE001
            refuse(event, "unparseable_path", _tname(p))
        if rp in prot:
            refuse(event, "protected_write", rp)
        if not _inside(rp, roots):
            refuse(event, "outside_scratch", rp)

    def hook(event, args):
        # fix round 6 (finding 3): an event raised while the hook is already busy on this thread can only come from
        # code running INSIDE the hook (the hook itself raises none: verified by the whole suite) - e.g. a finalizer
        # or anything a target object slipped in - so it is REFUSED, never let through unchecked
        if getattr(local, "busy", False):
            refuse(event, "reentrant_event", event if type(event) is str else "")
        local.busy = True
        try:
            if event == "ctypes.dlopen":                 # fix round 3 N2 / fix round 6: exact str, recorded set only
                name = args[0] if args else None
                if type(name) is not str or (event, name) not in CTYPES_ALLOWED:
                    refuse(event, "refused_family", name if type(name) is str else _tname(name))
                return
            if event == "ctypes.dlsym":
                # fix round 6 (findings 2 + 3): ctypes' own loader class by exact type, its _name from the genuine
                # instance __dict__ as an exact str, an exact-str symbol - no target property / __eq__ / __hash__
                # runs; only on the guarded __getitem__ path, once per resolution (recorded for getitem's wrap)
                lib, sym = (tuple(args) + (None, None))[:2]
                libname = _lib_name(lib)
                if libname is None or type(sym) is not str or (event, libname, sym) not in CTYPES_ALLOWED:
                    refuse(event, "refused_family", f"{libname or _tname(lib)}."
                                                    f"{sym if type(sym) is str else _tname(sym)}")
                if not getattr(_CT, "active", False):
                    refuse(event, "refused_family", f"{libname}.{sym} off the guarded resolution path")
                allowed = getattr(_CT, "allowed", None)
                if type(allowed) is not list or allowed:
                    refuse(event, "dlsym_reentry", f"{libname}.{sym}: a second resolution in one guarded window")
                allowed.append((lib, libname, sym))
                return
            if event.startswith(REFUSED_PREFIXES) and event != "_winapi.CreateFile":
                refuse(event, "refused_family", "")
            if event == "sqlite3.connect/handle":                         # fix round 3 N1: SQL-level file access
                # the handle event fires inside Connection.__init__, before set_authorizer can run; only a
                # connection of the guard class (which installs the authorizer right after its __init__) may open
                cls = _GUARD.get("sqlite_cls")
                if cls is None or not args or type(args[0]) is not cls:
                    refuse(event, "authorizer_not_installed", _tname(args[0]) if args else "")
            elif event == "_winapi.CreateFile":
                name, access, _share, disposition, flags = (tuple(args) + (None,) * 5)[:5]
                if not all(type(v) is int for v in (access, disposition, flags)):
                    refuse(event, "unparseable_access", "")
                check_read(event, name)
                if access & _WRITE_ACCESS or disposition != _OPEN_EXISTING or flags & _FLAG_DELETE_ON_CLOSE:
                    check_write(event, name)
            elif event == "mmap.__new__":
                fileno = args[0] if args else None
                if type(fileno) is not int or fileno != -1:
                    refuse(event, "fd_mapping", f"fileno {fileno if type(fileno) is int else _tname(fileno)}")
            elif event == "sqlite3.connect":
                if _GUARD.get("sqlite_cls") is not None and not getattr(_SQ, "active", False):
                    # fix round 4 (m1): a connection is (re)opened only through the guard path - a direct
                    # sqlite3.Connection.__init__ (e.g. re-initialising a guarded connection) is refused before
                    # SQLite opens anything
                    refuse(event, "unguarded_connection", "")
                try:
                    kind, path = _sqlite_target(args[0] if args else None)
                except Exception:                          # noqa: BLE001
                    refuse(event, "unparseable_path", "sqlite database")
                if kind != "memory":
                    check_read(event, path)
                    check_write(event, path)               # SQLite may create / journal: scratch only
            elif event == "open":
                path, mode, flags = (tuple(args) + (None, None, None))[:3]
                if type(mode) is str:                       # fix round 6: exact types only
                    writable = any(c in mode for c in "wax+")
                elif mode is None and (flags is None or type(flags) is int):
                    writable = type(flags) is int and bool(flags & _WRITE_FLAGS)
                else:
                    refuse(event, "unparseable_mode", _tname(mode))
                if type(path) is int:
                    if writable:
                        refuse(event, "fd_write", f"fd {path}")
                    return
                check_read(event, path)
                if writable:
                    check_write(event, path)
            elif event in READING or event in MUTATING:
                for i in READING.get(event, ()):
                    if i < len(args) and args[i] is not None:
                        check_read(event, args[i])
                for i in MUTATING.get(event, ()):
                    if i < len(args):
                        check_write(event, args[i])
            elif event not in SAFE:                         # unlisted: fail closed on anything path-like
                check_unlisted(event, args, 0)
        finally:
            local.busy = False

    def check_unlisted(event, value, depth):
        """Fix round 3 N3 / fix round 4 m3: tuple, list, set, frozenset and dict (keys AND values) arguments are
        checked recursively (too deep: refused). Fix round 6 (finding 3): classified by type identity / the C-level
        subtype check and iterated with the builtin types' own iterators, so no target __class__ / __iter__ /
        __fspath__ / __index__ runs; a str / bytes subclass or a non-stdlib PathLike is refused, not converted."""
        for v in value:
            t = type(v)
            if v is None or _is(t, (bool, float, complex)):
                continue
            if issubclass(t, (tuple, list, set, frozenset, dict)):
                if depth >= 8:
                    refuse(event, "unlisted_event_nesting", "")
                if issubclass(t, dict):
                    items = [x for kv in dict.items(v) for x in kv]
                elif issubclass(t, tuple):
                    items = list(tuple.__iter__(v))
                elif issubclass(t, list):
                    items = list(list.__iter__(v))
                elif issubclass(t, frozenset):
                    items = list(frozenset.__iter__(v))
                else:
                    items = list(set.__iter__(v))
                check_unlisted(event, items, depth + 1)
            elif issubclass(t, int):
                refuse(event, "unlisted_event_int", f"int argument {v}" if t is int else _tname(v))
            elif _is(t, (str, bytes, _DIRENTRY) + _STD_PATH_TYPES):
                check_write(event, v)
            elif issubclass(t, (str, bytes)) or _defines_fspath(t):
                refuse(event, "untrusted_path_type", _tname(v))

    def authorizer(action, arg1, arg2, dbname, source):
        """SQLite authorizer (fix round 3 N1): ATTACH - also what VACUUM INTO asks - only for an in-memory database or
        a path inside the scratch roots; never a protected path. A refusal is recorded like any other. COOPERATIVE:
        the target could replace the authorizer on its own connection."""
        if action != _SQLITE_ATTACH:
            return _SQLITE_OK
        try:
            kind, path = _sqlite_target(arg1 if arg1 is not None else "")
            if kind != "memory":
                rp = resolve(path)
                if rp in prot:
                    raise BarrierRefusal("protected")
                if not _inside(rp, roots):
                    raise BarrierRefusal("outside")
        except Exception as exc:                            # noqa: BLE001 - unknown / refused: deny, recorded
            reason = {"protected": "protected_read", "outside": "outside_scratch"}.get(str(exc), "unparseable_path")
            refusals.append({"event": "sqlite3.authorizer", "reason": reason, "detail": "ATTACH / VACUUM INTO "
                             + str(arg1)[:250]})
            return _SQLITE_DENY
        return _SQLITE_OK

    hook.authorizer = authorizer
    hook.refuse_call = lambda name: refuse("ctypes.call_function", "foreign_call_refused",
                                           f"{name} (no 3.12 audit event; refused by the probe's wrapper)")
    hook.refuse_resolution = lambda detail: refuse("ctypes.dlsym", "guarded_path_mismatch", detail)
    hook._local = local                          # fix round 6: the per-thread busy flag (tests)
    return hook


def _lib_name(lib):
    """Fix round 6 (finding 3): the loader's name, or None - only for an instance of ctypes' OWN loader classes (exact
    type identity: a subclass is refused) whose genuine instance __dict__ holds an exact-str _name. Nothing of the
    target's (property, __getattr__, __eq__) runs."""
    if not _is(type(lib), _CTYPES_LIB_CLASSES):
        return None
    try:
        name = _exact_key(_CDLL_DICT.__get__(lib), "_name")
    except Exception:                                  # noqa: BLE001
        return None
    return name if type(name) is str else None


def _genuine_funcptr(fp) -> bool:
    """The loader's _FuncPtr is the class ctypes' CDLL.__init__ made: exact metaclass, the single base _CFuncPtr and
    no class attribute beyond ctypes' own (no __new__ / __init__ / descriptor the target could add)."""
    if type(fp) is not _FUNCPTR_META:
        return False
    try:
        bases, keys = _TYPE_BASES.__get__(fp), list(_TYPE_DICT.__get__(fp))
    except Exception:                                  # noqa: BLE001
        return False
    return (type(bases) is tuple and len(bases) == 1 and bases[0] is _CFUNCPTR
            and all(type(k) is str and k in _FUNCPTR_CLASS_KEYS for k in keys))


# ---- guards installed right after the hook (fix round 3) -----------------------------------------------------
_GUARD: dict = {}
_CT = threading.local()                        # set only while the guarded CDLL.__getitem__ resolves a symbol
_SQ = threading.local()                        # set only while GuardedConnection.__init__ (re)opens a connection


def refusing_foreign_function(func, name, refuse_call):
    """A foreign function the target may DECLARE (argtypes / restype are forwarded) but never CALL: calling a ctypes
    foreign function raises no audit event in 3.12, so the call is refused here and recorded. Fix round 4 (m2): the
    raw pointer lives only in this closure - the instance has no attributes (empty __slots__), so no plain attribute
    of the wrapper yields it. Cooperative: introspecting the class's function closures would still reach it."""
    class RefusingForeignFunction:
        __slots__ = ()

        def __getattr__(self, k):
            if k.startswith("__"):                     # no dunder (e.g. __dict__) is forwarded to the pointer
                raise AttributeError(k)
            return getattr(func, k)

        def __setattr__(self, k, v):
            setattr(func, k, v)

        def __call__(self, *a, **kw):
            refuse_call(name)
    return RefusingForeignFunction()


def _namespace(obj):
    """obj's own __dict__ (a real dict) or None - never a custom __getattr__ / lazy attribute."""
    try:
        d = object.__getattribute__(obj, "__dict__")
    except Exception:                              # noqa: BLE001 - no namespace: nothing to scan
        return None
    return d if type(d) is dict else None


def wrap_preexisting_foreign_functions(modules, wrap) -> list:
    """Fix round 5 (R-N2): replace every pre-hook raw ctypes foreign-function alias with ``wrap(func, label)`` and
    return the sorted labels found. Scanned: each module's namespace in ``modules`` (sys.modules at guard install) -
    module-level _CFuncPtr objects (ctypes.GetLastError, memmove, memset, _cast, _string_at, _wstring_at ...), the
    pointers cached on module-level CDLL instances, and on the CDLL instances cached by module-level LibraryLoader
    objects (ctypes.windll.kernel32.GetLastError, cdll / oledll / pydll). Types only (type() / issubclass), never
    isinstance or getattr, so no target-controlled code runs; one wrapper per raw pointer."""
    fptr, cdll, loader = ctypes._CFuncPtr, ctypes.CDLL, ctypes.LibraryLoader
    memo: dict = {}
    found: list = []

    def wrapped(func, label):
        if id(func) not in memo:
            memo[id(func)] = (func, wrap(func, label))      # func kept alive: its id stays unique
        found.append(label)
        return memo[id(func)][1]

    def scan_dll(lib, label):
        ns = _namespace(lib)
        for k, v in list((ns or {}).items()):
            if issubclass(type(v), fptr):
                ns[k] = wrapped(v, f"{label}.{k}")
            elif any(v is w for _, w in memo.values()):     # already replaced via another path: record this one too
                found.append(f"{label}.{k}")
    for mname, mod in sorted(modules.items(), key=lambda kv: str(kv[0])):
        ns = _namespace(mod)
        if ns is None:
            continue
        for k, v in list(ns.items()):
            t = type(v)
            if issubclass(t, fptr):
                ns[k] = wrapped(v, f"{mname}.{k}")
            elif issubclass(t, cdll):
                scan_dll(v, f"{mname}.{k}")
            elif issubclass(t, loader):
                for a, lib in list((_namespace(v) or {}).items()):
                    if issubclass(type(lib), cdll):
                        scan_dll(lib, f"{mname}.{k}.{a}")
    return sorted(set(found))


def install_guards(hook) -> dict:
    """N1: sqlite3.connect makes a guard-class connection that installs the barrier's authorizer; a connection of
    another class (a direct _sqlite3 call, another factory) is refused by the handle event, and (fix round 4, m1) a
    (re)open off the guard path - e.g. sqlite3.Connection.__init__ on a guarded connection - by the connect event.
    COOPERATIVE, not fail-closed for every connection: the target can still call set_authorizer(None) on its own
    connection, which raises no audit event. N2: CDLL.__getitem__ (what
    attribute access uses) is the only path on which the allowed kernel32 symbols resolve, and (fix round 5, R-N2)
    every one of them comes back wrapped so that a call is refused; the pre-hook raw aliases found in sys.modules are
    replaced by refusing wrappers and recorded. Cooperative: a raw pointer reached another way is a disclosed limit."""
    auth = hook.authorizer
    orig_connect = sqlite3.connect

    class GuardedConnection(sqlite3.Connection):
        def __init__(self, *a, **kw):
            _SQ.active = True                      # fix round 4 (m1): only this path may (re)open a connection
            try:
                super().__init__(*a, **kw)
            finally:
                _SQ.active = False
            self.set_authorizer(auth)

    def connect(*a, factory=None, **kw):
        _SQ.active = True
        try:
            return orig_connect(*a, factory=GuardedConnection if factory in (None, sqlite3.Connection) else factory,
                                **kw)
        finally:
            _SQ.active = False
    sqlite3.connect = connect
    sqlite3.dbapi2.connect = connect
    _GUARD["sqlite_cls"] = GuardedConnection
    orig_getitem = ctypes.CDLL.__getitem__

    def getitem(self, name_or_ordinal):
        """Fix round 6 (re-review 4, finding 2): no TOCTOU. The guarded window opens only for an instance of ctypes'
        own loader class (exact type), an exact-str name, an exact-int handle and the genuine _FuncPtr class - all
        read without target code - and the pointer is resolved here directly. EVERY pointer resolved in the window
        is wrapped, unconditionally, and labelled from the names the HOOK validated (never re-read from target
        state); the window must hold exactly one allowed dlsym, for this loader and this name, else it is refused
        (also when the resolution raised). Anything else takes the original path with the window closed, where the
        hook refuses every dlsym."""
        ns = _CDLL_DICT.__get__(self) if _lib_name(self) is not None else None
        fp, handle = _exact_key(ns, "_FuncPtr"), _exact_key(ns, "_handle")
        if ns is None or type(name_or_ordinal) is not str or type(handle) is not int or not _genuine_funcptr(fp):
            return orig_getitem(self, name_or_ordinal)
        _CT.active, _CT.allowed = True, []
        ok = False
        try:
            func = fp((name_or_ordinal, self))
            ok = True
        finally:
            allowed = _CT.allowed
            _CT.active, _CT.allowed = False, []
            if not ok and allowed:
                hook.refuse_resolution(f"a resolution that raised after {len(allowed)} allowed dlsym(s)")
        if len(allowed) != 1 or allowed[0][0] is not self or allowed[0][2] != name_or_ordinal:
            hook.refuse_resolution(f"{len(allowed)} allowed dlsym(s) for one resolution")
        _, libname, sym = allowed[0]
        func.__name__ = sym
        return refusing_foreign_function(func, f"{libname}.{sym}", hook.refuse_call)
    ctypes.CDLL.__getitem__ = getitem
    # fix round 5 (R-N2): the pre-hook raw aliases (ctypes.GetLastError, loader / CDLL caches, module-level pointers)
    # never saw the guarded __getitem__ - replace each with a refusing wrapper before any mutation / target import
    pre = wrap_preexisting_foreign_functions(
        dict(sys.modules), lambda func, label: refusing_foreign_function(func, label, hook.refuse_call))
    return {"sqlite": "guard-class connections with the barrier's authorizer",
            "ctypes": f"CDLL.__getitem__ guarded; {[list(x) for x in CTYPES_WRAPPED]} wrapped: declare yes, call "
                      "refused; the enumerated pre-hook aliases below replaced by refusing wrappers",
            "ctypes_preexisting_wrapped": pre}


# -------------------------------------------------------------------------------------------- validation (A3)
_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")


def split_lines(text: str) -> list:
    """Lines with their endings, split ONLY on \\r\\n, \\r and \\n - Python's tokenizer / co_positions line model
    (review M3: str.splitlines also splits on \\x0b \\x0c \\x1c-\\x1e \\x85 \\u2028 \\u2029)."""
    return _LINE.findall(text)


def validate_mutation(pre: str, post: str, start, end) -> tuple:
    """Exactly one change, inside the item's single-line span [start, end), adding no line. The same rule as the
    driver's localize (the parent re-verifies independently). Returns (ok, info)."""
    if pre == post:
        return False, {"why": "unchanged: no mutation installed"}
    lines = split_lines(pre)
    try:
        (sl, sc), (el, ec) = (int(start[0]), int(start[1])), (int(end[0]), int(end[1]))
    except (TypeError, ValueError, IndexError):
        return False, {"why": "span_invalid: unparseable"}
    if sl != el or not 1 <= sl <= len(lines) or not 0 <= sc < ec <= len(lines[sl - 1].rstrip("\r\n")):
        return False, {"why": f"span_invalid: {start}-{end}"}
    base = sum(len(x) for x in lines[:sl - 1])
    a, b = base + sc, base + ec
    n = min(len(pre), len(post))
    p = 0
    while p < n and pre[p] == post[p]:
        p += 1
    s = 0
    while s < n - p and pre[-1 - s] == post[-1 - s]:
        s += 1
    pre_end, post_end = len(pre) - s, len(post) - s
    info = {"pre_change": [p, pre_end], "pre_text": pre[p:pre_end], "post_text": post[p:post_end], "allowed": [a, b]}
    if not (a <= p and pre_end <= b):
        return False, dict(info, why="not_localized: the change is not inside the item's span")
    if any(c in info["post_text"] + info["pre_text"] for c in "\r\n"):
        return False, dict(info, why="newline: the change adds or removes a line")
    delta = len(post) - len(pre)
    if ec + delta <= sc:
        return False, dict(info, why="span_invalid: empty mutated span")
    return True, dict(info, post_span=[[sl, sc], [el, ec + delta]])


# -------------------------------------------------------------------------------------------- frame facts (P3)
def _position(code, lasti: int):
    """(positions at tb_lasti // 2, the dis instruction's positions at offset tb_lasti, index, count)."""
    try:
        pos = list(code.co_positions())
    except Exception:                            # noqa: BLE001 - recorded as missing, the gate fails closed
        return None, None, None, None
    idx = lasti // 2 if isinstance(lasti, int) and lasti >= 0 else None
    at = list(pos[idx]) if idx is not None and idx < len(pos) else None
    try:
        ins = [i for i in dis.get_instructions(code) if i.offset == lasti]
        via_dis = list(ins[0].positions) if ins and ins[0].positions is not None else None
    except Exception:                            # noqa: BLE001
        via_dis = None
    return at, via_dis, idx, len(pos)


def frame_facts(tb, copy_root: str) -> list:
    out = []
    here = os.path.normcase(os.path.realpath(__file__))
    croot = os.path.normcase(copy_root)
    while tb is not None:
        code = tb.tb_frame.f_code
        fn = code.co_filename
        real = os.path.realpath(fn) if fn and not fn.startswith("<") else fn
        rel = None
        if real and not real.startswith("<") and _inside(os.path.normcase(real), [croot]):
            rel = Path(real).relative_to(copy_root).as_posix()
        at, via_dis, idx, n = _position(code, tb.tb_lasti)
        out.append({"filename": fn, "realpath": real, "rel": rel,
                    "file_sha256": _sha_file(real) if real and not real.startswith("<") else None,
                    "co_name": code.co_name, "co_qualname": getattr(code, "co_qualname", None),
                    "co_firstlineno": code.co_firstlineno, "co_flags": code.co_flags, "tb_lineno": tb.tb_lineno,
                    "tb_lasti": tb.tb_lasti, "position_index": idx, "positions_count": n, "position": at,
                    "dis_position": via_dis, "positions_agree": at is not None and at == via_dis,
                    "is_probe": bool(real) and os.path.normcase(str(real)) == here})
        tb = tb.tb_next
    return out


def _copy_modules(copy_root: str) -> list:
    croot = os.path.normcase(copy_root)
    out = []
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if isinstance(f, str) and _inside(os.path.normcase(os.path.realpath(f)), [croot]):
            out.append(name)
    return sorted(out)


def _write(out: Path, rec: dict) -> None:
    """Write-once and atomic: the record is encoded first, written to <out>.tmp (mode x), then renamed into place
    (os.rename refuses an existing destination on Windows). A child killed mid-write leaves no final record."""
    text = json.dumps(rec, indent=1, sort_keys=True, default=repr)
    if out.exists():
        raise FileExistsError(str(out))
    tmp = out.with_name(out.name + ".tmp")
    with open(tmp, "x", encoding="utf-8") as fh:
        fh.write(text)
    os.rename(tmp, out)


def preimport_path(out: Path) -> Path:
    return out.with_name(out.stem + ".preimport.json")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cr_import_probe.py")
    ap.add_argument("--mode", required=True, choices=("control", "mutated"))
    ap.add_argument("--copy-root", required=True)
    ap.add_argument("--module-rel", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pin", required=True)
    ap.add_argument("--prefix", action="append", default=None)
    ap.add_argument("--protected", action="append", default=[])
    a = ap.parse_args(argv)
    out = Path(a.out)
    copy_root = os.path.realpath(a.copy_root)
    scratch = os.path.realpath(a.scratch)
    target_path = Path(copy_root) / a.module_rel
    rec = {"schema": SCHEMA, "mode": a.mode, "target": a.target, "module_rel": a.module_rel,
           "python": sys.version.split()[0], "executable": sys.executable, "probe_sha256": _sha_file(__file__),
           "pin": a.pin,
           "scope": "probe context matches the selected import path / environment facts of the guard's pytest child "
                    "(conftest sys.path prefix order, cwd, bound env); NOT identical pytest initialization; the probe "
                    "loads sqlite3, ctypes and ctypes.wintypes (and Cosmic Ray) before the target in both modes, so "
                    "the set of modules present before the import differs from collection",
           "a4": "re-applied under probe context: the original attempt's mutated bytes were never persisted, so no "
                 "byte-for-byte comparison with the original attempt is possible or claimed",
           "stage": "start"}
    refusals: list = []
    try:
        # ---- end of the bootstrap window: nothing from the copy may have been loaded; then the barrier
        copy_mods = _copy_modules(copy_root)
        rec["bootstrap"] = {"copy_paths_hidden_during_bootstrap": list(_HIDDEN), "copy_modules_before_hook": copy_mods,
                            "loaded_before_hook": ["stdlib", "cosmic_ray.mutating", "cosmic_ray.plugins",
                                                   "cosmic_ray.util", "stevedore", "parso", "sqlite3", "ctypes",
                                                   "ctypes.wintypes"],
                            "hook_installed_before_target": True}
        if copy_mods:
            raise Refusal("bootstrap_imported_copy_module", ",".join(copy_mods))
        rec["barrier"] = {"installed": False, "refusals": refusals, "scratch_roots": [copy_root, scratch],
                          "protected": sorted(str(p) for p in a.protected), "claim": CLAIM,
                          "installed_at": "before_mutation_and_import",
                          "events": {"refused_prefixes": list(REFUSED_PREFIXES), "mutating": sorted(MUTATING),
                                     "reading": sorted(READING), "safe": sorted(SAFE),
                                     "handled": ["open", "sqlite3.connect", "sqlite3.connect/handle (authorizer: "
                                                 "ATTACH / VACUUM INTO)", "_winapi.CreateFile", "mmap.__new__",
                                                 "ctypes.dlopen / ctypes.dlsym (CTYPES_ALLOWED only)"],
                                     "ctypes_allowed": [list(x) for x in sorted(CTYPES_ALLOWED)],
                                     "unlisted": "fail closed: path-like args inside scratch only, no int args"}}
        barrier = make_barrier([copy_root, scratch], refusals, protected=a.protected)
        sys.addaudithook(barrier)
        rec["barrier"]["guards"] = install_guards(barrier)            # fix round 3: before any mutation / import
        rec["barrier"]["installed"] = True
        rec["stage"] = "barrier"
        spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        rec["spec"] = spec
        rec["spec_sha256"] = _sha_file(a.spec)
        rec["cosmic_ray_version"] = metadata.version("cosmic-ray")
        if str(spec.get("module_path", "")).replace("\\", "/") != a.module_rel:
            raise Refusal("spec_mismatch", f"spec module_path is not {a.module_rel}")
        pre_bytes = target_path.read_bytes()
        pre_text = read_python_source(target_path)
        rec["source"] = {"pre_sha256": _sha_bytes(pre_bytes), "pre_text_sha256": _sha_bytes(pre_text.encode("utf-8"))}
        if rec["source"]["pre_sha256"] != a.pin:                         # source identity BEFORE anything else
            raise Refusal("pre_source_mismatch", "the copy's target is not the pinned source")
        rec["stage"] = "context"
        if a.mode == "mutated":
            try:
                op_cls = cr_plugins.get_operator(spec["operator"])
                operator = op_cls(**(spec.get("operator_args") or {}))
                rec["operator"] = {"name": spec["operator"], "class": f"{op_cls.__module__}.{op_cls.__qualname__}",
                                   "operator_args": spec.get("operator_args") or {}, "occurrence": spec["occurrence"]}
                original, mutated = cr_mutating.apply_mutation(target_path, operator, int(spec["occurrence"]))
            except BarrierRefusal:
                raise
            except Exception as exc:                                     # noqa: BLE001
                raise Refusal("mutation_api_exception", f"{type(exc).__name__}: {exc}") from None
            post_bytes = target_path.read_bytes()
            post_text = read_python_source(target_path)
            rec["mutation"] = {"applied": mutated is not None,
                               "cr_original_equals_pre": original == pre_text,
                               "post_text_equals_cr_mutated": mutated is not None and post_text == mutated,
                               "post_sha256": _sha_bytes(post_bytes),
                               "post_text_sha256": _sha_bytes(post_text.encode("utf-8")),
                               "diff": "".join(difflib.unified_diff(
                                   pre_text.splitlines(True), post_text.splitlines(True), "pre", "post"))[:8000]}
            if mutated is None:
                raise Refusal("mutation_not_installed", "the operator / occurrence produced no mutation")
            ok, info = validate_mutation(pre_text, post_text, spec["start"], spec["end"])
            if not (rec["mutation"]["cr_original_equals_pre"] and rec["mutation"]["post_text_equals_cr_mutated"]):
                ok, info = False, dict(info, why="unexplained: the file is not Cosmic Ray's mutated text")
            rec["validation"] = {"ok": ok, **{k: info[k] for k in ("why", "post_span", "pre_change", "allowed",
                                                                   "pre_text", "post_text") if k in info}}
            _write(preimport_path(out), {k: rec[k] for k in ("schema", "mode", "pin", "spec_sha256", "source",
                                                             "mutation", "validation", "operator")})
            if not ok:
                raise Refusal(info["why"].split(":")[0], info["why"])
            rec["stage"] = "validated"
        else:
            rec["source"]["unchanged"] = _sha_file(target_path) == rec["source"]["pre_sha256"]
        # ---- A1: the collection-time import path, restored + the conftest-order prefix; then the import
        sys.path[:] = list(_SAVED_PATH)
        here = os.path.normcase(os.path.realpath(os.path.dirname(os.path.abspath(__file__))))
        sys.path[:] = [p for p in sys.path if os.path.normcase(os.path.realpath(p or ".")) != here]
        for rel in reversed(a.prefix or DEFAULT_PREFIX):
            sys.path.insert(0, str((Path(copy_root) / rel).resolve()))
        os.chdir(copy_root)
        rec["sys_path_prefix"] = sys.path[:len(a.prefix or DEFAULT_PREFIX)]
        rec["sys_path_sha256"] = _sha_bytes(json.dumps(sys.path).encode("utf-8"))
        rec["env_bound"] = {k: v for k, v in sorted(os.environ.items())       # the bound set only, no credentials
                            if k.upper().startswith(("PYTHON", "PYTEST", "HYPOTHESIS", "COV", "CR_GUARD"))
                            or k.upper() == "S1_HYPOTHESIS_ROOT"}
        rec["copy_modules_before_import"] = _copy_modules(copy_root)
        mods = sorted(sys.modules)
        rec["modules_before_import"] = {"count": len(mods), "sha256": _sha_bytes(json.dumps(mods).encode("utf-8"))}
        rec["stage"] = "import"
    except Refusal as r:
        rec["stage"] = "refused"
        rec["refusal"] = {"reason": r.reason, "detail": r.detail[:2000]}
        _write(out, rec)
        return 0
    except BaseException as exc:                # noqa: BLE001 - a setup failure / barrier refusal: never an import
        rec["stage_error"] = {"stage": rec.get("stage"), "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                              "message": str(exc)[:2000]}
        _write(out, rec)
        return 0
    try:
        mod = importlib.import_module(a.target)
    except BaseException as exc:                # noqa: BLE001 - the import's exception IS the evidence
        rec["imported"] = False
        rec["exception"] = {"module": type(exc).__module__, "qualname": type(exc).__qualname__,
                            "frames": frame_facts(exc.__traceback__, copy_root),
                            "syntax": ({"filename": getattr(exc, "filename", None), "lineno": getattr(exc, "lineno", None),
                                        "offset": getattr(exc, "offset", None)}
                                       if isinstance(exc, SyntaxError) else None),
                            "cause": type(exc.__cause__).__qualname__ if exc.__cause__ is not None else None,
                            "context": type(exc.__context__).__qualname__ if exc.__context__ is not None else None,
                            "rendered_secondary": "".join(traceback.format_exception(exc))[-4000:]}
        rec["stage"] = "done"
        _write(out, rec)
        return 0
    f = getattr(mod, "__file__", None)
    real = os.path.realpath(f) if isinstance(f, str) else None
    rec["imported"] = True
    rec["imported_file"] = {"realpath": real,
                            "rel": (Path(real).relative_to(copy_root).as_posix()
                                    if real and _inside(os.path.normcase(real), [os.path.normcase(copy_root)])
                                    else None),
                            "sha256": _sha_file(real) if real else None}
    rec["stage"] = "done"
    _write(out, rec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
