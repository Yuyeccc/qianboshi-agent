# -*- coding: utf-8 -*-
"""report_docs 单测（P2 刀3）。"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import report_docs as rd  # noqa: E402


@pytest.fixture()
def maps():
    return rd.build_scan_maps()


@pytest.fixture()
def tmpdb(tmp_path):
    p = tmp_path / "lifecycle.db"
    con = rd.connect(p)
    rd.ensure_schema(con)
    yield con, p
    con.close()


class TestEntityExtract:
    def test_canonical_hit(self, maps):
        cn_map, _, canon = maps
        assert "黄金有色" in rd.extract_entities("分析黄金对当前持仓的风险暴露", cn_map, canon)

    def test_alias_hit(self, maps):
        cn_map, _, canon = maps
        hits = rd.extract_entities("芯片板块反弹", cn_map, canon)
        assert "半导体" in hits

    def test_theme_word_not_false_positive(self, maps):
        """themes 泛词（如 政策）不进 restricted 词表 → 不误伤。"""
        cn_map, _, canon = maps
        hits = rd.extract_entities("9月政策情景概率推演", cn_map, canon)
        assert "创新药" not in hits

    def test_empty(self, maps):
        cn_map, _, canon = maps
        assert rd.extract_entities("", cn_map, canon) == []


class TestReportType:
    def test_research(self):
        assert rd.report_type_of({"coreIssue": "x", "opinions": []}) == "research"

    def test_portfolio_risk(self):
        assert rd.report_type_of({"goal": "g", "holdingsExposure": {}}) == "portfolio_risk"

    def test_unknown(self):
        assert rd.report_type_of({"foo": 1}) == "unknown"


class TestOpinionMatch:
    def test_exact_match(self, tmp_path):
        jl = tmp_path / "views.jsonl"
        rows = [
            {"view_id": "view_a1", "analyst": "钱博士直播", "date": "2026-08-12", "stance": "bullish"},
            {"view_id": "view_b1", "analyst": "钱博士直播", "date": "2026-08-12", "stance": "bearish"},
            {"view_id": "view_c1", "analyst": "任泽平", "date": "2026-08-12", "stance": "bullish"},
        ]
        with open(jl, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        idx = rd.build_view_index(jl)
        d = {"opinions": [
            {"text": "看多", "analyst": "钱博士直播", "date": "2026-08-12", "side": "bull"},
            {"text": "看空", "analyst": "钱博士直播", "date": "2026-08-12", "side": "bear"},
            {"text": "无匹配", "analyst": "不存在的人", "date": "2026-01-01", "side": "bull"},
        ]}
        out = rd.match_opinions(d, idx)
        assert out == ["view_a1", "view_b1"]

    def test_no_opinions(self):
        assert rd.match_opinions({"opinions": []}, {}) == []
        assert rd.match_opinions({}, {}) == []


class TestScanFile:
    def _mk_report(self, p: Path, schema_valid=True, research=True):
        d = {"_meta": {"schema_valid": schema_valid}}
        if research:
            d.update({"coreIssue": "半导体板块走势", "summary": "芯片周期上行",
                      "opinions": [{"analyst": "甲", "date": "2026-08-01", "side": "bull"}]})
        else:
            d.update({"goal": "分析黄金持仓", "holdingsExposure": {"exposed": []}})
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def test_insert_then_unchanged(self, tmp_path, tmpdb, maps):
        cn_map, code_map, canon = maps
        con, _ = tmpdb
        f = tmp_path / "20260901_000000_job1.json"
        self._mk_report(f)
        idx = {"甲": {"2026-08-01": {}}}
        r1 = rd.scan_file(f, con, cn_map, code_map, canon, idx, dry_run=False)
        assert r1["action"] == "inserted"
        r2 = rd.scan_file(f, con, cn_map, code_map, canon, idx, dry_run=False)
        assert r2["action"] == "unchanged"
        row = con.execute("SELECT * FROM report_docs WHERE doc_id=?", (f.stem,)).fetchone()
        assert row["report_type"] == "research"
        assert "半导体" in (row["entity_key"] or "")

    def test_invalid_skipped(self, tmp_path, tmpdb, maps):
        cn_map, code_map, canon = maps
        con, _ = tmpdb
        f = tmp_path / "bad.json"
        self._mk_report(f, schema_valid=False)
        r = rd.scan_file(f, con, cn_map, code_map, canon, {}, dry_run=False)
        assert "skipped" in r

    def test_changed_content_updates(self, tmp_path, tmpdb, maps):
        cn_map, code_map, canon = maps
        con, _ = tmpdb
        f = tmp_path / "20260901_000001_job2.json"
        self._mk_report(f, research=False)
        rd.scan_file(f, con, cn_map, code_map, canon, {}, dry_run=False)
        # 内容变化
        d = json.loads(f.read_text(encoding="utf-8"))
        d["goal"] = "分析黄金对当前持仓的风险暴露与风险点"
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        r = rd.scan_file(f, con, cn_map, code_map, canon, {}, dry_run=False)
        assert r["action"] == "updated"
        row = con.execute("SELECT entity_key FROM report_docs WHERE doc_id=?", (f.stem,)).fetchone()
        assert "黄金有色" in (row["entity_key"] or "")

    def test_linked_views_persisted(self, tmp_path, tmpdb, maps):
        cn_map, code_map, canon = maps
        con, _ = tmpdb
        f = tmp_path / "20260901_000002_job3.json"
        d = {"_meta": {"schema_valid": True}, "coreIssue": "存储周期",
             "opinions": [{"analyst": "甲", "date": "2026-08-01", "side": "bear"}]}
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        jl = tmp_path / "views.jsonl"
        jl.write_text(json.dumps({"view_id": "view_x", "analyst": "甲", "date": "2026-08-01",
                                  "stance": "bearish"}) + "\n", encoding="utf-8")
        idx = rd.build_view_index(jl)
        rd.scan_file(f, con, cn_map, code_map, canon, idx, dry_run=False)
        row = con.execute("SELECT linked_view_ids FROM report_docs WHERE doc_id=?", (f.stem,)).fetchone()
        assert json.loads(row["linked_view_ids"]) == ["view_x"]


class TestSetStatus:
    def test_flow(self, tmpdb):
        con, p = tmpdb
        rd.ensure_schema(con)
        import rule_lifecycle  # 复用其连接无关；直接手插
        con.execute(
            "INSERT INTO report_docs(doc_id,report_type,file_path,file_sha256,status,created_at,updated_at) "
            "VALUES('doc1','research','x.json','sha','valid','2026-09-03T00:00:00Z','2026-09-03T00:00:00Z')")
        con.commit()
        con.execute("UPDATE report_docs SET status='superseded', updated_at=? WHERE doc_id='doc1'",
                    (rd._utcnow(),))
        con.commit()
        assert con.execute("SELECT status FROM report_docs WHERE doc_id='doc1'").fetchone()[0] == "superseded"
