import pytest
from datetime import datetime, timezone
import s1_common as c


def test_aware_parses_both_utc_spellings_to_the_same_instant():
    a = c.aware("2026-10-15T14:30:00.123456+00:00")
    b = c.aware("2026-10-15T14:30:00.123456Z")
    assert a == b and a.tzinfo is not None


def test_aware_reads_naive_as_utc_and_rejects_garbage():
    assert c.aware("2026-10-15 14:30:00") == datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        c.aware("15/10/2026 2:30pm")


def test_pinned_core_and_p13():
    p = c.p13()
    assert (p["id"], p["hard"], p["trail"], p["target"], p["time"]) == ("P13", 0.08, 0.12, None, None)


def test_pinned_loader_refuses_a_changed_file(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="hash"):
        c.load_pinned("m_pinned", f, "0" * 64)


def test_canonical_is_order_independent():
    assert c.canonical({"b": 1, "a": [2, 1]}) == c.canonical({"a": [2, 1], "b": 1})


def test_fixture_has_the_real_schema(ledger):
    import sqlite3
    con = sqlite3.connect(ledger.path)
    cols = {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")] for t in ("agents", "trades", "portfolios")}
    assert cols["trades"] == ["id", "agent_id", "symbol", "action", "shares", "price", "timestamp", "reasoning", "pnl"]
    assert cols["portfolios"] == ["id", "agent_id", "symbol", "shares", "avg_cost", "current_value", "unrealized_pnl"]
