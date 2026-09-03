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


def snapshot_ids(db: str | Path | None = None) -> dict[str, Any] | None:
    """决策创建时冻结信念版本快照：current 全量 version_id 数组（决策可追溯"当时信什么"）。

    - 返回 {"as_of": ISO 时间, "ids": [version_id,...]}（按 view_key 序）；
    - lifecycle 库缺失/损坏/无表 → None（调用方降级，决策录入绝不因冻结失败而阻断）。
    """
    try:
        conn = connect(db=db)
        try:
            rows = conn.execute(
                "SELECT current_version_id FROM user_view_current ORDER BY view_key").fetchall()
        finally:
            conn.close()
        return {"as_of": _now(), "ids": [r["current_version_id"] for r in rows]}
    except Exception:
        return None


def get_current(conn: sqlite3.Connection, view_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM user_view_current WHERE view_key=?", (view_key,)
    ).fetchone()


def get_version_chain(conn: sqlite3.Connection, view_key: str) -> list[dict[str, Any]]:
    """某 view_key 的完整版本链（升序，审计/复盘用）。"""
    rows = conn.execute(
        "SELECT version_id, version_no, change_type, change_reason, parent_version_id, "
        "created_by, created_at, content_json FROM user_view_versions "
        "WHERE view_key=? ORDER BY version_no", (view_key,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["content"] = json.loads(d.pop("content_json"))
        except Exception:
            d["content"] = None
        out.append(d)
    return out


def _content_asset(content: dict[str, Any]) -> str:
    return str(content.get("asset", ""))


def rebuild_projection(
    conn: sqlite3.Connection,
    myviews_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """重建 my_views.json 投影（views 数组 = 版本链 current 的权威投影）。

    - 基准顺序 = 现文件 views[] asset 序（原位保留）；版本链中末版为 retire 的 key 剔除；
    - 版本链有而文件无、且末版非 retire 的 key（create 场景）追加尾部（按 updated_at 序）；
    - rule_engine 区原样保留；updated_at 刷新为 now；写回保留 BOM + LF（utf-8-sig）。
    - 原子写：先备份 .bak_*_pre_append 再 tmp+os.replace。
    """
    p = Path(myviews_path) if myviews_path else my_views_path()
    doc = read_my_views(p)
    file_keys = [v.get("asset") for v in (doc.get("views") or [])]
    cur_rows = conn.execute(
        "SELECT c.view_key, c.current_version_id, c.current_version_no, c.updated_at, "
        "v.content_json, v.change_type "
        "FROM user_view_current c JOIN user_view_versions v ON v.version_id=c.current_version_id "
        "ORDER BY c.updated_at, c.view_key").fetchall()
    cur_map = {r["view_key"]: r for r in cur_rows}

    rebuilt: list[dict[str, Any]] = []
    dropped_retired: list[str] = []
    # 1) 原位：文件顺序为基准
    for key in file_keys:
        if not key:
            continue
        r = cur_map.get(key)
        if not r:
            continue  # 链缺文件有 = 异常态，保守跳过
        if r["change_type"] == "retire":
            dropped_retired.append(key)
            continue
        content = json.loads(r["content_json"])
        content.setdefault("asset", key)
        rebuilt.append(content)
    # 2) 追加：链有文件无 且 非 retire
    appended_new: list[str] = []
    chain_keys = {r["view_key"] for r in cur_rows}
    for key in chain_keys - set(file_keys):
        r = cur_map[key]
        if r["change_type"] == "retire":
            dropped_retired.append(key)
            continue
        content = json.loads(r["content_json"])
        content.setdefault("asset", key)
        rebuilt.append(content)
        appended_new.append(key)

    result = {"rebuilt": len(rebuilt), "dropped_retired": dropped_retired,
              "appended_new": appended_new, "dry_run": dry_run, "path": str(p)}
    if dry_run:
        return result

    doc["views"] = rebuilt
    doc["updated_at"] = _now()
    if p.exists():
        bak = str(p) + f".bak_{datetime.now():%Y%m%d_%H%M%S}_pre_append"
        shutil.copy2(p, bak)
        result["backup"] = bak
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text("\ufeff" + text + "\n", encoding="utf-8", newline="\n")  # BOM+LF
    tmp.replace(p)
    return result


def append_version(
    conn: sqlite3.Connection,
    view_key: str,
    content: dict[str, Any],
    change_type: str,
    change_reason: str,
    created_by: str = DEFAULT_CREATED_BY,
    myviews_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """唯一正规写入口：写新版本 → 更新 current → 重建投影（原文件先备份）。

    校验：change_type 必在八枚举（split/merge 需多 key 事务，本轮拒绝）；
    change_reason 必填；content.asset 必须等于 view_key（改名=retire 旧+create 新）。
    """
    if change_type not in CHANGE_TYPES:
        raise ValueError(f"change_type 必须 ∈ {CHANGE_TYPES}")
    if change_type in ("split", "merge"):
        raise NotImplementedError("split/merge 需多 key 事务与投影重排，本轮走单 key 蓝图")
    if not change_reason or not str(change_reason).strip():
        raise ValueError("change_reason 必填（版本链可追溯的根基）")
    if _content_asset(content) != view_key:
        raise ValueError(f"content.asset ({_content_asset(content)!r}) 必须等于 view_key ({view_key!r})")
    cur = get_current(conn, view_key)
    if cur is None:
        if change_type != "create":
            raise ValueError(f"view_key '{view_key}' 尚无版本链：新 key 需 change_type=create，"
                             f"存量 key 请先跑 migrate 初始化")
        parent_id = None
        new_no = 1
    else:
        if change_type == "create":
            raise ValueError(f"view_key '{view_key}' 已有版本链，create 仅限新 key 首次入链")
        parent_id = cur["current_version_id"]
        new_no = int(cur["current_version_no"]) + 1

    new_id = version_id_for(view_key, new_no)
    content_json = json.dumps(content, ensure_ascii=False)
    now = _now()
    result: dict[str, Any] = {
        "version_id": new_id, "view_key": view_key, "version_no": new_no,
        "change_type": change_type, "parent_version_id": parent_id,
        "dry_run": dry_run,
    }
    if dry_run:
        result["projection"] = rebuild_projection(conn, myviews_path, dry_run=True)
        return result

    conn.execute(
        "INSERT INTO user_view_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id, view_key, new_no, content_json, change_type, change_reason,
         None, None, None, parent_id, created_by, now))
    conn.execute(
        """INSERT INTO user_view_current (view_key, current_version_id, current_version_no, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(view_key) DO UPDATE SET
             current_version_id=excluded.current_version_id,
             current_version_no=excluded.current_version_no,
             updated_at=excluded.updated_at""",
        (view_key, new_id, new_no, now))
    conn.commit()
    result["projection"] = rebuild_projection(conn, myviews_path)
    return result


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

    p_app = sub.add_parser("append", help="写新信念版本并重建投影（唯一正规写入口）")
    p_app.add_argument("--view-key", required=True, help="view_key（= views[] 的 asset 字段）")
    p_app.add_argument("--change-type", required=True, choices=list(CHANGE_TYPES),
                       help="八枚举之一（split/merge 本轮拒绝）")
    p_app.add_argument("--reason", required=True, help="变更原因（必填，可追溯根基）")
    src = p_app.add_mutually_exclusive_group(required=True)
    src.add_argument("--content-json", help="新版本整条 view 的 JSON 字符串（含 asset 键）")
    src.add_argument("--content-file", help="新版本整条 view 的 JSON 文件路径")
    p_app.add_argument("--by", default=DEFAULT_CREATED_BY, help="变更人（默认 manual）")
    p_app.add_argument("--myviews", help="覆盖 my_views.json 路径")
    p_app.add_argument("--dry-run", action="store_true", help="预演：不落库不写文件")
    p_app.add_argument("--db", help="覆盖 lifecycle 库路径")

    p_stats = sub.add_parser("stats", help="版本链现状统计")
    p_stats.add_argument("--db", help="覆盖 lifecycle 库路径")

    p_chain = sub.add_parser("chain", help="某 view_key 的完整版本链")
    p_chain.add_argument("--view-key", required=True)
    p_chain.add_argument("--db", help="覆盖 lifecycle 库路径")
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
    elif args.cmd == "append":
        conn = connect(db=args.db)
        try:
            content = json.loads(args.content_json) if args.content_json \
                else json.loads(Path(args.content_file).read_text(encoding="utf-8-sig"))
            result = append_version(
                conn, args.view_key, content, args.change_type, args.reason,
                created_by=args.by, myviews_path=args.myviews, dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except (ValueError, NotImplementedError) as e:
            print(f"[拒绝] {e}")
            sys.exit(2)
        finally:
            conn.close()
    elif args.cmd == "chain":
        conn = connect(db=args.db)
        try:
            chain = get_version_chain(conn, args.view_key)
            if not chain:
                print(f"[无] view_key '{args.view_key}' 无版本记录")
                sys.exit(1)
            for v in chain:
                print(f"v{v['version_no']:02d} {v['version_id']} [{v['change_type']}] "
                      f"{v['created_at']} parent={v['parent_version_id']} :: {v['change_reason']}")
                print(f"    {json.dumps(v['content'], ensure_ascii=False)[:160]}")
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
