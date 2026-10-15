from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from dashboard.schemas import GenerationRecord, current_iso_time

STEREO_MADNESS_TOTAL_SECONDS = 85.0
MIN_MEANINGFUL_TIME_DELTA = 0.30

# Known obstacle timings for Stereo Madness as optional jump seed
STEREO_MADNESS_SEED_JUMPS = [
    1.12, 1.95, 2.78, 3.65, 4.45, 5.25, 6.10, 7.30, 8.15, 9.00,
    10.20, 11.45, 12.30, 13.80, 15.10, 16.50, 18.20, 19.90, 21.40, 23.00,
    25.50, 27.20, 29.10, 31.00, 33.40, 35.80, 38.50, 41.20, 44.00, 47.50,
]


@dataclass
class CandidateRun:
    """Represents a specific candidate tap sequence policy."""
    jumps: List[float] = field(default_factory=list)
    attempt_number: int = 0
    generation: int = 1
    progress_time: float = 0.0       # Survival time in seconds (primary metric)
    progress_pct: float = 0.0        # Secondary percentage
    elapsed_time: float = 0.0
    fitness: float = 0.0
    outcome: str = "Unknown"
    mutation_type: str = "Initial"
    mutation_note: str = ""

    @property
    def progress(self) -> float:
        return self.progress_time

    @progress.setter
    def progress(self, val: float) -> None:
        self.progress_time = val

    def copy(self) -> CandidateRun:
        return CandidateRun(
            jumps=list(self.jumps),
            attempt_number=self.attempt_number,
            generation=self.generation,
            progress_time=self.progress_time,
            progress_pct=self.progress_pct,
            elapsed_time=self.elapsed_time,
            fitness=self.fitness,
            outcome=self.outcome,
            mutation_type=self.mutation_type,
            mutation_note=self.mutation_note,
        )


