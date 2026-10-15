import pytest
from dashboard import create_app
from dashboard.telemetry import TelemetryStore
from dashboard.schemas import (
    SessionState,
    AttemptState,
    GenerationRecord,
    TelemetryEvent,
    ConnectionState,
    AgentStatus,
)


@pytest.fixture
def app():
    # Create test app with simulator disabled to allow controlled deterministic tests
    app = create_app({
        "TESTING": True,
        "ENABLE_SIMULATOR": False,
    })
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_dashboard_page_loads(client):
    """Verify that main dashboard route returns 200 and loads HTML template."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Geometry Dash AI" in html
    assert "Stereo Madness" in html
    assert "window.__INITIAL_TELEMETRY__" in html


def test_api_status_endpoint(client, app):
    """Test /api/status JSON output."""
    store = app.config["TELEMETRY_STORE"]
    store.update_session(
        project_name="Geometry Dash AI / Stereo Madness",
        connection_state=ConnectionState.SIMULATED.value,
        agent_status=AgentStatus.RUNNING.value,
        best_completion=72.4,
    )

    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.get_json()
    assert "session" in data
    assert "attempt" in data
    assert data["session"]["best_completion"] == 72.4
    assert data["session"]["agent_status"] == "Running"


def test_api_metrics_endpoint(client, app):
    """Test /api/metrics endpoint for generations data."""
    store = app.config["TELEMETRY_STORE"]
    store.add_generation_record(
        GenerationRecord(
            generation=1,
            best_completion=15.0,
            avg_completion=8.5,
            best_fitness=200.0,
            avg_fitness=120.0,
        )
    )

    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["generations"]) == 1
    assert data["generations"][0]["best_completion"] == 15.0


def test_api_events_endpoint_and_clear(client, app):
    """Test events retrieval, incremental filtering, and clearing."""
    store = app.config["TELEMETRY_STORE"]
    store.add_event(TelemetryEvent(timestamp="2026-10-15T10:00:00Z", category="system", message="Test Event 1"))
    store.add_event(TelemetryEvent(timestamp="2026-10-15T10:00:01Z", category="jump", message="Test Jump Executed"))

    res = client.get("/api/events")
    assert res.status_code == 200
    events = res.get_json()["events"]
    assert len(events) == 2
    assert events[0]["message"] == "Test Event 1"

    # Test clear
    res_clear = client.post("/api/events/clear")
    assert res_clear.status_code == 200

    res2 = client.get("/api/events")
    events2 = res2.get_json()["events"]
    # Only the "cleared" event should now exist
    assert len(events2) == 1
    assert "cleared" in events2[0]["message"].lower()


def test_api_snapshot_endpoint(client):
    """Test consolidated telemetry snapshot."""
    response = client.get("/api/snapshot")
    assert response.status_code == 200
    data = response.get_json()
    assert "session" in data
    assert "attempt" in data
    assert "generations" in data
    assert "events" in data


def test_telemetry_ingest_from_real_agent(client, app):
    """Test real agent telemetry intake hook."""
    payload = {
        "session": {
            "session_id": "real_run_001",
            "agent_status": "Running",
            "best_completion": 88.5,
        },
        "event": {
            "category": "agent",
            "message": "Real OpenCV agent synchronized with game window",
            "severity": "info",
        }
    }
    response = client.post("/api/telemetry/ingest", json=payload)
    assert response.status_code == 200

    store = app.config["TELEMETRY_STORE"]
    assert store.session.connection_state == "Connected"
    assert store.session.is_simulated is False
    assert store.session.best_completion == 88.5


def test_simulator_execution():
    """Verify mock telemetry simulator initializes properly and generates mock history."""
    store = TelemetryStore()
    from dashboard.simulator import MockTelemetrySimulator
    sim = MockTelemetrySimulator(store=store, seed=123, tick_interval=0.05)
    # Check that bootstrap created generations
    assert len(store.generations_history) == 5
    assert store.session.connection_state == ConnectionState.SIMULATED.value

    # Start and run for brief moment then stop
    sim.start()
    import time
    time.sleep(0.15)
    sim.stop()
    assert store.current_attempt.attempt_number > 0
