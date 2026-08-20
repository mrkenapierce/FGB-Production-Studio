#!/usr/bin/env python3
"""GitHub-side entrypoint for the FGB YouTube broadcast controller.

Keep YouTube control code out of services/fgbears-live/** so changes to the
broadcast-control workflow do not trigger the Oracle production deploy.
The existing controller remains the implementation source until it is fully
migrated; this wrapper intentionally does not modify Oracle or FFmpeg.
"""

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "services" / "fgbears-live" / "bin" / "youtube-broadcast-control.py"
runpy.run_path(str(TARGET), run_name="__main__")
