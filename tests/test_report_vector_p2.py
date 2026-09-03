# -*- coding: utf-8 -*-
"""P2 刀4 单测：报告向量化（build_vector_db 报告域）+ query_rag 状态过滤。"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_vector_db as bvd  # noqa: E402
import query_rag as qr  # noqa: E402


class TestReportSerialize:
    def test_portfolio_risk_fields(self):
        d = {"goal": "分析黄金对当前持仓的风险暴露", "entity": "黄金",
             "summary": "金价波动影响账户净值",
             "holdingsExposure": {"exposed": [{"name": "华安黄金ETF", "marketCode": "518880.SS",
                                               "weightPct": 14.42, "relation": "同属黄金板块"}]}}
        t = bvd._report_serialize(d)
        assert "goal: 分析黄金" in t
        assert "持仓暴露: 华安黄金ETF (518880.SS)" in t
        assert "14.42" in t
        # 段落分隔保证 chunk_markdown 能切块
        assert "\n\n" in t

    def test_research_fields(self):
        d = {"coreIssue": "半导体周期推演", "summary": "芯片上行",
             "facts": [{"text": "费城半导体指数新高", "source": "新浪"}],
             "opinions": [{"text": "短线看多", "analyst": "甲", "side": "bull"}]}
        t = bvd._report_serialize(d)
        assert "coreIssue: 半导体周期推演" in t
        assert "facts: 费城半导体指数新高" in t
        assert "opinions: 短线看多" in t

    def test_chunking_works(self):
        """段落分隔后 chunk_markdown 正常切块（防 1 大 chunk）。"""
        d = {"summary": "\n\n".join(f"第 {i} 段内容反复填充保证长度超过五百字上限以便触发切块逻辑。" * 3
                                    for i in range(12))}
        t = bvd._report_serialize(d)
        chunks = bvd.chunk_markdown(t, "report:doc1", 500, 50)
        assert len(chunks) >= 2  # 长文必须切成多 chunk

    def test_empty(self):
        assert bvd._report_serialize({}) == ""


class TestClassifySource:
    def test_report_prefix(self):
        assert qr.QianboshiRAG._classify_source("report:20260903_x") == "report"

    def test_legacy_unchanged(self):
        assert qr.QianboshiRAG._classify_source("2026.6.25 xxx 短视频解读.md") == "short_video"
        assert qr.QianboshiRAG._classify_source("2026.6.25 钱博士直播复盘.md") == "livestream"


class TestExtractDate:
    def test_report_compact_date(self):
        assert qr.QianboshiRAG._extract_date("report:20260903_185657_job") == date(2026, 9, 3)

    def test_legacy_dotted(self):
        assert qr.QianboshiRAG._extract_date("2026.6.25 x.md") == date(2026, 6, 25)


class TestReportStatusFilter:
    def test_valid_report_ok(self):
        assert qr._report_status_ok({"doc_type": "report", "status": "valid"}) is True

    def test_superseded_rejected(self):
        assert qr._report_status_ok({"doc_type": "report", "status": "superseded"}) is False
        assert qr._report_status_ok({"doc_type": "report", "status": "retracted"}) is False

    def test_note_unaffected(self):
        # 笔记 chunk 无 doc_type → 永远通过
        assert qr._report_status_ok({}) is True
        assert qr._report_status_ok({"source": "xxx.md"}) is True
        assert qr._report_status_ok({"doc_type": "note"}) is True


class TestUpsertReportLogic:
    def test_make_chunk_id_deterministic(self):
        a = bvd.make_chunk_id("report:doc1", 3)
        b = bvd.make_chunk_id("report:doc1", 3)
        c = bvd.make_chunk_id("report:doc1", 4)
        assert a == b and a != c
