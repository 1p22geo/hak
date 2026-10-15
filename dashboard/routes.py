from __future__ import annotations

import os
from flask import Blueprint, jsonify, render_template, request, current_app
from dashboard.schemas import (
    TelemetryEvent,
    EventSeverity,
    ConnectionState,
    AgentStatus,
    current_iso_time,
)

dashboard_bp = Blueprint("dashboard", __name__)


def get_telemetry_store():
    return current_app.config["TELEMETRY_STORE"]


def get_simulator():
    return current_app.config.get("SIMULATOR")


@dashboard_bp.route("/")
def index():
    """Render the dashboard UI."""
    store = get_telemetry_store()
    snapshot = store.get_full_snapshot()
    return render_template("dashboard.html", initial_data=snapshot)


@dashboard_bp.route("/api/status", methods=["GET"])
def get_status():
    """Return session state and current attempt state."""
    store = get_telemetry_store()
    return jsonify(store.get_status_payload())


@dashboard_bp.route("/api/metrics", methods=["GET"])
def get_metrics():
    """Return historical generation metrics and session summary."""
    store = get_telemetry_store()
    return jsonify(store.get_metrics_payload())


@dashboard_bp.route("/api/events", methods=["GET"])
def get_events():
    """Return chronological event feed with optional limit and since_id."""
    store = get_telemetry_store()
    limit = request.args.get("limit", default=50, type=int)
    since_id = request.args.get("since_id", default=None, type=int)
    return jsonify(store.get_events_payload(limit=limit, since_id=since_id))


@dashboard_bp.route("/api/snapshot", methods=["GET"])
def get_snapshot():
    """Return complete consolidated dashboard telemetry snapshot."""
    store = get_telemetry_store()
    return jsonify(store.get_full_snapshot())


# --- Dashboard Monitoring & Ingestion Controls ---

@dashboard_bp.route("/api/controls/monitoring", methods=["POST"])
def toggle_monitoring():
    """
    Control dashboard monitoring simulation state (pause, resume, restart).
    Note: These control dashboard monitoring/simulation data generation,
    NOT the external game automation.
    """
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if not sim:
        return jsonify({"status": "error", "message": "Simulator not running"}), 400

    if action == "pause":
        sim.pause()
        return jsonify({"status": "ok", "message": "Monitoring paused"})
    elif action == "resume":
        sim.resume()
        return jsonify({"status": "ok", "message": "Monitoring resumed"})
    elif action == "disconnect":
        sim.set_disconnected_state()
        return jsonify({"status": "ok", "message": "Simulated disconnect"})
    elif action == "error":
        sim.trigger_error_event(data.get("message", "Simulated agent exception: frame buffer desync"))
        return jsonify({"status": "ok", "message": "Simulated error triggered"})
    else:
        return jsonify({"status": "error", "message": f"Unknown action: {action}"}), 400


@dashboard_bp.route("/api/events/clear", methods=["POST"])
def clear_events():
    """Clear displayed event history from store."""
    store = get_telemetry_store()
    store.clear_events()
    store.add_event(
        TelemetryEvent(
            timestamp=current_iso_time(),
            category="dashboard",
            message="Event history cleared by user",
            severity=EventSeverity.INFO.value,
        )
    )
    return jsonify({"status": "ok", "message": "Events cleared"})


@dashboard_bp.route("/api/telemetry/ingest", methods=["POST"])
def ingest_telemetry():
    """
    Integration endpoint for external real agent telemetry.
    Allows real game agent to push updates into the dashboard store.
    """
    payload = request.get_json()
    if not payload:
        return jsonify({"status": "error", "message": "Missing JSON payload"}), 400

    store = get_telemetry_store()

    # If real agent connects, switch connection state and mark as real (non-simulated)
    session_update = payload.get("session")
    if session_update:
        session_update["is_simulated"] = False
        session_update["connection_state"] = ConnectionState.CONNECTED.value
        store.update_session(**session_update)

    event_data = payload.get("event")
    if event_data:
        store.add_event(
            TelemetryEvent(
                timestamp=event_data.get("timestamp", current_iso_time()),
                category=event_data.get("category", "agent"),
                message=event_data.get("message", ""),
                severity=event_data.get("severity", EventSeverity.INFO.value),
                details=event_data.get("details"),
            )
        )

    return jsonify({"status": "ok", "message": "Telemetry accepted"})
