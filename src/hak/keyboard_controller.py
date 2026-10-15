from __future__ import annotations

import time
import threading
from typing import Callable, Iterable, List, Optional
from dashboard.schemas import JumpTiming

try:
    from pynput.keyboard import Controller, Key
except ImportError:
    Controller = None
    Key = None


class KeyboardController:
    """
    High-precision keyboard input controller for Geometry Dash spacebar taps.
    Uses hybrid sleep + spinning for sub-millisecond dispatch accuracy.
    Supports dry-run and cancellation upon crash.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._keyboard = Controller() if (Controller and not dry_run) else None
        self._cancel_event = threading.Event()
        self._active_thread: Optional[threading.Thread] = None

    def press_space(self, hold_seconds: float = 0.045) -> None:
        """Execute a physical spacebar press and release."""
        if self.dry_run or not self._keyboard:
            return

        try:
            self._keyboard.press(Key.space)
            if hold_seconds > 0:
                time.sleep(hold_seconds)
            self._keyboard.release(Key.space)
        except Exception as exc:
            print(f"[KeyboardController] Press error: {exc}")

    def execute_jump_sequence_async(
        self,
        jump_timings: List[float],
        start_time: float,
        on_jump_executed: Optional[Callable[[int, float, float, float], None]] = None,
    ) -> threading.Event:
        """
        Execute scheduled jumps in a dedicated high-precision worker thread.

        Parameters:
        - jump_timings: List of jump timestamps in seconds from start_time.
        - start_time: Base reference timestamp (perf_counter).
        - on_jump_executed: Callback(jump_idx, planned_time, actual_time, delta_ms).

        Returns:
        - An Event that is set when playback is cancelled or finished.
        """
        self.abort_sequence()
        self._cancel_event.clear()

        def _worker():
            stamps = sorted(float(t) for t in jump_timings)
            for idx, target_s in enumerate(stamps):
                if self._cancel_event.is_set():
                    break

                # Sleep until ~2ms before target, then spin for precision
                while not self._cancel_event.is_set():
                    elapsed = time.perf_counter() - start_time
                    remaining = target_s - elapsed
                    if remaining <= 0:
                        break
                    if remaining > 0.002:
                        time.sleep(remaining - 0.0015)

                if self._cancel_event.is_set():
                    break

                # Scheduled jumps are taps, not held inputs. A short pulse
                # keeps closely spaced jump/orb inputs distinguishable.
                self.press_space(hold_seconds=0.01)
                actual_s = time.perf_counter() - start_time
                delta_ms = (actual_s - target_s) * 1000.0

                if on_jump_executed:
                    try:
                        on_jump_executed(idx, target_s, actual_s, delta_ms)
                    except Exception:
                        pass

        self._active_thread = threading.Thread(
            target=_worker, daemon=True, name="JumpPlaybackWorker"
        )
        self._active_thread.start()
        return self._cancel_event

    def abort_sequence(self) -> None:
        """Immediately abort any active playback sequence (e.g. upon crash)."""
        self._cancel_event.set()
        if self._active_thread and self._active_thread.is_alive():
            self._active_thread.join(timeout=0.2)
        self._active_thread = None
