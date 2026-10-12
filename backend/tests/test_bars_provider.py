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


class TestBarsProviderTradingDaysOnly(unittest.TestCase):
    """C-32: snapshots recorded on a weekend (e.g. a live app running on a Sunday
    with a stale or unadjusted quote) must not become daily bars or trading days.
    BKNG on Sunday 2026-04-05 read $4,192.93 between ~$168 closes and the harness
    traded on that fake bar."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Thu 04-02, Fri 04-03, Sun 04-05 (stale unadjusted quote), Mon 04-06
        _write_parquet(self.tmp, "BKNG",
                       ["2026-04-02", "2026-04-03", "2026-04-05", "2026-04-06"],
                       [167.77, 168.10, 4192.93, 170.57], [100, 100, 100, 100])
        self.bp = BarsProvider(self.tmp)

    def test_weekend_snapshot_is_not_a_bar(self):
        bars = self.bp.bars_asof("BKNG", date(2026, 4, 6))
        self.assertNotIn(pd.Timestamp("2026-04-05"), bars.index)
        self.assertEqual(self.bp.close_asof("BKNG", date(2026, 4, 5)), 168.10,
                         "as of Sunday the last real close is Friday's")

    def test_weekend_is_not_a_trading_day(self):
        days = self.bp.trading_days(date(2026, 4, 1), date(2026, 4, 7))
        self.assertNotIn(date(2026, 4, 5), days)
        self.assertEqual(days, [date(2026, 4, 2), date(2026, 4, 3), date(2026, 4, 6)])
