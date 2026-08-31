import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from market_context import build_market_context, sector_market_score  # noqa: E402


class MarketContextTests(unittest.TestCase):
    def test_relative_strength_uses_sector_and_benchmark_changes(self):
        watchlist = {
            "光模块": {
                "market_proxy": "159770.SZ",
                "benchmark": "399006.SZ",
                "core_symbol_codes": {"新易盛": "300502.SZ"},
            }
        }
        cache = {
            "159770.SZ": {"price": 1.23, "change_pct": 2.5, "prices": [1.2, 1.23]},
            "399006.SZ": {"price": 2200, "change_pct": 1.0, "prices": [2180, 2200]},
            "300502.SZ": {"price": 110, "change_pct": 3.0, "prices": [107, 110]},
        }

        ctx = build_market_context(watchlist=watchlist, cache=cache, trade_date="2026-07-21")
        info = ctx["sectors"]["光模块"]

        self.assertEqual(info["return_pct"], 2.5)
        self.assertEqual(info["benchmark_return_pct"], 1.0)
        self.assertEqual(info["relative_strength"], 1.5)
        self.assertGreater(info["score"], 0)
        self.assertEqual(ctx["symbols"]["300502.SZ"]["change_pct"], 3.0)

    def test_missing_change_pct_does_not_invent_zero_return(self):
        watchlist = {"创新药": {"market_proxy": "159992.SZ", "benchmark": "399006.SZ"}}
        cache = {
            "159992.SZ": {"price": 0.82, "prices": [0.82]},
            "399006.SZ": {"price": 2200, "change_pct": 1.0, "prices": [2180, 2200]},
        }

        ctx = build_market_context(watchlist=watchlist, cache=cache, trade_date="2026-07-21")
        info = ctx["sectors"]["创新药"]

        self.assertIsNone(info["return_pct"])
        self.assertIsNone(info["relative_strength"])
        self.assertEqual(info["source"], "cached")
        self.assertIn("未计算涨跌", "；".join(ctx["notes"]))

    def test_null_market_proxy_stays_missing(self):
        watchlist = {"机器人": {"market_proxy": None, "proxy_note": "待核验，禁止误用ETF"}}

        ctx = build_market_context(watchlist=watchlist, cache={}, trade_date="2026-07-21")
        info = ctx["sectors"]["机器人"]

        self.assertIsNone(info["market_proxy"])
        self.assertEqual(info["source"], "missing")
        self.assertEqual(info["score"], 0)
        self.assertIn("待核验", "；".join(info["notes"]))

    def test_sector_market_score_uses_relative_strength_and_turnover(self):
        strong = {"relative_strength": 1.5, "turnover_vs_5d": 1.4}
        weak = {"relative_strength": -0.5, "turnover_vs_5d": 0.8}

        self.assertGreater(sector_market_score(strong), sector_market_score(weak))
        self.assertGreaterEqual(sector_market_score(strong), 0)
        self.assertLessEqual(sector_market_score(strong), 1)


if __name__ == "__main__":
    unittest.main()
