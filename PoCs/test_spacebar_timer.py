"""Tests for spacebar_timer scheduling (no real keypresses)."""

from __future__ import annotations

import time
import unittest

from spacebar_timer import parse_timestamps, run_timed_spacebars


class ParseTimestampsTests(unittest.TestCase):
    def test_parses_and_sorts(self) -> None:
        self.assertEqual(parse_timestamps("300, 100, 200"), [100.0, 200.0, 300.0])

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            parse_timestamps("")

    def test_rejects_negative(self) -> None:
        with self.assertRaises(ValueError):
            parse_timestamps("10,-1")


class TimingTests(unittest.TestCase):
    def test_hits_within_tolerance(self) -> None:
        targets = [50.0, 120.0, 200.0]
        hits: list[float] = []

        def press() -> None:
            hits.append(time.perf_counter())

        t0 = time.perf_counter()
        # Capture start inside run_timed_spacebars; compare via returned actual_ms.
        actual = run_timed_spacebars(targets, press=press, countdown_s=0)

        self.assertEqual(len(actual), len(targets))
        self.assertEqual(len(hits), len(targets))

        for target, actual_ms in zip(targets, actual):
            # Windows scheduling jitter; keep a generous but useful bound.
            self.assertLessEqual(
                abs(actual_ms - target),
                25.0,
                msg=f"target={target} actual={actual_ms}",
            )

        # Monotonic press order
        self.assertEqual(hits, sorted(hits))
        # Rough wall duration sanity
        self.assertLess(time.perf_counter() - t0, 1.0)


if __name__ == "__main__":
    unittest.main()
