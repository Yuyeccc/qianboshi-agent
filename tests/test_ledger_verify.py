#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账本一致性校验 单测（57 号方案 C 节）。"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger_verify import verify_ledger  # noqa: E402

PORTFOLIO = ROOT / "data" / "portfolio.json"


def _base_portfolio() -> dict:
    """构造账本一致的最小组合。"""
    return {
        "updated": "2026-09-01",
        "holdings": {"027695": {"buy_amount": 500, "name": "电池ETF联接C"}},
        "closed_positions": [
            {"code": "000217", "name": "黄金", "cost": 800, "proceeds": 891.62,
             "sell_dates": ["2026-08-25", "2026-08-26"]},
            {"code": "159992", "name": "创新药", "cost": 989.01, "proceeds": 1026.3,
             "sell_date": "2026-08-11"},
        ],
        "history": [
            {"date": "2026-08-04", "action": "buy", "code": "000217", "amount": 500, "shares": 168.01},
            {"date": "2026-08-05", "action": "buy", "code": "000217", "amount": 100, "shares": 32.85},
            {"date": "2026-08-06", "action": "buy", "code": "000217", "amount": 100, "shares": 32.1},
            {"date": "2026-08-07", "action": "buy", "code": "000217", "amount": 100, "shares": 31.94},
            {"date": "2026-08-05", "action": "buy", "code": "159992", "amount": 989.01, "shares": 1100},
            {"date": "2026-08-11", "action": "sell", "code": "159992", "amount": 1026.3, "shares": 1100},
            {"date": "2026-08-24", "action": "buy", "code": "027695", "amount": 500, "shares": 564.78},
            {"date": "2026-08-25", "action": "sell", "code": "000217", "amount": 504.8, "shares": 150},
            {"date": "2026-08-26", "action": "sell", "code": "000217", "amount": 386.82, "shares": 114.9},
        ],
    }


class LedgerVerifyTests(unittest.TestCase):
    def test_01_real_portfolio_passes(self):
        """真实 portfolio.json 全 5 项通过（补流水后）"""
        pf = json.loads(PORTFOLIO.read_text(encoding="utf-8-sig"))
        r = verify_ledger(pf)
        self.assertTrue(r["ok"], f"errors: {r['errors']}")
        self.assertEqual(r["checks"]["buy_total"], 2289.01)
        self.assertEqual(r["checks"]["sell_total"], 1917.92)

    def test_02_synthetic_base_passes(self):
        r = verify_ledger(_base_portfolio())
        self.assertTrue(r["ok"], f"errors: {r['errors']}")

    def test_03_missing_buy_flow_fails(self):
        """缺买入流水 → 买入总额 != gross_invested + 持仓无流水"""
        pf = _base_portfolio()
        pf["history"] = [e for e in pf["history"] if not (e["code"] == "159992" and e["action"] == "buy")]
        r = verify_ledger(pf)
        self.assertFalse(r["ok"])
        self.assertTrue(any("买入总额" in e or "无买入流水" in e for e in r["errors"]))

    def test_04_missing_sell_flow_fails(self):
        """缺卖出流水 → 卖出总额 != recovered + sell 条数不匹配"""
        pf = _base_portfolio()
        pf["history"] = [e for e in pf["history"] if not (e["code"] == "159992" and e["action"] == "sell")]
        r = verify_ledger(pf)
        self.assertFalse(r["ok"])
        self.assertTrue(any("卖出总额" in e or "卖出流水" in e for e in r["errors"]))

    def test_05_amount_mismatch_fails(self):
        """金额不符（改少 1 笔买入）→ 总额不闭合"""
        pf = _base_portfolio()
        pf["history"][0]["amount"] = 400  # 500→400
        r = verify_ledger(pf)
        self.assertFalse(r["ok"])
        self.assertTrue(any("买入总额" in e for e in r["errors"]))

    def test_06_oversell_shares_fails(self):
        """卖出份额 > 买入份额 → 负数仓位"""
        pf = _base_portfolio()
        for e in pf["history"]:
            if e["code"] == "159992" and e["action"] == "sell":
                e["shares"] = 1200  # 卖超 100 份
        r = verify_ledger(pf)
        self.assertFalse(r["ok"])
        self.assertTrue(any("负数仓位" in e for e in r["errors"]))

    def test_07_extra_sell_flow_fails(self):
        """多出 1 条无对应 closed 的卖出流水 → sell 条数不匹配"""
        pf = _base_portfolio()
        pf["history"].append({"date": "2026-08-30", "action": "sell", "code": "000217",
                              "amount": 10.0, "shares": 3.0})
        r = verify_ledger(pf)
        self.assertFalse(r["ok"])
        self.assertTrue(any("卖出流水" in e for e in r["errors"]))


class DisciplineRegressionTests(unittest.TestCase):
    """#17v2 纪律检查不回归（补流水后口径不变）"""

    def test_08_discipline_no_regression(self):
        from discipline_checker import check_discipline
        pf = json.loads(PORTFOLIO.read_text(encoding="utf-8-sig"))
        rules = json.loads((ROOT / "config" / "discipline_rules.json").read_text(encoding="utf-8-sig"))
        r = check_discipline(pf, rules)
        self.assertEqual(r["net_invested"], 371.09)
        self.assertEqual(r["drawdown_status"], "profit")
        self.assertEqual(r["cost_drawdown"], -0.3474)
        # 真实违规照常（主题/单标的超限）
        types = {v["type"] for v in r["violations"]}
        self.assertIn("theme_cap", types)


if __name__ == "__main__":
    unittest.main(verbosity=2)
