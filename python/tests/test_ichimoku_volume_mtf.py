import os
import sys
import unittest
from datetime import datetime, timedelta, timezone


EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
sys.path.insert(0, EXAMPLES)

from strategy_base import Candle
from strategy_ichimoku_volume_mtf import IchimokuVolumeMultiTimeframeStrategy


def candle(index, close=100.0, volume=100.0, high=None, low=None):
    return Candle(
        time=str(index), open=close, close=close, volume=volume,
        high=close + 1 if high is None else high,
        low=close - 1 if low is None else low,
    )


def daily_balanced():
    return [candle(index, close=100.0 + (index % 2), volume=1) for index in range(30)]


def atc_candle(hour=14, minute=45, close=110, volume=200):
    vietnam_tz = timezone(timedelta(hours=7))
    timestamp = int(datetime(2026, 8, 26, hour, minute, tzinfo=vietnam_tz).timestamp())
    return Candle(str(timestamp), close, close + 1, close - 1, close, volume)


class IchimokuVolumeMultiTimeframeTests(unittest.TestCase):
    def test_long_when_base_line_rises_and_volume_is_two_times_ma20(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        strategy.set_daily_candles(daily_balanced())
        bars = [candle(index) for index in range(154)]
        bars.append(candle(154, close=110, high=111, low=109, volume=200))

        signal = strategy.analyze(bars)

        self.assertEqual(signal.side, "NB")
        self.assertIsNone(signal.stop_loss)
        self.assertIsNone(signal.take_profit)

    def test_long_requires_base_line_to_be_above_kumo(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        strategy.set_daily_candles(daily_balanced())
        bars = [candle(index) for index in range(154)]
        # This high is only in the cloud's shifted Base Line window, not the
        # current Base Line window. It puts current Base129 at the Kumo top.
        bars[0] = candle(0, close=100, high=121, low=119, volume=100)
        bars.append(candle(154, close=110, high=111, low=109, volume=200))

        signal = strategy.analyze(bars)

        self.assertFalse(signal.actionable)
        self.assertIn("not above Kumo", signal.reason)

    def test_long_can_enter_below_base_line_without_fixed_stop_or_target(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        strategy.set_daily_candles(daily_balanced())
        bars = [candle(index) for index in range(154)]
        bars.append(candle(154, close=100, high=111, low=99, volume=200))

        signal = strategy.analyze(bars)

        self.assertEqual(signal.side, "NB")
        self.assertIsNone(signal.stop_loss)
        self.assertIsNone(signal.take_profit)

    def test_daily_rsi_above_60_blocks_long(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        strategy.set_daily_candles([candle(index, close=100 + index, volume=1) for index in range(30)])
        bars = [candle(index) for index in range(154)]
        bars.append(candle(154, close=110, high=111, low=109, volume=200))

        signal = strategy.analyze(bars)

        self.assertFalse(signal.actionable)
        self.assertIn("long blocked", signal.reason)

    def test_short_when_base_line_falls_and_volume_is_two_times_ma20(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        strategy.set_daily_candles(daily_balanced())
        bars = [candle(index) for index in range(154)]
        bars.append(candle(154, close=90, high=91, low=89, volume=200))

        signal = strategy.analyze(bars)

        self.assertEqual(signal.side, "NS")
        self.assertIsNone(signal.stop_loss)
        self.assertIsNone(signal.take_profit)

    def test_short_requires_base_line_to_be_below_kumo(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        strategy.set_daily_candles(daily_balanced())
        bars = [candle(index) for index in range(154)]
        # This low is only in the cloud's shifted Base Line window, not the
        # current Base Line window. It puts current Base129 at the Kumo bottom.
        bars[0] = candle(0, close=100, high=81, low=79, volume=100)
        bars.append(candle(154, close=90, high=91, low=89, volume=200))

        signal = strategy.analyze(bars)

        self.assertFalse(signal.actionable)
        self.assertIn("not below Kumo", signal.reason)

    def test_short_can_enter_above_base_line_without_fixed_stop_or_target(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        strategy.set_daily_candles(daily_balanced())
        bars = [candle(index) for index in range(154)]
        bars.append(candle(154, close=100, high=101, low=89, volume=200))

        signal = strategy.analyze(bars)

        self.assertEqual(signal.side, "NS")
        self.assertIsNone(signal.stop_loss)
        self.assertIsNone(signal.take_profit)

    def test_no_entry_when_base_line_is_flat(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        strategy.set_daily_candles(daily_balanced())
        bars = [candle(index) for index in range(130)]
        bars[-1] = candle(129, close=100, high=101, low=99, volume=200)

        signal = strategy.analyze(bars)

        self.assertFalse(signal.actionable)
        self.assertIn("no setup", signal.reason)

    def test_1445_candle_uses_normal_entry_conditions(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        strategy.set_daily_candles(daily_balanced())
        bars = [candle(index) for index in range(154)]
        bars.append(atc_candle())

        signal = strategy.analyze(bars)

        self.assertEqual(signal.side, "NB")

    def test_long_exits_only_after_closed_candle_crosses_below_base_line(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        bars = [candle(index) for index in range(129)]
        bars.append(candle(129, close=90, high=91, low=89, volume=100))

        should_exit, reason = strategy.should_exit_on_base_line_cross("NB", bars)

        self.assertTrue(should_exit)
        self.assertIn("crossed below", reason)

    def test_short_exits_only_after_closed_candle_crosses_above_base_line(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        bars = [candle(index) for index in range(129)]
        bars.append(candle(129, close=110, high=111, low=109, volume=100))

        should_exit, reason = strategy.should_exit_on_base_line_cross("NS", bars)

        self.assertTrue(should_exit)
        self.assertIn("crossed above", reason)


if __name__ == "__main__":
    unittest.main()
