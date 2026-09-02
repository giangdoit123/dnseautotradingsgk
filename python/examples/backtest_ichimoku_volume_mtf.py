#!/usr/bin/env python3
"""Backtest the one-minute Ichimoku-volume strategy on DNSE OHLC history.

This program only calls market-data endpoints. It never requests an OTP or
Trading Token and cannot submit an order.
"""
import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

EXAMPLES = Path(__file__).resolve().parent
sys.path[:0] = [str(EXAMPLES.parent), str(EXAMPLES)]

from dnse import DNSEClient
from env_util import load_dotenv
from strategy_base import Candle, Signal
from strategy_ichimoku_volume_mtf import IchimokuVolumeMultiTimeframeStrategy

VIETNAM_TZ = timezone(timedelta(hours=7))


@dataclass
class Trade:
    side: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    reason: str
    gross_pnl: float
    net_pnl: float


def _epoch(value) -> int:
    value = int(float(value))
    return value // 1000 if value > 1_000_000_000_000 else value


def _day(value: str):
    return datetime.fromtimestamp(_epoch(value), VIETNAM_TZ).date()


def _from_response(body: str) -> List[Candle]:
    payload = json.loads(body)
    columns = [payload.get(key, []) for key in ("t", "o", "h", "l", "c", "v")]
    if not all(isinstance(column, list) for column in columns):
        raise ValueError("DNSE OHLC response has an unexpected format")
    count = min(len(column) for column in columns)
    candles = [Candle(str(columns[0][i]), float(columns[1][i]), float(columns[2][i]),
                      float(columns[3][i]), float(columns[4][i]), float(columns[5][i]))
               for i in range(count)]
    return sorted(candles, key=lambda candle: _epoch(candle.time))


def fetch_ohlc(client, symbol: str, resolution: str, market_type: str, start: int, end: int):
    status, body = client.get_ohlc(
        bar_type=market_type,
        query={"symbol": symbol, "resolution": resolution, "from": start, "to": end},
    )
    if not status or status >= 300:
        raise RuntimeError(f"DNSE OHLC error [{status}]: {body}")
    candles = _from_response(body)
    if not candles:
        raise RuntimeError(f"DNSE returned no {resolution} candles for {symbol}")
    return candles


def _execution_price(raw_price: float, side: str, slippage_bps: float) -> float:
    """Apply adverse slippage: buys worse upward, sells worse downward."""
    factor = 1 + slippage_bps / 10_000 if side == "NB" else 1 - slippage_bps / 10_000
    return raw_price * factor


def _close_trade(open_trade, candle: Candle, reason: str, commission_bps: float, slippage_bps: float):
    exit_side = "NS" if open_trade["side"] == "NB" else "NB"
    exit_price = _execution_price(candle.open if reason == "base129_cross" else open_trade["raw_exit"], exit_side, slippage_bps)
    gross = (exit_price - open_trade["entry_price"]) * (1 if open_trade["side"] == "NB" else -1)
    costs = (open_trade["entry_price"] + exit_price) * commission_bps / 10_000
    return Trade(
        side=open_trade["side"], entry_time=open_trade["entry_time"], entry_price=open_trade["entry_price"],
        exit_time=candle.time, exit_price=exit_price, reason=reason, gross_pnl=gross, net_pnl=gross - costs,
    )


def run_backtest(
    candles_intraday: List[Candle],
    daily_candles: List[Candle],
    strategy=None,
    commission_bps: float = 2.0,
    slippage_bps: float = 1.0,
    entry_mode: str = "next_open",
):
    """Backtest with one open trade at a time and no look-ahead execution.

    ``next_open`` observes a completed candle then executes at the next open.
    ``intrabar_close`` executes an eligible entry at the current candle close,
    which keeps the entry on candle N. Historical OHLC does not contain each
    intrabar update, so the latter is explicitly a close-of-bar proxy for the
    live intrabar mode; it must not be described as a tick replay.

    Both modes keep Base129 exits conservative: the cross is confirmed by a
    completed candle and executed at the next candle open. There is no fixed
    take-profit or stop-loss.
    """
    if not candles_intraday:
        return [], {"trades": 0, "message": "No intraday candles"}
    if entry_mode not in {"next_open", "intrabar_close"}:
        raise ValueError("entry_mode must be 'next_open' or 'intrabar_close'")
    strategy = strategy or IchimokuVolumeMultiTimeframeStrategy()
    candles_intraday = sorted(candles_intraday, key=lambda candle: _epoch(candle.time))
    daily_candles = sorted(daily_candles, key=lambda candle: _epoch(candle.time))
    completed_daily, daily_index = [], 0
    trades, open_trade, pending_entry, pending_exit = [], None, None, None

    for index, candle in enumerate(candles_intraday):
        current_day = _day(candle.time)
        while daily_index < len(daily_candles) and _day(daily_candles[daily_index].time) < current_day:
            completed_daily.append(daily_candles[daily_index])
            daily_index += 1
        if hasattr(strategy, "set_daily_candles"):
            strategy.set_daily_candles(completed_daily)

        # Execute only decisions made after the previous bar had closed.
        if pending_exit and open_trade:
            open_trade["raw_exit"] = candle.open
            trades.append(_close_trade(open_trade, candle, pending_exit, commission_bps, slippage_bps))
            open_trade, pending_exit = None, None
        if pending_entry and open_trade is None:
            entry = _execution_price(candle.open, pending_entry.side, slippage_bps)
            open_trade = {
                "side": pending_entry.side, "entry_time": candle.time, "entry_price": entry,
            }
            pending_entry = None

        history = candles_intraday[:index + 1]
        if open_trade:
            should_exit, _ = strategy.should_exit_on_base_line_cross(open_trade["side"], history)
            if should_exit:
                pending_exit = "base129_cross"
        elif pending_entry is None:
            signal: Signal = strategy.analyze(history)
            if signal.actionable and index + 1 < len(candles_intraday):
                if entry_mode == "intrabar_close":
                    entry = _execution_price(candle.close, signal.side, slippage_bps)
                    open_trade = {
                        "side": signal.side, "entry_time": candle.time, "entry_price": entry,
                    }
                else:
                    pending_entry = signal

    if open_trade:
        final = candles_intraday[-1]
        open_trade["raw_exit"] = final.close
        trades.append(_close_trade(open_trade, final, "end_of_data", commission_bps, slippage_bps))
    return trades, summary(trades)


