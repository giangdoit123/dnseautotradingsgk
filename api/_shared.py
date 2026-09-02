"""Vercel Function entry point shared by the dashboard API routes."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from ui.server import Handler as handler  # noqa: E402,F401
