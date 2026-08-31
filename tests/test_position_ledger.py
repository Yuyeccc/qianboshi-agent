import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from position_ledger import build_ledger, verify_ledger_model  # noqa: E402


def portfolio(history, holdings=None, closed=None):
    return {
        "version": 3,
        "updated": "2026-09-01",
        "holdings": holdings or {},
        "cash": 0,
        "currency": "CNY",
        "total_cost": 0.0,
        "closed_positions": closed or [],
        "history": history,
    }


class PositionLedgerTests(unittest.TestCase):
    def test_fifo_partial_consume_single_lot(self):
        # 买 100 份@1.0，卖 40 份@1.5 → realized 20，剩余 60 份成本 60
        p = portfolio(
            [
                {"date": "2026-08-01", "action": "buy", "code": "A", "amount": 100, "shares": 100, "nav": 1.0},
                {"date": "2026-08-02", "action": "sell", "code": "A", "amount": 60, "shares": 40, "price": 1.5},
            ],
            holdings={"A": {"shares": 60, "avg_cost": 1.0, "buy_amount": 100, "name": "测试A"}},
            closed=[],
        )
        lm = build_ledger(p)["codes"]["A"]
        self.assertEqual(lm["remaining_shares"], 60)
        self.assertEqual(lm["remaining_cost"], 60)
        self.assertEqual(lm["realized_pnl"], 20.0)  # 60 - 40 = 20
        self.assertEqual(lm["avg_cost"], 1.0)

    def test_fifo_consumes_multiple_lots_in_order(self):
        # lot1: 50份@2.0(成本100), lot2: 50份@3.0(成本150)；卖 80 份@4.0
        # 消耗 lot1 全部 + lot2 的 30/50 → cost = 100 + 150*0.6 = 190；realized = 320-190 = 130
        p = portfolio(
            [
                {"date": "2026-08-01", "action": "buy", "code": "B", "amount": 100, "shares": 50, "nav": 2.0},
                {"date": "2026-08-03", "action": "buy", "code": "B", "amount": 150, "shares": 50, "nav": 3.0},
                {"date": "2026-08-05", "action": "sell", "code": "B", "amount": 320, "shares": 80, "price": 4.0},
            ],
            holdings={"B": {"shares": 20, "avg_cost": 3.0, "buy_amount": 50, "name": "测试B"}},
        )
        lm = build_ledger(p)["codes"]["B"]
        self.assertEqual(lm["remaining_shares"], 20)
        self.assertEqual(lm["realized_pnl"], 130.0)
        self.assertEqual(lm["remaining_cost"], 60)  # lot2 剩余 20 份 × 3.0
        self.assertEqual(lm["avg_cost"], 3.0)

    def test_realized_matches_closed_pnl_real_data(self):
        # 用仓库真实账本：realized 总额 == closed.pnl 合计
        with open(ROOT / "data" / "portfolio.json", encoding="utf-8-sig") as f:
            p = json.load(f)
        result = verify_ledger_model(p)
        self.assertTrue(result["ok"], f"对账失败: {result['errors']}")
        self.assertEqual(result["checks"]["realized_total"], result["checks"]["closed_pnl"])
        # 027695 剩余份额与 avg_cost 精确匹配 holdings
        h = p["holdings"]["027695"]
        lm = result["ledger"]["codes"]["027695"]
        self.assertEqual(lm["remaining_shares"], h["shares"])
        self.assertAlmostEqual(lm["avg_cost"], h["avg_cost"], places=4)

    def test_empty_history_does_not_crash(self):
        p = portfolio([], holdings={"X": {"shares": 1, "avg_cost": 1.0, "buy_amount": 1, "name": "无流水"}})
        result = verify_ledger_model(p)
        self.assertFalse(result["ok"])  # 无流水持仓 → 对账失败（报告缺口，不崩）
        self.assertTrue(any("无记录" in e for e in result["errors"]))

    def test_account_field_defaults_main(self):
        p = portfolio(
            [
                {"date": "2026-08-01", "action": "buy", "code": "C", "amount": 50, "shares": 50, "nav": 1.0},
            ]
        )
        lm = build_ledger(p)["codes"]["C"]
        self.assertEqual(lm["lots"][0]["account"], "main")

    def test_fifo_cost_uses_amount_not_nav_product(self):
        # 关键口径：nav×shares 有舍入差，成本必须用 amount 字段
        p = portfolio(
            [
                {"date": "2026-08-01", "action": "buy", "code": "D", "amount": 100, "shares": 33.34, "nav": 2.9994},
                {"date": "2026-08-02", "action": "sell", "code": "D", "amount": 150, "shares": 33.34, "price": 4.5},
            ],
            holdings={},
            closed=[{"code": "D", "cost": 100, "proceeds": 150, "pnl": 50.0}],
        )
        lm = build_ledger(p)["codes"]["D"]
        # 33.34×2.9994 = 100.0（此例恰好一致），换真实舍入场景：用 0.8853×564.78=500.02 vs amount 500
        p2 = portfolio(
            [
                {"date": "2026-08-24", "action": "buy", "code": "E", "amount": 500, "shares": 564.78, "nav": 0.8853},
                {"date": "2026-08-25", "action": "sell", "code": "E", "amount": 250, "shares": 282.39, "price": 0.9},
            ],
            holdings={"E": {"shares": 282.39, "avg_cost": 0.8853, "buy_amount": 250, "name": "测试E"}},
        )
        lm2 = build_ledger(p2)["codes"]["E"]
        # 若用 nav×shares=500.02 摊成本，剩余成本=250.01；amount 口径=250.00（与 buy_amount 精确一致）
        self.assertEqual(lm2["remaining_cost"], 250.0)
        self.assertAlmostEqual(lm2["realized_pnl"], 4.15, places=2)  # 254.15 - 250.00 = 4.15


if __name__ == "__main__":
    unittest.main()
