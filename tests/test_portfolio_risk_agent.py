"""portfolio_risk_agent.py 单测（P2-B）：确定性持仓匹配/估值/schema/合规（不调 LLM 不写盘）"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from portfolio_risk_agent import (  # noqa: E402
    build_report,
    match_exposed,
    validate_report,
)

# 真实持仓只读夹具（portfolio.json 为现役数据，仅读取）
import portfolio_risk_agent as pra  # noqa: E402

REAL = json.loads((ROOT / "data" / "portfolio.json").read_text(encoding="utf-8-sig"))["holdings"]


class MatchTests(unittest.TestCase):
    def test_match_gold_etf(self):
        hit = match_exposed("黄金", REAL)
        self.assertEqual([h["code"] for h in hit], ["518880"])
        self.assertIn("黄金", hit[0]["relation"])

    def test_match_china_state_construction(self):
        hit = match_exposed("中国建筑", REAL)
        self.assertEqual([h["code"] for h in hit], ["601668"])

    def test_match_battery_sector(self):
        hit = match_exposed("电池", REAL)
        self.assertEqual([h["code"] for h in hit], ["027695"])

    def test_match_sector_keyword_in_entity(self):
        """entity 是板块词但持仓 sector 命中：新能源 → 电池 ETF。"""
        hit = match_exposed("新能源", REAL)
        self.assertEqual([h["code"] for h in hit], ["027695"])

    def test_no_relation(self):
        self.assertEqual(match_exposed("光模块", REAL), [])
        self.assertEqual(match_exposed("", REAL), [])


class BuildReportTests(unittest.TestCase):
    def setUp(self):
        self.portfolio = {
            "holdings": {
                "518880": {"name": "华安黄金ETF", "sector": "黄金", "market_code": "518880.SS",
                           "shares": 200, "avg_cost": 9.1895},
                "601668": {"name": "中国建筑", "sector": "基建/中字头", "market_code": "601668.SS",
                           "shares": 200, "avg_cost": 4.4423},
            },
            "snapshot": {"date": "2026-09-01", "total_assets": 18690.61,
                         "market_value_onmarket": 2695.6, "cash_available": 15511.11,
                         "position_pct": 14.42},
        }

    def test_no_llm_report_schema_valid(self):
        """确定性降级报告（无 LLM）必须 schema 合法。"""
        exposed = match_exposed("黄金", self.portfolio["holdings"])
        rep = build_report("黄金波动", "黄金", self.portfolio, exposed, llm_out=None)
        ok, errs = validate_report(rep)
        self.assertTrue(ok, msg=f"schema 错误: {errs}")
        self.assertEqual(rep["_meta"]["agent_type"], "portfolio_risk")
        self.assertFalse(rep["_meta"]["llm_used"])
        self.assertEqual(rep["riskPoints"], [])
        self.assertIn("analysisNote", rep)

    def test_no_relation_report_schema_valid(self):
        exposed = match_exposed("光模块", self.portfolio["holdings"])
        rep = build_report("光模块", "光模块", self.portfolio, exposed, llm_out=None)
        ok, errs = validate_report(rep)
        self.assertTrue(ok, msg=f"schema 错误: {errs}")
        self.assertEqual(rep["holdingsExposure"]["exposed"], [])

    def test_llm_out_merged_and_schema_valid(self):
        llm = {"summary": "结论", "riskPoints": [{"risk": "下行", "severity": "high",
                                                 "rationale": "依据", "watch": "观察"}],
               "watchlist": [{"text": "金价", "trigger": "破位"}]}
        exposed = match_exposed("黄金", self.portfolio["holdings"])
        rep = build_report("黄金波动", "黄金", self.portfolio, exposed, llm_out=llm)
        ok, errs = validate_report(rep)
        self.assertTrue(ok, msg=f"schema 错误: {errs}")
        self.assertEqual(rep["riskPoints"][0]["severity"], "high")
        self.assertTrue(rep["_meta"]["llm_used"])

    def test_compliance_fixed_by_code(self):
        """合规字段代码固定：不经 LLM（LLM 输出即使带交易词也不进 compliance）。"""
        evil_llm = {"summary": "买入！", "riskPoints": [{"risk": "x", "severity": "low",
                                                       "rationale": "y"}], "watchlist": []}
        exposed = match_exposed("黄金", self.portfolio["holdings"])
        rep = build_report("g", "黄金", self.portfolio, exposed, llm_out=evil_llm)
        self.assertTrue(rep["compliance"]["passed"])
        self.assertIn("不含任何交易指令", rep["compliance"]["note"])
        self.assertNotIn("买入", rep["compliance"]["note"])

    def test_job_id_meta(self):
        exposed = match_exposed("黄金", self.portfolio["holdings"])
        rep = build_report("g", "黄金", self.portfolio, exposed, llm_out=None)
        rep["_meta"]["job_id"] = "abc123"
        self.assertEqual(rep["_meta"]["job_id"], "abc123")

    def test_schema_file_exists_and_is_valid_json(self):
        self.assertTrue((ROOT / "docs" / "31_risk_v0.1.schema.json").exists())
        schema = json.loads((ROOT / "docs" / "31_risk_v0.1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["title"], "持仓风险评估报告 v0.1（portfolio_risk agent 产物协议）")


if __name__ == "__main__":
    unittest.main()
