from __future__ import annotations

import time
import pytest
import numpy as np

from dashboard import create_app
from dashboard.telemetry import TelemetryStore
from src.hak.ocr_reader import ScreenReader
from src.hak.keyboard_controller import KeyboardController
from src.hak.rl_optimizer import RLTASOptimizer, CandidateRun, STEREO_MADNESS_SEED_JUMPS
from src.hak.tas_engine import TASEngine


def test_screen_reader_mock_ocr_and_frame():
    """Verify ScreenReader can parse synthetic GD HUD frames."""
    reader = ScreenReader(mock_mode=True)
    frame = reader.generate_mock_frame(
        percentage=45.67, attempt=88, elapsed=12.4, taps=15
    )
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (720, 1280, 3)

    # Annotated frame generation
    annotated_jpeg = reader.generate_annotated_frame(
        frame=frame,
        telemetry_info={"percentage": 45.67, "attempt": 88, "time": 12.4, "tap_count": 15},
    )
    assert isinstance(annotated_jpeg, bytes)
    assert len(annotated_jpeg) > 1000  # valid JPEG payload


def test_screen_reader_roi_cropping():
    """Verify safe ROI cropping within bounds."""
    reader = ScreenReader(mock_mode=True)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    crop = reader.crop_roi(frame, "percentage")
    assert crop.shape[0] > 0
    assert crop.shape[1] > 0


def test_keyboard_controller_dry_run():
    """Verify high-precision keyboard scheduler in dry-run mode."""
    controller = KeyboardController(dry_run=True)
    dispatched: list[tuple[int, float, float, float]] = []

    def on_jump(idx, planned, actual, delta):
        dispatched.append((idx, planned, actual, delta))

    t0 = time.perf_counter()
    cancel_event = controller.execute_jump_sequence_async(
        jump_timings=[0.05, 0.10],
        start_time=t0,
        on_jump_executed=on_jump,
    )

    # Wait for completion
    time.sleep(0.18)
    assert len(dispatched) == 2
    assert dispatched[0][0] == 0
    assert dispatched[1][0] == 1
    assert abs(dispatched[0][3]) < 25.0  # within 25ms jitter bound
    controller.abort_sequence()


def test_keyboard_controller_abort():
    """Verify aborting an active jump sequence upon simulated crash."""
    controller = KeyboardController(dry_run=True)
    dispatched: list[int] = []

    def on_jump(idx, planned, actual, delta):
        dispatched.append(idx)

    t0 = time.perf_counter()
    controller.execute_jump_sequence_async(
        jump_timings=[0.05, 0.50, 1.00],
        start_time=t0,
        on_jump_executed=on_jump,
    )

    time.sleep(0.10)
    controller.abort_sequence()
    time.sleep(0.10)

    # Should have only fired the first jump
    assert len(dispatched) == 1
    assert dispatched[0] == 0


def test_rl_optimizer_mutation_and_evaluation():
    """Test time-centric RL policy generation, barrier mutation, and noise filtering."""
    optimizer = RLTASOptimizer(
        seed_jumps=[1.05],
        attempts_per_gen=5,
        random_seed=42,
    )

    # 1. Baseline candidate
    c1 = optimizer.generate_next_candidate()
    assert c1.attempt_number == 1
    assert c1.jumps == [1.05]

    # Evaluate baseline attempt (crashed at 1.05s)
    is_improved, label, delta = optimizer.evaluate_attempt(
        candidate=c1,
        measured_time=1.05,
        outcome="Crashed",
    )
    assert is_improved is True
    assert label == "INITIAL_BASELINE"
    assert optimizer.best_time == 1.05

    # 2. Mutated candidate 2 (tests systematic obstacle offset)
    c2 = optimizer.generate_next_candidate(last_crash_time=1.05)
    assert c2.attempt_number == 2
    assert len(c2.jumps) >= 1

    # Case A: Small improvement (crashed at 1.08s -> delta +0.03s)
    is_improved_noise, label_noise, delta_noise = optimizer.evaluate_attempt(
        candidate=c2,
        measured_time=1.08,
        outcome="Crashed",
    )
    assert is_improved_noise is True
    assert label_noise == "IMPROVED"
    assert optimizer.best_time == 1.08
    assert optimizer.best_candidate.attempt_number == 2

    # Case B: Regression / Worsened (crashed earlier at 0.50s)
    c3 = optimizer.generate_next_candidate(last_crash_time=1.05)
    is_improved_worse, label_worse, delta_worse = optimizer.evaluate_attempt(
        candidate=c3,
        measured_time=0.50,
        outcome="Crashed",
    )
    assert is_improved_worse is False
    assert label_worse == "WORSENED"
    assert optimizer.best_time == 1.05

    # Case C: Larger improvement (cleared spike, survived to 1.85s)
    c4 = optimizer.generate_next_candidate(last_crash_time=1.05)
    is_improved_better, label_better, delta_better = optimizer.evaluate_attempt(
        candidate=c4,
        measured_time=1.85,
        outcome="Crashed",
    )
    assert is_improved_better is True
    assert label_better == "IMPROVED"
    assert delta_better == 0.80
    assert optimizer.best_time == 1.85
    assert optimizer.best_candidate.attempt_number == 4
    # Locked winning jump sequence
    assert len(optimizer.locked_jumps) >= 1


