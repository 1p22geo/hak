#!/usr/bin/env python3
"""
Application entry point for Geometry Dash AI / Stereo Madness RL TAS & Monitoring Dashboard.
"""
from __future__ import annotations

import os
import sys
import argparse
from dashboard import create_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Geometry Dash Reinforcement Learning TAS & Telemetry Dashboard"
    )
    parser.add_argument(
        "--countdown",
        "-c",
        type=float,
        default=float(os.environ.get("GD_COUNTDOWN", 10.0)),
        help="Seconds of countdown grace period to switch to GD and start level (default: 10.0)",
    )
    parser.add_argument(
        "--no-countdown",
        action="store_true",
        help="Skip the countdown and engage agent immediately",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("GD_DRY_RUN", "0") == "1",
        help="Simulate spacebar presses without dispatching physical keypresses",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=os.environ.get("GD_MOCK_MODE", "0") == "1",
        help="Run in mock/synthetic mode simulating GD screen and physics",
    )
    parser.add_argument(
        "--seed-madness",
        action="store_true",
        default=os.environ.get("GD_SEED_MADNESS", "0") == "1",
        help="Seed initial candidate with Stereo Madness obstacle timings",
    )
    parser.add_argument(
        "--select-rois",
        action="store_true",
        help="Launch interactive snipping tool to configure ROIs before starting",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Do not auto-start countdown; wait for user to press Start in Web UI",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=int(os.environ.get("PORT", 5000)),
        help="Web server port (default: 5000)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "0.0.0.0"),
        help="Web server host (default: 0.0.0.0)",
    )
    return parser.parse_args(argv)


def run_app(argv: list[str] | None = None):
    args = parse_args(argv)

    if args.select_rois:
        print("\n[SETUP] Launching interactive ROI selector...")
        try:
            from PoCs.select_roi import select_screen_roi, print_roi_report
            from src.hak.ocr_reader import ScreenReader
            reader = ScreenReader()
            for name in ["percentage", "attempt_count", "time", "tap_count"]:
                print(f"\nPlease select region for: {name.upper()}")
                roi = select_screen_roi()
                if roi:
                    reader.rois[name] = roi
                    print(f"  -> Saved {name}: {roi}")
            reader.save_rois(reader.rois)
            print("[SETUP] ROI configuration saved.\n")
        except Exception as exc:
            print(f"[SETUP] ROI selection error: {exc}")

    countdown_sec = 0.0 if args.no_countdown else args.countdown
    auto_start = not args.no_auto_start

    # Configure application
    app = create_app({
        "ENABLE_TAS_AGENT": True,
        "AUTO_START_TAS_AGENT": auto_start,
        "COUNTDOWN_SECONDS": countdown_sec,
        "DRY_RUN": args.dry_run,
        "MOCK_MODE": args.mock,
        "SEED_MADNESS": args.seed_madness,
        "ENABLE_SIMULATOR": False,
    })

    mode_label = (
        "Synthetic Mock" if args.mock
        else ("Live (Dry-Run Keypresses)" if args.dry_run else "Live Game (Windows OCR + Real Spacebar)")
    )

    print("=" * 68)
    print("  GEOMETRY DASH REINFORCEMENT LEARNING TAS & TELEMETRY CONTROLLER")
    print("=" * 68)
    print(f"  • Web Dashboard URL:  http://127.0.0.1:{args.port}")
    print(f"  • Execution Mode:     {mode_label}")
    print(f"  • Countdown Grace:    {countdown_sec:.0f} seconds")
    print(f"  • Auto-Start:         {'YES (10s grace period)' if auto_start else 'Manual (via Web UI)'}")
    print("=" * 68)
    print("  Switch to Geometry Dash, enter Stereo Madness, and let the RL agent")
    print("  discover and optimize winning tap combinations!")
    print("  Press CTRL+C in this terminal to quit.")
    print("=" * 68 + "\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    run_app()
