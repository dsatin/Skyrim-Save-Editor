from __future__ import annotations

from pathlib import Path
import sys


def app_root() -> Path:
    """Return the app package root for dev and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).joinpath("app")
    return Path(__file__).resolve().parents[1]


def resource_path(*parts: str) -> Path:
    return app_root().joinpath("resources", *parts)
