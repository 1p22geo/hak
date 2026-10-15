# Geometry Dash TAS / Reinforcement Learning System

A unified, controllable **Tool-Assisted Speedrun (TAS)** and **Reinforcement Learning (RL)** system for **Geometry Dash** (focused on *Stereo Madness*).

Built with **Windows Media OCR (`winocr`)**, **`mss` screen grabber**, high-precision **`pynput` keyboard controller**, an **Evolutionary Strategy (1+1)-ES mutation optimizer**, and a live **Flask + Chart.js web telemetry dashboard**.

---

## 1. Quickstart

### Launching the RL TAS Controller

Run the unified interface:
```bash
python app.py
```
Or via uv:
```bash
uv run python app.py
```

### What Happens on Launch:
1. **10-Second Grace Period Countdown**: The terminal and Web UI immediately begin a 10-second countdown allowing you to focus your Geometry Dash game window and enter a level (*Stereo Madness*).
2. **Autonomous RL Loop Engages**:
   - The agent schedules spacebar taps with sub-millisecond precision.
   - Screen capture (`mss`) and Windows Media OCR read:
     - **Percentage** (`0.0% - 100.0%`)
     - **Attempt Count** (e.g. `Attempt 152`)
     - **In-Game Time** (e.g. `12.4s`)
     - **Tap / Jump Count** (e.g. `15`)
   - Upon crash or completion, the RL policy mutates the tap sequence (timing jitter, jump insertion before collision points, bad jump pruning).
   - If the mutation **improved** the run, it is saved as the new elite baseline. If it **worsened**, it reverts back to the best sequence.
3. **Web Dashboard**: Access `http://127.0.0.1:5000` to monitor live attempt telemetry, jump timing rail, generation curves, chronological event logs, and live OCR annotated gameplay frames.

---

## 2. CLI Options

| Flag | Description | Default |
|---|---|---|
| `--countdown <N>` | Set grace countdown duration in seconds | `10.0` |
| `--no-countdown` | Skip countdown and engage agent immediately | `False` |
| `--dry-run` | Test spacebar timing without dispatching physical keypresses | `False` |
| `--mock` | Run in synthetic mode simulating GD obstacles & screen | `False` |
| `--seed-madness` | Seed initial candidate with known Stereo Madness obstacle timings | `False` |
| `--select-rois` | Launch interactive snipping tool to configure OCR ROIs | `False` |
| `--no-auto-start` | Wait for user to click "Start RL Agent" in Web UI | `False` |
| `--port <port>` | Web dashboard port | `5000` |

---

## 3. Architecture

```
hak/
├── app.py                     # Unified entrypoint (CLI + Server + 10s countdown)
├── roi_config.json            # Persisted screen coordinates for the 4 OCR ROIs
├── src/hak/
│   ├── ocr_reader.py          # Windows Media OCR & mss reader (pct, attempt, time, taps)
│   ├── keyboard_controller.py # High-precision spacebar dispatcher & async scheduler
│   ├── rl_optimizer.py        # (1+1)-ES evolutionary mutation engine (improved vs worsened)
│   └── tas_engine.py          # Master orchestrator: countdown, attempt loop, telemetry
├── dashboard/
│   ├── __init__.py            # Flask app factory connecting TASEngine & TelemetryStore
│   ├── routes.py              # Web UI, agent control endpoints, and live frame stream
│   ├── telemetry.py           # In-memory thread-safe state store
│   └── schemas.py             # Data models (AttemptState, SessionState, GenerationRecord)
├── templates/
│   └── dashboard.html         # Responsive web UI with countdown banner & live controls
├── static/
│   ├── css/dashboard.css      # Dark technical styling
│   └── js/dashboard.js        # Live polling, Chart.js updates & control triggers
├── PoCs/                      # Original proof-of-concept building blocks
└── tests/
    ├── test_dashboard.py      # Dashboard & API unit tests
    └── test_rl_tas.py         # End-to-end OCR, keyboard controller, optimizer & engine tests
```

---

## 4. Web Control API

The dashboard exposes REST endpoints for interactive control:

- `POST /api/agent/start`: Start the agent (accepts `{"countdown": 10.0}`)
- `POST /api/agent/pause`: Pause active agent
- `POST /api/agent/resume`: Resume paused agent
- `POST /api/agent/stop`: Halt agent immediately
- `POST /api/agent/reset`: Reset elite baseline tap sequence
- `GET /api/agent/status`: Live agent state, countdown, and OCR readings
- `GET /api/agent/frame`: Live annotated JPEG frame with OCR bounding boxes
- `GET /api/agent/rois`: Get current ROI bounding boxes
- `POST /api/agent/rois`: Update and persist ROI coordinates
- `POST /api/agent/select-roi`: Trigger Windows Snipping Tool overlay on screen

---

## 5. Running Automated Tests

Run the full test suite with `pytest`:

```bash
uv run python -m pytest
```

All 18 tests validate OCR parsing, keyboard timing, RL mutation improvements/regressions, engine lifecycles, and dashboard routes.
