#!/usr/bin/env python3
"""event_timeline 单测（记忆体系 P1b，刀3）：DDL/幂等插入/链接/全量 build/决策链 trace。

跑：cd E:\\qianboshi-agent && C:/Python314/python.exe -m pytest tests/test_event_timeline.py -q
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import event_timeline as evt  # noqa: E402
import user_view_versions as uvv  # noqa: E402
import build_event_timeline as build  # noqa: E402
from build_event_timeline import build_all  # noqa: E402


# ---------- service：DDL/幂等/链接 ----------

def test_schema_created(tmp_path):
    conn = evt.connect(db=tmp_path / "lifecycle.db")
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"event_timeline", "event_links"} <= tabs
    conn.close()


def test_insert_idempotent_by_fingerprint(tmp_path):
    conn = evt.connect(db=tmp_path / "lifecycle.db")
    payload = {"decision_id": "dec_x", "asset_id": "GOLD"}
    r1 = evt.insert_event(conn, "decision_created", "2026-09-03", "user",
                          "t", "s", "src/dec_x", payload)
    r2 = evt.insert_event(conn, "decision_created", "2026-09-03", "user",
                          "t", "s", "src/dec_x", payload)
    assert r1["inserted"] is True and r2["inserted"] is False
    assert r1["event_id"] == r2["event_id"]  # 确定性派生
    assert evt.total(conn) == 1
    # 内容变 → 新指纹 → 新事件
    r3 = evt.insert_event(conn, "decision_created", "2026-09-03", "user",
                          "t", "s", "src/dec_x", {**payload, "asset_id": "SEMI"})
    assert r3["inserted"] is True and evt.total(conn) == 2
    conn.close()


def test_insert_bad_type_rejected(tmp_path):
    conn = evt.connect(db=tmp_path / "lifecycle.db")
    try:
        evt.insert_event(conn, "not_a_type", "2026-09-03", "u", "t", None, "s", {})
        assert False
    except ValueError:
        pass
    conn.close()


def test_link_and_trace(tmp_path):
    conn = evt.connect(db=tmp_path / "lifecycle.db")
    r = evt.insert_event(conn, "decision_created", "2026-09-03", "user",
                         "决策", None, "src/dec_a", {"decision_id": "dec_a"})
    evt.link_event(conn, r["event_id"], "decision", "dec_a", "self")
    r2 = evt.insert_event(conn, "review_created", "2026-09-10", "user",
                          "复盘", None, "src/rev_1", {"review_id": "rev_1", "decision_id": "dec_a"})
    evt.link_event(conn, r2["event_id"], "decision", "dec_a", "reviewed_by")
    chain = evt.trace_decision(conn, "dec_a")
    assert [c["event_type"] for c in chain] == ["decision_created", "review_created"]
    conn.close()


# ---------- 全量 build ----------

def _seed_decision_db(p: Path) -> None:
    conn = sqlite3.connect(p)
    conn.execute("""CREATE TABLE user_decision_logs (
        decision_id TEXT PRIMARY KEY, asset_id TEXT, asset_name TEXT, asset_type TEXT,
        decision_date TEXT, horizon TEXT, direction TEXT, conviction REAL,
        thesis TEXT, status TEXT, market_snapshot TEXT, user_view_version_ids TEXT,
        created_at TEXT)""")
    conn.execute("""CREATE TABLE decision_reviews (
        review_id TEXT PRIMARY KEY, decision_id TEXT, review_date TEXT,
        outcome_return REAL, benchmark_return REAL, excess_return REAL,
        result_label TEXT, what_went_wrong TEXT, new_rule_learned TEXT,
        linked_new_card_version TEXT, created_at TEXT)""")
    conn.execute("""CREATE TABLE asset_card_versions (
        version_id TEXT PRIMARY KEY, asset_id TEXT, version INTEGER,
        config_json TEXT, change_reason TEXT, changed_by TEXT,
        linked_review_id TEXT, created_at TEXT)""")
    conn.execute("""CREATE TABLE prediction_events (
        event_id TEXT PRIMARY KEY, view_id TEXT, entity TEXT, stance TEXT,
        horizon TEXT, event_date TEXT, window_days INTEGER, return_pct REAL, status TEXT)""")
    conn.execute("""CREATE TABLE prediction_events_legacy (
        event_id TEXT PRIMARY KEY, view_id TEXT, entity TEXT, stance TEXT,
        horizon TEXT, event_date TEXT, window_days INTEGER, return_pct REAL, status TEXT)""")
    conn.execute("INSERT INTO user_decision_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("dec_a", "GOLD", "黄金", "commodity", "2026-08-06", "medium", "bullish", 0.7,
                  "判断文本", "open", '{"price": 580}', '["uvv_黄金_v01"]', "2026-08-06T10:00:00"))
    conn.execute("INSERT INTO user_decision_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("dec_b", "SEMI", "半导体", "sector", "2026-08-10", "short", "watch", None,
                  "观察", "open", None, None, "2026-08-10T09:00:00"))
    conn.execute("INSERT INTO decision_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("rev_1", "dec_a", "2026-08-20", -3.2, 1.0, -4.2, "miss",
                  "追高", "等回调", "acv_1", "2026-08-20T18:00:00"))
    conn.execute("INSERT INTO asset_card_versions VALUES (?,?,?,?,?,?,?,?)",
                 ("acv_1", "GOLD", 2, '{"version": 2}', "复盘修正", "user", "rev_1",
                  "2026-08-20T18:30:00"))
    # prediction_events: 2 resolved + 1 error（error 不建）
    for i, (st, ret) in enumerate([("resolved", -5.1), ("resolved", 3.0), ("error", None)]):
        conn.execute("INSERT INTO prediction_events VALUES (?,?,?,?,?,?,?,?,?)",
                     (f"pe_{i}", "vid_gold_1" if i < 2 else None, "黄金", "bullish",
                      "medium", "2026-08-07", 10, ret, st))
    # legacy: 1 resolved
    conn.execute("INSERT INTO prediction_events_legacy VALUES (?,?,?,?,?,?,?,?,?)",
                 ("pe_legacy_0", "vid_gold_1", "黄金", "bullish", "medium",
                  "2026-08-08", 5, -2.0, "resolved"))
    conn.commit()
    conn.close()


def _seed_lifecycle_history(p: Path) -> None:
    """lifecycle 库：P0 表 + 两条 view 痕迹（一条 falsified 带 outcome link，一条 active）。"""
    conn = evt.connect(db=p)
    uvv.ensure_schema(conn)  # P1a 版本链表（build 的 user_view_changed 读取）
    conn.execute("CREATE TABLE IF NOT EXISTS view_status_history ("
                 "id INTEGER PRIMARY KEY AUTOINCREMENT, view_id TEXT NOT NULL,"
                 "old_status TEXT, new_status TEXT NOT NULL, reason TEXT NOT NULL,"
                 "linked_outcome_id TEXT, linked_view_id TEXT,"
                 "changed_by TEXT NOT NULL, changed_at TEXT NOT NULL)")
    conn.execute("INSERT INTO view_status_history (view_id, old_status, new_status, reason,"
                 "linked_outcome_id, linked_view_id, changed_by, changed_at) VALUES (?,?,?,?,?,?,?,?)",
                 ("vid_gold_1", "active", "falsified", "行情打脸", "pe_0", None,
                  "evaluate_view_outcomes", "2026-09-03T12:00:00"))
    conn.execute("INSERT INTO view_status_history (view_id, old_status, new_status, reason,"
                 "linked_outcome_id, linked_view_id, changed_by, changed_at) VALUES (?,?,?,?,?,?,?,?)",
                 ("vid_other_1", "active", "expired", "超窗", None, None,
                  "migrate", "2026-09-03T01:00:00"))
    conn.commit()
    conn.close()


def _seed_jsonl(p: Path) -> None:
    rows = [
        {"view_id": "vid_gold_1", "analyst": "任泽平", "claim": "黄金长期看多",
         "date": "2026-06-27", "horizon": "long", "authority": "B"},
        {"view_id": "vid_other_1", "analyst": "某机构", "claim": "其他观点",
         "date": "2026-06-20", "horizon": "medium", "authority": "C"},
    ]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def test_build_full_and_idempotent(tmp_path):
    dec_db = tmp_path / "decision.db"
    _seed_decision_db(dec_db)
    lc_db = tmp_path / "lifecycle.db"
    _seed_lifecycle_history(lc_db)
    jl = tmp_path / "structured_views.jsonl"
    _seed_jsonl(jl)

    r1 = build_all(lc_db, dec_db, jl, dry_run=False)
    assert r1["decision_created"] == 2
    assert r1["review_created"] == 1
    assert r1["asset_card_versioned"] == 1
    assert r1["outcome_observed"] == 3  # 2 resolved + 1 legacy resolved
    assert r1["view_status_changed"] == 2
    assert r1["view_created"] == 2
    assert r1["view_created_missing_src"] == 0
    assert r1["total_events"] == 2 + 1 + 1 + 3 + 2 + 2

    # 幂等：重跑零新增
    r2 = build_all(lc_db, dec_db, jl, dry_run=False)
    assert r2["total_events"] == r1["total_events"]

    # event_links 关系齐全
    conn = evt.connect(db=lc_db)
    links = conn.execute("SELECT linked_type, linked_id, relation FROM event_links").fetchall()
    rel = {(l["linked_type"], l["linked_id"], l["relation"]) for l in links}
    assert ("decision", "dec_a", "self") in rel
    assert ("decision", "dec_a", "reviewed_by") in rel
    assert ("review", "rev_1", "produced_version") in rel
    assert ("view", "vid_gold_1", "outcome_of") in rel
    assert ("outcome", "pe_0", "caused_status") in rel
    conn.close()


def test_build_dry_run_no_write(tmp_path):
    dec_db = tmp_path / "decision.db"
    _seed_decision_db(dec_db)
    lc_db = tmp_path / "lifecycle.db"
    _seed_lifecycle_history(lc_db)
    jl = tmp_path / "structured_views.jsonl"
    _seed_jsonl(jl)
    r = build_all(lc_db, dec_db, jl, dry_run=True)
    assert r["dry_run"] and r["total_events"] == 0
    conn = evt.connect(db=lc_db)
    assert evt.total(conn) == 0
    conn.close()


def test_trace_decision_chain(tmp_path):
    dec_db = tmp_path / "decision.db"
    _seed_decision_db(dec_db)
    lc_db = tmp_path / "lifecycle.db"
    _seed_lifecycle_history(lc_db)
    jl = tmp_path / "structured_views.jsonl"
    _seed_jsonl(jl)
    build_all(lc_db, dec_db, jl)
    conn = evt.connect(db=lc_db)
    chain = evt.trace_decision(conn, "dec_a")
    types = [c["event_type"] for c in chain]
    assert "decision_created" in types and "review_created" in types
    assert "asset_card_versioned" in types  # link review → 决策链含资产卡版本
    conn.close()


# ---------- reconcile（刀4：幂等补缺） ----------

def _seed_user_view_v2(p: Path) -> None:
    """版本链加一条 v2（模拟 P1a append 产物）→ 应产生 user_view_changed 事件。"""
    conn = evt.connect(db=p)
    conn.execute("INSERT INTO user_view_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("uvv_黄金_v02", "黄金", 2,
                  json.dumps({"asset": "黄金", "view": "v2 新观点"}, ensure_ascii=False),
                  "strengthen", "9月加仓逻辑更清晰", None, None, None,
                  "uvv_黄金_v01", "manual", "2026-09-03T22:30:00"))
    conn.execute("""INSERT INTO user_view_current VALUES (?,?,?,?)
                    ON CONFLICT(view_key) DO UPDATE SET
                      current_version_id=excluded.current_version_id,
                      current_version_no=excluded.current_version_no,
                      updated_at=excluded.updated_at""",
                 ("黄金", "uvv_黄金_v02", 2, "2026-09-03T22:30:00"))
    conn.commit()
    conn.close()


def _env_full(tmp_path):
    dec_db = tmp_path / "decision.db"
    _seed_decision_db(dec_db)
    lc_db = tmp_path / "lifecycle.db"
    _seed_lifecycle_history(lc_db)
    jl = tmp_path / "structured_views.jsonl"
    _seed_jsonl(jl)
    return dec_db, lc_db, jl


def test_query_timeline_filters(tmp_path):
    conn = evt.connect(db=tmp_path / "lifecycle.db")
    evt.insert_event(conn, "decision_created", "2026-09-01", "user", "d1", None,
                     "s/1", {"decision_id": "dec_1"})
    evt.insert_event(conn, "decision_created", "2026-09-03", "user", "d2", None,
                     "s/2", {"decision_id": "dec_2"})
    evt.insert_event(conn, "outcome_observed", "2026-09-02", "market", "o1", None,
                     "s/3", {"view_id": "v1"})
    # 倒序 + limit
    rows = evt.query_timeline(conn, limit=2)
    assert [r["title"] for r in rows] == ["d2", "o1"]
    # 类型过滤
    rows = evt.query_timeline(conn, event_type="outcome_observed")
    assert len(rows) == 1 and rows[0]["payload"]["view_id"] == "v1"
    # actor 过滤
    rows = evt.query_timeline(conn, actor="market")
    assert len(rows) == 1 and rows[0]["event_type"] == "outcome_observed"
    # since 过滤
    rows = evt.query_timeline(conn, since="2026-09-02", limit=10)
    assert [r["title"] for r in rows] == ["d2", "o1"]
    conn.close()


def test_reconcile_after_build_zero_delta(tmp_path):
    dec_db, lc_db, jl = _env_full(tmp_path)
    build_all(lc_db, dec_db, jl)
    before = evt.total(evt.connect(db=lc_db))
    build.build_all(lc_db, dec_db, jl)  # reconcile 内核 = build_all（幂等补缺）
    after = evt.total(evt.connect(db=lc_db))
    assert before == after  # 无缺漏零新增


def test_reconcile_picks_new_decision(tmp_path):
    """build 后新增一条决策 → reconcile 补 1 条 decision_created。"""
    dec_db, lc_db, jl = _env_full(tmp_path)
    build_all(lc_db, dec_db, jl)
    # 新增决策（迟到/新录入）
    conn = sqlite3.connect(dec_db)
    conn.execute("INSERT INTO user_decision_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("dec_new", "GOLD", "黄金", "commodity", "2026-09-04", "medium",
                  "bullish", 0.8, "新决策", "open", None, None, "2026-09-04T09:00:00"))
    conn.commit()
    conn.close()
    conn = evt.connect(db=lc_db)
    n_before = evt.total(conn)
    conn.close()
    build.build_all(lc_db, dec_db, jl)
    conn = evt.connect(db=lc_db)
    assert evt.total(conn) == n_before + 1
    types = evt.count_by_type(conn)
    conn.close()
    # 新增的是 decision_created
    conn2 = sqlite3.connect(lc_db)
    r = conn2.execute("SELECT event_type, payload_json FROM event_timeline "
                      "WHERE source_ref LIKE '%dec_new%'").fetchone()
    conn2.close()
    assert r is not None and r[0] == "decision_created"
    assert "dec_new" in r[1]


def test_reconcile_picks_user_view_v2(tmp_path):
    """版本链 append v2（build 后发生）→ reconcile 补 user_view_changed。"""
    dec_db, lc_db, jl = _env_full(tmp_path)
    build_all(lc_db, dec_db, jl)
    _seed_user_view_v2(lc_db)
    conn = evt.connect(db=lc_db)
    n_before = evt.total(conn)
    conn.close()
    build.build_all(lc_db, dec_db, jl)
    conn = evt.connect(db=lc_db)
    assert evt.total(conn) == n_before + 1
    assert evt.count_by_type(conn).get("user_view_changed") == 1
    # link 到 user_view 对象
    lk = conn.execute("SELECT linked_id FROM event_links WHERE linked_type='user_view'").fetchall()
    assert any(l["linked_id"] == "黄金" for l in lk)
    conn.close()
