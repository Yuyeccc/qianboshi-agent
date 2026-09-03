# -*- coding: utf-8 -*-
"""memory_conflicts 单测（P2 刀1）。"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from entity_coverage_audit import build_maps  # noqa: E402
import memory_conflicts as mc  # noqa: E402

ALIASES = {"entities": {
    "半导体": {"aliases": ["芯片"], "etfs": ["159813.SZ"], "stocks": ["688981.SS"],
             "themes": ["国产替代"], "us_mapping": ["NVDA"]},
    "大盘": {"aliases": ["上证", "指数"], "indexes": ["000001.SS"]},
}}


def vmk(vid, stance, date="2026-07-01", analyst="甲", entity=("半导体",), horizon="short",
        claim="", confidence=0.6, timestamp=""):
    """快速构造 view dict。entity 为 sectors 词（词典命中）。"""
    v = {
        "view_id": vid, "stance": stance, "date": date, "analyst": analyst,
        "horizon": horizon, "confidence": confidence, "claim": claim or f"观点{vid}",
        "entities": {"sectors": list(entity), "themes": [], "etfs": [], "stocks": [],
                     "indexes": [], "us_mapping": []},
    }
    if timestamp:
        v["timestamp"] = timestamp
    return v


@pytest.fixture()
def maps():
    return build_maps(ALIASES)


@pytest.fixture()
def tmpdb(tmp_path):
    p = tmp_path / "lifecycle.db"
    con = mc.connect(p)
    mc.ensure_schema(con)
    yield con
    con.close()


class TestTextOk:
    def test_contradiction_detected(self):
        assert mc._text_ok(vmk("a", "bullish", claim="中长线：看空（蕴含巨大风险）🐻")) is False
        assert mc._text_ok(vmk("b", "bearish", claim="短线：看多，布局机会")) is False

    def test_consistent_ok(self):
        assert mc._text_ok(vmk("c", "bullish", claim="看好半导体，加仓")) is True
        assert mc._text_ok(vmk("d", "bearish", claim="不看好，清仓回避")) is True

    def test_mixed_text_ok(self):
        # 双向都含 = 中性混杂不判
        assert mc._text_ok(vmk("e", "bullish", claim="长期看好但短期减仓")) is True

    def test_weak_words_no_false_positive(self):
        # "风险/涨/跌" 弱词不触发（"中性偏多但需规避风险" 不应误伤）
        assert mc._text_ok(vmk("f", "bullish", claim="中性偏多，短期需规避风险")) is True

    def test_no_claim_ok(self):
        assert mc._text_ok(vmk("g", "bullish", claim="")) is True


class TestPickRep:
    def test_pick_clean_highest(self):
        cluster = [vmk("a", "bullish", confidence=0.9, claim="看空"),   # 脏且高置信
                   vmk("b", "bullish", confidence=0.7, claim="看好")]
        assert mc._pick_rep(cluster)["view_id"] == "b"

    def test_all_dirty_fallback(self):
        cluster = [vmk("a", "bullish", confidence=0.9, claim="看空"),
                   vmk("b", "bullish", confidence=0.8, claim="看空")]
        assert mc._pick_rep(cluster)["view_id"] == "a"


class TestViewCanonicals:
    def test_sector_and_code(self, maps):
        am, cm, cn, _ = maps
        v = vmk("a", "bullish", entity=("芯片",))
        assert mc.view_canonicals(v, am, cm) == ["半导体"]
        v2 = dict(v, entities={"sectors": [], "etfs": ["159813.SZ"], "us_mapping": ["NVDA"]})
        assert mc.view_canonicals(v2, am, cm) == ["半导体"]
        v3 = dict(v, entities={"sectors": [], "indexes": ["000001.SS"]})
        assert mc.view_canonicals(v3, am, cm) == ["大盘"]


class TestDetectDirection:
    def test_opposing_clusters_one_pair(self, maps):
        am, cm, cn, _ = maps
        views = [vmk("b1", "bullish", date="2026-06-01", confidence=0.8),
                 vmk("b2", "bullish", date="2026-06-02", confidence=0.6),
                 vmk("s1", "bearish", date="2026-06-03", confidence=0.9)]
        st = {v["view_id"]: "active" for v in views}
        cands = mc.detect_direction(views, st, am, cm)
        assert len(cands) == 1
        assert cands[0]["view_id_a"] == "b1"  # 最高置信多头
        assert cands[0]["view_id_b"] == "s1"
        assert "多头簇 2 条" in cands[0]["evidence_summary"]

    def test_horizon_split_no_conflict(self, maps):
        am, cm, cn, _ = maps
        views = [vmk("b1", "bullish", horizon="intraday"),
                 vmk("s1", "bearish", horizon="long")]  # 短窗不参与长周期判定
        st = {v["view_id"]: "active" for v in views}
        assert mc.detect_direction(views, st, am, cm) == []

    def test_entity_split_no_conflict(self, maps):
        am, cm, cn, _ = maps
        views = [vmk("b1", "bullish", entity=("半导体",)),
                 vmk("s1", "bearish", entity=("大盘",))]
        st = {v["view_id"]: "active" for v in views}
        assert mc.detect_direction(views, st, am, cm) == []

    def test_non_active_excluded(self, maps):
        am, cm, cn, _ = maps
        views = [vmk("b1", "bullish"), vmk("s1", "bearish")]
        st = {"b1": "active", "s1": "falsified"}  # 空头已 falsified 不参与
        assert mc.detect_direction(views, st, am, cm) == []

    def test_dirty_rep_replaced(self, maps):
        am, cm, cn, _ = maps
        views = [vmk("dirty", "bullish", confidence=0.99, claim="看空，蕴含巨大风险"),
                 vmk("clean", "bullish", confidence=0.5, claim="看好"),
                 vmk("s1", "bearish", confidence=0.8)]
        st = {v["view_id"]: "active" for v in views}
        cands = mc.detect_direction(views, st, am, cm)
        assert cands[0]["view_id_a"] == "clean"


class TestDetectTemporal:
    def test_flip_reports_latest(self, maps):
        am, cm, cn, _ = maps
        views = [vmk("o1", "bullish", date="2026-06-01"),
                 vmk("o2", "bearish", date="2026-06-15"),
                 vmk("o3", "bullish", date="2026-07-01")]
        st = {v["view_id"]: "active" for v in views}  # 全部未 supersede
        cands = mc.detect_temporal(views, st, am, cm)
        # 两次翻转但只报最近一次（o2→o3）
        assert len(cands) == 1
        assert cands[0]["view_id_a"] == "o2"
        assert cands[0]["view_id_b"] == "o3"

    def test_old_superseded_no_conflict(self, maps):
        am, cm, cn, _ = maps
        views = [vmk("o1", "bullish", date="2026-06-01"),
                 vmk("o2", "bearish", date="2026-07-01")]
        st = {"o1": "superseded", "o2": "active"}
        assert mc.detect_temporal(views, st, am, cm) == []

    def test_same_day_no_flip(self, maps):
        am, cm, cn, _ = maps
        views = [vmk("o1", "bullish", date="2026-07-01", timestamp="09:00"),
                 vmk("o2", "bearish", date="2026-07-01", timestamp="15:00")]
        st = {v["view_id"]: "active" for v in views}
        assert mc.detect_temporal(views, st, am, cm) == []

    def test_high_freq_source_filtered(self, maps):
        am, cm, cn, _ = maps
        views = []
        dates = ["2026-06-%02d" % d for d in range(1, 20)]
        # 制造 10 次以上翻转（逐日翻向）
        for i, dt in enumerate(dates):
            views.append(vmk(f"o{i}", "bullish" if i % 2 == 0 else "bearish", date=dt))
        st = {v["view_id"]: "active" for v in views}
        assert mc.detect_temporal(views, st, am, cm, max_flips=8) == []

    def test_dirty_view_out_of_sequence(self, maps):
        am, cm, cn, _ = maps
        views = [vmk("o1", "bullish", date="2026-06-01"),
                 vmk("o2", "bearish", date="2026-06-15", claim="看多，机会布局"),  # 脏：bearish标看多文
                 ]
        st = {v["view_id"]: "active" for v in views}
        assert mc.detect_temporal(views, st, am, cm) == []


class TestDetectUserBelief:
    def test_opposing_user(self, maps):
        am, cm, cn, _ = maps
        user_views = {"黄金": {"view": "我不碰黄金，清仓离场", "strategy": "回避"}}
        views = [vmk("v1", "bullish", analyst="乙", confidence=0.9, entity=("半导体",)),
                 vmk("v2", "bullish", analyst="丙", confidence=0.8, entity=("黄金",))]
        # 黄金→黄金有色 canonical 需词典含"黄金"别名——小词典没有，直接测 key 含 canonical
        user_views2 = {"半导体": {"view": "不看好半导体，清仓", "strategy": "减仓"}}
        cands = mc.detect_user_belief(views, {"v1": "active", "v2": "active"}, user_views2,
                                      am, cm, cn)
        assert len(cands) == 1
        assert cands[0]["view_id_a"] == "user:半导体"
        assert cands[0]["view_id_b"] == "v1"
        assert "观点簇 1 条" in cands[0]["evidence_summary"]

    def test_no_stance_text_no_output(self, maps):
        am, cm, cn, _ = maps
        user_views = {"半导体": {"view": "观察中", "strategy": "暂无操作"}}
        views = [vmk("v1", "bullish")]
        assert mc.detect_user_belief(views, {"v1": "active"}, user_views, am, cm, cn) == []


class TestUserKeyToCanonicals:
    def test_seg_match(self, maps):
        am, cm, cn, _ = maps
        assert mc.user_key_to_canonicals("半导体", am, cn) == ["半导体"]
        assert mc.user_key_to_canonicals("科技股/半导体", am, cn) == ["半导体"]  # 段含 canonical
        assert mc.user_key_to_canonicals("芯片", am, cn) == ["半导体"]  # alias 命中
        assert mc.user_key_to_canonicals("黄金", am, cn) == []  # 词典无


class TestConflictId:
    def test_stable_and_unique(self):
        a = mc._conflict_id("direction", "半导体", "v1", "v2", "short")
        b = mc._conflict_id("direction", "半导体", "v1", "v2", "short")
        c = mc._conflict_id("temporal", "半导体", "v1", "v2", "short")
        assert a == b and a != c


class TestResolveFlow:
    def test_resolve_writes_history_and_closes(self, tmpdb):
        now = mc._utcnow()
        tmpdb.execute(
            "INSERT INTO memory_conflicts(conflict_id,conflict_type,entity_key,status,created_at) "
            "VALUES('c1','direction','半导体','open',?)", (now,))
        tmpdb.commit()
        mc.ensure_schema(tmpdb)  # 幂等
        # 模拟 CLI resolve 逻辑
        row = tmpdb.execute("SELECT * FROM memory_conflicts WHERE conflict_id='c1'").fetchone()
        assert row["status"] == "open"
        tmpdb.execute("UPDATE memory_conflicts SET status='resolved', verdict='a_wins', "
                      "resolution_reason='样本核对确认', resolved_at=?, resolved_by=? WHERE conflict_id='c1'",
                      (now, "tester"))
        tmpdb.execute("INSERT INTO conflict_history(history_id,conflict_id,action,verdict,reason,by,at) "
                      "VALUES('h1','c1','resolve','a_wins','样本核对确认','tester',?)", (now,))
        tmpdb.commit()
        assert tmpdb.execute("SELECT status FROM memory_conflicts WHERE conflict_id='c1'").fetchone()[0] == "resolved"
        assert tmpdb.execute("SELECT COUNT(*) FROM conflict_history WHERE conflict_id='c1'").fetchone()[0] == 1

    def test_schema_idempotent(self, tmpdb):
        mc.ensure_schema(tmpdb)
        mc.ensure_schema(tmpdb)
        tabs = {r[0] for r in tmpdb.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"memory_conflicts", "conflict_history"} <= tabs
