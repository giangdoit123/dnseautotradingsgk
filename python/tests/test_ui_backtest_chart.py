import importlib.util
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "examples"))

from strategy_base import Candle
from backtest_ichimoku_volume_mtf import Trade
from strategy_ichimoku_volume_mtf import IchimokuVolumeMultiTimeframeStrategy


spec = importlib.util.spec_from_file_location("dnse_ui_server", os.path.join(ROOT, "ui", "server.py"))
ui_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui_server)


def candle(index):
    price = 100 + index * 0.1
    return Candle(str(1_700_000_000 + index * 60), price, price + 1, price - 1, price + 0.2, 100)


class UiBacktestChartTests(unittest.TestCase):
    def test_environment_is_inferred_from_configured_base_url(self):
        previous = os.environ.get("DNSE_BASE_URL")
        try:
            os.environ["DNSE_BASE_URL"] = "https://openapi-uat.dnse.com.vn"
            self.assertEqual(ui_server.configured_environment(), "uat")
            os.environ["DNSE_BASE_URL"] = "https://openapi.dnse.com.vn"
            self.assertEqual(ui_server.configured_environment(), "production")
        finally:
            if previous is None:
                os.environ.pop("DNSE_BASE_URL", None)
            else:
                os.environ["DNSE_BASE_URL"] = previous

    def test_chart_data_compacts_bars_and_keeps_indicator_marker_coordinates(self):
        strategy = IchimokuVolumeMultiTimeframeStrategy()
        candles = [candle(index) for index in range(180)]
        trade = Trade(
            side="NB", entry_time=candles[42].time, entry_price=candles[42].open,
            exit_time=candles[87].time, exit_price=candles[87].open,
            reason="base129_cross", gross_pnl=1, net_pnl=1,
        )
        chart = ui_server.chart_data(candles, [trade], strategy, max_bars=25)

        self.assertLessEqual(chart["displayBars"], 25)
        self.assertTrue(chart["aggregated"])
        self.assertIsNotNone(chart["bars"][-1]["base"])
        self.assertIsNotNone(chart["bars"][-1]["leadA"])
        self.assertIsNotNone(chart["bars"][-1]["leadB"])
        self.assertIsNotNone(chart["bars"][-1]["volumeMa"])
        self.assertIn("sourceStart", chart["bars"][0])
        self.assertEqual(chart["markers"][0]["sourceIndex"], 42)
        self.assertEqual(chart["markers"][1]["sourceIndex"], 87)


if __name__ == "__main__":
    unittest.main()
