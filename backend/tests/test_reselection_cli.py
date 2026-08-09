import unittest
import tempfile
import sys
from pathlib import Path
import pandas as pd


def _write(dir_, sym, days, prices):
    ts = [pd.Timestamp(d).value // 10**9 for d in days]
    pd.DataFrame({"snapshot_ts": ts, "price": prices, "volume": [1000] * len(days)}).to_parquet(
        dir_ / f"{sym}.parquet")


class TestReselectionCLI(unittest.TestCase):
    def test_cli_writes_report_for_two_variants(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
        import reselection_backtest as cli
        tmp = Path(tempfile.mkdtemp())
        hist = tmp / "history"; hist.mkdir()
        logs = tmp / "logs"; logs.mkdir()
        days = [f"2026-04-{d:02d}" for d in range(1, 29)]
        _write(hist, "AAA", days, [100 + i for i in range(len(days))])
        rc = cli.main([
            "--history", str(hist), "--logs", str(logs),
            "--universe", "AAA", "--start", "2026-04-01", "--end", "2026-04-28",
            "--variant", "baseline=HIST_SEASONAL_WEIGHT=0.20",
            "--variant", "no_seasonal=HIST_SEASONAL_WEIGHT=0.0",
        ])
        self.assertEqual(rc, 0)
        reports = list(logs.glob("reselection_*.md"))
        self.assertEqual(len(reports), 1)
        text = reports[0].read_text()
        self.assertIn("baseline", text)
        self.assertIn("no_seasonal", text)
