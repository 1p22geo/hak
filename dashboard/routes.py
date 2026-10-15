from __future__ import annotations

import os
import threading
from flask import Blueprint, jsonify, render_template, request, current_app, Response
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


def get_tas_engine():
    return current_app.config.get("TAS_ENGINE")


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
    """Control monitoring / simulation or TAS agent state."""
    sim = get_simulator()
    agent = get_tas_engine()
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action == "pause":
        if agent:
            agent.pause()
        elif sim:
            sim.pause()
        return jsonify({"status": "ok", "message": "Monitoring / Agent paused"})
    elif action == "resume":
        if agent:
            agent.resume()
        elif sim:
            sim.resume()
        return jsonify({"status": "ok", "message": "Monitoring / Agent resumed"})
    elif action == "disconnect":
        if sim:
            sim.set_disconnected_state()
        return jsonify({"status": "ok", "message": "Simulated disconnect"})
    elif action == "error":
        if sim:
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


# --- Real TAS RL Agent Controls ---

@dashboard_bp.route("/api/agent/start", methods=["POST"])
def agent_start():
    """Start the TAS RL Agent with specified countdown."""
    agent = get_tas_engine()
    if not agent:
        return jsonify({"status": "error", "message": "TAS Engine not configured"}), 400

    data = request.get_json(silent=True) or {}
    countdown = float(data.get("countdown", 10.0))
    agent.start(countdown_seconds=countdown)
    return jsonify({
        "status": "ok",
        "message": f"TAS RL Agent starting in {countdown:.0f} seconds",
        "countdown": countdown,
    })


@dashboard_bp.route("/api/agent/pause", methods=["POST"])
def agent_pause():
    """Pause the TAS RL Agent."""
    agent = get_tas_engine()
    if not agent:
        return jsonify({"status": "error", "message": "TAS Engine not configured"}), 400

    agent.pause()
    return jsonify({"status": "ok", "message": "TAS RL Agent paused"})


@dashboard_bp.route("/api/agent/resume", methods=["POST"])
def agent_resume():
    """Resume the TAS RL Agent."""
    agent = get_tas_engine()
    if not agent:
        return jsonify({"status": "error", "message": "TAS Engine not configured"}), 400

    agent.resume()
    return jsonify({"status": "ok", "message": "TAS RL Agent resumed"})


@dashboard_bp.route("/api/agent/stop", methods=["POST"])
def agent_stop():
    """Halt the TAS RL Agent."""
    agent = get_tas_engine()
    if not agent:
        return jsonify({"status": "error", "message": "TAS Engine not configured"}), 400

    agent.stop()
    return jsonify({"status": "ok", "message": "TAS RL Agent stopped"})


@dashboard_bp.route("/api/agent/reset", methods=["POST"])
def agent_reset():
    """Reset the best elite tap sequence baseline."""
    agent = get_tas_engine()
    if not agent:
        return jsonify({"status": "error", "message": "TAS Engine not configured"}), 400

    agent.reset_best()
    return jsonify({"status": "ok", "message": "Elite baseline reset to fresh state"})


@dashboard_bp.route("/api/agent/status", methods=["GET"])
def agent_status():
    """Return live status of the TAS engine."""
    agent = get_tas_engine()
    if not agent:
        return jsonify({"available": False})

    return jsonify({
        "available": True,
        "running": agent._running,
        "paused": agent._paused,
        "is_counting_down": agent.is_counting_down,
        "countdown_remaining": round(agent.countdown_remaining, 1),
        "dry_run": agent.dry_run,
        "mock_mode": agent.mock_mode,
        "best_progress": agent.optimizer.best_progress,
        "best_fitness": agent.optimizer.best_fitness,
        "total_attempts": agent.optimizer.total_attempts,
        "current_generation": agent.optimizer.current_generation,
        "ocr_telemetry": agent.latest_ocr_data,
    })


@dashboard_bp.route("/api/agent/frame", methods=["GET"])
def agent_frame():
    """Serve latest annotated frame with OCR bounding boxes."""
    agent = get_tas_engine()
    if agent and agent.latest_annotated_frame:
        return Response(agent.latest_annotated_frame, mimetype="image/jpeg")

    # Generate a fallback frame if no frame has been captured yet
    from src.hak.ocr_reader import ScreenReader
    fallback = ScreenReader.generate_mock_frame(
        percentage=0.0, attempt=1, elapsed=0.0, taps=0
    )
    reader = agent.screen_reader if agent else ScreenReader(mock_mode=True)
    frame_bytes = reader.generate_annotated_frame(
        fallback, {"percentage": 0.0, "attempt": 1, "time": 0.0, "tap_count": 0}
    )
    return Response(frame_bytes, mimetype="image/jpeg")


@dashboard_bp.route("/api/agent/rois", methods=["GET", "POST"])
def agent_rois():
    """Get or update OCR Regions of Interest."""
    agent = get_tas_engine()
    if not agent:
        return jsonify({"status": "error", "message": "TAS Engine not configured"}), 400

    if request.method == "POST":
        data = request.get_json() or {}
        new_rois = {}
        for k in ["percentage", "attempt_count", "time", "tap_count"]:
            if k in data and len(data[k]) == 4:
                new_rois[k] = tuple(int(x) for x in data[k])
            else:
                new_rois[k] = agent.screen_reader.rois.get(k, (0, 0, 100, 50))
        agent.screen_reader.save_rois(new_rois)
        return jsonify({"status": "ok", "message": "ROIs updated successfully", "rois": new_rois})

    return jsonify({"rois": {k: list(v) for k, v in agent.screen_reader.rois.items()}})


@dashboard_bp.route("/api/agent/select-roi", methods=["POST"])
def select_roi():
    """Trigger interactive screen ROI selection in a background thread."""
    data = request.get_json(silent=True) or {}
    target_roi_name = data.get("roi_name", "percentage")

    def _select_worker():
        try:
            from PoCs.select_roi import select_screen_roi
            coords = select_screen_roi()
            if coords:
                agent = get_tas_engine()
                if agent:
                    agent.screen_reader.rois[target_roi_name] = coords
                    agent.screen_reader.save_rois(agent.screen_reader.rois)
                    agent.store.add_event(
                        TelemetryEvent(
                            timestamp=current_iso_time(),
                            category="system",
                            message=f"Updated ROI for {target_roi_name}: {coords}",
                            severity=EventSeverity.INFO.value,
                        )
                    )
        except Exception as e:
            print(f"[select_roi] Error: {e}")

    threading.Thread(target=_select_worker, daemon=True).start()
    return jsonify({
        "status": "ok",
        "message": f"Interactive ROI selection started for '{target_roi_name}' on primary screen."
    })
