"""
Trigger spacebar presses at absolute timestamps (milliseconds from start).

Usage:
  python spacebar_timer.py
  python spacebar_timer.py --dry-run
  python spacebar_timer.py --timestamps 100,250,500 --countdown 3
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Callable, Iterable, List


def parse_timestamps(raw: str) -> List[float]:
    """Parse a comma-separated list of millisecond timestamps."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("timestamp list is empty")
    values = [float(p) for p in parts]
    if any(v < 0 for v in values):
        raise ValueError("timestamps must be >= 0")
    return sorted(values)


def make_spacebar_presser(dry_run: bool) -> Callable[[], None]:
    """Return a callable that presses spacebar (or logs in dry-run mode)."""
    if dry_run:
        def press() -> None:
            print(f"  [dry-run] SPACE @ {time.perf_counter():.6f}s (perf_counter)")

        return press

    try:
        from pynput.keyboard import Controller, Key
    except ImportError as exc:
        raise SystemExit(
            "pynput is required for real keypresses. "
            "Install it in the active uv environment with: uv pip install pynput\n"
            "or run with --dry-run to test timing without sending keys."
        ) from exc

    keyboard = Controller()

    def press() -> None:
        keyboard.press(Key.space)
        keyboard.release(Key.space)

    return press


def run_timed_spacebars(
    timestamps_ms: Iterable[float],
    press: Callable[[], None],
    countdown_s: float = 0.0,
) -> List[float]:
    """
    Start a timer and press at each timestamp (ms from t0).

    Returns the actual elapsed times (ms) when each press happened.
    """
    stamps = sorted(float(t) for t in timestamps_ms)
    actual_ms: List[float] = []

    if countdown_s > 0:
        print(f"Starting in {countdown_s:.1f}s…")
        end = time.perf_counter() + countdown_s
        while True:
            remaining = end - time.perf_counter()
            if remaining <= 0:
                break
            # Print whole-second ticks without busy-waiting the whole countdown.
            time.sleep(min(0.05, remaining))

    print(f"Timer started. {len(stamps)} spacebar event(s).")
    t0 = time.perf_counter()

    for target_ms in stamps:
        target_s = target_ms / 1000.0
        # Sleep until close, then spin for the last ~1.5ms for tighter timing.
        while True:
            elapsed = time.perf_counter() - t0
            remaining = target_s - elapsed
            if remaining <= 0:
                break
            if remaining > 0.002:
                time.sleep(remaining - 0.0015)

        press()
        hit_ms = (time.perf_counter() - t0) * 1000.0
        actual_ms.append(hit_ms)
        err = hit_ms - target_ms
        print(f"  space @ {target_ms:8.1f} ms  (actual {hit_ms:8.2f} ms, err {err:+.2f} ms)")

    total = (time.perf_counter() - t0) * 1000.0
    print(f"Done in {total:.2f} ms.")
    return actual_ms


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Press spacebar at given millisecond timestamps.")
    p.add_argument(
        "--timestamps",
        "-t",
        default="500,1000,1500,2000",
        help="Comma-separated ms timestamps from start (default: 500,1000,1500,2000)",
    )
    p.add_argument(
        "--countdown",
        "-c",
        type=float,
        default=2.0,
        help="Seconds to wait before starting the timer (default: 2)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print events instead of sending real spacebar input",
    )
    return p


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        timestamps = parse_timestamps(args.timestamps)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    press = make_spacebar_presser(dry_run=args.dry_run)
    run_timed_spacebars(timestamps, press=press, countdown_s=args.countdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
