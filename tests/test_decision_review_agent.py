"""decision_review_agent.py 单测（P2-C）：决策选择/组装/schema/合规（只读 DB 不调 LLM 不写盘）"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from decision_review_agent import (  # noqa: E402
    _fetch_decisions,
    _pick_decision,
    build_report,
    validate_report,
)


def fake_decision(decision_id="dec_2026-08-06_GOLD_001", asset_id="GOLD", asset_name="黄金",
                  direction="bullish", status="reviewed"):
    return {
        "decision_id": decision_id, "asset_id": asset_id, "asset_name": asset_name,
        "asset_type": "商品", "direction": direction, "horizon": "medium",
        "conviction": 0.6, "decision_date": "2026-08-06", "thesis": "测试论点",
        "key_reasons": ["理由1"], "premise": ["前提1"], "invalidation_conditions": ["证伪1"],
        "action_note": None, "status": status,
    }


FAKE_REVIEW = {
    "review_date": "2026-08-26", "horizon_days": 20, "outcome_return": 2.35,
    "benchmark_return": None, "excess_return": None, "max_drawdown": None,
    "result_label": "right", "what_went_right": "判断成立", "what_went_wrong": None,
    "missed_factors": None, "over_weighted_factors": None, "new_rule_learned": None,
}


class PickDecisionTests(unittest.TestCase):
    def setUp(self):
        self.decs = [
            fake_decision(),
            fake_decision("dec_2026-08-06_TECH_001", "TECH", "科技股", "bearish"),
        ]

    def test_match_by_asset_id(self):
        d = _pick_decision("GOLD", self.decs)
        self.assertEqual(d["asset_id"], "GOLD")

    def test_match_by_asset_name(self):
        d = _pick_decision("科技", self.decs)
        self.assertEqual(d["asset_id"], "TECH")

    def test_no_match_takes_latest(self):
        """无匹配 → 取最新一条（列表首位，fetch 已按日期降序）。"""
        d = _pick_decision("光模块", self.decs)
        self.assertEqual(d["decision_id"], "dec_2026-08-06_GOLD_001")

    def test_empty_entity_takes_latest(self):
        d = _pick_decision("", self.decs)
        self.assertEqual(d["decision_id"], "dec_2026-08-06_GOLD_001")

    def test_no_decisions_returns_none(self):
        self.assertIsNone(_pick_decision("黄金", []))


class BuildReportTests(unittest.TestCase):
    def test_reviewed_report_schema_valid(self):
        d = fake_decision()
        rep = build_report("复盘黄金", "GOLD", d, FAKE_REVIEW, llm_out=None)
        ok, errs = validate_report(rep)
        self.assertTrue(ok, msg=f"schema 错误: {errs}")
        self.assertEqual(rep["reviewStatus"], "reviewed")
        self.assertEqual(rep["outcome"]["resultLabel"], "right")
        self.assertEqual(rep["decisionId"], "dec_2026-08-06_GOLD_001")

    def test_pending_outcome_no_review(self):
        d = fake_decision(status="open")
        rep = build_report("复盘", "GOLD", d, None, llm_out=None)
        ok, errs = validate_report(rep)
        self.assertTrue(ok, msg=f"schema 错误: {errs}")
        self.assertEqual(rep["reviewStatus"], "pending_outcome")
        self.assertIsNone(rep["outcome"])

    def test_all_null_review_outcome_null(self):
        """review 行映射字段全空 → outcome=null 不留空对象。"""
        d = fake_decision()
        rep = build_report("复盘", "GOLD", d, {"result_label": None, "review_date": None}, llm_out=None)
        self.assertIsNone(rep["outcome"])

    def test_label_only_review_outcome_keeps_label_and_date(self):
        """review 仅有 label+date 无数值 → outcome 保留非空字段（snake→camel 映射）。"""
        d = fake_decision()
        rep = build_report("复盘", "GOLD", d, {"result_label": "right", "review_date": "2026-08-26"}, llm_out=None)
        self.assertEqual(rep["outcome"], {"resultLabel": "right", "reviewDate": "2026-08-26"})

    def test_llm_lessons_merged(self):
        llm = {"summary": "复盘结论", "lessons": [{"type": "premise", "lesson": "量化前提", "evidence": "X"}]}
        d = fake_decision()
        rep = build_report("复盘", "GOLD", d, FAKE_REVIEW, llm_out=llm)
        ok, errs = validate_report(rep)
        self.assertTrue(ok, msg=f"schema 错误: {errs}")
        self.assertEqual(rep["summary"], "复盘结论")
        self.assertEqual(rep["lessons"][0]["type"], "premise")
        self.assertTrue(rep["_meta"]["llm_used"])

    def test_llm_lessons_schema_strict(self):
        """LLM 输出 type 非法（交易类词也不得进 compliance/lessons type 枚举）。"""
        llm = {"summary": "买入建议", "lessons": [{"type": "advice", "lesson": "快买"}]}
        d = fake_decision()
        rep = build_report("复盘", "GOLD", d, FAKE_REVIEW, llm_out=llm)
        ok, errs = validate_report(rep)
        self.assertFalse(ok)  # type=advice 违反枚举 → schema 拦
        self.assertTrue(rep["compliance"]["passed"])
        self.assertIn("不含任何交易指令", rep["compliance"]["note"])

    def test_compliance_fixed_by_code(self):
        d = fake_decision()
        rep = build_report("复盘", "GOLD", d, FAKE_REVIEW, llm_out=None)
        self.assertTrue(rep["compliance"]["passed"])
        self.assertIn("不含任何交易指令", rep["compliance"]["note"])

    def test_meta_agent_type(self):
        d = fake_decision()
        rep = build_report("复盘", "GOLD", d, FAKE_REVIEW, llm_out=None)
        self.assertEqual(rep["_meta"]["agent_type"], "decision_review")


class ReadOnlyTests(unittest.TestCase):
    def test_real_db_read_only_snapshot(self):
        """现役 DB 只读：fetch 正常且不产生写副作用（对比行数不变）。"""
        before = None
        with __import__("decision_db").connect() as conn:
            before = conn.execute("SELECT COUNT(*) FROM user_decision_logs").fetchone()[0]
        decs = _fetch_decisions()
        self.assertGreaterEqual(len(decs), 1)
        with __import__("decision_db").connect() as conn:
            after = conn.execute("SELECT COUNT(*) FROM user_decision_logs").fetchone()[0]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
