# Geometry Dash TAS / Machine-Learning Dashboard

Monitoring and visual control room for the Python-based Geometry Dash AI / TAS project focused on **Stereo Madness**.

Built with **Flask**, **Chart.js**, and an in-memory thread-safe telemetry store. The dashboard works standalone out-of-the-box with a mock telemetry simulator and defines a contract for connecting the real OpenCV / ML agent.

---

## 1. Quickstart

### Prerequisites
- Python 3.10+
- Flask (`pip install -r requirements.txt`)
- pytest (for automated tests)

### Launching the Dashboard

Run the standalone server:
```bash
python3 app.py
```
Open your browser at:
```
http://127.0.0.1:5000
```

By default, the server runs with the **Mock Telemetry Simulator** enabled, showing live generation progression, simulated jump timings, attempts, and event logging.

---

## 2. Project Architecture

```
hak/
├── app.py                     # Application entry point and server startup
├── requirements.txt           # Python dependencies
├── dashboard/
│   ├── __init__.py            # Application factory (create_app)
│   ├── routes.py              # Flask endpoints (UI + JSON API)
│   ├── telemetry.py           # Thread-safe in-memory TelemetryStore
│   ├── simulator.py           # Background mock telemetry generator
│   └── schemas.py             # DTOs, Enums, and data models
├── templates/
│   └── dashboard.html         # Responsive dark-theme dashboard UI
├── static/
│   ├── css/
│   │   └── dashboard.css      # Dark technical styling
│   └── js/
│       ├── chart.min.js       # Local Chart.js library
│       └── dashboard.js       # Client polling, Chart.js updates & timeline
└── tests/
    └── test_dashboard.py      # Automated test suite
```

---

## 3. Telemetry Data Contract & Endpoints

The dashboard polls JSON endpoints every second without reloading the browser.

### A. Core Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `GET /` | GET | Main dashboard web interface |
| `GET /api/status` | GET | Current session state and active attempt telemetry |
| `GET /api/metrics` | GET | Historical generation curves (best & average completion, fitness) |
| `GET /api/events` | GET | Chronological event logs with optional `limit` and `since_id` |
| `GET /api/snapshot` | GET | Consolidated snapshot of status, metrics, attempt & events |
| `POST /api/telemetry/ingest` | POST | Ingestion endpoint for external real game agents |
| `POST /api/controls/monitoring` | POST | Dashboard-level simulator controls (`pause`, `resume`, `disconnect`, `error`) |
| `POST /api/events/clear` | POST | Clear displayed event history |

### B. Telemetry Schema

#### Session State (`SessionState`)
```json
{
  "session_id": "sim_stereo_madness_1760515000",
  "project_name": "Geometry Dash AI / Stereo Madness",
  "connection_state": "Simulated",    // "Connected" | "Disconnected" | "Simulated"
  "agent_status": "Running",          // "Idle" | "Initializing" | "Running" | "Paused" | "Evaluating" | "Error"
  "is_simulated": true,
  "session_start_time": "2026-10-15T08:00:00Z",
  "uptime_seconds": 124.5,
  "last_update": "2026-10-15T08:02:04Z",
  "current_generation": 6,
  "current_attempt": 54,
  "total_attempts": 54,
  "successful_completions": 0,
  "best_completion": 48.25,
  "best_fitness": 648.12,
  "live_frame_url": null
}
```

#### Attempt State (`AttemptState`)
```json
{
  "attempt_number": 54,
  "generation": 6,
  "level_progress": 34.2,             // Percentage 0.0 - 100.0
  "elapsed_time": 29.1,               // Elapsed seconds in current attempt
  "outcome": "Running",               // "Running" | "Crashed" | "Completed" | "Unknown"
  "latest_action": "Jump! (Δ +8.2ms)",
  "planned_jumps_count": 22,
  "executed_jumps_count": 18,
  "jumps": [
    {
      "planned_time": 1.12,           // In seconds from level start
      "executed_time": 1.128,         // In seconds (or null if upcoming)
      "action": "jump",
      "delta_ms": 8.0                 // Execution timing offset in milliseconds
    }
  ],
  "fitness": 427.5
}
```

#### Event Object (`TelemetryEvent`)
```json
{
  "id": 14,
  "timestamp": "2026-10-15T08:02:04Z",
  "category": "jump",                 // "system" | "agent" | "attempt" | "jump" | "record" | "error"
  "message": "Executed jump at 1.13s (offset +8.0ms)",
  "severity": "info",                 // "info" | "success" | "warning" | "error"
  "details": null
}
```

---

## 4. How to Integrate the Real Game Agent

When the OpenCV capture and TAS jump execution system is ready, integrate it in one of two ways:

### Option 1: HTTP Push (Recommended)
Disable the mock simulator (`export GD_ENABLE_SIMULATOR=0`) and have your Python agent push updates via `POST /api/telemetry/ingest`:

```python
import requests

DASHBOARD_URL = "http://127.0.0.1:5000/api/telemetry/ingest"

# Report an attempt crash or progress
requests.post(DASHBOARD_URL, json={
    "session": {
        "agent_status": "Running",
        "current_generation": 3,
        "current_attempt": 24,
        "best_completion": 62.8
    },
    "event": {
        "category": "attempt",
        "message": "Attempt #24 reached 62.8% (Ship Sequence)",
        "severity": "info"
    }
})
```

### Option 2: Shared In-Memory Store Adapter
If the agent runs in the same Python process as Flask, simply call methods on the shared `TelemetryStore`:

```python
from dashboard.telemetry import TelemetryStore
from dashboard.schemas import AttemptState, TelemetryEvent

store.update_attempt(AttemptState(...))
store.add_event(TelemetryEvent(...))
```

---

## 5. Running Automated Tests

Run the test suite using `pytest`:

```bash
python3 -m pytest tests/
```

All 7 test cases validate page loading, all API endpoints, simulator progression, event ingestion, and error resilience.
