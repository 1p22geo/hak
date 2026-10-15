from __future__ import annotations

import os
from flask import Flask
from dashboard.telemetry import TelemetryStore
from dashboard.simulator import MockTelemetrySimulator
from dashboard.routes import dashboard_bp


def create_app(config: dict | None = None) -> Flask:
    """Factory to create and configure the Flask dashboard app."""
    # Note: templates and static folders are in root directory
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    template_folder = os.path.join(base_dir, "templates")
    static_folder = os.path.join(base_dir, "static")

    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
    )

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "gd-ai-stereo-madness-secret")
    app.config["ENABLE_SIMULATOR"] = True

    if config:
        app.config.update(config)

    # Initialize shared thread-safe telemetry store
    store = TelemetryStore()
    app.config["TELEMETRY_STORE"] = store

    # Initialize and optionally start simulator
    if app.config.get("ENABLE_SIMULATOR", True):
        simulator = MockTelemetrySimulator(store=store, seed=42)
        app.config["SIMULATOR"] = simulator
        # Auto-start simulator background thread unless disabled (e.g. during specific unit tests)
        if app.config.get("AUTO_START_SIMULATOR", True):
            simulator.start()
    else:
        app.config["SIMULATOR"] = None

    # Register blueprints
    app.register_blueprint(dashboard_bp)

    return app
