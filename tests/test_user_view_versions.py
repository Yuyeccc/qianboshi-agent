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


# ---------- append（刀1：唯一正规写入口 + 投影重建） ----------

def _mig(env):
    uvv.migrate_from_myviews(env["conn"], myviews_path=env["myviews"])


def _gold_v2_content() -> dict:
    return {"asset": "黄金", "date": "2026-09-03", "view": "黄金 新观点 v2",
            "strategy": "回调买入", "status": "关注"}


def test_append_increments_to_v2(env):
    _mig(env)
    r = uvv.append_version(env["conn"], "黄金", _gold_v2_content(), "strengthen",
                           "9月验证回调后加仓逻辑更清晰", myviews_path=env["myviews"])
    assert r["version_no"] == 2 and r["parent_version_id"] == "uvv_黄金_v01"
    cur = uvv.get_current(env["conn"], "黄金")
    assert cur["current_version_id"] == "uvv_黄金_v02" and cur["current_version_no"] == 2
    assert uvv.stats(env["conn"])["versions"] == 7
    # v1 原文保留
    v1 = env["conn"].execute(
        "SELECT content_json FROM user_view_versions WHERE version_id='uvv_黄金_v01'").fetchone()
    assert "黄金 观点原文" in v1["content_json"]


def test_append_multi_versions_chain(env):
    _mig(env)
    uvv.append_version(env["conn"], "黄金", _gold_v2_content(), "clarify",
                       "第一改", myviews_path=env["myviews"])
    r3 = uvv.append_version(env["conn"], "黄金",
                            {"asset": "黄金", "view": "黄金 新观点 v3", "status": "关注"},
                            "weaken", "第二改 减弱", myviews_path=env["myviews"])
    assert r3["version_no"] == 3 and r3["parent_version_id"] == "uvv_黄金_v02"
    chain = uvv.get_version_chain(env["conn"], "黄金")
    assert [v["version_no"] for v in chain] == [1, 2, 3]
    assert chain[2]["change_type"] == "weaken"


def test_append_missing_reason_rejected(env):
    _mig(env)
    try:
        uvv.append_version(env["conn"], "黄金", _gold_v2_content(), "clarify", "   ")
        assert False, "应拒绝空 reason"
    except ValueError:
        pass


def test_append_bad_change_type_rejected(env):
    _mig(env)
    try:
        uvv.append_version(env["conn"], "黄金", _gold_v2_content(), "invalid", "原因")
        assert False, "应拒绝非法 change_type"
    except ValueError:
        pass


def test_append_split_merge_not_supported(env):
    _mig(env)
    try:
        uvv.append_version(env["conn"], "黄金", _gold_v2_content(), "split", "拆分")
        assert False, "split 本轮应拒绝"
    except NotImplementedError:
        pass


def test_append_content_asset_mismatch_rejected(env):
    _mig(env)
    try:
        uvv.append_version(env["conn"], "黄金",
                           {"asset": "白银", "view": "key 不一致"}, "replace", "原因")
        assert False, "content.asset 与 view_key 不一致应拒绝"
    except ValueError:
        pass


def test_append_projection_rebuilt_bom_kept(env):
    _mig(env)
    uvv.append_version(env["conn"], "黄金", _gold_v2_content(), "strengthen",
                       "投影重建验证", myviews_path=env["myviews"])
    raw = env["myviews"].read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM 保留
    assert b"\r\n" not in raw  # LF 保持
    d = json.loads(raw.decode("utf-8-sig"))
    keys = [v["asset"] for v in d["views"]]
    assert keys == env["keys"]  # 顺序原位保持
    gold = next(v for v in d["views"] if v["asset"] == "黄金")
    assert gold["view"] == "黄金 新观点 v2"
    assert d["rule_engine"] == {"version": "1.0"}  # rule_engine 原样保留
    assert d["updated_at"] != "2026-08-05"
    # 备份已生成
    baks = list(env["myviews"].parent.glob("my_views.json.bak_*_pre_append"))
    assert len(baks) == 1


def test_append_retire_removes_from_projection(env):
    _mig(env)
    uvv.append_version(env["conn"], "白酒",
                       {"asset": "白酒", "view": "白酒 最后版", "status": "回避"},
                       "retire", "白酒 观察结束，退出跟踪", myviews_path=env["myviews"])
    d = json.loads(env["myviews"].read_text(encoding="utf-8-sig"))
    keys = [v["asset"] for v in d["views"]]
    assert "白酒" not in keys and len(keys) == 5
    # 版本链仍完整保留
    chain = uvv.get_version_chain(env["conn"], "白酒")
    assert len(chain) == 2 and chain[1]["change_type"] == "retire"


def test_append_create_new_key_tail(env):
    _mig(env)
    # create 已在链的 key 拒绝
    try:
        uvv.append_version(env["conn"], "黄金", _gold_v2_content(), "create", "重复建")
        assert False, "create 仅限新 key，已链 key 应拒绝"
    except ValueError:
        pass
    # create 新 key：v1 建链 + 投影尾部追加
    r = uvv.append_version(env["conn"], "科技ETF",
                           {"asset": "科技ETF", "view": "新标的 观点"}, "create",
                           "用户新关注标的入链", myviews_path=env["myviews"])
    assert r["version_no"] == 1 and r["parent_version_id"] is None
    cur = uvv.get_current(env["conn"], "科技ETF")
    assert cur["current_version_id"] == "uvv_科技ETF_v01"
    d = json.loads(env["myviews"].read_text(encoding="utf-8-sig"))
    assert [v["asset"] for v in d["views"]][-1] == "科技ETF"
    # create 后 clarify v2
    r2 = uvv.append_version(env["conn"], "科技ETF",
                            {"asset": "科技ETF", "view": "新标的 澄清 v2"}, "clarify",
                            "补充逻辑", myviews_path=env["myviews"])
    assert r2["version_no"] == 2 and r2["parent_version_id"] == "uvv_科技ETF_v01"


def test_append_dry_run_no_side_effect(env):
    _mig(env)
    before_ver = uvv.stats(env["conn"])["versions"]
    before_file = env["myviews"].read_bytes()
    r = uvv.append_version(env["conn"], "黄金", _gold_v2_content(), "strengthen",
                           "dry 预演", myviews_path=env["myviews"], dry_run=True)
    assert r["dry_run"] and r["version_no"] == 2
    assert uvv.stats(env["conn"])["versions"] == before_ver  # 未落库
    assert env["myviews"].read_bytes() == before_file  # 文件未动
    assert not list(env["myviews"].parent.glob("my_views.json.bak_*"))
