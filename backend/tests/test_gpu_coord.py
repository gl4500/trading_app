"""Tests for data/gpu_coord.py — Backlog 0.7 GPU/Ollama coordination."""
import asyncio
import json
import os
import tempfile
import time
import unittest

from data.gpu_coord import OllamaCoordinator, STALE_AFTER_SECS


class TestOllamaCoordinatorPerAppLock(unittest.IsolatedAsyncioTestCase):
    """Layer 1 — per-process asyncio.Lock serializes Ollama calls within one app."""

    async def test_concurrent_acquire_serializes(self):
        """Two coroutines both call acquire() — must run one at a time."""
        with tempfile.TemporaryDirectory() as td:
            coord_path = os.path.join(td, "state.json")
            coord = OllamaCoordinator(app_name="trading_app", coord_path=coord_path)
            order = []

            async def worker(label: str, work_secs: float):
                async with coord.acquire(expected_ms=int(work_secs * 1000)):
                    order.append(f"start:{label}")
                    await asyncio.sleep(work_secs)
                    order.append(f"end:{label}")

            await asyncio.gather(worker("A", 0.05), worker("B", 0.05))
            # Strict serialization: A's end must come before B's start (or vice versa)
            self.assertEqual(len(order), 4)
            # Whichever started first must end before the other starts
            first = order[0].split(":", 1)[1]
            second = order[2].split(":", 1)[1]
            self.assertEqual(order[0], f"start:{first}")
            self.assertEqual(order[1], f"end:{first}")
            self.assertEqual(order[2], f"start:{second}")
            self.assertEqual(order[3], f"end:{second}")


class TestOllamaCoordinatorExposure(unittest.TestCase):
    """update_exposure writes a clean record into the coord file."""

    def test_update_writes_app_record(self):
        with tempfile.TemporaryDirectory() as td:
            coord_path = os.path.join(td, "state.json")
            coord = OllamaCoordinator(app_name="trading_app", coord_path=coord_path)
            coord.update_exposure(12_500.50)

            with open(coord_path) as f:
                state = json.load(f)
            self.assertIn("trading_app", state)
            self.assertAlmostEqual(state["trading_app"]["exposure_usd"], 12_500.50)
            self.assertGreater(state["trading_app"]["updated_at"], time.time() - 5)

    def test_update_preserves_other_apps(self):
        """Updating trading_app must not erase polymarket_app's record."""
        with tempfile.TemporaryDirectory() as td:
            coord_path = os.path.join(td, "state.json")
            os.makedirs(os.path.dirname(coord_path), exist_ok=True)
            with open(coord_path, "w") as f:
                json.dump({
                    "polymarket_app": {"exposure_usd": 9_999.0, "updated_at": time.time()},
                }, f)
            coord = OllamaCoordinator(app_name="trading_app", coord_path=coord_path)
            coord.update_exposure(2_000.0)
            with open(coord_path) as f:
                state = json.load(f)
            self.assertIn("trading_app", state)
            self.assertIn("polymarket_app", state)
            self.assertAlmostEqual(state["polymarket_app"]["exposure_usd"], 9_999.0)

    def test_update_failure_does_not_raise(self):
        """A path the coordinator can't write to must be a soft failure."""
        # Use a path we can't create — e.g., a file as the parent directory.
        with tempfile.NamedTemporaryFile(delete=False, suffix=".file") as f:
            blocking_file = f.name
        try:
            bad_path = os.path.join(blocking_file, "state.json")
            coord = OllamaCoordinator(app_name="trading_app", coord_path=bad_path)
            # Must not raise
            coord.update_exposure(100.0)
        finally:
            os.unlink(blocking_file)