def test_generation_rollover_keeps_completed_generation_recordable():
    """A completed generation must not be reset before its record is saved."""
    optimizer = RLTASOptimizer(seed_jumps=[], attempts_per_gen=2)

    for measured_time in (1.05, 1.85):
        candidate = optimizer.generate_next_candidate()
        optimizer.evaluate_attempt(candidate, measured_time=measured_time, outcome="Crashed")

    record = optimizer.get_generation_record()
    assert record.generation == 1
    assert record.attempts_count == 2
    assert record.best_completion == round(1.85 / 85.0 * 100, 2)

    next_candidate = optimizer.generate_next_candidate()
    assert next_candidate.generation == 2
    assert optimizer.gen_attempts_count == 0



def test_tas_engine_lifecycle_and_mock_run():
    """Verify TASEngine execution in mock mode."""
    store = TelemetryStore()
    engine = TASEngine(
        store=store,
        dry_run=True,
        mock_mode=True,
        seed_with_stereo_madness=True,
        poll_interval=0.02,
    )

    # Fast start with 0.1s countdown
    engine.start(countdown_seconds=0.1)
    time.sleep(0.4)

    assert engine._running is True
    snap = store.get_status_payload()
    assert snap["session"]["agent_status"] in ["Running", "Evaluating"] or "Countdown" in snap["session"]["agent_status"]

    # Pause
    engine.pause()
    assert engine._paused is True
    assert store.session.agent_status == "Paused"

    # Resume
    engine.resume()
    assert engine._paused is False

    # Stop
    engine.stop()
    assert engine._running is False
    assert store.session.agent_status == "Idle"


def test_dashboard_agent_api_endpoints():
    """Verify Flask API routes for agent control."""
    app = create_app({
        "TESTING": True,
        "ENABLE_TAS_AGENT": True,
        "AUTO_START_TAS_AGENT": False,
        "DRY_RUN": True,
        "MOCK_MODE": True,
    })
    client = app.test_client()

    # 1. Status endpoint
    res_status = client.get("/api/agent/status")
    assert res_status.status_code == 200
    data = res_status.get_json()
    assert data["available"] is True
    assert data["running"] is False

    # 2. Start endpoint
    res_start = client.post("/api/agent/start", json={"countdown": 0.1})
    assert res_start.status_code == 200

    # 3. Pause & Resume endpoints
    res_pause = client.post("/api/agent/pause")
    assert res_pause.status_code == 200

    res_resume = client.post("/api/agent/resume")
    assert res_resume.status_code == 200

    # 4. Stop endpoint
    res_stop = client.post("/api/agent/stop")
    assert res_stop.status_code == 200

    # 5. Reset best endpoint
    res_reset = client.post("/api/agent/reset")
    assert res_reset.status_code == 200

    # 6. Live frame endpoint
    res_frame = client.get("/api/agent/frame")
    assert res_frame.status_code == 200
    assert res_frame.content_type == "image/jpeg"
    assert len(res_frame.data) > 500

    # 7. ROIs endpoint
    res_rois = client.get("/api/agent/rois")
    assert res_rois.status_code == 200
    rois = res_rois.get_json()["rois"]
    assert "percentage" in rois
    assert "attempt_count" in rois

    # Update ROIs and restore
    orig_rois = dict(rois)
    res_update_rois = client.post(
        "/api/agent/rois",
        json={"percentage": [100, 20, 200, 60]},
    )
    assert res_update_rois.status_code == 200
    assert res_update_rois.get_json()["rois"]["percentage"] == [100, 20, 200, 60]

    # Restore original config
    client.post("/api/agent/rois", json=orig_rois)


