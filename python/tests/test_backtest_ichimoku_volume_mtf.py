import os
import sys
import unittest
from datetime import datetime, timedelta, timezone


EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
sys.path.insert(0, EXAMPLES)

from backtest_ichimoku_volume_mtf import run_backtest
from strategy_base import Candle, Signal


def candle(index, open_price, high, low, close):
    return Candle(str(1_700_000_000 + index * 180), open_price, high, low, close, 100)


class EntryThenCrossStrategy:
    def set_daily_candles(self, _candles):
        pass

    def analyze(self, history):
        return Signal(side="NB", entry=history[-1].close) if len(history) == 1 else Signal()

    def should_exit_on_base_line_cross(self, _side, history):
        return (len(history) == 2), "cross"


class BacktestTests(unittest.TestCase):
    def test_does_not_close_on_intrabar_extremes_without_fixed_tp_or_sl(self):
        bars = [
            candle(0, 100, 101, 99, 100),
            candle(1, 101, 106, 94, 104),
            candle(2, 103, 104, 96, 98),
            candle(3, 97, 99, 96, 98),
        ]
        trades, report = run_backtest(bars, [], strategy=EntryThenCrossStrategy(), commission_bps=0, slippage_bps=0)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].entry_price, 101)
        # Candle 1 spans both former 2R levels, yet the trade survives until
        # the Base129 cross observed at candle 1 and exits at candle 2's open.
        self.assertEqual(trades[0].exit_price, 103)
        self.assertEqual(trades[0].reason, "base129_cross")
        self.assertEqual(report["trades"], 1)

    def test_base_line_cross_exits_at_following_open(self):
        bars = [
            candle(0, 100, 101, 99, 100),
            candle(1, 100, 102, 98, 99),
            candle(2, 97, 99, 96, 98),
        ]
        trades, _ = run_backtest(bars, [], strategy=EntryThenCrossStrategy(), commission_bps=0, slippage_bps=0)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].reason, "base129_cross")
        self.assertEqual(trades[0].exit_price, 97)

    def test_intrabar_close_mode_enters_on_signal_candle(self):
        bars = [
            candle(0, 100, 101, 99, 100),
            candle(1, 101, 106, 94, 104),
            candle(2, 103, 104, 96, 98),
        ]
        trades, report = run_backtest(
            bars, [], strategy=EntryThenCrossStrategy(), commission_bps=0, slippage_bps=0,
            entry_mode="intrabar_close",
        )

        self.assertEqual(len(trades), 1)
        # The first completed OHLC bar is a historical proxy for the forming
        # candle: execution is attached to candle N, never candle N+1.
        self.assertEqual(trades[0].entry_time, bars[0].time)
        self.assertEqual(trades[0].entry_price, bars[0].close)
        self.assertEqual(trades[0].exit_price, bars[2].open)
        self.assertEqual(report["trades"], 1)

    def test_opens_a_position_when_next_candle_is_1430(self):
        vietnam_tz = timezone(timedelta(hours=7))
        def atc_bar(minute):
            timestamp = int(datetime(2026, 8, 26, 14, minute, tzinfo=vietnam_tz).timestamp())
            return Candle(str(timestamp), 100, 101, 99, 100, 100)

        # The first candle creates a signal. Its next executable candle happens
        # to be 14:30, but time of day must not change the strategy decision.
        trades, report = run_backtest(
            [atc_bar(29), atc_bar(30), atc_bar(31)], [],
            strategy=EntryThenCrossStrategy(), commission_bps=0, slippage_bps=0,
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].entry_time, atc_bar(30).time)
        self.assertEqual(trades[0].entry_price, 100)
        self.assertEqual(report["trades"], 1)


if __name__ == "__main__":
    unittest.main()
