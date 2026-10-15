from __future__ import annotations

import random
import threading
import time
from typing import List, Optional
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


# Stereo Madness standard obstacles / jump points rough timing map (in seconds)
# Stereo Madness at 1x speed takes roughly 85 seconds total
STEREO_MADNESS_KEY_JUMPS = [
    1.12, 1.95, 2.78, 3.65, 4.45, 5.25, 6.10, 7.30, 8.15, 9.00,
    10.20, 11.45, 12.30, 13.80, 15.10, 16.50, 18.20, 19.90, 21.40, 23.00,
    25.50, 27.20, 29.10, 31.00, 33.40, 35.80, 38.50, 41.20, 44.00, 47.50,
    51.00, 54.50, 58.00, 62.00, 66.50, 71.00, 75.50, 80.00, 83.50, 85.00
]


class MockTelemetrySimulator:
    """
    Background simulation worker that generates realistic Geometry Dash AI telemetry.
    Runs in a dedicated thread and periodically updates a TelemetryStore.
    Can be paused, resumed, stopped, or seeded.
    """

    def __init__(
        self,
        store: TelemetryStore,
        seed: Optional[int] = 42,
        tick_interval: float = 0.25,  # 250ms tick for smooth live attempt progression
    ):
        self.store = store
        self.tick_interval = tick_interval
        self.seed = seed
        self.rng = random.Random(seed)

        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Simulation internal state
        self.generation = 1
        self.attempt_in_gen = 1
        self.total_attempts = 0
        self.successful_completions = 0
        self.best_completion = 14.5  # Seed initial best
        self.best_fitness = 120.0

        # Attempt tracking
        self.attempt_active = False
        self.attempt_time = 0.0
        self.attempt_crash_time = 0.0
        self.attempt_target_progress = 0.0
        self.attempt_planned_jumps: List[JumpTiming] = []
        self.current_jump_idx = 0
        self.start_session_time = time.time()

        # Initialize with baseline historical generations for immediate dashboard visual richness
        self._bootstrap_history()

    def _bootstrap_history(self) -> None:
        """Populate initial 5 generations of mock training history."""
        hist_rng = random.Random(self.seed if self.seed else 100)
        curr_best = 8.0
        for gen in range(1, 6):
            # Gradual learning curve
            improvement = hist_rng.uniform(2.5, 7.5)
            curr_best = min(100.0, curr_best + improvement)
            avg = max(3.0, curr_best - hist_rng.uniform(4.0, 9.0))
            best_fit = round(curr_best * 12.5 + hist_rng.uniform(10, 50), 2)
            avg_fit = round(avg * 11.0 + hist_rng.uniform(5, 30), 2)

            self.store.add_generation_record(
                GenerationRecord(
                    generation=gen,
                    best_completion=round(curr_best, 2),
                    avg_completion=round(avg, 2),
                    best_fitness=best_fit,
                    avg_fitness=avg_fit,
                    attempts_count=10,
                    success_count=1 if curr_best >= 100.0 else 0,
                    completed_at=current_iso_time(),
                )
            )
            self.total_attempts += 10

        self.generation = 6
        self.best_completion = round(curr_best, 2)
        self.best_fitness = round(curr_best * 12.5 + 45.0, 2)

        self.store.update_session(
            session_id=f"sim_stereo_madness_{int(time.time())}",
            project_name="Geometry Dash AI / Stereo Madness",
            connection_state=ConnectionState.SIMULATED.value,
            agent_status=AgentStatus.RUNNING.value,
            is_simulated=True,
            session_start_time=current_iso_time(),
            current_generation=self.generation,
            current_attempt=1,
            total_attempts=self.total_attempts,
            successful_completions=0,
            best_completion=self.best_completion,
            best_fitness=self.best_fitness,
        )

        self.store.add_event(
            TelemetryEvent(
                timestamp=current_iso_time(),
                category="system",
                message="Telemetry simulator initialized with Stereo Madness mock profile",
                severity=EventSeverity.INFO.value,
            )
        )
        self.store.add_event(
            TelemetryEvent(
                timestamp=current_iso_time(),
                category="agent",
                message=f"Generation {self.generation} started (pop size: 10)",
                severity=EventSeverity.INFO.value,
            )
        )

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._paused = False
            self.start_session_time = time.time()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="TelemetrySimulator")
            self._thread.start()

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            self.store.update_session(agent_status=AgentStatus.PAUSED.value)
            self.store.add_event(
                TelemetryEvent(
                    timestamp=current_iso_time(),
                    category="agent",
                    message="Agent simulation paused by operator",
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
                    message="Agent simulation resumed",
                    severity=EventSeverity.INFO.value,
                )
            )

    def stop(self) -> None:
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def set_disconnected_state(self) -> None:
        self.store.set_agent_disconnected()
        self.store.add_event(
            TelemetryEvent(
                timestamp=current_iso_time(),
                category="network",
                message="Agent connection lost / disconnected",
                severity=EventSeverity.ERROR.value,
            )
        )

    def trigger_error_event(self, message: str) -> None:
        self.store.update_session(agent_status=AgentStatus.ERROR.value)
        self.store.add_event(
            TelemetryEvent(
                timestamp=current_iso_time(),
                category="error",
                message=message,
                severity=EventSeverity.ERROR.value,
            )
        )

    def _start_new_attempt(self) -> None:
        self.total_attempts += 1
        self.attempt_active = True
        self.attempt_time = 0.0
        self.current_jump_idx = 0

        # Decide how far this attempt will go
        # Probability of matching or slightly beating current best, or crashing earlier
        roll = self.rng.random()
        total_song_time = 85.0  # Stereo Madness duration

        if roll < 0.20:
            # New best!
            improvement = self.rng.uniform(1.0, 5.0)
            self.attempt_target_progress = min(100.0, self.best_completion + improvement)
        elif roll < 0.70:
            # Normal run reaching near current frontier
            self.attempt_target_progress = max(4.0, self.best_completion - self.rng.uniform(0.5, 12.0))
        else:
            # Early fail (e.g. first spike triple jump mistake)
            self.attempt_target_progress = self.rng.uniform(2.0, 18.0)

        self.attempt_crash_time = (self.attempt_target_progress / 100.0) * total_song_time
        if self.attempt_target_progress >= 100.0:
            self.attempt_crash_time = total_song_time

        # Prepare planned jumps for this attempt (subset of key jumps up to crash + extra)
        self.attempt_planned_jumps = []
        for t in STEREO_MADNESS_KEY_JUMPS:
            if t <= self.attempt_crash_time + 4.0:
                self.attempt_planned_jumps.append(
                    JumpTiming(
                        planned_time=t,
                        executed_time=None,
                        action="jump",
                        delta_ms=None,
                    )
                )

        self.store.add_event(
            TelemetryEvent(
                timestamp=current_iso_time(),
                category="attempt",
                message=f"Attempt #{self.total_attempts} started (Gen {self.generation}, #{self.attempt_in_gen}/10)",
                severity=EventSeverity.INFO.value,
            )
        )

    def _run_loop(self) -> None:
        while self._running:
            time.sleep(self.tick_interval)

            if self._paused:
                continue

            uptime = time.time() - self.start_session_time

            if not self.attempt_active:
                self._start_new_attempt()

            # Advance attempt time by simulated speed factor
            # Let simulation run at ~2.5x real speed so user sees interesting dynamic jumps and attempts
            sim_dt = self.tick_interval * 2.5
            self.attempt_time += sim_dt

            # Check for executed jumps
            latest_action = "Hold None"
            for j in self.attempt_planned_jumps:
                if j.planned_time <= self.attempt_time and j.executed_time is None:
                    # Execute jump with realistic small timing jitter (-15ms to +25ms)
                    jitter = self.rng.uniform(-0.015, 0.025)
                    j.executed_time = round(j.planned_time + jitter, 3)
                    j.delta_ms = round(jitter * 1000, 1)
                    latest_action = f"Jump! (Δ {j.delta_ms:+.1f}ms)"
                    if self.rng.random() < 0.25:  # log some jumps to event stream
                        self.store.add_event(
                            TelemetryEvent(
                                timestamp=current_iso_time(),
                                category="jump",
                                message=f"Executed jump at {j.executed_time:.2f}s (offset {j.delta_ms:+.1f}ms)",
                                severity=EventSeverity.INFO.value,
                            )
                        )

            # Calculate progress
            current_progress = min(100.0, (self.attempt_time / 85.0) * 100.0)
            executed_count = sum(1 for j in self.attempt_planned_jumps if j.executed_time is not None)

            # Check if crashed or completed
            if self.attempt_time >= self.attempt_crash_time:
                outcome = AttemptOutcome.COMPLETED.value if self.attempt_target_progress >= 100.0 else AttemptOutcome.CRASHED.value
                final_progress = min(100.0, self.attempt_target_progress)
                fit_calc = round(final_progress * 12.5 + self.rng.uniform(1.0, 20.0), 2)

                # Update attempt
                st = AttemptState(
                    attempt_number=self.total_attempts,
                    generation=self.generation,
                    level_progress=final_progress,
                    elapsed_time=self.attempt_crash_time,
                    outcome=outcome,
                    latest_action=latest_action,
                    planned_jumps_count=len(self.attempt_planned_jumps),
                    executed_jumps_count=executed_count,
                    jumps=self.attempt_planned_jumps,
                    fitness=fit_calc,
                )
                self.store.update_attempt(st)

                if outcome == AttemptOutcome.COMPLETED.value:
                    self.successful_completions += 1
                    self.store.add_event(
                        TelemetryEvent(
                            timestamp=current_iso_time(),
                            category="attempt",
                            message=f"Attempt #{self.total_attempts} COMPLETED Stereo Madness (100%)! 🎉",
                            severity=EventSeverity.SUCCESS.value,
                        )
                    )
                else:
                    is_new_best = final_progress > self.best_completion
                    if is_new_best:
                        self.best_completion = round(final_progress, 2)
                        self.store.add_event(
                            TelemetryEvent(
                                timestamp=current_iso_time(),
                                category="record",
                                message=f"★ New record progress: {self.best_completion:.1f}% on attempt #{self.total_attempts}",
                                severity=EventSeverity.SUCCESS.value,
                            )
                        )
                    else:
                        self.store.add_event(
                            TelemetryEvent(
                                timestamp=current_iso_time(),
                                category="attempt",
                                message=f"Attempt #{self.total_attempts} crashed at {final_progress:.1f}% ({self.attempt_time:.1f}s)",
                                severity=EventSeverity.WARNING.value,
                            )
                        )

                # Check generation advancement
                self.attempt_in_gen += 1
                if self.attempt_in_gen > 10:
                    # Generation completed, evaluate
                    self.store.update_session(agent_status=AgentStatus.EVALUATING.value)
                    self.store.add_event(
                        TelemetryEvent(
                            timestamp=current_iso_time(),
                            category="agent",
                            message=f"Generation {self.generation} evaluation complete. Ranking fitness...",
                            severity=EventSeverity.INFO.value,
                        )
                    )

                    # Compute gen record
                    avg_comp = max(5.0, self.best_completion - self.rng.uniform(4.0, 10.0))
                    gen_rec = GenerationRecord(
                        generation=self.generation,
                        best_completion=self.best_completion,
                        avg_completion=round(avg_comp, 2),
                        best_fitness=round(self.best_completion * 12.5 + 40.0, 2),
                        avg_fitness=round(avg_comp * 11.0 + 20.0, 2),
                        attempts_count=10,
                        success_count=self.successful_completions,
                        completed_at=current_iso_time(),
                    )
                    self.store.add_generation_record(gen_rec)

                    self.generation += 1
                    self.attempt_in_gen = 1
                    self.store.update_session(agent_status=AgentStatus.RUNNING.value)
                    self.store.add_event(
                        TelemetryEvent(
                            timestamp=current_iso_time(),
                            category="agent",
                            message=f"Generation {self.generation} initialized with updated jump policies",
                            severity=EventSeverity.INFO.value,
                        )
                    )

                self.attempt_active = False
                time.sleep(0.3)  # Brief pause between attempts
            else:
                # Update running state
                st = AttemptState(
                    attempt_number=self.total_attempts,
                    generation=self.generation,
                    level_progress=current_progress,
                    elapsed_time=self.attempt_time,
                    outcome=AttemptOutcome.RUNNING.value,
                    latest_action=latest_action,
                    planned_jumps_count=len(self.attempt_planned_jumps),
                    executed_jumps_count=executed_count,
                    jumps=self.attempt_planned_jumps,
                    fitness=round(current_progress * 12.5, 2),
                )
                self.store.update_attempt(st)

            self.store.update_session(
                uptime_seconds=uptime,
                current_generation=self.generation,
                current_attempt=self.total_attempts,
                total_attempts=self.total_attempts,
                successful_completions=self.successful_completions,
                best_completion=self.best_completion,
                agent_status=AgentStatus.RUNNING.value if not self._paused else AgentStatus.PAUSED.value,
            )
