"""
Geometry Dash RL TAS & Telemetry System.
"""
from __future__ import annotations

import sys


def main() -> None:
    from app import run_app
    run_app(sys.argv[1:])


if __name__ == "__main__":
    main()
