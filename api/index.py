"""Single Vercel Function that dispatches the dashboard API endpoints."""
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import urllib3

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from ui.server import DashboardError, Handler as DashboardHandler, run_visual_backtest  # noqa: E402

ALLOWED_ENDPOINTS = {"health", "operations", "connect", "connect-env", "run", "ws", "backtest", "public-demo", "public-demo-1", "public-demo-3"}


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
        if self.path in {"/api/public-demo", "/api/public-demo-1", "/api/public-demo-3"}:
            resolution = self.path.rsplit("-", 1)[-1] if self.path != "/api/public-demo" else None
            return self.public_demo(resolution)
        return DashboardHandler.do_GET(self)

    def do_POST(self):
        if self.endpoint():
            return DashboardHandler.do_POST(self)

    def public_demo(self, resolution=None):
        """Serve only market-data backtest output; never account or trade APIs."""
        try:
            base_payload = {
                "symbol": os.environ.get("OHLC_SYMBOL", "VN30F1M"),
                "marketType": os.environ.get("MARKET_TYPE", "DERIVATIVE"),
                "entryMode": "intrabar_close",
                "days": 10,
                "commissionBps": 2,
                "slippageBps": 1,
            }
            if resolution:
                return self.send_json(run_visual_backtest({**base_payload, "resolution": resolution}))
            return self.send_json({"timeframes": {
                "1": run_visual_backtest({**base_payload, "resolution": "1"}),
                "3": run_visual_backtest({**base_payload, "resolution": "3"}),
            }})
        except DashboardError as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        except urllib3.exceptions.HTTPError:
            return self.send_json({
                "error": "DNSE không phản hồi kịp từ máy chủ Vercel. Hãy thử lại; nếu vẫn lặp lại, kiểm tra DNSE_API_KEY, DNSE_API_SECRET và DNSE_BASE_URL.",
            }, HTTPStatus.GATEWAY_TIMEOUT)
        except Exception as exc:
            return self.send_json({"error": f"Không thể tải dữ liệu thị trường DNSE ({type(exc).__name__})."}, HTTPStatus.BAD_GATEWAY)
