#!/usr/bin/env python3
"""用户信念版本链单测（记忆体系 P1a，刀0）：DDL/存量迁移幂等/current 保护。

跑：cd E:\\qianboshi-agent && C:/Python314/python.exe -m pytest tests/test_user_view_versions.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import user_view_versions as uvv  # noqa: E402


def _myviews(tmp: Path, keys: list[str]) -> Path:
    views = [{"asset": k, "date": "2026-08-05", "view": f"{k} 观点原文",
              "strategy": f"{k} 策略", "status": "关注"} for k in keys]
    d = {"updated_at": "2026-08-05", "account": "母若凡", "views": views,
         "rule_engine": {"version": "1.0"}}
    p = tmp / "my_views.json"
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    return p


@pytest.fixture()
def env(tmp_path):
    keys = ["投资理念", "黄金", "创新药", "科技股半导体", "白酒", "铝神火股份"]
    mv = _myviews(tmp_path, keys)
    db = tmp_path / "view_lifecycle.db"
    conn = uvv.connect(db=db)
    yield {"conn": conn, "myviews": mv, "db": db, "keys": keys}
    conn.close()


# ---------- DDL ----------

def test_connect_creates_p1a_schema(env):
    tabs = {r[0] for r in env["conn"].execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"user_view_versions", "user_view_current"} <= tabs
    # P0 表共存
    assert "view_lifecycle" in tabs


# ---------- 存量迁移 ----------

def test_migrate_six_keys(env):
    r = uvv.migrate_from_myviews(env["conn"], myviews_path=env["myviews"])
    assert r["total"] == 6 and r["created"] == 6 and r["skipped"] == 0
    s = uvv.stats(env["conn"])
    assert s["versions"] == 6 and s["current"] == 6
    # 每 key version_no=1 create legacy_import
    rows = env["conn"].execute(
        "SELECT version_id, view_key, version_no, change_type, change_reason, content_json "
        "FROM user_view_versions ORDER BY view_key").fetchall()
    assert len(rows) == 6
    for row in rows:
        assert row["version_no"] == 1
        assert row["change_type"] == "create"
        assert "legacy_import" in row["change_reason"]
        content = json.loads(row["content_json"])
        assert content["asset"] == row["view_key"]
        assert content["view"]  # 原文逐字保留


def test_migrate_idempotent(env):
    uvv.migrate_from_myviews(env["conn"], myviews_path=env["myviews"])
    r2 = uvv.migrate_from_myviews(env["conn"], myviews_path=env["myviews"])
    assert r2["created"] == 0 and r2["skipped"] == 6
    assert uvv.stats(env["conn"])["versions"] == 6


def test_migrate_dry_run_no_write(env):
    r = uvv.migrate_from_myviews(env["conn"], myviews_path=env["myviews"], dry_run=True)
    assert r["dry_run"] and r["total"] == 6 and r["created"] == 6
    assert uvv.stats(env["conn"])["versions"] == 0  # 未落库


def test_migrate_never_overwrites_higher_current(env):
    """已 append 到 v2 的 key，重跑 migrate 不得把 current 拉回 v1。"""
    conn = env["conn"]
    uvv.migrate_from_myviews(conn, myviews_path=env["myviews"])
    # 模拟刀1 append：黄金 → v2
    conn.execute(
        "INSERT INTO user_view_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("uvv_黄金_v02", "黄金", 2, json.dumps({"asset": "黄金", "view": "v2 新观点"},
                                            ensure_ascii=False), "clarify",
         "黄金 更新为 v2", None, None, None, "uvv_黄金_v01", "manual", "2026-09-03T22:00:00+08:00"))
    conn.execute(
        """INSERT INTO user_view_current VALUES (?,?,?,?)
           ON CONFLICT(view_key) DO UPDATE SET
             current_version_id=excluded.current_version_id,
             current_version_no=excluded.current_version_no,
             updated_at=excluded.updated_at""",
        ("黄金", "uvv_黄金_v02", 2, "2026-09-03T22:00:00+08:00"))
    conn.commit()
    # 重跑 migrate
    r = uvv.migrate_from_myviews(conn, myviews_path=env["myviews"])
    assert r["skipped"] == 6
    cur = conn.execute(
        "SELECT current_version_id, current_version_no FROM user_view_current WHERE view_key='黄金'"
    ).fetchone()
    assert cur["current_version_no"] == 2  # 不被拉回 v1


def test_migrate_no_key_row_skipped(tmp_path):
    p = _myviews(tmp_path, ["黄金"])
    d = json.loads(p.read_text(encoding="utf-8-sig"))
    d["views"].append({"date": "2026-08-05", "view": "无 asset 键", "strategy": ""})
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8-sig")
    conn = uvv.connect(db=tmp_path / "t.db")
    r = uvv.migrate_from_myviews(conn, myviews_path=p)
    assert r["no_key"] == 1 and r["total"] == 1
    conn.close()
