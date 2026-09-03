#!/usr/bin/env python3
"""用户信念版本链 service（记忆体系 P1a，架构文档 v6 §5.1 / 03 融合终版 §5）。

职责：
- 建表：data/views/view_lifecycle.db 追加 user_view_versions + user_view_current
  （与 P0 view_lifecycle 同库，但 schema 独立管理，不动已交付的 view_lifecycle.py）
- migrate：把 data/my_views.json 存量 views[]（asset=view_key 粒度）初始化为
  version_no=1 / change_type=create / reason=legacy_import，my_views.json 只读不写
- append（刀1）：唯一正规写入口——写版本 → 更新 current → 重建投影
- stats：版本链现状统计

原则：my_views.json 为当前投影（views 数组权威）；禁直接编辑 json；
版本变更必填 change_reason；迁移幂等可重跑；版本只追加不覆盖。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_data_dir, load_config  # noqa: E402
import view_lifecycle  # noqa: E402  (复用 db_path/connect)

# change_type 八枚举（03 融合终版 §5）
CHANGE_TYPES = ("create", "clarify", "strengthen", "weaken", "replace", "split", "merge", "retire")
DEFAULT_CREATED_BY = "manual"

SCHEMA_P1A = """
CREATE TABLE IF NOT EXISTS user_view_versions (
    version_id TEXT PRIMARY KEY,
    view_key TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    content_json TEXT NOT NULL,
    change_type TEXT NOT NULL CHECK (change_type IN ('create','clarify','strengthen','weaken','replace','split','merge','retire')),
    change_reason TEXT NOT NULL,
    trigger_event_id TEXT,
    linked_decision_id TEXT,
    linked_review_id TEXT,
    parent_version_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (view_key, version_no)
);
CREATE TABLE IF NOT EXISTS user_view_current (
    view_key TEXT PRIMARY KEY,
    current_version_id TEXT NOT NULL,
    current_version_no INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_uvv_key_no ON user_view_versions(view_key, version_no);
"""


def my_views_path(config: dict[str, Any] | None = None) -> Path:
    """my_views.json 路径：data_dir/my_views.json（带 BOM+LF，读写按 utf-8-sig）。"""
    config = config or load_config()
    return get_data_dir(config) / "my_views.json"


def read_my_views(path: str | Path | None = None) -> dict[str, Any]:
    """读 my_views.json（utf-8-sig，兼容 BOM）。文件缺失/损坏返回最小骨架。"""
    p = Path(path) if path else my_views_path()
    if not p.exists():
        return {"views": [], "updated_at": "", "account": "", "rule_engine": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"views": [], "updated_at": "", "account": "", "rule_engine": {}}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """P1a 两表幂等建表（与 P0 表同库共存，独立管理）。"""
    conn.executescript(SCHEMA_P1A)


def connect(config: dict[str, Any] | None = None, db: str | Path | None = None) -> sqlite3.Connection:
    """连 lifecycle 库并确保 P1a schema 就位。"""
    conn = view_lifecycle.connect(config=config, db=db)
    ensure_schema(conn)
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug(view_key: str) -> str:
    """view_key → 稳定 id 前缀（中文保留，其余非字符合理化为 _）。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", str(view_key)).strip("_")
    return s or "key"


def version_id_for(view_key: str, version_no: int) -> str:
    return f"uvv_{_slug(view_key)}_v{version_no:02d}"


def migrate_from_myviews(
    conn: sqlite3.Connection,
    myviews_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """存量初始化迁移（幂等）：my_views.json views[] → 每 key 一条 version_no=1 create。

    - my_views.json 只读不写；投影未变（现存量即 v1），无需重建。
    - 已存在 version_id → 跳过（幂等可重跑，绝不覆盖）。
    返回 {"total","created","skipped","no_key","dry_run","db_path"}。
    """
    d = read_my_views(myviews_path)
    rows = d.get("views") or []
    total = created = skipped = no_key = 0
    now = _now()
    to_insert = []
    cur_upsert = []
    existing: set[str] = {r[0] for r in conn.execute(
        "SELECT version_id FROM user_view_versions WHERE version_no=1").fetchall()}
    for v in rows:
        key = v.get("asset")
        if not key:
            no_key += 1
            continue
        total += 1
        vid = version_id_for(key, 1)
        content = json.dumps(v, ensure_ascii=False)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        reason = f"legacy_import: 存量信念初始化 v1 (sha256={digest})"
        if vid in existing:
            skipped += 1
            continue
        created += 1
        if not dry_run:
            to_insert.append((vid, key, 1, content, "create", reason, None, None, None, None, DEFAULT_CREATED_BY, now))
            cur_upsert.append((key, vid, 1, now))
    if not dry_run:
        conn.executemany(
            "INSERT OR IGNORE INTO user_view_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", to_insert
        )
        # current 只初始化（v1 恒为最早版）；若已存在更高版本 current，绝不覆盖
        conn.executemany(
            "INSERT OR IGNORE INTO user_view_current (view_key, current_version_id, current_version_no, updated_at) VALUES (?,?,?,?)",
            cur_upsert,
        )
        conn.commit()
    return {"total": total, "created": created, "skipped": skipped,
            "no_key": no_key, "dry_run": dry_run}


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    n_ver = conn.execute("SELECT COUNT(*) FROM user_view_versions").fetchone()[0]
    n_cur = conn.execute("SELECT COUNT(*) FROM user_view_current").fetchone()[0]
    cur_rows = conn.execute(
        "SELECT view_key, current_version_no, updated_at FROM user_view_current ORDER BY view_key"
    ).fetchall()
    return {"versions": n_ver, "current": n_cur,
            "keys": [dict(r) for r in cur_rows]}


def main() -> None:
    parser = argparse.ArgumentParser(description="用户信念版本链（P1a）：migrate/stats/append")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mig = sub.add_parser("migrate", help="存量 my_views.json 初始化迁移（幂等）")
    p_mig.add_argument("--dry-run", action="store_true", help="只统计不落库")
    p_mig.add_argument("--db", help="覆盖 lifecycle 库路径")

    p_stats = sub.add_parser("stats", help="版本链现状统计")
    p_stats.add_argument("--db", help="覆盖 lifecycle 库路径")
    args = parser.parse_args()

    if args.cmd == "migrate":
        target = Path(args.db) if args.db else view_lifecycle.db_path()
        if not args.dry_run and target.exists():
            bak = str(target) + f".bak_{datetime.now():%Y%m%d_%H%M%S}_pre_uvv_migrate"
            shutil.copy2(target, bak)
            print(f"[备份] {target} -> {bak}")
        conn = connect(db=target)
        try:
            result = migrate_from_myviews(conn, dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps(stats(conn), ensure_ascii=False, indent=2))
        finally:
            conn.close()
    elif args.cmd == "stats":
        conn = connect(db=args.db)
        try:
            print(json.dumps(stats(conn), ensure_ascii=False, indent=2))
        finally:
            conn.close()


if __name__ == "__main__":
    main()
