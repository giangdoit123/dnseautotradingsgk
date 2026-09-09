#!/usr/bin/env python3
"""Local, form-based control panel for DNSE OpenAPI.

Credentials and trading tokens are retained only in this Python process. The
browser talks exclusively to 127.0.0.1 and never has to construct signatures,
headers, query strings, or request bodies.
"""
import asyncio
import hmac
import json
from bisect import bisect_right
import os
import re
import sys
import time
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import urllib3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(EXAMPLES))

from dnse import DNSEClient, TradingClient  # noqa: E402
from backtest_ichimoku_volume_mtf import fetch_ohlc, run_backtest  # noqa: E402
from env_util import load_dotenv  # noqa: E402
from strategy_ichimoku_volume_mtf import IchimokuVolumeMultiTimeframeStrategy  # noqa: E402

HOST = os.environ.get("DNSE_UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("DNSE_UI_PORT", "8787"))
# A Vercel Function is public by default. It must use server-side credentials,
# never credentials typed into a browser.
VERCEL_DEPLOYMENT = os.environ.get("VERCEL", "") == "1"
ENV_ONLY = os.environ.get("DNSE_UI_ENV_ONLY", "0") == "1" or VERCEL_DEPLOYMENT
MAX_BODY = 200_000
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")

SESSION = {
    "api_key": "", "api_secret": "", "base_url": "https://openapi.dnse.com.vn",
    "ws_url": "wss://ws-openapi.dnse.com.vn", "api_version": "2026-07-23",
    "account_no": "", "trading_token": "",
}

ENVIRONMENTS = {
    "production": ("https://openapi.dnse.com.vn", "wss://ws-openapi.dnse.com.vn"),
    "uat": ("https://openapi-uat.dnse.com.vn", "wss://ws-openapi-uat.dnse.com.vn"),
}


class DashboardError(ValueError):
    """An input or API state error suitable for display in the UI."""


def field(key, label, *, kind="text", default="", required=False, options=None, location="query", help_text=""):
    return {
        "key": key, "label": label, "type": kind, "default": default,
        "required": required, "options": options or [], "location": location,
        "help": help_text,
    }


# Each public DNSE REST ability is expressed as a business form. The server,
# rather than the browser, maps those fields to paths, query parameters, bodies
# and authorization headers.
OPERATIONS = [
    {"id": "accounts", "group": "Tài khoản", "label": "Danh sách tiểu khoản", "method": "GET", "path": "/accounts", "fields": []},
    {"id": "balances", "group": "Tài khoản", "label": "Số dư", "method": "GET", "path": "/accounts/{accountNo}/balances", "auto_account": True, "fields": [field("accountNo", "Tiểu khoản", location="path", help_text="Để trống để dùng tiểu khoản giao dịch tự chọn.")]},
    {"id": "loan_packages", "group": "Tài khoản", "label": "Gói vay", "method": "GET", "path": "/accounts/{accountNo}/loan-packages", "auto_account": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"]), field("symbol", "Mã chứng khoán", help_text="Không bắt buộc.")]},
    {"id": "positions", "group": "Tài khoản", "label": "Vị thế đang nắm", "method": "GET", "path": "/accounts/{accountNo}/positions", "auto_account": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"])]},
    {"id": "position_detail", "group": "Tài khoản", "label": "Chi tiết vị thế", "method": "GET", "path": "/positions/{positionId}", "fields": [field("positionId", "Mã vị thế", location="path", required=True), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"])]},
    {"id": "position_pnl", "group": "Tài khoản", "label": "Cấu hình lãi/lỗ vị thế", "method": "GET", "path": "/positions/{positionId}/pnl-configs", "fields": [field("positionId", "Mã vị thế", location="path", required=True), field("marketType", "Thị trường", kind="select", default="DERIVATIVE", options=["DERIVATIVE"])]},
    {"id": "update_position_pnl", "group": "Giao dịch", "label": "Thiết lập chốt lời / cắt lỗ", "method": "POST", "path": "/positions/{positionId}/pnl-configs", "needs_token": True, "danger": True, "pnl_payload": True, "fields": [field("positionId", "Mã vị thế", location="path", required=True), field("marketType", "Thị trường", kind="select", default="DERIVATIVE", options=["DERIVATIVE"]), field("takeProfitEnabled", "Bật chốt lời", kind="select", default="true", options=["true", "false"], location="body"), field("takeProfitStrategy", "Chiến lược chốt lời", kind="select", default="PNL_RATE", options=["PNL_RATE", "DELTA_PRICE"], location="body"), field("takeProfitRate", "Tỷ lệ chốt lời", kind="number", default="0.4", location="body"), field("takeProfitDelta", "Chênh lệch giá chốt lời", kind="number", default="0", location="body"), field("stopLossEnabled", "Bật cắt lỗ", kind="select", default="true", options=["true", "false"], location="body"), field("stopLossStrategy", "Chiến lược cắt lỗ", kind="select", default="DELTA_PRICE", options=["PNL_RATE", "DELTA_PRICE"], location="body"), field("stopLossRate", "Tỷ lệ cắt lỗ", kind="number", default="1", location="body"), field("stopLossDelta", "Chênh lệch giá cắt lỗ", kind="number", default="0", location="body")]},
    {"id": "orders", "group": "Lệnh", "label": "Lệnh trong ngày", "method": "GET", "path": "/accounts/{accountNo}/orders", "auto_account": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"]), field("orderCategory", "Loại lệnh", kind="select", default="NORMAL", options=["NORMAL", "STOP", "OCO"]), field("pageIndex", "Trang", kind="number", default="0"), field("pageSize", "Số dòng", kind="number", default="20")]},
    {"id": "order_detail", "group": "Lệnh", "label": "Chi tiết lệnh", "method": "GET", "path": "/accounts/{accountNo}/orders/{orderId}", "auto_account": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("orderId", "Mã lệnh", location="path", required=True), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"]), field("orderCategory", "Loại lệnh", kind="select", default="NORMAL", options=["NORMAL", "STOP", "OCO"])]},
    {"id": "execution_detail", "group": "Lệnh", "label": "Chi tiết khớp lệnh", "method": "GET", "path": "/accounts/{accountNo}/executions/{orderId}", "auto_account": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("orderId", "Mã lệnh", location="path", required=True), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"]), field("orderCategory", "Loại lệnh", kind="select", default="NORMAL", options=["NORMAL", "STOP", "OCO"])]},
    {"id": "order_history", "group": "Lệnh", "label": "Lịch sử lệnh", "method": "GET", "path": "/accounts/{accountNo}/orders/history", "auto_account": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"]), field("from", "Từ ngày", kind="date", required=True), field("to", "Đến ngày", kind="date", required=True), field("pageIndex", "Trang", kind="number", default="0"), field("pageSize", "Số dòng", kind="number", default="20")]},
    {"id": "corporate_actions", "group": "Tài khoản", "label": "Quyền doanh nghiệp", "method": "GET", "path": "/accounts/{accountNo}/corporate-action-history", "auto_account": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("symbol", "Mã chứng khoán", help_text="Không bắt buộc.")]},
    {"id": "ppse", "group": "Tài khoản", "label": "Sức mua / sức bán", "method": "GET", "path": "/accounts/{accountNo}/ppse", "auto_account": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"]), field("symbol", "Mã chứng khoán", default="HPG", required=True), field("price", "Giá dự kiến", kind="number", required=True), field("loanPackageId", "Mã gói vay", kind="number", required=True)]},
    {"id": "security_definition", "group": "Thị trường", "label": "Thông tin mã & biên giá", "method": "GET", "path": "/price/{symbol}/secdef", "fields": [field("symbol", "Mã chứng khoán", location="path", default="HPG", required=True), field("boardId", "Sàn / bảng giá", default="G1", help_text="Không bắt buộc.")]},
    {"id": "ohlc", "group": "Thị trường", "label": "Nến OHLC", "method": "GET", "path": "/price/ohlc", "fields": [field("type", "Khung nến", kind="select", default="1D", options=["1", "3", "5", "15", "30", "1H", "1D", "1W"]), field("symbol", "Mã chứng khoán", default="HPG", required=True), field("from", "Từ ngày", kind="date"), field("to", "Đến ngày", kind="date")]},
    {"id": "trades", "group": "Thị trường", "label": "Lịch sử khớp lệnh", "method": "GET", "path": "/price/{symbol}/trades", "fields": [field("symbol", "Mã chứng khoán", location="path", default="HPG", required=True), field("boardId", "Sàn / bảng giá", default="G1"), field("from", "Từ ngày", kind="date"), field("to", "Đến ngày", kind="date"), field("limit", "Số dòng", kind="number", default="50")]},
    {"id": "expected_price", "group": "Thị trường", "label": "Giá dự kiến", "method": "GET", "path": "/price/{symbol}/expected-price", "fields": [field("symbol", "Mã chứng khoán", location="path", default="HPG", required=True), field("boardId", "Sàn / bảng giá", default="G1"), field("limit", "Số dòng", kind="number", default="50")]},
    {"id": "quotes", "group": "Thị trường", "label": "Chào giá", "method": "GET", "path": "/price/{symbol}/quotes", "fields": [field("symbol", "Mã chứng khoán", location="path", default="HPG", required=True), field("boardId", "Sàn / bảng giá", default="G1"), field("limit", "Số dòng", kind="number", default="50")]},
    {"id": "foreign_trading", "group": "Thị trường", "label": "Giao dịch khối ngoại", "method": "GET", "path": "/price/{symbol}/foreign-trading", "fields": [field("symbol", "Mã chứng khoán", location="path", default="HPG", required=True), field("boardId", "Sàn / bảng giá", default="G1"), field("limit", "Số dòng", kind="number", default="50")]},
    {"id": "instruments", "group": "Thị trường", "label": "Danh sách mã giao dịch", "method": "GET", "path": "/market/instruments", "fields": [field("symbol", "Mã chứng khoán"), field("marketId", "Mã thị trường"), field("securityGroupId", "Nhóm chứng khoán"), field("limit", "Số dòng", kind="number", default="50"), field("page", "Trang", kind="number", default="1")]},
    {"id": "latest_trade", "group": "Thị trường", "label": "Khớp lệnh mới nhất", "method": "GET", "path": "/price/{symbol}/trades/latest", "fields": [field("symbol", "Mã chứng khoán", location="path", default="HPG", required=True), field("boardId", "Sàn / bảng giá", default="G1")]},
    {"id": "latest_quote", "group": "Thị trường", "label": "Chào giá mới nhất", "method": "GET", "path": "/price/{symbol}/quotes/latest", "fields": [field("symbol", "Mã chứng khoán", location="path", default="HPG", required=True), field("boardId", "Sàn / bảng giá", default="G1")]},
    {"id": "close_price", "group": "Thị trường", "label": "Giá đóng cửa", "method": "GET", "path": "/price/{symbol}/close", "fields": [field("symbol", "Mã chứng khoán", location="path", default="HPG", required=True), field("boardId", "Sàn / bảng giá", default="G1")]},
    {"id": "working_dates", "group": "Thị trường", "label": "Ngày giao dịch", "method": "GET", "path": "/market/working-dates", "fields": []},
    {"id": "trading_session", "group": "Thị trường", "label": "Phiên giao dịch", "method": "GET", "path": "/market/trading-session", "fields": [field("tscProdGrpId", "Nhóm sản phẩm"), field("boardId", "Sàn / bảng giá", default="G1")]},
    {"id": "broker_care_by", "group": "Khác", "label": "Chuyên viên phụ trách", "method": "GET", "path": "/brokers/accounts/care-by", "fields": []},
    {"id": "send_email_otp", "group": "Xác thực giao dịch", "label": "Gửi Email OTP", "method": "POST", "path": "/registration/send-email-otp", "fields": []},
    {"id": "create_trading_token", "group": "Xác thực giao dịch", "label": "Lấy Trading Token", "method": "POST", "path": "/registration/trading-token", "token_result": True, "fields": [field("otpType", "Loại OTP", kind="select", default="email_otp", required=True, options=["email_otp", "smart_otp"], location="body"), field("passcode", "Mã OTP", kind="password", required=True, location="body")]},
    {"id": "place_order", "group": "Giao dịch", "label": "Đặt lệnh", "method": "POST", "path": "/accounts/{accountNo}/orders", "auto_account": True, "needs_token": True, "danger": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"]), field("orderCategory", "Loại lệnh", kind="select", default="NORMAL", options=["NORMAL", "STOP", "OCO"]), field("symbol", "Mã chứng khoán", default="HPG", required=True, location="body"), field("side", "Chiều lệnh", kind="select", default="NB", options=["NB", "NS"], location="body"), field("orderType", "Loại giá", kind="select", default="LO", options=["LO", "MP", "ATO", "ATC"], location="body"), field("price", "Giá (VND / điểm)", kind="number", required=True, location="body"), field("quantity", "Khối lượng", kind="number", required=True, location="body"), field("loanPackageId", "Mã gói vay", kind="number", location="body", help_text="Không bắt buộc với lệnh không vay.")]},
    {"id": "update_order", "group": "Giao dịch", "label": "Sửa lệnh", "method": "PUT", "path": "/accounts/{accountNo}/orders/{orderId}", "auto_account": True, "needs_token": True, "danger": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("orderId", "Mã lệnh", location="path", required=True), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"]), field("orderCategory", "Loại lệnh", kind="select", default="NORMAL", options=["NORMAL", "STOP", "OCO"]), field("price", "Giá mới", kind="number", required=True, location="body"), field("quantity", "Khối lượng mới", kind="number", required=True, location="body")]},
    {"id": "cancel_order", "group": "Giao dịch", "label": "Hủy lệnh", "method": "DELETE", "path": "/accounts/{accountNo}/orders/{orderId}", "auto_account": True, "needs_token": True, "danger": True, "fields": [field("accountNo", "Tiểu khoản", location="path"), field("orderId", "Mã lệnh", location="path", required=True), field("marketType", "Thị trường", kind="select", default="STOCK", options=["STOCK", "DERIVATIVE", "BOND"]), field("orderCategory", "Loại lệnh", kind="select", default="NORMAL", options=["NORMAL", "STOP", "OCO"])]},
    {"id": "close_position", "group": "Giao dịch", "label": "Đóng vị thế", "method": "POST", "path": "/positions/{positionId}/close", "needs_token": True, "danger": True, "fields": [field("positionId", "Mã vị thế", location="path", required=True), field("marketType", "Thị trường", kind="select", default="DERIVATIVE", options=["DERIVATIVE"])]},
]
OPERATION_BY_ID = {operation["id"]: operation for operation in OPERATIONS}


def json_value(value):
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return {key: json_value(item) for key, item in vars(value).items() if not key.startswith("_")}
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def safe_operations():
    operations = []
    for operation in OPERATIONS:
        # Serverless instances do not reliably retain OTP-derived trading tokens.
        # A public endpoint is not an appropriate place to execute real trades.
        if VERCEL_DEPLOYMENT and operation.get("danger"):
            continue
        operations.append({key: value for key, value in operation.items() if key != "path"})
    return operations


def load_server_credentials():
    """Load local or server-side credentials on demand for read-only charts."""
    if SESSION["api_key"] and SESSION["api_secret"]:
        return
    load_dotenv()
    api_key = os.environ.get("DNSE_API_KEY", "").strip()
    api_secret = os.environ.get("DNSE_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise DashboardError("Thiếu DNSE_API_KEY hoặc DNSE_API_SECRET trong cấu hình máy chủ.")
    environment = configured_environment()
    default_base_url, default_ws_url = ENVIRONMENTS[environment]
    # Honour the explicit Vercel values as well as the production/UAT preset.
    # This keeps each credential pair bound to the endpoint configured by the
    # project without ever exposing either secret to the browser.
    base_url = os.environ.get("DNSE_BASE_URL", default_base_url).strip() or default_base_url
    ws_url = os.environ.get("DNSE_WS_URL", default_ws_url).strip() or default_ws_url
    api_version = os.environ.get("DNSE_API_VERSION", SESSION["api_version"]).strip() or SESSION["api_version"]
    SESSION.update({
        "api_key": api_key, "api_secret": api_secret, "base_url": base_url,
        "ws_url": ws_url, "api_version": api_version,
    })


def require_client():
    load_server_credentials()
    if not SESSION["api_key"] or not SESSION["api_secret"]:
        raise DashboardError("Nhập API key và API secret, rồi bấm Kết nối.")
    # Vercel is only used for the read-only demo.  Fail quickly enough to
    # return a diagnostic to the visitor rather than waiting for the browser
    # request to expire while DNSE is unreachable from the Function region.
    timeout = urllib3.Timeout(connect=7.0, read=12.0) if VERCEL_DEPLOYMENT else None
    return DNSEClient(
        api_key=SESSION["api_key"], api_secret=SESSION["api_secret"],
        base_url=SESSION["base_url"], api_version=SESSION["api_version"], timeout=timeout,
    )


def parse_response(body):
    try:
        return json.loads(body) if body else None
    except json.JSONDecodeError:
        return body


def default_account(api):
    if SESSION["account_no"]:
        return SESSION["account_no"]
    status, body = api.get_accounts()
    if not status or status >= 300:
        raise DashboardError(f"Không lấy được tiểu khoản tự động [{status}]: {body}")
    data = parse_response(body) or {}
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    selected = next((item for item in accounts if item.get("dealAccount")), None) or (accounts[0] if accounts else None)
    if not selected or not selected.get("id"):
        raise DashboardError("API key này không có tiểu khoản khả dụng.")
    SESSION["account_no"] = str(selected["id"])
    return SESSION["account_no"]


def coerce(value, kind):
    if value in (None, ""):
        return None
    if kind == "number":
        number = float(value)
        return int(number) if number.is_integer() else number
    return str(value).strip()


def validate_identifier(value, label):
    if not IDENTIFIER.fullmatch(value):
        raise DashboardError(f"{label} chỉ được chứa chữ, số, dấu chấm, gạch dưới hoặc gạch ngang.")
    return value


def run_operation(payload):
    operation = OPERATION_BY_ID.get(payload.get("operation"))
    if not operation:
        raise DashboardError("Chức năng không tồn tại.")
    if VERCEL_DEPLOYMENT and operation.get("danger"):
        raise DashboardError("Bản Vercel chỉ cho phép đọc dữ liệu và backtest. Hãy dùng Docker/VPN riêng tư để giao dịch.")
    if operation.get("danger") and payload.get("confirmation") != "EXECUTE":
        raise DashboardError("Hãy xác nhận trước khi thực hiện giao dịch thật.")
    api = require_client()
    values = payload.get("values", {})
    if not isinstance(values, dict):
        raise DashboardError("Dữ liệu biểu mẫu không hợp lệ.")
    path, query, body = operation["path"], {}, {}
    for descriptor in operation.get("fields", []):
        key, location = descriptor["key"], descriptor["location"]
        value = coerce(values.get(key, ""), descriptor["type"])
        if value is None:
            if descriptor["required"]:
                raise DashboardError(f"Hãy nhập {descriptor['label']}.")
            continue
        if location == "path":
            path = path.replace("{" + key + "}", validate_identifier(value, descriptor["label"]))
        elif location == "body":
            body[key] = value
        else:
            query[key] = value
    if operation.get("auto_account") and "{accountNo}" in path:
        path = path.replace("{accountNo}", default_account(api))
    if "{" in path:
        raise DashboardError("Biểu mẫu còn thiếu thông tin bắt buộc.")
    headers = None
    if operation.get("needs_token"):
        if not SESSION["trading_token"]:
            raise DashboardError("Hãy lấy Trading Token trước khi giao dịch.")
        headers = {"trading-token": SESSION["trading_token"]}
    if operation.get("pnl_payload"):
        body = {
            "takeProfit": {
                "enabled": body.pop("takeProfitEnabled", "true") == "true",
                "strategy": body.pop("takeProfitStrategy", "PNL_RATE"),
                "rate": body.pop("takeProfitRate", 0),
                "deltaPrice": body.pop("takeProfitDelta", 0),
                "orderMethod": "FASTEST",
                "orderDeltaPrice": 0,
            },
            "stopLoss": {
                "enabled": body.pop("stopLossEnabled", "true") == "true",
                "strategy": body.pop("stopLossStrategy", "DELTA_PRICE"),
                "rate": body.pop("stopLossRate", 0),
                "deltaPrice": body.pop("stopLossDelta", 0),
                "orderMethod": "FASTEST",
                "orderDeltaPrice": 0,
                "trailingEnabled": False,
            },
        }
    status, response_body = api._request(operation["method"], path, query=query or None, body=body or None, headers=headers)
    response = parse_response(response_body)
    if operation["id"] == "accounts" and status and status < 300:
        accounts = response.get("accounts", []) if isinstance(response, dict) else []
        selected = next((item for item in accounts if item.get("dealAccount")), None)
        if selected and selected.get("id"):
            SESSION["account_no"] = str(selected["id"])
    token_ready = False
    if operation.get("token_result") and status and status < 300 and isinstance(response, dict):
        token = response.get("trading-token") or response.get("tradingToken")
        if token:
            SESSION["trading_token"] = str(token)
            token_ready = True
            response = {"message": "Trading Token đã lưu trong bộ nhớ UI và không hiển thị ra trình duyệt."}
    return {"operation": operation["label"], "status": status, "body": response, "tokenReady": token_ready, "accountNo": SESSION["account_no"] or None}


async def stream_snapshot(payload):
    require_client()
    stream_type = payload.get("stream", "quote")
    board = validate_identifier(str(payload.get("board", "G1")), "Sàn / bảng giá")
    symbol = validate_identifier(str(payload.get("symbol", "HPG")), "Mã chứng khoán")
    seconds = min(max(float(payload.get("seconds", 8)), 1), 30)
    resolution = str(payload.get("resolution", "1"))
    prefix = {"quote": "top_price", "trade": "tick", "secdef": "security_definition", "ohlc": "ohlc"}.get(stream_type)
    if not prefix:
        raise DashboardError("Loại dữ liệu WebSocket không hợp lệ.")
    channel = f"{prefix}.{resolution if stream_type == 'ohlc' else board}.json"
    stream = TradingClient(api_key=SESSION["api_key"], api_secret=SESSION["api_secret"], base_url=SESSION["ws_url"], encoding="json", auto_reconnect=False)
    events = []
    try:
        await stream.connect()
        await stream._subscribe_channel(channel, [symbol])
        queue = stream.queue("*")
        deadline = asyncio.get_running_loop().time() + seconds
        while len(events) < 30:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                events.append(json_value(await asyncio.wait_for(queue.get(), remaining)))
            except asyncio.TimeoutError:
                break
    finally:
        await stream.disconnect()
    return {"channel": channel, "events": events}


def connect_credentials(api_key, api_secret, environment):
    if not api_key or not api_secret:
        raise DashboardError("Cần có cả API key và API secret.")
    if environment not in ENVIRONMENTS:
        raise DashboardError("Môi trường không hợp lệ.")
    base_url, ws_url = ENVIRONMENTS[environment]
    SESSION.update({"api_key": api_key, "api_secret": api_secret, "base_url": base_url, "ws_url": ws_url, "account_no": "", "trading_token": ""})
    return {"connected": True, "accountNo": default_account(require_client()), "environment": environment, "environmentOnly": ENV_ONLY}


def connect(payload):
    if ENV_ONLY:
        raise DashboardError("Bản triển khai này chỉ cho phép kết nối bằng cấu hình máy chủ. Hãy dùng nút Dùng cấu hình máy chủ.")
    return connect_credentials(
        str(payload.get("apiKey", "")).strip(), str(payload.get("apiSecret", "")).strip(),
        payload.get("environment", "production"),
    )


def configured_environment():
    """Infer the DNSE environment from the local examples/.env configuration."""
    return "uat" if "uat" in os.environ.get("DNSE_BASE_URL", "").lower() else "production"


def connect_from_env():
    """Connect with local credentials without ever returning them to the browser."""
    load_dotenv()
    api_key = os.environ.get("DNSE_API_KEY", "").strip()
    api_secret = os.environ.get("DNSE_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise DashboardError("Không tìm thấy DNSE_API_KEY và DNSE_API_SECRET trong cấu hình máy chủ.")
    return connect_credentials(api_key, api_secret, configured_environment())


def require_access_token(headers):
    """Protect the public Vercel API with a separate, user-chosen secret."""
    if not VERCEL_DEPLOYMENT:
        return
    expected = os.environ.get("DNSE_UI_ACCESS_TOKEN", "")
    supplied = headers.get("X-DNSE-Access-Token", "")
    if not expected:
        raise DashboardError("Thiếu DNSE_UI_ACCESS_TOKEN trong Vercel Environment Variables.")
    if not hmac.compare_digest(supplied, expected):
        raise DashboardError("Mã truy cập không hợp lệ.")


def epoch(value):
    value = int(float(value))
    return value // 1000 if value > 1_000_000_000_000 else value


def chart_data(candles, trades, strategy, max_bars=1800):
    """Return a compact OHLC chart with the indicators used by the strategy."""
    step = max(1, (len(candles) + max_bars - 1) // max_bars)
    bars = []
    for start in range(0, len(candles), step):
        chunk = candles[start:start + step]
        end = start + len(chunk) - 1
        base = lead_a = lead_b = None
        if end >= strategy.base_line_period - 1:
            base = strategy._midpoint(candles, end, strategy.base_line_period)
        past = end - strategy.displacement
        if past >= max(strategy.base_line_period, strategy.span_b_period) - 1:
            conversion = strategy._midpoint(candles, past, strategy.conversion_period)
            past_base = strategy._midpoint(candles, past, strategy.base_line_period)
            lead_a = (conversion + past_base) / 2.0
            lead_b = strategy._midpoint(candles, past, strategy.span_b_period)
        volume_ma = None
        if end >= strategy.volume_ma_period:
            volume_ma = sum(candle.volume for candle in candles[end - strategy.volume_ma_period:end]) / strategy.volume_ma_period
        bars.append({
            "time": epoch(chunk[0].time), "open": chunk[0].open, "high": max(c.high for c in chunk),
            "low": min(c.low for c in chunk), "close": chunk[-1].close, "volume": sum(c.volume for c in chunk),
            "base": base, "leadA": lead_a, "leadB": lead_b, "volumeMa": volume_ma,
            "sourceStart": start, "sourceEnd": end,
        })
    source_times = [epoch(candle.time) for candle in candles]

    def source_index(timestamp):
        """Map an execution timestamp to its original OHLC candle index."""
        return max(0, min(len(candles) - 1, bisect_right(source_times, timestamp) - 1))

    markers = []
    for number, trade in enumerate(trades, 1):
        entry_time, exit_time = epoch(trade.entry_time), epoch(trade.exit_time)
        markers.append({"kind": "entry", "trade": number, "side": trade.side, "time": entry_time,
                        "sourceIndex": source_index(entry_time), "price": trade.entry_price})
        markers.append({"kind": "exit", "trade": number, "side": trade.side, "time": exit_time,
                        "sourceIndex": source_index(exit_time), "price": trade.exit_price,
                        "reason": trade.reason, "pnl": trade.net_pnl})
    return {"bars": bars, "markers": markers, "sourceBars": len(candles), "displayBars": len(bars), "aggregated": step > 1}


def positive_number(payload, key, default, minimum, maximum):
    raw = payload.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise DashboardError(f"{key} phải là một số.")
    if not minimum <= value <= maximum:
        raise DashboardError(f"{key} phải nằm trong khoảng {minimum}–{maximum}.")
    return value


def run_visual_backtest(payload):
    """Read OHLC from DNSE and return a safe visual backtest; never trades."""
    api = require_client()
    symbol = validate_identifier(str(payload.get("symbol", "VN30F1M")).upper(), "Mã chứng khoán")
    market_type = str(payload.get("marketType", "DERIVATIVE")).upper()
    if market_type not in {"STOCK", "DERIVATIVE", "BOND"}:
        raise DashboardError("Thị trường không hợp lệ.")
    resolution = str(payload.get("resolution", "1"))
    if resolution not in {"1", "3"}:
        raise DashboardError("Backtest trực quan hiện hỗ trợ khung 1 hoặc 3 phút.")
    days = int(positive_number(payload, "days", 30, 5, 365))
    commission_bps = positive_number(payload, "commissionBps", 2, 0, 100)
    slippage_bps = positive_number(payload, "slippageBps", 1, 0, 100)
    entry_mode = str(payload.get("entryMode", "intrabar_close"))
    if entry_mode not in {"next_open", "intrabar_close"}:
        raise DashboardError("Chế độ vào lệnh không hợp lệ.")
    end = int(time.time())
    candles = fetch_ohlc(api, symbol, resolution, market_type, end - days * 86400, end)
    daily = fetch_ohlc(api, symbol, "1D", market_type, end - (days + 60) * 86400, end)
    strategy = IchimokuVolumeMultiTimeframeStrategy()
    trades, summary = run_backtest(
        candles, daily, strategy=strategy, commission_bps=commission_bps, slippage_bps=slippage_bps,
        entry_mode=entry_mode,
    )
    return {
        "symbol": symbol, "marketType": market_type, "resolution": resolution, "days": days,
        "summary": summary, "trades": [asdict(trade) for trade in trades],
        "chart": chart_data(candles, trades, strategy),
        "source": {
            "provider": "DNSE OpenAPI", "baseUrl": SESSION["base_url"], "endpoint": "/price/ohlc",
            "intraday": {"symbol": symbol, "resolution": resolution, "type": market_type, "from": end - days * 86400, "to": end},
            "dailyFilter": {"symbol": symbol, "resolution": "1D", "type": market_type, "from": end - (days + 60) * 86400, "to": end},
            "executionModel": (
                "Vào lệnh tại giá đóng nến N (proxy OHLC cho tín hiệu nội nến); Base129 vẫn xác nhận khi nến đóng và thoát ở giá mở nến kế tiếp. Không dùng TP/SL cố định."
                if entry_mode == "intrabar_close"
                else "Tín hiệu tại nến đóng; vào và thoát Base129 ở giá mở nến kế tiếp. Không dùng TP/SL cố định."
            ),
        },
    }


def public_demo_payload(resolution=None):
    """Return the read-only, two-timeframe demo used by local and Vercel UI."""
    base_payload = {
        "symbol": os.environ.get("OHLC_SYMBOL", "VN30F1M"),
        "marketType": os.environ.get("MARKET_TYPE", "DERIVATIVE"),
        "entryMode": "intrabar_close",
        "days": 10,
        "commissionBps": 2,
        "slippageBps": 1,
    }
    if resolution:
        if resolution not in {"1", "3"}:
            raise DashboardError("Khung thời gian demo không hợp lệ.")
        return run_visual_backtest({**base_payload, "resolution": resolution})
    return {"timeframes": {
        "1": run_visual_backtest({**base_payload, "resolution": "1"}),
        "3": run_visual_backtest({**base_payload, "resolution": "3"}),
    }}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).parent), **kwargs)

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        if self.path in {"/api/public-demo", "/api/public-demo-1", "/api/public-demo-3"}:
            try:
                resolution = self.path.rsplit("-", 1)[-1] if self.path != "/api/public-demo" else None
                return self.send_json(public_demo_payload(resolution))
            except DashboardError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            except Exception as exc:
                return self.send_json({"error": f"Không thể tải dữ liệu thị trường DNSE ({type(exc).__name__})."}, HTTPStatus.BAD_GATEWAY)
        if self.path.startswith("/api/"):
            try:
                require_access_token(self.headers)
            except DashboardError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        if self.path == "/api/health":
            try:
                load_server_credentials()
            except DashboardError:
                pass
            return self.send_json({"connected": bool(SESSION["api_key"] and SESSION["api_secret"]), "accountNo": SESSION["account_no"] or None, "tokenReady": bool(SESSION["trading_token"]), "apiVersion": SESSION["api_version"], "environmentOnly": ENV_ONLY})
        if self.path == "/api/operations":
            return self.send_json({"operations": safe_operations()})
        if self.path in {"/", "/index.html"}:
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        try:
            require_access_token(self.headers)
            size = int(self.headers.get("Content-Length", "0"))
            if size > MAX_BODY:
                raise DashboardError("Yêu cầu quá lớn.")
            payload = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(payload, dict):
                raise DashboardError("Dữ liệu gửi lên phải là một đối tượng.")
            if self.path == "/api/connect":
                return self.send_json(connect(payload))
            if self.path == "/api/connect-env":
                return self.send_json(connect_from_env())
            if self.path == "/api/run":
                return self.send_json(run_operation(payload))
            if self.path == "/api/ws":
                return self.send_json(asyncio.run(stream_snapshot(payload)))
            if self.path == "/api/backtest":
                return self.send_json(run_visual_backtest(payload))
            self.send_error(HTTPStatus.NOT_FOUND)
        except DashboardError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except json.JSONDecodeError:
            self.send_json({"error": "Dữ liệu gửi lên không hợp lệ."}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": f"Không thể hoàn tất yêu cầu: {exc}"}, HTTPStatus.BAD_GATEWAY)

    def send_json(self, data, status=HTTPStatus.OK):
        encoded = json.dumps(data, ensure_ascii=False, default=json_value, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    print(f"DNSE UI đang chạy tại http://{HOST}:{PORT}")
    print("Chỉ máy tính này mới truy cập được; nhấn Ctrl+C để dừng.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
