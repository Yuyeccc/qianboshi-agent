#!/usr/bin/env python3
"""决策冻结信念版本单测（记忆体系 P1a，刀2）：列幂等迁移/冻结写入回读/snapshot_ids。

跑：cd E:\\qianboshi-agent && C:/Python314/python.exe -m pytest tests/test_decision_freeze.py -q
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import decision_db as ddb  # noqa: E402
import user_view_versions as uvv  # noqa: E402


def _mk_lifecycle(tmp: Path, keys: list[str]) -> Path:
    """造一个含 current 的 lifecycle 库（模拟 P1a 迁移后状态）。"""
    db = tmp / "view_lifecycle.db"
    conn = uvv.connect(db=db)
    for i, k in enumerate(keys, 1):
        vid = f"uvv_{k}_v01"
        conn.execute("INSERT INTO user_view_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (vid, k, 1, json.dumps({"asset": k, "view": f"{k} 原文"},
                                            ensure_ascii=False),
                      "create", f"legacy_import {k}", None, None, None, None,
                      "manual", "2026-09-03T22:00:00"))
        conn.execute("INSERT INTO user_view_current VALUES (?,?,?,?)",
                     (k, vid, 1, "2026-09-03T22:00:00"))
    conn.commit()
    conn.close()
    return db


# ---------- schema：新库与老库幂等迁移 ----------

def test_new_db_has_freeze_column(tmp_path):
    db = tmp_path / "dec.db"
    conn = ddb.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(user_decision_logs)")}
    assert "user_view_version_ids" in cols
    conn.close()


def test_legacy_db_alters_column(tmp_path):
    """老库无冻结列 → ensure 幂等补列，数据不丢。"""
    db = tmp_path / "dec.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE user_decision_logs (
            decision_id TEXT PRIMARY KEY, user_id TEXT DEFAULT 'default',
            asset_id TEXT NOT NULL, asset_name TEXT NOT NULL, asset_type TEXT,
            decision_date TEXT NOT NULL, horizon TEXT NOT NULL, direction TEXT NOT NULL,
            conviction REAL, thesis TEXT NOT NULL, key_reasons TEXT, premise TEXT,
            invalidation_conditions TEXT, action_note TEXT, asset_card_version INTEGER,
            debate_card_id TEXT, market_snapshot TEXT, status TEXT DEFAULT 'open',
            created_at TEXT, updated_at TEXT)
    """)
    conn.execute("INSERT INTO user_decision_logs (decision_id, asset_id, asset_name, "
                 "decision_date, horizon, direction, thesis, status) VALUES (?,?,?,?,?,?,?,?)",
                 ("dec_legacy_001", "GOLD", "黄金", "2026-08-01", "medium",
                  "bullish", "旧判断", "open"))
    conn.commit()
    conn.close()
    conn = ddb.connect(db)  # init_db 触发幂等迁移
    cols = {r[1] for r in conn.execute("PRAGMA table_info(user_decision_logs)")}
    assert "user_view_version_ids" in cols
    row = conn.execute("SELECT thesis, user_view_version_ids FROM user_decision_logs "
                       "WHERE decision_id='dec_legacy_001'").fetchone()
    assert row["thesis"] == "旧判断" and row["user_view_version_ids"] is None  # 数据不丢
    conn.close()


# ---------- upsert：冻结列写入与回读 ----------

def _decision(frozen=None):
    d = {"decision_id": "dec_freeze_test_001", "asset_id": "GOLD", "asset_name": "黄金",
         "asset_type": "commodity", "decision_date": "2026-09-03", "horizon": "medium",
         "direction": "bullish", "conviction": 0.7, "thesis": "冻结测试判断",
         "key_reasons": ["r1"], "premise": [], "invalidation_conditions": ["跌破 x"]}
    if frozen is not None:
        d["user_view_version_ids"] = frozen
    return d


def test_upsert_with_frozen_ids(tmp_path):
    db = tmp_path / "dec.db"
    ddb.upsert_decision_log(_decision(frozen=["uvv_黄金_v01", "uvv_投资理念_v01"]), path=db)
    rows = ddb.fetch_decisions(path=db)
    assert len(rows) == 1
    ids = json.loads(rows[0]["user_view_version_ids"])
    assert ids == ["uvv_黄金_v01", "uvv_投资理念_v01"]


def test_upsert_without_frozen_no_crash(tmp_path):
    db = tmp_path / "dec.db"
    ddb.upsert_decision_log(_decision(), path=db)
    rows = ddb.fetch_decisions(path=db)
    assert rows[0]["user_view_version_ids"] is None


def test_upsert_frozen_update_keeps_reasons(tmp_path):
    db = tmp_path / "dec.db"
    ddb.upsert_decision_log(_decision(frozen=["uvv_a_v01"]), path=db)
    d = _decision(frozen=["uvv_a_v02"])
    d["thesis"] = "更新后判断"
    ddb.upsert_decision_log(d, path=db)
    rows = ddb.fetch_decisions(path=db)
    assert len(rows) == 1
    assert json.loads(rows[0]["user_view_version_ids"]) == ["uvv_a_v02"]
    assert rows[0]["thesis"] == "更新后判断"


# ---------- snapshot_ids（冻结读取） ----------

def test_snapshot_ids_full(tmp_path):
    db = _mk_lifecycle(tmp_path, ["黄金", "投资理念", "白酒"])
    snap = uvv.snapshot_ids(db=db)
    assert snap is not None
    # snapshot 按 view_key 稳定序（中文按码点：投资理念<白酒<黄金）
    assert snap["ids"] == ["uvv_投资理念_v01", "uvv_白酒_v01", "uvv_黄金_v01"]
    assert "as_of" in snap


def test_snapshot_ids_empty_db(tmp_path):
    db = tmp_path / "empty.db"
    snap = uvv.snapshot_ids(db=db)  # connect 自动建库（空链）
    assert snap is not None and snap["ids"] == []


def test_snapshot_ids_missing_db_graceful(tmp_path):
    snap = uvv.snapshot_ids(db=tmp_path / "no_such_dir_anywhere" / "x.db")
    # connect 会尝试 mkdir 自动建库（空链）→ 返回空 ids 而非炸
    assert snap is not None and snap["ids"] == []


def test_snapshot_ids_corrupt_db_returns_none(tmp_path):
    """损坏库 → snapshot_ids 降级 None（决策录入不阻断）。"""
    db = tmp_path / "broken.db"
    db.write_bytes(b"not a sqlite file at all" * 100)
    assert uvv.snapshot_ids(db=db) is None
