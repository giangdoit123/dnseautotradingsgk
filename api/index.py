"""Single Vercel Function that dispatches the dashboard API endpoints."""
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from ui.server import Handler as DashboardHandler  # noqa: E402

ALLOWED_ENDPOINTS = {"health", "operations", "connect", "connect-env", "run", "ws", "backtest"}


class handler(BaseHTTPRequestHandler):
    """Vercel-recognized HTTP handler that delegates to the dashboard API."""

    def log_message(self, _format, *_args):
        return

    def send_json(self, data, status=HTTPStatus.OK):
        return DashboardHandler.send_json(self, data, status)

    def endpoint(self):
        query = parse_qs(urlparse(self.path).query)
        endpoint = query.get("endpoint", [""])[0]
        if endpoint not in ALLOWED_ENDPOINTS:
            self.send_json({"error": "API endpoint không tồn tại."}, HTTPStatus.NOT_FOUND)
            return False
        self.path = f"/api/{endpoint}"
        return True

    def do_GET(self):
        if self.endpoint():
            return DashboardHandler.do_GET(self)

    def do_POST(self):
        if self.endpoint():
            return DashboardHandler.do_POST(self)