def test_proven_prefix_is_immutable_and_only_modifies_afterwards():
    """
    User Requirement:
    'Make sure that if you reach some point in time, it doesn't modify the path before it,
    and repeats the sequence that led to it modifying only what's afterwards.
    Don't fix what ain't broke, lad!'
    """
    optimizer = RLTASOptimizer(seed_jumps=[])

    # Attempt 1 crashes at initial spike at 1.05s
    c1 = optimizer.generate_next_candidate()
    optimizer.evaluate_attempt(c1, measured_time=1.05, outcome="Crashed")
    # Failed probe must not be frozen as proven
    assert optimizer.proven_jumps == []

    # Attempt 2 tests a jump at 0.93s and CLEARS the first spike!
    c2 = optimizer.generate_next_candidate(last_crash_time=1.05)
    first_spike_jump = c2.jumps[0]
    is_improved, label, delta = optimizer.evaluate_attempt(
        c2, measured_time=1.85, outcome="Crashed"
    )
    assert is_improved is True
    assert label == "IMPROVED"
    assert optimizer.proven_jumps == [first_spike_jump]
    assert optimizer.best_time == 1.85

    # Run 10 subsequent attempts searching for obstacle 2.
    # VERIFY: In EVERY SINGLE ATTEMPT, the first spike jump is 100% UNTOUCHED!
    # And only what comes AFTERWARDS (jump 2) is modified!
    for _ in range(10):
        next_cand = optimizer.generate_next_candidate(last_crash_time=1.85)

        # 1. Prefix is identical to the proven path
        assert len(next_cand.jumps) == 2
        assert next_cand.jumps[0] == first_spike_jump  # UNTOUCHED!

        # 2. Frontier jump is strictly AFTER the first jump
        assert next_cand.jumps[1] > first_spike_jump + 0.12

        # Simulate collision at obstacle 2 (failed frontier jump)
        optimizer.evaluate_attempt(next_cand, measured_time=1.84, outcome="Crashed")

        # Proven path remains completely unchanged
        assert optimizer.proven_jumps == [first_spike_jump]


def test_attempt_one_clear_locks_proven_prefix():
    """Clearing spike 1 on attempt 1 must lock the jump (no instant forget)."""
    optimizer = RLTASOptimizer(seed_jumps=[])

    c1 = optimizer.generate_next_candidate()
    assert len(c1.jumps) == 1
    winning_jump = c1.jumps[0]

    is_improved, label, _ = optimizer.evaluate_attempt(
        c1, measured_time=1.85, outcome="Crashed"
    )
    assert is_improved is True
    assert label == "INITIAL_BASELINE"
    assert optimizer.proven_jumps == [winning_jump]
    assert optimizer.best_time == 1.85

    c2 = optimizer.generate_next_candidate(last_crash_time=1.85)
    assert c2.jumps[0] == winning_jump
    assert len(c2.jumps) == 2
    assert c2.jumps[1] > winning_jump + 0.12


def test_failed_seed_hints_are_not_frozen_as_proven():
    """Unverified seed timings must not block frontier search at spike 1."""
    optimizer = RLTASOptimizer(seed_jumps=[1.12, 1.95, 2.78, 47.50])

    c1 = optimizer.generate_next_candidate()
    assert c1.jumps == [1.12, 1.95, 2.78, 47.50]
    assert c1.mutation_type == "BaselineSeed"

    optimizer.evaluate_attempt(c1, measured_time=1.05, outcome="Crashed")
    assert optimizer.proven_jumps == []
    assert optimizer.best_time == 1.05

    c2 = optimizer.generate_next_candidate(last_crash_time=1.05)
    # Must explore near the first spike, not append after 47.5s
    assert len(c2.jumps) == 1
    assert 0.5 <= c2.jumps[0] <= 1.05
