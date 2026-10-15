#!/usr/bin/env python3
"""
Application entry point for Geometry Dash AI / Stereo Madness Monitoring Dashboard.
"""
import os
import sys

from dashboard import create_app

app = create_app({
    "ENABLE_SIMULATOR": os.environ.get("GD_ENABLE_SIMULATOR", "1") == "1",
    "AUTO_START_SIMULATOR": True,
})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    print("=" * 65)
    print("  GEOMETRY DASH AI / STEREO MADNESS DASHBOARD")
    print("=" * 65)
    print(f"  • Running on http://127.0.0.1:{port}")
    print(f"  • Telemetry Source: {'Mock Simulator' if app.config['SIMULATOR'] else 'Awaiting Live Agent'}")
    print("  • Press CTRL+C to quit")
    print("=" * 65)

    app.run(host=host, port=port, debug=debug)
