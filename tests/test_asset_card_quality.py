#!/usr/bin/env python3
"""71号方案 #10/#8 资产卡三维 单测（含缺数传播修正 P0-2 + 禁词红线）。

覆盖：资料充分度徽标、质量因子卡、8问框架、三类卡适用性（ETF/commodity/sector）、
缺数不产生方向/置信、渲染禁词。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from asset_card_builder import (
    _render_analysis_framework,
    _render_data_status_badge,
    _render_quality_factors,
    render_asset_card,
)
import factor_state_refresher as fsr
from factor_state_refresher import _answer_question, _base_state, _judge_qf


# ---------------------------------------------------------------------------
# 缺数传播修正（P0-2）
# ---------------------------------------------------------------------------

class TestMissingPropagation:
    def test_missing_state_no_confidence_no_direction(self):
        st = _base_state(
            {"factor_id": "F1", "factor_name": "测试因子", "impact_rule": {"relation": "positive", "strength": "high"}},
            "TEST", "2026-09-01", "数据缺失", "unknown", "neutral", {}, [],
        )
        assert st["confidence"] is None
        assert st["impact_direction"] == "unknown"
        assert "影响待定" in st["summary"]
        assert "构成" not in st["summary"]

    def test_manual_missing_value_unknown_direction(self):
        factor = {
            "factor_id": "M1", "factor_name": "手工因子", "data_binding": {"type": "manual", "manual_value": "待更新"},
            "impact_rule": {"relation": "positive", "strength": "medium"},
        }
        st = fsr.refresh_factor(factor, "TEST", "2026-09-01")
        assert st["impact_direction"] == "unknown"
        assert st["confidence"] is None

    def test_manual_valid_value_uses_relation(self):
        factor = {
            "factor_id": "M2", "factor_name": "手工因子", "data_binding": {"type": "manual", "manual_value": "A=抬升"},
            "impact_rule": {"relation": "positive", "strength": "medium"},
        }
        st = fsr.refresh_factor(factor, "TEST", "2026-09-01")
        assert st["impact_direction"] == "positive"
        assert st["confidence"] == 0.8

    def test_known_state_normal(self):
        st = _base_state(
            {"factor_id": "F2", "factor_name": "正常因子", "impact_rule": {"relation": "negative", "strength": "high"}},
            "TEST", "2026-09-01", "近5日走强+2.10%", "up", "negative", {}, [],
        )
        assert st["confidence"] == 0.8
        assert st["impact_direction"] == "negative"


# ---------------------------------------------------------------------------
# _judge_qf 质量因子判定
# ---------------------------------------------------------------------------

class TestJudgeQF:
    @pytest.mark.parametrize(
        "fid,metrics,expected_judgement",
        [
            ("LEVERAGE", {"liability_to_asset": 0.80}, "高杠杆"),
            ("LEVERAGE", {"liability_to_asset": 0.50}, "正常"),
            ("LEVERAGE", {"liability_to_asset": 0.20}, "低杠杆"),
            ("LEVERAGE", {}, "待补"),
            ("INTEREST_COVERAGE", {"ebit_to_interest": 2.0}, "充裕"),
            ("INTEREST_COVERAGE", {"ebit_to_interest": 0.7}, "正常"),
            ("INTEREST_COVERAGE", {"ebit_to_interest": 0.3}, "偏紧"),
            ("CASHFLOW_QUALITY", {"cfo_to_np": 1.2}, "含金量高"),
            ("CASHFLOW_QUALITY", {"cfo_to_np": 0.3}, "含金量低"),
            ("ASSET_STRUCTURE", {"tangible_to_asset": 0.80}, "重资产"),
            ("ASSET_STRUCTURE", {"tangible_to_asset": 0.30}, "轻资产"),
            ("IMPAIRMENT_EXPOSURE", {}, "待补（免费接口无减值科目）"),
        ],
    )
    def test_thresholds(self, fid, metrics, expected_judgement):
        assert _judge_qf(fid, metrics)["judgement"] == expected_judgement

    def test_impairment_never_guesses(self):
        r = _judge_qf("IMPAIRMENT_EXPOSURE", {"whatever": 1.0})
        assert r["value"] is None  # 无科目 → 永不产生数值


# ---------------------------------------------------------------------------
# _answer_question 8问答案
# ---------------------------------------------------------------------------

class TestAnswerQuestion:
    def test_q1_trend_improved(self):
        periods = [
            {"found": True, "metrics": {"cfo_to_or": 0.12}},
            {"found": True, "metrics": {"cfo_to_or": 0.08}},
        ]
        r = _answer_question("Q1", periods, periods[0])
        assert "改善" in r["answer"]
        assert r["status"] == "available"

    def test_q1_missing_pending(self):
        r = _answer_question("Q1", [], {"found": False})
        assert r["answer"] == "—"
        assert r["status"] == "pending"

    def test_q2_interest_coverage(self):
        fund = {"found": True, "metrics": {"ebit_to_interest": 2.5}}
        r = _answer_question("Q2", [fund], fund)
        assert "能覆盖" in r["answer"]

    def test_q8_impairment_pending(self):
        # 减值无科目 → 诚实待补，绝不编
        fund = {"found": True, "metrics": {"net_profit": 100.0}}
        r = _answer_question("Q8", [fund], fund)
        assert r["answer"] == "—"
        assert r["status"] == "pending"


# ---------------------------------------------------------------------------
# 渲染：徽标 / 质量因子 / 8问 / 三维卡
# ---------------------------------------------------------------------------

class TestRenderBlocks:
    def test_badge_four_states(self):
        badge = _render_data_status_badge(
            {"market": "available", "views": "pending", "fundamentals": "insufficient", "valuation": "na"}
        )
        assert "行情✅已拿到" in badge
        assert "观点⏳待补" in badge
        assert "财报⚠️不足" in badge
        assert "估值⛔不适用" in badge

    def test_badge_empty(self):
        assert _render_data_status_badge({}) == ""

    def test_quality_factors_empty(self):
        assert _render_quality_factors([]) == ""

    def test_quality_factors_render(self):
        text = _render_quality_factors([
            {"factor_name": "杠杆", "value": 55.0, "unit": "%", "judgement": "正常", "period": "2026Q2", "source": "baostock"},
            {"factor_name": "减值暴露", "value": None, "unit": "-", "judgement": "待补", "period": "2026Q2", "source": "baostock"},
        ])
        assert "杠杆" in text and "55.0%" in text
        assert "待补" in text  # 缺值显示 — 不编数字

    def test_framework_na_for_etf(self):
        text = _render_analysis_framework([])
        assert "不适用" in text

    def test_framework_render(self):
        text = _render_analysis_framework([
            {"question_id": "Q1", "question": "现金流趋势？", "dimension": "现金流", "answer": "改善", "status": "available"},
            {"question_id": "Q8", "question": "减值？", "dimension": "减值", "answer": "—", "status": "pending"},
        ])
        assert "Q1" in text and "现金流趋势" in text and "改善" in text
        assert "待补" in text

    def test_full_card_three_dimensions(self):
        """验收总纲6：三维（便宜/质量/资料）区分可见 + 无买卖文案。"""
        card = {
            "asset_id": "ALUMINUM", "asset_name": "铝", "version": 1,
            "logic_chain_summary": "正向驱动来自紫金矿业代理。",
            "data_status": {"market": "available", "views": "available", "fundamentals": "available", "valuation": "available"},
            "factors": [
                {"factor_name": "紫金矿业代理", "current_state": "近5日走强+2.1%", "change_direction": "up",
                 "impact_direction": "positive", "impact_strength": "medium", "evidence_refs": []},
            ],
            "quality_factors": [
                {"factor_name": "盈利质量", "value": 1.11, "unit": "倍", "judgement": "含金量高", "period": "2026Q2", "source": "baostock"},
            ],
            "analysis_framework": [
                {"question_id": "Q2", "question": "利息覆盖？", "dimension": "现金流", "answer": "能覆盖（2.5倍）", "status": "available"},
            ],
            "valuation": {
                "status": "ok", "level": "临界", "pe_rank": 8.9, "pb_rank": 74.5,
                "pe_current": 13.23, "pb_current": 4.43, "samples": {"valid": 732},
                "risk_columns": [
                    {"name": "杠杆", "value": 49.6, "judgement": "正常", "period": "2026Q2", "source": "baostock", "unit": "%"},
                ],
            },
        }
        text = render_asset_card(card)
        assert "📦 资料充分度" in text            # #10 资料
        assert "质量因子卡" in text                # #10 质量
        assert "8问框架" in text                   # #8 质量
        assert "估值水位" in text and "临界" in text  # #9 价格
        assert "估值≠安全边际" in text
        for phrase in ("值得买", "可以买", "买入", "低估可入", "建议买入"):
            assert phrase not in text, f"渲染含禁词: {phrase}"

    def test_etf_card_honest_na(self):
        """ETF/商品卡：财报/估值 na 诚实标注，8问显示不适用。"""
        card = {
            "asset_id": "GOLD", "asset_name": "黄金", "version": 1,
            "logic_chain_summary": "当前黄金的……。",
            "data_status": {"market": "available", "views": "available", "fundamentals": "na", "valuation": "na"},
            "factors": [],
            "quality_factors": [],
            "analysis_framework": [],
            "valuation": None,
        }
        text = render_asset_card(card)
        assert "财报⛔不适用" in text
        assert "估值⛔不适用" in text
        assert "8问框架不适用" in text
        assert "估值水位" not in text  # 无 valuation → 不渲染估值区


# ---------------------------------------------------------------------------
# build_quality_snapshot 三类卡适用性（monkeypatch 网络）
# ---------------------------------------------------------------------------

class TestQualitySnapshot:
    def test_etf_card_all_na(self, monkeypatch):
        """commodity/sector 卡（无 fundamentals_symbol）→ 财报/估值 na，无 8问/质量因子。"""
        monkeypatch.setattr(fsr, "load_views", lambda: [{"view_id": "v1"}])
        monkeypatch.setattr(fsr, "_load_json", lambda path: {"601899.SS": {}})
        config = {"asset_id": "GOLD", "asset_type": "commodity", "factors": []}
        snap = fsr.build_quality_snapshot(config, "2026-09-01")
        assert snap["data_status"]["market"] == "available"
        assert snap["data_status"]["fundamentals"] == "na"
        assert snap["data_status"]["valuation"] == "na"
        assert snap["quality_factors"] == []
        assert snap["analysis_framework"] == []
        assert snap["valuation"] is None

    def test_stock_card_full(self, monkeypatch):
        """个股卡（fundamentals_symbol）→ 财报 available、质量因子/8问/估值齐全。"""
        monkeypatch.setattr(fsr, "load_views", lambda: [{"view_id": "v1"}])
        monkeypatch.setattr(fsr, "_load_json", lambda path: {"601899.SS": {}})
        fund = {
            "found": True, "stat_date": "2026-06-30", "pub_date": "2026-08-25",
            "period": "2026Q2", "source": "baostock",
            "metrics": {
                "liability_to_asset": 0.496, "yoy_liability": 5.0, "current_ratio": 1.5,
                "cfo_to_np": 1.11, "cfo_to_or": 0.12, "ebit_to_interest": 2.5,
                "np_margin": 0.13, "gp_margin": 0.18, "nca_to_asset": 0.55,
                "tangible_to_asset": 0.20,
            },
        }
        monkeypatch.setattr(fsr, "fetch_fundamentals_periods", lambda *a, **k: [
            fund,
            {**fund, "period": "2026Q1", "metrics": {**fund["metrics"], "cfo_to_or": 0.08}},
        ])
        monkeypatch.setattr(
            fsr, "compute_valuation",
            lambda *a, **k: {"status": "ok", "level": "临界", "pe_rank": 8.9, "pb_rank": 74.5,
                             "pe_current": 13.23, "pb_current": 4.43, "samples": {"valid": 732},
                             "risk_columns": []},
        )
        config = {
            "asset_id": "ALUMINUM", "asset_type": "commodity", "factors": [],
            "fundamentals_symbol": "601899.SS", "valuation": {"enabled": True},
            "quality_factors": [{"factor_id": "LEVERAGE", "factor_name": "杠杆"}],
            "analysis_framework": [{"question_id": "Q1", "question": "现金流趋势？", "dimension": "现金流"}],
        }
        snap = fsr.build_quality_snapshot(config, "2026-09-01")
        assert snap["data_status"]["fundamentals"] == "available"
        assert snap["data_status"]["valuation"] == "available"
        assert len(snap["quality_factors"]) == 1
        assert snap["quality_factors"][0]["judgement"] == "正常"
        assert snap["analysis_framework"][0]["answer"] != "—"
        assert snap["valuation"]["level"] == "临界"

    def test_stale_fundamentals_insufficient(self, monkeypatch):
        """财报公告距今 >180 天 → fundamentals insufficient（诚实降级）。"""
        monkeypatch.setattr(fsr, "load_views", lambda: [{"view_id": "v1"}])
        monkeypatch.setattr(fsr, "_load_json", lambda path: {"601899.SS": {}})
        stale_fund = {
            "found": True, "stat_date": "2025-12-31", "pub_date": "2026-01-15",
            "period": "2025Q4", "source": "baostock", "metrics": {"liability_to_asset": 0.5},
        }
        monkeypatch.setattr(fsr, "fetch_fundamentals_periods", lambda *a, **k: [stale_fund])
        monkeypatch.setattr(fsr, "compute_valuation", lambda *a, **k: {"status": "insufficient", "level": "数据不足"})
        config = {
            "asset_id": "ALUMINUM", "asset_type": "commodity",
            "fundamentals_symbol": "601899.SS", "valuation": {"enabled": True},
            "quality_factors": [], "analysis_framework": [],
        }
        snap = fsr.build_quality_snapshot(config, "2026-09-01")
        assert snap["data_status"]["fundamentals"] == "insufficient"
        assert snap["data_status"]["valuation"] == "insufficient"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