class TestOllamaCoordinatorStaleEntries(unittest.TestCase):
    """Stale entries (>STALE_AFTER_SECS) must be ignored in priority calc."""

    def test_stale_other_app_treated_as_zero(self):
        with tempfile.TemporaryDirectory() as td:
            coord_path = os.path.join(td, "state.json")
            os.makedirs(os.path.dirname(coord_path), exist_ok=True)
            # polymarket_app last updated 2 minutes ago — well past STALE_AFTER_SECS=60
            with open(coord_path, "w") as f:
                json.dump({
                    "polymarket_app": {
                        "exposure_usd": 50_000.0,
                        "updated_at":   time.time() - (STALE_AFTER_SECS + 60),
                    },
                }, f)
            coord = OllamaCoordinator(app_name="trading_app", coord_path=coord_path)
            self.assertEqual(coord._other_app_priority_exposure(), 0.0)

    def test_fresh_other_app_counts(self):
        with tempfile.TemporaryDirectory() as td:
            coord_path = os.path.join(td, "state.json")
            os.makedirs(os.path.dirname(coord_path), exist_ok=True)
            with open(coord_path, "w") as f:
                json.dump({
                    "polymarket_app": {
                        "exposure_usd": 50_000.0,
                        "updated_at":   time.time() - 5,  # 5s ago — fresh
                    },
                }, f)
            coord = OllamaCoordinator(app_name="trading_app", coord_path=coord_path)
            self.assertAlmostEqual(coord._other_app_priority_exposure(), 50_000.0)


class TestOllamaCoordinatorAcquireBypassesWhenWeWin(unittest.IsolatedAsyncioTestCase):
    """When our exposure >= other's, acquire() returns immediately (no wait)."""

    async def test_higher_exposure_fires_immediately(self):
        with tempfile.TemporaryDirectory() as td:
            coord_path = os.path.join(td, "state.json")
            os.makedirs(os.path.dirname(coord_path), exist_ok=True)
            with open(coord_path, "w") as f:
                json.dump({
                    "polymarket_app": {"exposure_usd": 1_000.0, "updated_at": time.time()},
                }, f)
            coord = OllamaCoordinator(app_name="trading_app", coord_path=coord_path)
            coord.update_exposure(50_000.0)  # we win priority

            t0 = time.monotonic()
            async with coord.acquire(expected_ms=1_000):
                pass
            elapsed = time.monotonic() - t0
            # Should be near-instant (< 200ms is generous)
            self.assertLess(elapsed, 0.2)

    async def test_lower_exposure_waits_then_fires(self):
        """When other app has more exposure and never updates, we wait up to MAX_WAIT_SECS."""
        with tempfile.TemporaryDirectory() as td:
            coord_path = os.path.join(td, "state.json")
            os.makedirs(os.path.dirname(coord_path), exist_ok=True)
            with open(coord_path, "w") as f:
                json.dump({
                    "polymarket_app": {"exposure_usd": 50_000.0, "updated_at": time.time()},
                }, f)
            coord = OllamaCoordinator(app_name="trading_app", coord_path=coord_path)
            coord.update_exposure(1_000.0)   # we lose priority

            # Patch MAX_WAIT_SECS down so the test runs in seconds, not 10s
            from data import gpu_coord as _gc
            old_max, old_poll = _gc.MAX_WAIT_SECS, _gc.POLL_WAIT_SECS
            _gc.MAX_WAIT_SECS = 0.5
            _gc.POLL_WAIT_SECS = 0.1
            try:
                t0 = time.monotonic()
                async with coord.acquire(expected_ms=1_000):
                    pass
                elapsed = time.monotonic() - t0
            finally:
                _gc.MAX_WAIT_SECS, _gc.POLL_WAIT_SECS = old_max, old_poll
            # Waited ~0.5s before firing, but did fire (didn't hang)
            self.assertGreaterEqual(elapsed, 0.4)
            self.assertLess(elapsed, 1.0)


class TestOllamaCoordinatorMissingFile(unittest.IsolatedAsyncioTestCase):
    """Coord file missing or unreadable → fall back to lock-only behavior."""

    async def test_missing_coord_file_does_not_block(self):
        with tempfile.TemporaryDirectory() as td:
            coord_path = os.path.join(td, "missing", "state.json")  # parent doesn't exist
            coord = OllamaCoordinator(app_name="trading_app", coord_path=coord_path)
            # No update_exposure call → no file written; acquire must still work
            t0 = time.monotonic()
            async with coord.acquire(expected_ms=100):
                pass
            self.assertLess(time.monotonic() - t0, 0.2)


if __name__ == "__main__":
    unittest.main()
