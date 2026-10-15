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
    app.config["ENABLE_SIMULATOR"] = False
    app.config["ENABLE_TAS_AGENT"] = True
    app.config["COUNTDOWN_SECONDS"] = 10.0
    app.config["DRY_RUN"] = False
    app.config["MOCK_MODE"] = False
    app.config["SEED_MADNESS"] = False

    if config:
        app.config.update(config)

    # Initialize shared thread-safe telemetry store
    store = TelemetryStore()
    app.config["TELEMETRY_STORE"] = store

    # Initialize TAS Engine if enabled
    if app.config.get("ENABLE_TAS_AGENT", True):
        from src.hak.tas_engine import TASEngine
        tas_engine = TASEngine(
            store=store,
            dry_run=app.config.get("DRY_RUN", False),
            mock_mode=app.config.get("MOCK_MODE", False),
            seed_with_stereo_madness=app.config.get("SEED_MADNESS", False),
        )
        app.config["TAS_ENGINE"] = tas_engine
        app.config["SIMULATOR"] = None

        if app.config.get("AUTO_START_TAS_AGENT", False):
            countdown = float(app.config.get("COUNTDOWN_SECONDS", 10.0))
            tas_engine.start(countdown_seconds=countdown)
    else:
        app.config["TAS_ENGINE"] = None
        # Initialize and optionally start simulator if fallback requested
        if app.config.get("ENABLE_SIMULATOR", False):
            simulator = MockTelemetrySimulator(store=store, seed=42)
            app.config["SIMULATOR"] = simulator
            if app.config.get("AUTO_START_SIMULATOR", True):
                simulator.start()
        else:
            app.config["SIMULATOR"] = None

    # Register blueprints
    app.register_blueprint(dashboard_bp)

    return app
