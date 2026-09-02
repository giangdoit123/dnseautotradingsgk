#!/usr/bin/env python3
"""Run independent 1-minute and 3-minute Ichimoku-volume auto-traders.

Each timeframe is a separate child process with its own candle buffer and
position-state file. Signals, entries and Base129 exits are intentionally not
combined or filtered against the other timeframe. PLACE_ORDER remains opt-in.
"""
import os
import subprocess
import sys
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXAMPLES))

from env_util import load_dotenv


def timeframes(value: str):
    """Parse TIMEFRAMES while keeping this runner limited to 1m and 3m."""
    values = tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    if not values or any(item not in {"1", "3"} for item in values):
        raise ValueError("TIMEFRAMES must contain one or both of: 1,3")
    return values


def main():
    load_dotenv()
    frames = timeframes(os.environ.get("TIMEFRAMES", "1,3"))
    strategy = os.environ.get("STRATEGY", "ichimoku_volume_mtf")
    runner = Path(__file__).with_name("auto-trader.py")
    processes = []

    for resolution in frames:
        child_env = os.environ.copy()
        child_env["RESOLUTION"] = resolution
        child_env["STRATEGY"] = strategy
        # Keep restart recovery state independent for each timeframe.
        child_env["DNSE_POSITION_STORE"] = str(EXAMPLES / f".position_{resolution}m.json")
        print(f"Khởi động luồng độc lập {resolution}m với chiến lược '{strategy}' (PLACE_ORDER={child_env.get('PLACE_ORDER', '0')})")
        processes.append(subprocess.Popen([sys.executable, str(runner)], env=child_env))

    try:
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        print("Dừng các luồng 1m/3m...")
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait()


if __name__ == "__main__":
    main()
