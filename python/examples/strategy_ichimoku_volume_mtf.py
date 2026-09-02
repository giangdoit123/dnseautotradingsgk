#!/usr/bin/env python3
"""Intraday Ichimoku/volume strategy with daily RSI and Kumo filters.

This module only decides whether a setup exists.  The auto-trader remains in
dry-run mode unless PLACE_ORDER=1 is deliberately configured.
"""
from typing import List

from indicators import rsi
from strategy_base import Candle, Signal, Strategy, register


@register
class IchimokuVolumeMultiTimeframeStrategy(Strategy):
    """Trade configured intraday candles while filtering long setups.

    Entry rules:
    - Long when the 129-period Base Line is rising, is above the current Kumo,
      and current volume is at least 2x the preceding 20-bar volume SMA. Daily
      RSI must not exceed 60.
    - Short when the Base Line is falling, is below the current Kumo, and
      current volume is at least 2x the preceding 20-bar volume SMA.
    The close may be on either side of the Base Line. There is deliberately no
    fixed take-profit or stop-loss: a position is exited only on the specified
    closed-candle Base129 cross in the opposite direction.
    """

    name = "ichimoku_volume_mtf"

    def __init__(
        self,
        base_line_period: int = 129,
        volume_ma_period: int = 20,
        daily_rsi_period: int = 14,
        daily_long_rsi_ceiling: float = 60.0,
        conversion_period: int = 9,
        span_b_period: int = 52,
        displacement: int = 26,
    ):
        self.base_line_period = base_line_period
        self.volume_ma_period = volume_ma_period
        self.daily_rsi_period = daily_rsi_period
        self.daily_long_rsi_ceiling = daily_long_rsi_ceiling
        self.conversion_period = conversion_period
        self.span_b_period = span_b_period
        self.displacement = displacement
        self._daily_candles: List[Candle] = []

    def set_daily_candles(self, candles: List[Candle]) -> None:
        """Refresh the daily context, supplied by the auto-trader."""
        self._daily_candles = list(candles)

    @staticmethod
    def _midpoint(candles: List[Candle], end: int, period: int) -> float:
        window = candles[end - period + 1:end + 1]
        return (max(candle.high for candle in window) + min(candle.low for candle in window)) / 2.0

    def _cloud_at_current_candle(self, candles: List[Candle]):
        """Return Leading Span A/B displayed at the latest candle, or ``None``.

        Leading spans are calculated ``displacement`` candles earlier, because
        that is the cloud visually aligned with the latest candle. Span A uses
        the 9-period Conversion Line and this strategy's 129-period Base Line;
        Span B uses its standard 52-period midpoint.
        """
        past = len(candles) - 1 - self.displacement
        if past < max(self.base_line_period, self.span_b_period) - 1:
            return None
        conversion = self._midpoint(candles, past, self.conversion_period)
        past_base = self._midpoint(candles, past, self.base_line_period)
        lead_span_a = (conversion + past_base) / 2.0
        lead_span_b = self._midpoint(candles, past, self.span_b_period)
        return lead_span_a, lead_span_b

    def should_exit_on_base_line_cross(self, side: str, candles: List[Candle]):
        """Return ``(should_exit, reason)`` on a *closed* candle crossover.

        Long positions exit when the close crosses from on/above the previous
        Base Line to below the current Base Line. Short positions use the
        mirrored upward cross. The two Base Line values are recalculated at
        their respective candle closes, avoiding a look-ahead calculation.
        """
        if side not in ("NB", "NS") or len(candles) < self.base_line_period + 1:
            return False, "need one extra candle to confirm Base Line cross"
        previous, current = candles[-2], candles[-1]
        previous_window = candles[-self.base_line_period - 1:-1]
        current_window = candles[-self.base_line_period:]
        previous_base = (max(c.high for c in previous_window) + min(c.low for c in previous_window)) / 2.0
        current_base = (max(c.high for c in current_window) + min(c.low for c in current_window)) / 2.0

        if side == "NB" and previous.close >= previous_base and current.close < current_base:
            return True, (f"long exit: close crossed below Base129 "
                          f"({previous.close:.2f}→{current.close:.2f}; "
                          f"base {previous_base:.2f}→{current_base:.2f})")
        if side == "NS" and previous.close <= previous_base and current.close > current_base:
            return True, (f"short exit: close crossed above Base129 "
                          f"({previous.close:.2f}→{current.close:.2f}; "
                          f"base {previous_base:.2f}→{current_base:.2f})")
        return False, "no Base129 cross"

    def analyze(self, candles: List[Candle]) -> Signal:
        required = max(self.base_line_period + 1, self.volume_ma_period + 1)
        if len(candles) < required:
            return Signal(reason=f"need {required} candles, have {len(candles)}")
        if len(self._daily_candles) <= self.daily_rsi_period:
            return Signal(reason=f"need {self.daily_rsi_period + 1} daily candles, have {len(self._daily_candles)}")

        last = candles[-1]
        previous_base_window = candles[-self.base_line_period - 1:-1]
        base_window = candles[-self.base_line_period:]
        previous_base_line = (
            max(c.high for c in previous_base_window) + min(c.low for c in previous_base_window)
        ) / 2.0
        base_line = (max(c.high for c in base_window) + min(c.low for c in base_window)) / 2.0
        volume_ma = sum(c.volume for c in candles[-self.volume_ma_period - 1:-1]) / self.volume_ma_period
        if volume_ma <= 0:
            return Signal(reason="volume MA20 is zero → skip")

        daily_rsi = rsi([c.close for c in self._daily_candles], self.daily_rsi_period)
        if daily_rsi is None:
            return Signal(reason="not enough daily closes for RSI")
        volume_ratio = last.volume / volume_ma

        base_line_rising = base_line > previous_base_line
        if base_line_rising and volume_ratio >= 2.0:
            cloud = self._cloud_at_current_candle(candles)
            if cloud is None:
                needed = self.base_line_period + self.displacement
                return Signal(reason=f"need {needed} candles to evaluate the current Kumo, have {len(candles)}")
            lead_span_a, lead_span_b = cloud
            cloud_top = max(lead_span_a, lead_span_b)
            if base_line <= cloud_top:
                return Signal(
                    reason=(f"long skipped: Base129 rising {previous_base_line:.2f}→{base_line:.2f} "
                            f"but is not above Kumo top={cloud_top:.2f} "
                            f"(Lead A={lead_span_a:.2f}, Lead B={lead_span_b:.2f})"),
                )
            if daily_rsi > self.daily_long_rsi_ceiling:
                return Signal(
                    reason=(f"long blocked: daily RSI={daily_rsi:.1f} > "
                            f"{self.daily_long_rsi_ceiling:.0f} (close={last.close:.2f} > "
                            f"base={base_line:.2f}; base129 rising {previous_base_line:.2f}→"
                            f"{base_line:.2f} > Kumo={cloud_top:.2f}; volume={volume_ratio:.2f}x MA20)"),
                )
            return Signal(
                side="NB",
                entry=last.close,
                reason=(f"LONG: Base129 rising {previous_base_line:.2f}→{base_line:.2f}; "
                        f"base129 > Kumo={cloud_top:.2f}; "
                        f"volume={volume_ratio:.2f}x MA20; "
                        f"daily RSI={daily_rsi:.1f}"),
            )

        base_line_falling = base_line < previous_base_line
        if base_line_falling and volume_ratio >= 2.0:
            cloud = self._cloud_at_current_candle(candles)
            if cloud is None:
                needed = self.base_line_period + self.displacement
                return Signal(reason=f"need {needed} candles to evaluate the current Kumo, have {len(candles)}")
            lead_span_a, lead_span_b = cloud
            cloud_bottom = min(lead_span_a, lead_span_b)
            if base_line >= cloud_bottom:
                return Signal(
                    reason=(f"short skipped: Base129 falling {previous_base_line:.2f}→{base_line:.2f} "
                            f"but is not below Kumo bottom={cloud_bottom:.2f} "
                            f"(Lead A={lead_span_a:.2f}, Lead B={lead_span_b:.2f})"),
                )
            return Signal(
                side="NS",
                entry=last.close,
                reason=(f"SHORT: Base129 falling {previous_base_line:.2f}→{base_line:.2f}; "
                        f"base129 < Kumo={cloud_bottom:.2f}; "
                        f"volume={volume_ratio:.2f}x MA20; "
                        f"daily RSI={daily_rsi:.1f}"),
            )

        return Signal(
            reason=(f"no setup: Base129={previous_base_line:.2f}→{base_line:.2f}, "
                    f"volume={volume_ratio:.2f}x MA20, daily RSI={daily_rsi:.1f}"),
        )
