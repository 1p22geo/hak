from __future__ import annotations

import os
import time
import threading
from typing import Optional, List, Dict, Any, Callable

from dashboard.schemas import (
    SessionState,
    AttemptState,
    GenerationRecord,
    TelemetryEvent,
    ConnectionState,
    AgentStatus,
    AttemptOutcome,
    EventSeverity,
    JumpTiming,
    current_iso_time,
)
from dashboard.telemetry import TelemetryStore
from src.hak.ocr_reader import ScreenReader
from src.hak.keyboard_controller import KeyboardController
from src.hak.rl_optimizer import (
    RLTASOptimizer,
    CandidateRun,
    STEREO_MADNESS_SEED_JUMPS,
    STEREO_MADNESS_TOTAL_SECONDS,
)


class TASEngine:
    """
    Main Geometry Dash TAS Orchestrator (Prefix-Preserving & Zero-Desync).

    Guarantees:
    1. Immutable Proven Path: Never alters, jitters, or deletes jumps that cleared
       previous obstacles. Repeats the exact winning sequence on every run.
    2. Reliable Jump Dispatch: Never aborts scheduled jumps due to single-frame OCR glitches.
    3. True-Zero Respawn Synchronization: Aligns t0 with in-game 0.00s timer to prevent
       premature or missed jump executions.
    4. Improvement Tracking: Locks new frontier jumps whenever survival time improves.
    """

    def __init__(
        self,
        store: TelemetryStore,
        screen_reader: Optional[ScreenReader] = None,
        keyboard_controller: Optional[KeyboardController] = None,
        optimizer: Optional[RLTASOptimizer] = None,
        dry_run: bool = False,
        mock_mode: bool = False,
        seed_with_stereo_madness: bool = False,
        poll_interval: float = 0.04,  # 40ms polling (~25 FPS)
    ):
        self.store = store
        self.dry_run = dry_run
        self.mock_mode = mock_mode
        self.poll_interval = poll_interval

        # Core sub-modules
        self.screen_reader = screen_reader or ScreenReader(mock_mode=mock_mode)
        self.keyboard = keyboard_controller or KeyboardController(dry_run=dry_run)
        seed_jumps = STEREO_MADNESS_SEED_JUMPS if seed_with_stereo_madness else []
        self.optimizer = optimizer or RLTASOptimizer(seed_jumps=seed_jumps)

        # Threading and control
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

        # State tracking
        self.countdown_remaining: float = 0.0
        self.is_counting_down: bool = False
        self.last_crash_time: Optional[float] = None
        self.current_candidate: Optional[CandidateRun] = None
        self.active_jumps_executed: int = 0
        self.active_jump_timings: List[JumpTiming] = []
        self.latest_ocr_data: Dict[str, Any] = {
            "percentage": 0.0,
            "attempt": 1,
            "time": 0.0,
            "tap_count": 0,
        }
        self.latest_annotated_frame: bytes = b""

        self._sync_session_init()

    def _sync_session_init(self) -> None:
        self.store.update_session(
            session_id=f"tas_gd_{int(time.time())}",
            project_name="Geometry Dash AI / Stereo Madness TAS",
            connection_state=ConnectionState.CONNECTED.value if not self.mock_mode else ConnectionState.SIMULATED.value,
            agent_status=AgentStatus.IDLE.value,
            is_simulated=self.mock_mode,
            session_start_time=current_iso_time(),
            current_generation=self.optimizer.current_generation,
            current_attempt=0,
            total_attempts=0,
            successful_completions=0,
            best_completion=0.0,
            best_fitness=0.0,
        )

    def start(self, countdown_seconds: float = 10.0) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._paused = False
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(countdown_seconds,),
                daemon=True,
                name="TASEngineThread",
            )
            self._thread.start()

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            self.keyboard.abort_sequence()
            self.store.update_session(agent_status=AgentStatus.PAUSED.value)
            self.store.add_event(
                TelemetryEvent(
                    timestamp=current_iso_time(),
                    category="agent",
                    message="TAS agent paused by operator",
                    severity=EventSeverity.WARNING.value,
                )
            )

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self.store.update_session(agent_status=AgentStatus.RUNNING.value)
            self.store.add_event(
                TelemetryEvent(
                    timestamp=current_iso_time(),
                    category="agent",
                    message="TAS agent resumed",
                    severity=EventSeverity.INFO.value,
                )
            )

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._paused = False
            self._stop_event.set()
            self.keyboard.abort_sequence()
            self.store.update_session(agent_status=AgentStatus.IDLE.value)
            self.store.add_event(
                TelemetryEvent(
                    timestamp=current_iso_time(),
                    category="agent",
                    message="TAS agent halted",
                    severity=EventSeverity.WARNING.value,
                )
            )
        if self._thread and self._thread.is_alive() and threading.current_thread() != self._thread:
            self._thread.join(timeout=1.0)
        self._thread = None

    def reset_best(self, seed: Optional[List[float]] = None) -> None:
        with self._lock:
            self.optimizer.reset_best_to_baseline(seed)
            self.store.update_session(
                best_completion=0.0,
                best_fitness=0.0,
                reset_best=True,
            )
            self.store.add_event(
                TelemetryEvent(
                    timestamp=current_iso_time(),
                    category="agent",
                    message="Elite baseline sequence reset",
                    severity=EventSeverity.INFO.value,
                )
            )

    def _execute_countdown(self, countdown_seconds: float) -> bool:
        if countdown_seconds <= 0:
            return True

        self.is_counting_down = True
        self.countdown_remaining = countdown_seconds
        self.store.update_session(agent_status=AgentStatus.INITIALIZING.value)

        self.store.add_event(
            TelemetryEvent(
                timestamp=current_iso_time(),
                category="system",
                message=f"Starting in {countdown_seconds:.0f}s... Focus Geometry Dash and enter Stereo Madness!",
                severity=EventSeverity.INFO.value,
            )
        )
        print("\n" + "=" * 65)
        print(f"  [COUNTDOWN] Switch to Geometry Dash! Starting in {countdown_seconds:.0f}s...")
        print("=" * 65)

        end_time = time.perf_counter() + countdown_seconds
        last_printed_sec = int(countdown_seconds) + 1

        while not self._stop_event.is_set():
            remaining = end_time - time.perf_counter()
            self.countdown_remaining = max(0.0, remaining)

            self.store.update_session(
                agent_status=f"Countdown: {int(remaining) + 1}s" if remaining > 0 else AgentStatus.RUNNING.value
            )

            current_sec = int(remaining) + 1
            if current_sec < last_printed_sec and remaining > 0:
                print(f"  • Starting in {current_sec}s... Focus Geometry Dash window!")
                last_printed_sec = current_sec

            if remaining <= 0:
                break
            time.sleep(0.1)

        self.is_counting_down = False
        if self._stop_event.is_set():
            return False

        print("  • Countdown complete! TAS RL Agent is now ACTIVE.\n" + "=" * 65 + "\n")
        self.store.update_session(agent_status=AgentStatus.RUNNING.value)
        return True

    def _wait_for_level_respawn(self) -> float:
        """
        Wait for death screen to finish and calibrate t0 to exact level start.
        Prevents starting in the middle of a desynchronized run.
        """
        if self.mock_mode:
            time.sleep(0.05)
            return time.perf_counter()

        wait_start = time.perf_counter()
        tapped_retry = False
        last_seen_high_time = 0.0

        while not self._stop_event.is_set():
            elapsed_waiting = time.perf_counter() - wait_start

            try:
                frame = self.screen_reader.capture_screen()
                ocr_time = self.screen_reader.read_time(frame)
            except Exception:
                ocr_time = None

            if ocr_time is not None:
                if ocr_time > 0.8:
                    last_seen_high_time = max(last_seen_high_time, ocr_time)
                # Level respawn detected! In-game time is between 0.00 and 0.45s.
                # Calibrate t0 with millisecond precision to the exact moment the level started.
                if ocr_time <= 0.45:
                    calibrated_t0 = time.perf_counter() - ocr_time
                    print(f"  [RESPAWN] Calibrated t0 @ in-game time {ocr_time:.2f}s (offset -{ocr_time:.3f}s)")
                    return calibrated_t0

            # Fallback manual retry tap: ONLY if stuck on death screen for > 2.0s without auto-retry
            if elapsed_waiting > 2.0 and not tapped_retry and not self.dry_run:
                self.keyboard.press_space(hold_seconds=0.04)
                tapped_retry = True

            # Safety fallback: do not block indefinitely
            if elapsed_waiting > 3.5:
                return time.perf_counter()

            time.sleep(0.015)

        return time.perf_counter()

    def _run_loop(self, countdown_seconds: float) -> None:
        """Master attempt evaluation and RL loop."""
        try:
            if not self._execute_countdown(countdown_seconds):
                return

            while not self._stop_event.is_set():
                while self._paused and not self._stop_event.is_set():
                    time.sleep(0.2)

                if self._stop_event.is_set():
                    break

                # 1. Generate candidate tap sequence
                # (Proven prefix is strictly untouched; only tests 1 frontier jump)
                candidate = self.optimizer.generate_next_candidate(
                    last_crash_time=self.last_crash_time
                )
                self.current_candidate = candidate

                # 2. Wait for level respawn to calibrate true t0
                calibrated_t0 = self._wait_for_level_respawn()

                if self._stop_event.is_set():
                    break

                # 3. Execute attempt
                survival_time, measured_pct, outcome = self._run_single_attempt(
                    candidate, calibrated_t0
                )

                if self._stop_event.is_set():
                    break

                # 4. Evaluate the candidate and retain every improvement
                is_improved, eval_label, delta_s = self.optimizer.evaluate_attempt(
                    candidate=candidate,
                    measured_time=survival_time,
                    measured_progress=measured_pct,
                    outcome=outcome,
                )

                # 5. Update session telemetry and charts
                gen_record = self.optimizer.get_generation_record()
                self.store.add_generation_record(gen_record)
                self.store.update_session(
                    current_generation=self.optimizer.current_generation,
                    current_attempt=self.optimizer.total_attempts,
                    total_attempts=self.optimizer.total_attempts,
                    successful_completions=self.optimizer.successful_completions,
                    best_completion=round(self.optimizer.best_time, 2),
                    best_fitness=self.optimizer.best_fitness,
                )

                # 6. Informative event logging
                if is_improved and eval_label == "IMPROVED":
                    msg = (
                        f"Attempt #{candidate.attempt_number}: ★ OBSTACLE CLEARED! "
                        f"Survival: {self.optimizer.best_time:.2f}s (+{delta_s:+.2f}s). "
                        f"Proven path locked: {self.optimizer.proven_jumps}"
                    )
                    severity = EventSeverity.SUCCESS.value
                    print(f"  [+] {msg}")
                elif eval_label == "SAME_OBSTACLE":
                    msg = (
                        f"Attempt #{candidate.attempt_number}: Same obstacle (~{survival_time:.2f}s vs best {self.optimizer.best_time:.2f}s). "
                        f"Kept proven path {self.optimizer.proven_jumps}. Testing next frontier offset."
                    )
                    severity = EventSeverity.INFO.value
                    print(f"  [.] {msg}")
                elif eval_label == "INITIAL_BASELINE":
                    msg = (
                        f"Attempt #{candidate.attempt_number}: Initial baseline collision at {survival_time:.2f}s. "
                        f"Targeting obstacle 1."
                    )
                    severity = EventSeverity.INFO.value
                    print(f"  [*] {msg}")
                else:
                    msg = (
                        f"Attempt #{candidate.attempt_number}: Crashed earlier ({survival_time:.2f}s vs best {self.optimizer.best_time:.2f}s). "
                        f"Kept proven path {self.optimizer.proven_jumps} unchanged."
                    )
                    severity = EventSeverity.WARNING.value
                    print(f"  [-] {msg}")

                self.store.add_event(
                    TelemetryEvent(
                        timestamp=current_iso_time(),
                        category="agent",
                        message=msg,
                        severity=severity,
                        details={
                            "attempt": candidate.attempt_number,
                            "survival_time": survival_time,
                            "best_time": self.optimizer.best_time,
                            "delta_s": delta_s,
                            "proven_jumps": list(self.optimizer.proven_jumps),
                            "mutation": candidate.mutation_note,
                        },
                    )
                )

                self.last_crash_time = survival_time if outcome != "Completed" else None
                time.sleep(0.3)

        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.store.update_session(agent_status=AgentStatus.ERROR.value)
            self.store.add_event(
                TelemetryEvent(
                    timestamp=current_iso_time(),
                    category="agent",
                    message=f"Agent exception: {exc}",
                    severity=EventSeverity.ERROR.value,
                )
            )
        finally:
            self._running = False
            self.keyboard.abort_sequence()

    def _on_jump_dispatched(
        self, jump_idx: int, planned_s: float, actual_s: float, delta_ms: float
    ) -> None:
        """Callback invoked when spacebar is tapped."""
        self.active_jumps_executed = jump_idx + 1
        if jump_idx < len(self.active_jump_timings):
            self.active_jump_timings[jump_idx].executed_time = round(actual_s, 3)
            self.active_jump_timings[jump_idx].delta_ms = round(delta_ms, 2)

        action_msg = f"SPACE #{jump_idx + 1} @ {planned_s:.2f}s ({delta_ms:+.1f}ms)"
        print(f"    -> [JUMP #{jump_idx + 1}] Tapped Space @ {actual_s:.3f}s (planned {planned_s:.3f}s, Δ {delta_ms:+.1f}ms)")

        attempt_snap = AttemptState(
            attempt_number=self.current_candidate.attempt_number if self.current_candidate else 0,
            generation=self.current_candidate.generation if self.current_candidate else 1,
            level_progress=round(actual_s, 2),
            elapsed_time=round(actual_s, 2),
            outcome=AttemptOutcome.RUNNING.value,
            latest_action=action_msg,
            planned_jumps_count=len(self.active_jump_timings),
            executed_jumps_count=self.active_jumps_executed,
            jumps=list(self.active_jump_timings),
            fitness=round(actual_s * 10.0, 3),
        )
        self.store.update_attempt(attempt_snap)

    def _run_single_attempt(
        self, candidate: CandidateRun, attempt_start_time: float
    ) -> tuple[float, float, str]:
        """
        Execute one attempt with synchronized t0.
        Protected against premature aborts from single-frame OCR glitches.
        """
        self.active_jumps_executed = 0
        self.active_jump_timings = [
            JumpTiming(planned_time=round(t, 3), action="jump")
            for t in candidate.jumps
        ]

        try:
            initial_ocr = self.screen_reader.read_all()
        except Exception:
            initial_ocr = {}

        baseline_attempt_num = initial_ocr.get("attempt") or candidate.attempt_number
        max_ocr_time_seen = initial_ocr.get("time") or 0.0
        max_pct_seen = initial_ocr.get("percentage") or 0.0

        # Announce attempt start
        print(f"\n[ATTEMPT #{candidate.attempt_number}] Starting run with {len(candidate.jumps)} jumps: {candidate.jumps}")
        self.store.add_event(
            TelemetryEvent(
                timestamp=current_iso_time(),
                category="agent",
                message=(
                    f"Attempt #{candidate.attempt_number} engaged | "
                    f"Jumps: {candidate.jumps} | {candidate.mutation_note}"
                ),
                severity=EventSeverity.INFO.value,
            )
        )

        # Start high-precision spacebar playback thread
        cancel_event = self.keyboard.execute_jump_sequence_async(
            jump_timings=candidate.jumps,
            start_time=attempt_start_time,
            on_jump_executed=self._on_jump_dispatched,
        )

        outcome = AttemptOutcome.RUNNING.value
        elapsed_wall_s = 0.0
        consecutive_zero_time_frames = 0
        consecutive_stalled_frames = 0
        consecutive_att_increment_frames = 0
        last_observed_time = 0.0

        # Calculate time when all planned jumps will have finished dispatching
        last_planned_jump = candidate.jumps[-1] if candidate.jumps else 0.8
        all_jumps_completed_time = last_planned_jump + 0.15

        try:
            while not self._stop_event.is_set():
                if self._paused:
                    break

                loop_t = time.perf_counter()
                elapsed_wall_s = loop_t - attempt_start_time

                # Screen capture & OCR read
                if self.mock_mode:
                    ocr_result = self._simulate_mock_attempt_step(
                        candidate.jumps, elapsed_wall_s, candidate.attempt_number
                    )
                else:
                    try:
                        frame = self.screen_reader.capture_screen()
                        ocr_result = self.screen_reader.read_all(frame)
                        self.latest_annotated_frame = self.screen_reader.generate_annotated_frame(
                            frame=frame, telemetry_info=ocr_result
                        )
                    except Exception:
                        ocr_result = {
                            "percentage": max_pct_seen,
                            "attempt": baseline_attempt_num,
                            "time": elapsed_wall_s,
                            "tap_count": len(candidate.jumps),
                        }

                self.latest_ocr_data = ocr_result

                curr_ocr_time = ocr_result.get("time")
                curr_pct = ocr_result.get("percentage")
                curr_att = ocr_result.get("attempt")

                # Filter out spurious OCR anomalies (> 1.5s higher than wall clock)
                if curr_ocr_time is not None:
                    if curr_ocr_time <= elapsed_wall_s + 0.4:
                        if curr_ocr_time > max_ocr_time_seen:
                            max_ocr_time_seen = curr_ocr_time
                            consecutive_stalled_frames = 0
                        elif curr_ocr_time == last_observed_time and elapsed_wall_s > 0.4:
                            consecutive_stalled_frames += 1
                        last_observed_time = curr_ocr_time

                if curr_pct is not None and curr_pct > max_pct_seen:
                    max_pct_seen = curr_pct

                effective_survival_time = max_ocr_time_seen if max_ocr_time_seen > 0.4 else elapsed_wall_s

                latest_act = (
                    f"SPACE #{self.active_jumps_executed}"
                    if self.active_jumps_executed > 0
                    else "Cube moving forward..."
                )
                attempt_snap = AttemptState(
                    attempt_number=candidate.attempt_number,
                    generation=candidate.generation,
                    level_progress=round(effective_survival_time, 2),
                    elapsed_time=round(effective_survival_time, 2),
                    outcome=AttemptOutcome.RUNNING.value,
                    latest_action=latest_act,
                    planned_jumps_count=len(self.active_jump_timings),
                    executed_jumps_count=self.active_jumps_executed,
                    jumps=list(self.active_jump_timings),
                    fitness=round(effective_survival_time * 10.0, 3),
                )
                self.store.update_attempt(attempt_snap)

                # Check completion
                if effective_survival_time >= STEREO_MADNESS_TOTAL_SECONDS or max_pct_seen >= 100.0:
                    outcome = AttemptOutcome.COMPLETED.value
                    break

                # Mock mode immediate crash detection
                if self.mock_mode and ocr_result.get("crashed"):
                    outcome = AttemptOutcome.CRASHED.value
                    break

                # CRASH CHECK: Protected against premature aborts during jump window!
                # In Stereo Madness, there are 0 obstacles before 0.65s (first spike is at ~1.05s).
                # During elapsed_wall_s < 0.65, NO crash is possible; any attempt change is just
                # the respawn text settling.
                if elapsed_wall_s < 0.65:
                    if curr_att is not None and baseline_attempt_num is not None:
                        if curr_att > baseline_attempt_num:
                            baseline_attempt_num = curr_att
                else:
                    # Verified crash check (elapsed_wall_s >= 0.65s)
                    # 1. Attempt counter incremented (require 2 frames or attempt increment + low timer)
                    if curr_att is not None and baseline_attempt_num is not None:
                        if curr_att > baseline_attempt_num:
                            consecutive_att_increment_frames += 1
                            if consecutive_att_increment_frames >= 2 or (curr_ocr_time is not None and curr_ocr_time <= 0.20):
                                outcome = AttemptOutcome.CRASHED.value
                                break
                        else:
                            consecutive_att_increment_frames = 0

                    # 2. Timer reset to zero/near-zero (3 consecutive frames).
                    # Do not treat the initial HUD state as a crash: until
                    # meaningful progress has been observed, the level may
                    # simply not have started and playback must continue.
                    if (
                        max_ocr_time_seen > 0.4
                        and curr_ocr_time is not None
                        and curr_ocr_time <= 0.08
                    ):
                        consecutive_zero_time_frames += 1
                        if consecutive_zero_time_frames >= 3:
                            outcome = AttemptOutcome.CRASHED.value
                            break
                    else:
                        consecutive_zero_time_frames = 0

                    # 3. Timer stalled verification (only after jumps have had time to dispatch)
                    if elapsed_wall_s >= all_jumps_completed_time:
                        if consecutive_stalled_frames >= 12:  # ~480ms stalled
                            outcome = AttemptOutcome.CRASHED.value
                            break

                    # 4. Traversed well past last planned jump into unmapped obstacles
                    if elapsed_wall_s > last_planned_jump + 1.2:
                        outcome = AttemptOutcome.CRASHED.value
                        break

                if elapsed_wall_s > 90.0:
                    outcome = AttemptOutcome.COMPLETED.value
                    break

                time.sleep(self.poll_interval)

        finally:
            self.keyboard.abort_sequence()

        final_survival_time = max_ocr_time_seen if max_ocr_time_seen > 0.4 else elapsed_wall_s

        attempt_snap.outcome = outcome
        attempt_snap.level_progress = round(final_survival_time, 2)
        attempt_snap.elapsed_time = round(final_survival_time, 2)
        self.store.update_attempt(attempt_snap)

        return round(final_survival_time, 2), round(max_pct_seen, 2), outcome

    def _simulate_mock_attempt_step(
        self, candidate_jumps: List[float], elapsed_s: float, attempt_num: int
    ) -> Dict[str, Any]:
        """Simulate game physics and obstacle clearance in mock mode."""
        obstacles = STEREO_MADNESS_SEED_JUMPS
        crashed = False
        survival_s = elapsed_s

        for obs_t in obstacles:
            if elapsed_s >= obs_t + 0.08:
                cleared = any(abs(j - (obs_t - 0.12)) <= 0.09 for j in candidate_jumps)
                if not cleared:
                    crashed = True
                    survival_s = obs_t
                    break

        pct = min(100.0, (survival_s / STEREO_MADNESS_TOTAL_SECONDS) * 100.0)

        mock_frame = ScreenReader.generate_mock_frame(
            percentage=pct,
            attempt=attempt_num,
            elapsed=survival_s,
            taps=len(candidate_jumps),
        )
        self.latest_annotated_frame = self.screen_reader.generate_annotated_frame(
            frame=mock_frame,
            telemetry_info={
                "percentage": round(pct, 2),
                "attempt": attempt_num,
                "time": round(survival_s, 2),
                "tap_count": len(candidate_jumps),
            },
        )

        return {
            "percentage": round(pct, 2),
            "attempt": attempt_num,
            "time": round(survival_s, 2),
            "tap_count": len(candidate_jumps),
            "crashed": crashed,
        }
