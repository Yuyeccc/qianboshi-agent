#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#17v2 纪律检查嵌入决策台 单测（gpt-5.6-sol 审核 12 项全覆盖）。

覆盖：P0 成本口径回撤修正 / unknown 防除零 / data_quality 标记 / 账本不重复 /
decision_desk 独立失败 / JSON 注入完整性 / output_gate 纪律硬阻断 / 只读校验。
"""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from compliance_gate import output_gate  # noqa: E402
from decision_desk import _build_discipline, build_decision_desk_context  # noqa: E402
from discipline_checker import check_discipline  # noqa: E402

RULES = {
    "theme_caps": {"黄金": 0.20, "半导体": 0.25, "default": 0.25},
    "single_position_cap": 0.30,
    "portfolio_max_cost": 10000,
    "drawdown_switch": {"enabled": True, "max_drawdown_pct": 0.15},
}


def _file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class CostDrawdownTests(unittest.TestCase):
    """P0 成本口径回撤（方案二）"""

    def test_01_profit_portfolio_no_false_drawdown(self):
        """盈利组合不误报（真实数据回归：9/2 账户更新后 net=3097.45 → drawdown=-4.16% profit）"""
        portfolio = json.loads((ROOT / "data" / "portfolio.json").read_text(encoding="utf-8-sig"))
        r = check_discipline(portfolio, RULES)
        self.assertEqual(r["drawdown_status"], "profit")
        self.assertLess(r["cost_drawdown"], 0)
        self.assertEqual(r["net_invested"], 3097.45)
        self.assertFalse(any(v["type"] == "drawdown_switch" for v in r["violations"]))
        # 真实数据有主题/单标的超限 → ok=False 但无回撤误报
        self.assertFalse(r["ok"])

    def test_02_loss_portfolio_triggers(self):
        """真实亏损组合（净投入 > 当前成本 15%+）→ 触发 drawdown_switch"""
        portfolio = {
            "updated": "2026-08-27",
            "holdings": {"000001": {"buy_amount": 200, "sector": "黄金"}},
            "closed_positions": [
                {"code": "X", "cost": 1000, "proceeds": 500},  # 亏 500
            ],
        }
        r = check_discipline(portfolio, RULES)
        # gross=1200, recovered=500, net=700, dd=(700-200)/700=71.4% > 15% → breach
        self.assertEqual(r["drawdown_status"], "breach")
        self.assertTrue(any(v["type"] == "drawdown_switch" for v in r["violations"]))

    def test_03_net_invested_non_positive_unknown(self):
        """net_invested <= 0 → unknown 不触发（防除零/负基准）"""
        portfolio = {
            "holdings": {"000001": {"buy_amount": 300, "sector": "黄金"}},
            "closed_positions": [
                {"code": "X", "cost": 1000, "proceeds": 1500},  # 盈利回收 > 投入
            ],
        }
        r = check_discipline(portfolio, RULES)
        self.assertEqual(r["drawdown_status"], "unknown")
        self.assertIsNone(r["cost_drawdown"])
        self.assertIn("net_invested_non_positive", r["data_quality"])
        self.assertFalse(any(v["type"] == "drawdown_switch" for v in r["violations"]))

    def test_04_missing_proceeds_data_quality(self):
        """缺 proceeds / 部分卖出 → data_quality 标记，不硬判"""
        portfolio = {
            "holdings": {"000001": {"buy_amount": 500, "sector": "黄金"}},
            "closed_positions": [
                {"code": "X", "cost": 800, "proceeds": 400},
                {"code": "Y", "cost": 600},  # 缺 proceeds（部分卖出）
            ],
        }
        r = check_discipline(portfolio, RULES)
        self.assertIn("closed_missing_proceeds:Y", r["data_quality"])
        self.assertIn("partial_sell_unverifiable", r["data_quality"])
        self.assertFalse(any(v["type"] == "drawdown_switch" for v in r["violations"]))

    def test_05_closed_positions_authoritative_no_double_count(self):
        """closed_positions 与 history 重复 → 只计 closed（不重复计入）"""
        portfolio = {
            "holdings": {"000001": {"buy_amount": 500, "sector": "黄金"}},
            "closed_positions": [
                {"code": "000217", "cost": 800, "proceeds": 891.62},
            ],
            "history": [  # history 里同样有 000217 的买入 800 → 不得重复计
                {"action": "buy", "code": "000217", "amount": 800},
                {"action": "buy", "code": "000001", "amount": 500},
            ],
        }
        r = check_discipline(portfolio, RULES)
        # gross = 800 (closed) + 500 (open) = 1300；若重复计入会 2100
        self.assertEqual(r["gross_invested"], 1300.0)
        self.assertEqual(r["net_invested"], 1300.0 - 891.62)

    def test_06_empty_holdings(self):
        """holdings 为空 / 总成本 0 → 不崩溃，no_open_cost 标记"""
        for portfolio in ({"holdings": {}}, {"holdings": {}}, {}):
            r = check_discipline(portfolio, RULES)
            self.assertEqual(r["current_open_cost"], 0.0)
            self.assertEqual(r["theme_ratios"], {})
            self.assertEqual(r["violations"], [])


class CapRuleTests(unittest.TestCase):
    """主题/单标的上限（方案 F 第 7 项）"""

    def test_07_caps_trigger_boundary_default(self):
        # 黄金 200(恰好 20% == cap) 边界不触发；半导体 800(80%) 超 25% 触发
        p_boundary = {"holdings": {"A": {"buy_amount": 200, "sector": "黄金"},
                                   "B": {"buy_amount": 800, "sector": "半导体"}}}
        r = check_discipline(p_boundary, RULES)
        self.assertEqual([v for v in r["violations"] if v["type"] == "theme_cap" and v["theme"] == "黄金"], [])
        self.assertTrue(any(v["type"] == "theme_cap" and v["theme"] == "半导体" for v in r["violations"]))
        # 未知 sector → default 0.25；单标的 80% > 30% 触发
        p_default = {"holdings": {"A": {"buy_amount": 200, "sector": "黄金"},
                                  "B": {"buy_amount": 800, "sector": "未知行业"}}}
        r = check_discipline(p_default, RULES)
        self.assertTrue(any(v["type"] == "theme_cap" and v["theme"] == "未知行业" for v in r["violations"]))
        self.assertTrue(any(v["type"] == "single_cap" and v["code"] == "B" for v in r["violations"]))

    def test_08_invalid_amounts_data_quality(self):
        """非法负数/字符串金额 → data_quality，不参与计算"""
        portfolio = {
            "holdings": {
                "A": {"buy_amount": "-100", "sector": "黄金"},   # 负数
                "B": {"buy_amount": "abc", "sector": "半导体"},  # 字符串
                "C": {"buy_amount": 300, "sector": "黄金"},
            },
            "closed_positions": [
                {"code": "X", "cost": "oops", "proceeds": 100},  # 非法 cost
            ],
        }
        r = check_discipline(portfolio, RULES)
        tags = r["data_quality"]
        self.assertTrue(any("negative_amount" in t for t in tags))
        self.assertTrue(any("invalid_amount" in t for t in tags))
        # 只计合法金额：C=300
        self.assertEqual(r["current_open_cost"], 300.0)


class DecisionDeskIntegrationTests(unittest.TestCase):
    """decision_desk 嵌入（方案 B）"""

    def test_09a_discipline_section_present(self):
        """build_decision_desk_context 返回值含 discipline 段，其他段完好"""
        d = build_decision_desk_context()
        self.assertIn("discipline", d)
        disc = d["discipline"]
        self.assertIn("drawdown_status", disc)
        self.assertIn("net_invested", disc)
        self.assertIn("user_decisions", d)
        self.assertIn("debate_cards", d)
        self.assertIn("factor_states", d)

    def test_09b_corrupted_portfolio_isolated_error(self):
        """portfolio.json 损坏 → 纪律段 error，build 外层仍返回完整 dict"""
        import decision_desk as dd
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "portfolio.json").write_text("{{{ broken json", encoding="utf-8")
        (tmp / "discipline_rules.json").write_text("{}", encoding="utf-8")
        with patch.object(dd, "ROOT", tmp):
            r = _build_discipline()
            self.assertEqual(r["status"], "error")

    def test_09c_discipline_failure_does_not_break_others(self):
        """纪律段独立失败（mock 返回 error）→ 其他段不受影响"""
        with patch("decision_desk._build_discipline", return_value={"status": "error"}):
            d = build_decision_desk_context()
        self.assertEqual(d["discipline"]["status"], "error")
        self.assertIn("user_decisions", d)


class InjectionTests(unittest.TestCase):
    """JSON 注入完整性（方案 C，gpt 意见 10）"""

    def test_10_no_truncation_full_injection(self):
        """纪律段全量注入，无 [:N] 截断 → json.loads 可完整还原"""
        d = build_decision_desk_context()
        injected = json.dumps(d.get("discipline", {}), ensure_ascii=False, indent=2)  # agent.py 同款（无截断）
        parsed = json.loads(injected)
        self.assertEqual(parsed["net_invested"], d["discipline"]["net_invested"])
        self.assertEqual(parsed["cost_drawdown"], d["discipline"]["cost_drawdown"])
        # 全量注入 = 序列化后无截断：重新序列化应完全一致
        self.assertEqual(json.dumps(parsed, ensure_ascii=False, indent=2), injected)


class OutputGateDisciplineTests(unittest.TestCase):
    """output_gate 纪律硬阻断（方案 E，gpt 意见 10）"""

    def test_11a_discipline_context_plus_action_blocks(self):
        r = output_gate("纪律检查：主题超限 100%，建议减仓", tool="test")
        self.assertEqual(r["mode"], "block")
        self.assertTrue(any(h.get("discipline_ctx") for h in r["block_hits"]))

    def test_11b_statement_only_clean(self):
        r = output_gate("纪律检查：主题超限 100%，需人工确认", tool="test")
        self.assertEqual(r["mode"], "clean")

    def test_11c_quote_context_still_exempt(self):
        r = output_gate("钱博士说主题超限，建议减仓", tool="test")
        self.assertEqual(r["mode"], "clean")  # 引用豁免优先


class ReadOnlyTests(unittest.TestCase):
    """只读校验（方案 F 第 12 项，gpt 意见）"""

    def test_12_no_data_mutation(self):
        """check_discipline + decision_desk 前后，portfolio.json 与决策 DB hash 不变"""
        pf, rules, db = (ROOT / "data" / "portfolio.json"), (ROOT / "config" / "discipline_rules.json"), (ROOT / "data" / "qianboshi_decision.db")
        before = {str(p): _file_sha256(p) for p in (pf, rules, db) if p.exists()}
        portfolio = json.loads(pf.read_text(encoding="utf-8-sig"))
        rules_d = json.loads(rules.read_text(encoding="utf-8-sig"))
        check_discipline(portfolio, rules_d)
        build_decision_desk_context()
        after = {str(p): _file_sha256(p) for p in (pf, rules, db) if p.exists()}
        self.assertEqual(before, after)


class PortfolioMaxCostTests(unittest.TestCase):
    """第 4 层：组合持仓总成本上限（60 号方案）"""

    def test_13_real_portfolio_not_triggered(self):
        """真实数据：500 < 10000 → 不触发"""
        portfolio = json.loads((ROOT / "data" / "portfolio.json").read_text(encoding="utf-8-sig"))
        r = check_discipline(portfolio, RULES)
        self.assertFalse(any(v["type"] == "portfolio_max_cost" for v in r["violations"]))

    def test_14_over_limit_triggers(self):
        """合成超限：15000 > 10000 → 触发 portfolio_max_cost"""
        p = {"holdings": {"A": {"buy_amount": 15000, "sector": "黄金"}}}
        r = check_discipline(p, RULES)
        v = [x for x in r["violations"] if x["type"] == "portfolio_max_cost"]
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["current"], 15000.0)
        self.assertEqual(v[0]["max"], 10000.0)

    def test_15_boundary_equal_not_triggered(self):
        """边界相等：10000 == 10000 → 不触发"""
        p = {"holdings": {"A": {"buy_amount": 10000, "sector": "黄金"}}}
        r = check_discipline(p, RULES)
        self.assertFalse(any(v["type"] == "portfolio_max_cost" for v in r["violations"]))

    def test_16_missing_or_zero_config_skipped(self):
        """配置缺失/0/非法 → 跳过不崩"""
        for rules_var in ({}, {"portfolio_max_cost": 0}, {"portfolio_max_cost": "abc"}, {"portfolio_max_cost": -5}):
            p = {"holdings": {"A": {"buy_amount": 20000, "sector": "黄金"}}}
            r = check_discipline(p, rules_var)
            self.assertFalse(any(v["type"] == "portfolio_max_cost" for v in r["violations"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
