import unittest
import tempfile
from pathlib import Path
from datetime import date
import pandas as pd

from backtest.bars_provider import BarsProvider


def _write_parquet(dir_: Path, symbol: str, days, prices, volumes):
    ts = [pd.Timestamp(d).value // 10**9 for d in days]  # unix seconds
    pd.DataFrame({"snapshot_ts": ts, "price": prices, "volume": volumes}).to_parquet(
        dir_ / f"{symbol}.parquet")


class TestBarsProvider(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
        _write_parquet(self.tmp, "AAA", days, [10.0, 11.0, 12.0, 13.0], [100, 100, 100, 100])
        _write_parquet(self.tmp, "BBB", ["2026-01-05", "2026-01-08"], [50.0, 55.0], [9, 9])
        self.bp = BarsProvider(self.tmp)

    def test_bars_asof_never_returns_future_rows(self):
        df = self.bp.bars_asof("AAA", date(2026, 1, 6))
        self.assertIsNotNone(df)
        self.assertEqual(list(df.columns), ["close", "volume"])
        self.assertLessEqual(df.index.max().date(), date(2026, 1, 6))
        self.assertEqual(len(df), 3)  # 01-02, 01-05, 01-06 only
        self.assertEqual(float(df["close"].iloc[-1]), 12.0)

    def test_close_asof_is_last_on_or_before(self):
        self.assertEqual(self.bp.close_asof("AAA", date(2026, 1, 6)), 12.0)
        self.assertEqual(self.bp.close_asof("AAA", date(2026, 1, 4)), 10.0)  # last <= date
        self.assertIsNone(self.bp.close_asof("AAA", date(2025, 12, 31)))

    def test_missing_symbol_returns_none(self):
        self.assertIsNone(self.bp.bars_asof("ZZZ", date(2026, 1, 6)))
        self.assertIsNone(self.bp.close_asof("ZZZ", date(2026, 1, 6)))

    def test_trading_days_is_sorted_union_in_range(self):
        days = self.bp.trading_days(date(2026, 1, 5), date(2026, 1, 7))
        self.assertEqual(days, [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)])
