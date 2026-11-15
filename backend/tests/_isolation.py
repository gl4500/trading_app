# tests._isolation -- throwaway-database bootstrap (finding X-14)
#
# Point every test run at a throwaway database before anything imports config.
# Several agent tests reach database.save_token_log / update_price_snapshot
# through real code paths; without this they wrote into the live
# backend/trading.db. Always overridden (never setdefault), so a DATABASE_URL in
# the shell or .env cannot aim the suite at real data.
#
# Import it ONLY by its package-qualified name (`import tests._isolation`);
# a bare `_isolation` alias would create a second module object and a second
# temp dir. Python caches the module, so the body below runs once per process.
#
# Init-time safety check: if `config` or `database` was imported before this
# bootstrap ran and is bound to a path outside the temp dir, changing
# os.environ cannot repair it, so we refuse (never reload or patch). This
# covers initialization only; later fixture overrides of DB_PATH stay legal.
import atexit
import os
import shutil
import sys
import tempfile

_TEST_DB_DIR = tempfile.mkdtemp(prefix="trading_app_tests_")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(path: str, directory: str) -> bool:
    return _norm(path).startswith(_norm(directory) + os.sep)


def _refuse_unsafe_preimports() -> None:
    cfg_mod = sys.modules.get("config")
    db_mod = sys.modules.get("database")
    bound = []
    cfg_obj = getattr(cfg_mod, "config", None)
    if cfg_obj is not None and hasattr(cfg_obj, "DATABASE_URL"):
        bound.append(("config.config.DATABASE_URL", cfg_obj.DATABASE_URL))
    if db_mod is not None and hasattr(db_mod, "DB_PATH"):
        bound.append(("database.DB_PATH", db_mod.DB_PATH))
    for name, value in bound:
        if not _inside(str(value), _TEST_DB_DIR):
            shutil.rmtree(_TEST_DB_DIR, True)
            raise RuntimeError(
                "%s was imported before tests._isolation and is bound to %r, "
                "outside the throwaway test dir; import tests._isolation before "
                "any backend module (config/database are never reloaded or patched)."
                % (name, value)
            )


_refuse_unsafe_preimports()
os.environ["DATABASE_URL"] = os.path.join(_TEST_DB_DIR, "trading.db")
atexit.register(shutil.rmtree, _TEST_DB_DIR, True)
