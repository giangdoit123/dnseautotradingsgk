"""Single Vercel Function that dispatches the dashboard API endpoints."""
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from ui.server import DashboardError, Handler as DashboardHandler, run_visual_backtest  # noqa: E402

ALLOWED_ENDPOINTS = {"health", "operations", "connect", "connect-env", "run", "ws", "backtest", "public-demo"}


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
        if not self.endpoint():
            return
        if self.path == "/api/public-demo":
            return self.public_demo()
        return DashboardHandler.do_GET(self)

    def do_POST(self):
        if self.endpoint():
            return DashboardHandler.do_POST(self)

    def public_demo(self):
        """Serve only market-data backtest output; never account or trade APIs."""
        try:
            data = run_visual_backtest({
                "symbol": os.environ.get("OHLC_SYMBOL", "VN30F1M"),
                "marketType": os.environ.get("MARKET_TYPE", "DERIVATIVE"),
                "resolution": os.environ.get("RESOLUTION", "1"),
                "entryMode": "intrabar_close",
                "days": 30,
                "commissionBps": 2,
                "slippageBps": 1,
            })
            return self.send_json(data)
        except DashboardError as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        except Exception:
            return self.send_json({"error": "Không thể tải dữ liệu thị trường DNSE cho demo."}, HTTPStatus.BAD_GATEWAY)
