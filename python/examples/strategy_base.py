#!/usr/bin/env python3
"""Pluggable strategy interface for the auto-trader demo.

A strategy takes the recent candle history and returns a Signal describing the
trade to take. A strategy may optionally define price-based stop-loss and
take-profit levels; it is not required to do so.

To add your own strategy: subclass Strategy, decorate it with @register, give it
a unique `name`, and import your module before calling get_strategy(name).
See strategy_price_action.py for a minimal reference implementation.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Candle:
    """One OHLCV bar."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    """A strategy decision. side=None means 'do nothing'."""

    side: Optional[str] = None       # "NB" = long/buy, "NS" = short/sell, None = flat
    entry: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""

    @property
    def actionable(self) -> bool:
        return self.side in ("NB", "NS")


class Strategy(ABC):
    """Base class every strategy implements."""

    name: str = "base"

    @abstractmethod
    def analyze(self, candles: List[Candle]) -> Signal:
        """Return a Signal given the recent candle history (oldest -> newest)."""
        raise NotImplementedError


# ─── Registry (so customers can swap strategies by name) ─────────────────────
_REGISTRY = {}


def register(cls):
    """Class decorator: register a Strategy subclass under its `name`."""
    _REGISTRY[cls.name] = cls
    return cls


def get_strategy(name, **kwargs) -> Strategy:
    """Instantiate a registered strategy by name (kwargs go to its __init__)."""
    if name not in _REGISTRY:
        raise ValueError(f"unknown strategy '{name}'; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**kwargs)