class RLTASOptimizer:
    """
    Prefix-Preserving Barrier Reinforcement Learning Optimizer for Geometry Dash.

    Core Principle: "Don't fix what ain't broke!"
    1. Proven Prefix is IMMUTABLE:
       Once a sequence of jumps [j_1, j_2, ..., j_k] successfully clears obstacles up
       to time T, this prefix is FROZEN. It is repeated on EVERY run with exact timing.
       It is NEVER jittered, NEVER deleted, and NEVER shifted.
    2. Frontier Exploration Only:
       The agent ONLY adds or modifies a single candidate jump AFTER the proven prefix,
       targeting the active obstacle barrier that caused the latest crash.
    3. Noise-Immune Evaluation:
       If the frontier jump clears the obstacle (gaining >= 0.30s survival time),
       that jump is permanently locked into proven_jumps.
       If it fails, proven_jumps is untouched and the next candidate tests a different offset.
    """

    def __init__(
        self,
        seed_jumps: Optional[List[float]] = None,
        attempts_per_gen: int = 10,
        random_seed: Optional[int] = None,
        min_meaningful_delta: float = MIN_MEANINGFUL_TIME_DELTA,
    ):
        self.rng = random.Random(random_seed)
        self.attempts_per_gen = max(1, attempts_per_gen)
        self.min_meaningful_delta = min_meaningful_delta

        # Soft timing hints only — NEVER treated as proven until actually survived.
        self.hint_jumps: List[float] = sorted(seed_jumps) if seed_jumps else []
        # Proven sequence of jumps that are 100% FROZEN and IMMUTABLE
        self.proven_jumps: List[float] = []

        # Systematic pre-obstacle jump offset sweep
        # In GD, jumping ~0.08s to ~0.35s before an obstacle will clear it
        self.frontier_offsets = [
            -0.12, -0.18, -0.24, -0.08, -0.30, -0.04, -0.36, -0.42, -0.15, -0.21
        ]
        self.current_offset_index = 0

        # Global counters
        self.total_attempts = 0
        self.current_generation = 1
        self.attempt_in_generation = 0
        self.successful_completions = 0
        self.meaningful_improvements_count = 0

        # Collision barrier & failure tracking
        self.best_time: float = 0.0
        self.frontier_barrier: float = 1.05  # Stereo Madness spike 1 barrier
        self.consecutive_barrier_failures: int = 0

        self.best_candidate = CandidateRun(
            jumps=[],
            attempt_number=0,
            generation=1,
            progress_time=0.0,
            progress_pct=0.0,
            fitness=0.0,
            mutation_type="Initial",
            mutation_note="Baseline initial state",
        )

        # Generation tracking
        self.gen_attempts_count = 0
        self.gen_best_time = 0.0
        self.gen_time_sum = 0.0
        self.gen_best_fitness = 0.0
        self.gen_fitness_sum = 0.0
        self.gen_success_count = 0

        self.history: List[CandidateRun] = []

    # Compatibility properties for existing dashboard & tests
    @property
    def locked_jumps(self) -> List[float]:
        return self.proven_jumps

    @locked_jumps.setter
    def locked_jumps(self, val: List[float]) -> None:
        self.proven_jumps = list(val)

    @property
    def current_barrier(self) -> float:
        return self.frontier_barrier

    @current_barrier.setter
    def current_barrier(self, val: float) -> None:
        self.frontier_barrier = val

    @property
    def search_offsets(self) -> List[float]:
        return self.frontier_offsets

    @property
    def best_progress(self) -> float:
        return self.best_time

    @best_progress.setter
    def best_progress(self, val: float) -> None:
        self.best_time = val

    @property
    def best_fitness(self) -> float:
        return self.best_candidate.fitness

    def compute_fitness(self, survival_time: float, completed: bool = False) -> float:
        score = survival_time * 10.0
        if completed or survival_time >= STEREO_MADNESS_TOTAL_SECONDS:
            score += 1000.0
        return round(score, 3)

    def generate_next_candidate(self, last_crash_time: Optional[float] = None) -> CandidateRun:
        """
        Produce candidate tap sequence.
        Policy:
        1. 0% deletions - NEVER delete any jump.
        2. Focus on ADDING jumps at the end (Frontier Exploration) - >= 90% of attempts.
        3. Rare fine-tuning of ONLY the last jump - <= 10% of attempts, only after multiple
           failed barrier attempts, leaving all prior jumps [:-1] strictly immutable.
        """
        self.total_attempts += 1
        self.attempt_in_generation += 1

        if self.attempt_in_generation > self.attempts_per_gen:
            self.current_generation += 1
            self.attempt_in_generation = 1
            self.gen_attempts_count = 0
            # Carry global best forward so charts don't falsely regress to ~0 each gen
            self.gen_best_time = self.best_time
            self.gen_time_sum = 0.0
            self.gen_best_fitness = self.best_candidate.fitness
            self.gen_fitness_sum = 0.0
            self.gen_success_count = 0

        # Attempt 1: optionally probe soft seed hints (not proven until survived)
        if self.total_attempts == 1 and len(self.hint_jumps) > 0:
            return CandidateRun(
                jumps=list(self.hint_jumps),
                attempt_number=self.total_attempts,
                generation=self.current_generation,
                mutation_type="BaselineSeed",
                mutation_note=f"Testing unverified seed hints ({len(self.hint_jumps)} jumps)",
            )

        # Update barrier from actual measured crash time if ahead of current barrier
        if last_crash_time and last_crash_time > self.best_time - 0.2:
            self.frontier_barrier = max(self.frontier_barrier, last_crash_time)

        # Rare fine-tuning: Only when we have proven jumps AND have failed on this barrier
        # for at least 8 attempts, and only on 1 out of 10 attempts (<= 10%).
        should_fine_tune_last = (
            len(self.proven_jumps) >= 1
            and self.consecutive_barrier_failures >= 8
            and (self.total_attempts % 10 == 0)
        )

        if should_fine_tune_last:
            # Fine-tune ONLY the very last jump. All prior jumps [:-1] are 100% frozen.
            deltas = [-0.02, 0.02, -0.03, 0.03, -0.015, 0.015]
            chosen_delta = deltas[(self.consecutive_barrier_failures // 10) % len(deltas)]
            prev_jump = self.proven_jumps[-2] if len(self.proven_jumps) >= 2 else 0.2
            new_last = round(max(prev_jump + 0.15, self.proven_jumps[-1] + chosen_delta), 3)

            cand = CandidateRun(
                jumps=list(self.proven_jumps[:-1]) + [new_last],
                attempt_number=self.total_attempts,
                generation=self.current_generation,
                mutation_type="FineTuneLastJump",
                mutation_note=(
                    f"Preserved {len(self.proven_jumps) - 1} prior jumps | "
                    f"Fine-tuning ONLY last jump #{len(self.proven_jumps)} from {self.proven_jumps[-1]:.2f}s "
                    f"to {new_last:.2f}s ({chosen_delta:+.3f}s)"
                ),
            )
            return cand

        # Primary mode (>= 90%): Add jump at the end (Frontier Exploration)
        # All proven jumps are 100% repeated verbatim
        cand = CandidateRun(
            jumps=list(self.proven_jumps),
            attempt_number=self.total_attempts,
            generation=self.current_generation,
        )

        last_proven_t = self.proven_jumps[-1] if self.proven_jumps else 0.0
        min_frontier_jump_t = last_proven_t + 0.15 if self.proven_jumps else 0.20

        offset = self.frontier_offsets[self.current_offset_index % len(self.frontier_offsets)]
        frontier_jump = round(max(min_frontier_jump_t, self.frontier_barrier + offset), 3)

        cand.jumps.append(frontier_jump)
        cand.mutation_type = "AddFrontierJump"
        cand.mutation_note = (
            f"Preserved {len(self.proven_jumps)} proven jumps | "
            f"Adding frontier jump #{len(cand.jumps)} @ {frontier_jump:.2f}s "
            f"({offset:+.2f}s before barrier {self.frontier_barrier:.2f}s)"
        )

        self.current_offset_index += 1
        return cand

    def evaluate_attempt(
        self,
        candidate: CandidateRun,
        measured_time: float,
        measured_progress: Optional[float] = None,
        outcome: str = "Unknown",
    ) -> Tuple[bool, str, float]:
        """
        Evaluate candidate attempt result against current best survival time.
        Enforces:
        - Improvements >= 0.30s lock the frontier jump into proven_jumps permanently.
        - Failures (< 0.30s) preserve proven_jumps untouched and discard the frontier jump.
        """
        completed = (measured_time >= STEREO_MADNESS_TOTAL_SECONDS) or (outcome == "Completed")
        fitness = self.compute_fitness(measured_time, completed=completed)
        pct = (
            measured_progress
            if (measured_progress is not None and measured_progress > 0)
            else min(100.0, round((measured_time / STEREO_MADNESS_TOTAL_SECONDS) * 100, 2))
        )

        candidate.progress_time = measured_time
        candidate.progress_pct = pct
        candidate.elapsed_time = measured_time
        candidate.fitness = fitness
        candidate.outcome = outcome

        self.gen_attempts_count += 1
        self.gen_time_sum += measured_time
        self.gen_fitness_sum += fitness
        if measured_time > self.gen_best_time:
            self.gen_best_time = measured_time
        if fitness > self.gen_best_fitness:
            self.gen_best_fitness = fitness
        if completed:
            self.gen_success_count += 1
            self.successful_completions += 1

        delta_time = measured_time - self.best_time

        # 1. First attempt initialization
        if self.total_attempts == 1:
            self.best_candidate = candidate.copy()
            self.best_time = measured_time
            self.frontier_barrier = max(1.05, measured_time)
            # Only lock jumps that actually cleared past the opening barrier.
            # Failed seed hints / failed first probes must NOT become "proven".
            if measured_time >= 1.05 + self.min_meaningful_delta:
                self.proven_jumps = self._jumps_survived_before_crash(
                    candidate.jumps, measured_time
                )
                self.meaningful_improvements_count += 1
                self.current_offset_index = 0
            else:
                self.proven_jumps = []
            self.history.append(candidate.copy())
            return True, "INITIAL_BASELINE", round(measured_time, 2)

        # 2. Case A: MEANINGFUL IMPROVEMENT (Obstacle Cleared!)
        # In GD, jumping an obstacle yields at least +0.30s survival time gain
        if delta_time >= self.min_meaningful_delta or completed:
            self.meaningful_improvements_count += 1
            self.best_candidate = candidate.copy()
            self.best_time = measured_time
            self.consecutive_barrier_failures = 0

            # LOCK IN THE WINNING JUMP SEQUENCE PERMANENTLY
            # Only jumps that occurred before the crash are proven; later
            # unverified schedule entries (e.g. leftover seed hints) are dropped.
            self.proven_jumps = self._jumps_survived_before_crash(
                candidate.jumps, measured_time
            )

            # Advance frontier obstacle barrier to the new crash point ahead
            self.frontier_barrier = max(self.frontier_barrier + 0.5, measured_time)
            # Reset offset sweep index for the next obstacle
            self.current_offset_index = 0

            self.history.append(candidate.copy())
            return True, "IMPROVED", round(delta_time, 2)

        # 3. Case B: SAME OBSTACLE COLLISION (Noise / Failed Frontier Jump)
        # Proven prefix is 100% UNTOUCHED. Failed frontier jump is discarded.
        self.consecutive_barrier_failures += 1
        if abs(delta_time) < self.min_meaningful_delta:
            self.history.append(candidate.copy())
            return False, "SAME_OBSTACLE", round(delta_time, 2)

        # 4. Case C: REGRESSION / WORSENED
        # Frontier jump caused a premature hazard. Proven prefix is UNTOUCHED.
        self.history.append(candidate.copy())
        return False, "WORSENED", round(delta_time, 2)

    def get_generation_record(self) -> GenerationRecord:
        count = max(1, self.gen_attempts_count)
        avg_time = round(self.gen_time_sum / count, 2)
        best_t = round(self.gen_best_time, 2)
        best_pct = min(100.0, round((best_t / STEREO_MADNESS_TOTAL_SECONDS) * 100, 2))
        avg_pct = min(100.0, round((avg_time / STEREO_MADNESS_TOTAL_SECONDS) * 100, 2))

        return GenerationRecord(
            generation=self.current_generation,
            best_completion=best_pct,
            avg_completion=avg_pct,
            best_fitness=round(self.gen_best_fitness, 3),
            avg_fitness=round(self.gen_fitness_sum / count, 3),
            attempts_count=count,
            success_count=self.gen_success_count,
            completed_at=current_iso_time(),
        )

    @staticmethod
    def _jumps_survived_before_crash(
        jumps: List[float], crash_time: float, margin: float = 0.05
    ) -> List[float]:
        """Keep only jumps that were scheduled before the measured crash."""
        cutoff = crash_time - margin
        return [round(j, 3) for j in jumps if j <= cutoff]

    def reset_best_to_baseline(self, new_jumps: Optional[List[float]] = None) -> None:
        # Explicit reset may install a known-good prefix; otherwise clear memory.
        jumps = sorted(new_jumps) if new_jumps else []
        self.hint_jumps = list(jumps)
        self.proven_jumps = list(jumps)
        self.best_candidate = CandidateRun(
            jumps=list(jumps),
            attempt_number=self.total_attempts,
            generation=self.current_generation,
            progress_time=0.0,
            progress_pct=0.0,
            fitness=0.0,
            mutation_type="Reset",
            mutation_note="Reset by user",
        )
        self.best_time = 0.0
        self.frontier_barrier = 1.05
        self.consecutive_barrier_failures = 0
        self.current_offset_index = 0