def summary(trades: List[Trade]):
    if not trades:
        return {"trades": 0, "message": "No completed trades"}
    equity, peak, max_drawdown = 0.0, 0.0, 0.0
    for trade in trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    winners = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losers = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    win_total, loss_total = sum(winners), abs(sum(losers))
    return {
        "trades": len(trades),
        "wins": len(winners),
        "win_rate_pct": round(100 * len(winners) / len(trades), 2),
        "net_pnl_points": round(sum(trade.net_pnl for trade in trades), 4),
        "gross_pnl_points": round(sum(trade.gross_pnl for trade in trades), 4),
        "profit_factor": round(win_total / loss_total, 4) if loss_total else None,
        "max_drawdown_points": round(max_drawdown, 4),
        "exit_reasons": {reason: sum(1 for trade in trades if trade.reason == reason)
                         for reason in sorted({trade.reason for trade in trades})},
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only DNSE OHLC backtest")
    parser.add_argument("--symbol", default=os.getenv("OHLC_SYMBOL", "VN30F1M"))
    parser.add_argument("--market-type", default=os.getenv("MARKET_TYPE", "DERIVATIVE"))
    parser.add_argument("--resolution", default="1", help="Intraday OHLC resolution in minutes (default: 1)")
    parser.add_argument("--days", type=int, default=30, help="Calendar days of intraday history")
    parser.add_argument("--commission-bps", type=float, default=2.0)
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    parser.add_argument(
        "--entry-mode", choices=("next_open", "intrabar_close"), default="next_open",
        help="next_open = xác nhận nến đóng, intrabar_close = vào tại giá đóng nến N (proxy OHLC)",
    )
    parser.add_argument("--output", help="Optional JSON report path")
    parser.add_argument("--show-trades", action="store_true", help="Print every simulated trade")
    args = parser.parse_args()
    if args.days < 5:
        parser.error("--days must be at least 5")

    load_dotenv()
    client = DNSEClient(
        api_key=os.environ.get("DNSE_API_KEY", ""), api_secret=os.environ.get("DNSE_API_SECRET", ""),
        base_url=os.environ.get("DNSE_BASE_URL", "https://openapi.dnse.com.vn"),
        api_version=os.environ.get("DNSE_API_VERSION", "2026-07-23"),
    )
    if not client._api_key or not client._api_secret:
        raise SystemExit("DNSE_API_KEY and DNSE_API_SECRET are required in examples/.env")
    end = int(time.time())
    candles_intraday = fetch_ohlc(
        client, args.symbol, args.resolution, args.market_type, end - args.days * 86400, end
    )
    # Daily data starts earlier to make the RSI filter available from the first test day.
    daily = fetch_ohlc(client, args.symbol, "1D", args.market_type, end - (args.days + 60) * 86400, end)
    trades, report = run_backtest(
        candles_intraday, daily, commission_bps=args.commission_bps, slippage_bps=args.slippage_bps,
        entry_mode=args.entry_mode,
    )
    result = {"symbol": args.symbol, "market_type": args.market_type, "resolution": args.resolution, "days": args.days,
              "assumptions": {"commission_bps_per_side": args.commission_bps, "slippage_bps_per_side": args.slippage_bps,
                              "entry_exit": (
                                  "current candle close OHLC proxy for intrabar entries; Base129 exits at next open; no fixed TP/SL"
                                  if args.entry_mode == "intrabar_close"
                                  else "next candle open after each confirmed Base129 signal; no fixed TP/SL"
                              )},
              "summary": report, "trades": [asdict(trade) for trade in trades]}
    display = result if args.show_trades else {key: value for key, value in result.items() if key != "trades"}
    print(json.dumps(display, ensure_ascii=False, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
