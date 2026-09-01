#!/usr/bin/env python3
"""71号方案 #9 绝对估值确定性计算 单测（表驱动边界）。

覆盖（gpt审P2-2）：负 PE/PB 剔除、全缺/部分缺→数据不足、财报过期→insufficient、
baostock 登录失败→pending、重复日期去重、样本门槛、分档边界、渲染禁词。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import valuation_calc as vc


# ---------------------------------------------------------------------------
# _percentile_rank
# ---------------------------------------------------------------------------

class TestPercentileRank:
    def test_empty(self):
        assert vc._percentile_rank([], 10.0) is None

    def test_none_current(self):
        assert vc._percentile_rank([1.0, 2.0], None) is None

    def test_all_above_current(self):
        # 当前值 1.0，序列最小值 2.0 → 0% 分位
        assert vc._percentile_rank([2.0, 3.0, 4.0], 1.0) == 0.0

    def test_all_below_current(self):
        assert vc._percentile_rank([2.0, 3.0, 4.0], 5.0) == 100.0

    def test_median_value(self):
        assert vc._percentile_rank([1.0, 2.0, 3.0], 2.0) == pytest.approx(66.7, abs=0.1)

    def test_duplicates(self):
        assert vc._percentile_rank([1.0, 1.0, 1.0, 2.0], 1.0) == 75.0


# ---------------------------------------------------------------------------
# _valuation_level 分档查表
# ---------------------------------------------------------------------------

class TestValuationLevel:
    @pytest.mark.parametrize(
        "pe_rank,pb_rank,expected",
        [
            (25.0, 25.0, "一眼便宜"),   # 边界：==25 算便宜
            (24.9, 10.0, "一眼便宜"),
            (10.0, 25.0, "一眼便宜"),
            (25.1, 25.1, "临界"),
            (50.0, 60.0, "临界"),
            (75.1, 10.0, "未达门槛"),   # 任一 >75
            (10.0, 76.0, "未达门槛"),
            (75.0, 75.0, "临界"),       # 边界：==75 不算 >75
            (None, 50.0, "数据不足"),   # 任一 None 兜底
            (50.0, None, "数据不足"),
            (None, None, "数据不足"),
        ],
    )
    def test_levels(self, pe_rank, pb_rank, expected):
        assert vc._valuation_level(pe_rank, pb_rank) == expected


# ---------------------------------------------------------------------------
# assess_gate 数据充分度闸门
# ---------------------------------------------------------------------------

def _series(n: int, pe=15.0, pb=3.0, as_of=None) -> list[dict]:
    """构造 n 条日频序列：跨 n-1 天，最后一条 = as_of（闸门时效通过）。

    n>=731 时 span>=730 天且样本>=250，闸门可通过。
    """
    as_of = as_of or date(2026, 9, 1)
    base = as_of - timedelta(days=n - 1)
    out = []
    for i in range(n):
        out.append({"date": (base + timedelta(days=i)).isoformat(), "pe": pe, "pb": pb})
    return out


class TestGate:
    def test_pass(self):
        s = _series(800)
        g = vc.assess_gate(s, date(2026, 9, 1))
        assert g["passed"] is True

    def test_insufficient_samples(self):
        g = vc.assess_gate(_series(100), date(2026, 9, 1))
        assert g["passed"] is False

    def test_insufficient_span(self):
        # 样本够（400>=250）但跨度 399 天 <730 → 不过
        g = vc.assess_gate(_series(400), date(2026, 9, 1))
        assert g["passed"] is False

    def test_stale_last_date(self):
        # 最近观测 63 天前 → 时效不过
        s = _series(800)
        s[-1]["date"] = "2026-06-30"
        g = vc.assess_gate(s, date(2026, 9, 1))
        assert g["passed"] is False

    def test_empty_series(self):
        g = vc.assess_gate([], date(2026, 9, 1))
        assert g["passed"] is False


# ---------------------------------------------------------------------------
# _sane 数据合理性护栏（检修 2026-09-01）
# ---------------------------------------------------------------------------

class TestSaneGuard:
    @pytest.mark.parametrize(
        "value,lo,hi,expected",
        [
            (0.50, 0.01, 1.2, 0.50),    # 正常
            (0.005, 0.01, 1.2, None),   # baostock 2025Q2 紫金异常值 → 剔除
            (1.5, 0.01, 1.2, None),     # 超上限
            (None, 0.01, 1.2, None),    # 缺失
            (0.0, 0.0, 1.0, 0.0),       # 下界含 0
        ],
    )
    def test_ranges(self, value, lo, hi, expected):
        assert vc._sane(value, lo, hi) == expected

    def test_guard_prevents_false_leverage(self):
        """2025Q2 异常资产负债率 0.005 → 剔除后 _judge_qf 判待补而非低杠杆。"""
        # 模拟 2025Q2 期：liability_to_asset 经 _sane 后为 None
        m = {"liability_to_asset": vc._sane(0.005, 0.01, 1.2)}
        import factor_state_refresher as fsr
        assert fsr._judge_qf("LEVERAGE", m)["judgement"] == "待补"


# ---------------------------------------------------------------------------
# compute_valuation 全链路（monkeypatch 网络）
# ---------------------------------------------------------------------------

class TestComputeValuation:
    def test_baostock_login_fail_pending(self, monkeypatch):
        monkeypatch.setattr(vc, "fetch_pe_pb_series", lambda *a, **k: ([], {"error": "baostock 登录失败"}))
        r = vc.compute_valuation("601899.SS", as_of_date="2026-09-01")
        assert r["status"] == "pending"
        assert r["level"] == "数据不足"

    def test_gate_fail_insufficient(self, monkeypatch):
        s = _series(100, 1100)  # 样本不足
        monkeypatch.setattr(vc, "fetch_pe_pb_series", lambda *a, **k: (s, {"valid": 100, "dropped": 0, "span_days": 1100, "last_date": "2026-08-30"}))
        monkeypatch.setattr(vc, "fetch_latest_fundamentals", lambda *a, **k: {"found": False})
        r = vc.compute_valuation("601899.SS", as_of_date="2026-09-01")
        assert r["status"] == "insufficient"
        assert r["level"] == "数据不足"
        assert r["risk_columns"]  # 风险分栏仍尝试（待补）
        assert all(c["judgement"] == "待补" for c in r["risk_columns"])

    def test_ok_cheap(self, monkeypatch):
        # 构造：当前 PE/PB 都在序列低位 → 一眼便宜
        s = _series(800)
        s[-1]["pe"], s[-1]["pb"] = 8.0, 1.2
        monkeypatch.setattr(vc, "fetch_pe_pb_series", lambda *a, **k: (s, {"valid": 400, "dropped": 0, "span_days": 1100, "last_date": "2026-08-30"}))
        monkeypatch.setattr(
            vc, "fetch_latest_fundamentals",
            lambda *a, **k: {
                "found": True, "period": "2026Q2", "pub_date": "2026-08-25", "source": "baostock",
                "metrics": {
                    "liability_to_asset": 0.55, "tangible_to_asset": 0.6,
                    "cfo_to_np": 0.82, "yoy_liability": 5.0, "current_ratio": 1.5,
                },
            },
        )
        r = vc.compute_valuation("601899.SS", as_of_date="2026-09-01")
        assert r["status"] == "ok"
        assert r["level"] == "一眼便宜"
        assert r["pe_rank"] <= 25 and r["pb_rank"] <= 25
        cols = {c["name"]: c for c in r["risk_columns"]}
        assert cols["杠杆（资产负债率）"]["value"] == 55.0
        assert cols["盈利质量（经营CF/净利）"]["judgement"] == "正常"

    def test_ok_expensive(self, monkeypatch):
        s = _series(800)
        s[-1]["pe"], s[-1]["pb"] = 60.0, 9.0  # 高位
        monkeypatch.setattr(vc, "fetch_pe_pb_series", lambda *a, **k: (s, {"valid": 400, "dropped": 0, "span_days": 1100, "last_date": "2026-08-30"}))
        monkeypatch.setattr(vc, "fetch_latest_fundamentals", lambda *a, **k: {"found": False})
        r = vc.compute_valuation("601899.SS", as_of_date="2026-09-01")
        assert r["status"] == "ok"
        assert r["level"] == "未达门槛"
        # 财报不可得 → 风险分栏全待补（不猜）
        assert all(c["judgement"] == "待补" for c in r["risk_columns"])


# ---------------------------------------------------------------------------
# 清洗规则（负值剔除/重复去重）——直接测 fetch_pe_pb_series 的纯逻辑部分
# ---------------------------------------------------------------------------

class TestCleaning:
    def test_negative_and_duplicate_dropped(self, monkeypatch):
        """负 PE/PB 与重复日期被剔除：monkeypatch baostock 返回脏数据。"""
        class FakeRs:
            error_code = "0"
            def __init__(self, rows):
                self._rows = rows
                self._i = -1
            def next(self):
                self._i += 1
                return self._i < len(self._rows)
            def get_row_data(self):
                return self._rows[self._i]

        fake_rows = [
            ["2026-01-02", "15.0", "3.0"],
            ["2026-01-02", "15.0", "3.0"],   # 重复日期
            ["2026-01-03", "-5.0", "3.0"],   # 负 PE（亏损）→ 剔除
            ["2026-01-04", "16.0", "0.0"],   # PB=0 → 剔除
            ["2026-01-05", "16.5", "3.2"],
            ["2026-01-06", "nan", "3.3"],    # 非数值 → 剔除
            ["2026-01-07", "17.0", "3.4"],
        ]
        monkeypatch.setattr(vc, "_bs_login", lambda: True)
        monkeypatch.setattr(vc, "bs", type("BS", (), {"login": lambda: type("L", (), {"error_code": "0"})(), "logout": lambda: None, "query_history_k_data_plus": lambda *a, **k: FakeRs(fake_rows)})())
        s, stats = vc.fetch_pe_pb_series("601899.SS", date(2026, 1, 1), date(2026, 1, 31))
        assert stats["fetched"] == 7
        assert stats["dropped"] == 4  # 1重复 + 1负PE + 1零PB + 1非数值
        assert stats["valid"] == 3
        assert [r["date"] for r in s] == ["2026-01-02", "2026-01-05", "2026-01-07"]

    def test_series_sorted(self):
        s = [{"date": "2026-03-01", "pe": 2.0, "pb": 1.0}, {"date": "2026-01-01", "pe": 1.0, "pb": 1.0}]
        # 不做排序断言，只验证 assess_gate 对乱序不崩（span 计算用首尾）
        g = vc.assess_gate(s, date(2026, 9, 1))
        assert g["passed"] is False


# ---------------------------------------------------------------------------
# 渲染禁词红线
# ---------------------------------------------------------------------------

class TestRenderForbidden:
    @pytest.mark.parametrize(
        "valuation",
        [
            {"status": "ok", "level": "一眼便宜", "pe_rank": 16.0, "pb_rank": 22.0,
             "pe_current": 16.1, "pb_current": 4.6, "samples": {"valid": 742},
             "risk_columns": [{"name": "杠杆", "value": 55.0, "judgement": "正常", "period": "2026Q2", "source": "baostock", "unit": "%"}]},
            {"status": "insufficient", "level": "数据不足", "note": "样本不足", "samples": {"valid": 100, "dropped": 0, "span_days": 300}},
            {"status": "pending", "level": "数据不足", "note": "登录失败", "samples": {}},
        ],
    )
    def test_no_forbidden_phrases(self, valuation):
        text = vc.render_valuation_block(valuation)
        for phrase in vc.FORBIDDEN_PHRASES:
            assert phrase not in text, f"渲染含禁词: {phrase}\n{text}"

    def test_fixed_note_present(self):
        text = vc.render_valuation_block({"status": "ok", "level": "临界", "pe_rank": 50.0, "pb_rank": 50.0,
                                           "pe_current": 20.0, "pb_current": 5.0, "samples": {"valid": 400},
                                           "risk_columns": []})
        assert "估值≠安全边际" in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
