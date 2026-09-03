#!/usr/bin/env python3
"""观点生命周期 service（记忆体系 P0，架构文档 v6 §5.1 / ADR-004）。

职责：
- 建库建表：data/views/view_lifecycle.db（view_lifecycle + view_status_history）
- migrate：把 data/views/structured_views.jsonl 全量 view_id 派生为生命周期行
  （非 excluded → active；excluded(坏时间戳/幻觉质量排除 2026-08-30) → expired + suspect）
- transition：六态转移（active/active_low_quality/confirmed/falsified/expired/superseded），
  只追加不覆盖，history 全留痕
- 只读：status_map()（供 view_store 过滤 facade）、stats()

原则：jsonl 原文件永不改动；迁移幂等可重跑；状态变更必带 reason；
db 缺失/损坏时所有读接口返回空（不阻断日报）。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import get_data_dir, load_config  # noqa: E402

# 六态（架构文档 v6 §5.1）
STATUSES = ("active", "active_low_quality", "confirmed", "falsified", "expired", "superseded")
# 可作当前建议引用的状态（日报/查询只读这些）
ACTIVE_SET = {"active", "confirmed", "active_low_quality"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS view_lifecycle (
    view_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('active','active_low_quality','confirmed','falsified','expired','superseded')),
    valid_from TEXT, valid_until TEXT,
    authority TEXT, confidence REAL, match_quality REAL,
    linked_outcome_id TEXT, superseded_by_view_id TEXT,
    transition_reason TEXT, transitioned_at TEXT,
    source_ref TEXT, data_quality TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS view_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    view_id TEXT NOT NULL,
    old_status TEXT, new_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    linked_outcome_id TEXT, linked_view_id TEXT,
    changed_by TEXT NOT NULL, changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lifecycle_status ON view_lifecycle(status);
"""


def db_path(config: dict[str, Any] | None = None) -> Path:
    """lifecycle 库路径：config.memory.view_lifecycle_db 优先，默认 data/views/view_lifecycle.db。"""
    config = config or load_config()
    mem = config.get("memory") or {}
    p = mem.get("view_lifecycle_db")
    if p:
        path = Path(p)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path
    return get_data_dir(config) / "views" / "view_lifecycle.db"


def enabled(config: dict[str, Any] | None = None) -> bool:
    """feature flag：memory.view_lifecycle_enabled（默认 False=旧行为不变）。"""
    config = config or load_config()
    return bool(((config.get("memory") or {}).get("view_lifecycle_enabled")))


def connect(config: dict[str, Any] | None = None, db: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db) if db else db_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def migrate_from_jsonl(
    conn: sqlite3.Connection,
    views_path: str | Path | None = None,
    excluded_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """存量派生迁移（幂等）：读 jsonl 全量 view_id → 写 lifecycle 行。

    - 已存在行（曾迁移/状态已转移）→ ON CONFLICT 跳过，绝不覆盖现状态。
    - excluded_view_ids（坏时间戳/幻觉质量排除）→ expired + data_quality=suspect。
    - 其余 → active。
    - dry_run=True 只统计不落库。
    返回 {"total","active","expired","skipped","dry_run","db_path"}。
    """
    from view_store import views_path as vs_views_path

    vp = Path(views_path) if views_path else vs_views_path()
    ep = Path(excluded_path) if excluded_path else vp.with_name("excluded_view_ids.json")

    excluded: set[str] = set()
    if ep.exists():
        try:
            excluded = set(json.loads(ep.read_text(encoding="utf-8")))
        except Exception:
            excluded = set()

    total = active = expired = 0
    rows_skipped = 0
    now = _now()
    to_insert: list[tuple[Any, ...]] = []
    with vp.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except Exception:
                continue
            vid = v.get("view_id")
            if not vid:
                continue
            total += 1
            if excluded and vid in excluded:
                status, dq, reason = "expired", "suspect", "legacy_excluded: 坏时间戳/幻觉质量排除(2026-08-30 黑名单)"
                expired += 1
            else:
                status, dq, reason = "active", "complete", "legacy_migrate: 存量观点默认 active(2026-09-03)"
                active += 1
            to_insert.append((
                vid, status, v.get("date"), None,
                str(v.get("authority")) if v.get("authority") else None,
                _num(v.get("confidence")), _num(v.get("match_quality")),
                None, None, reason, now,
                v.get("source_file") or v.get("source_bv"), dq, now, now,
            ))

    if dry_run:
        return {"total": total, "active": active, "expired": expired,
                "skipped": 0, "dry_run": True, "db_path": None}

    before = conn.execute("SELECT COUNT(*) c FROM view_lifecycle").fetchone()["c"]
    conn.executemany(
        """INSERT OR IGNORE INTO view_lifecycle
           (view_id,status,valid_from,valid_until,authority,confidence,match_quality,
            linked_outcome_id,superseded_by_view_id,transition_reason,transitioned_at,
            source_ref,data_quality,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        to_insert,
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) c FROM view_lifecycle").fetchone()["c"]
    return {"total": total, "active": active, "expired": expired,
            "skipped": total - (after - before), "dry_run": False,
            "db_path": str(db_path())}


def _num(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def transition(
    conn: sqlite3.Connection,
    view_id: str,
    new_status: str,
    reason: str,
    changed_by: str = "cli",
    linked_outcome_id: str | None = None,
    superseded_by_view_id: str | None = None,
    skip_outcome_check: bool = False,
) -> dict[str, Any]:
    """六态转移（只追加不覆盖，history 全留痕）。

    校验：状态值合法；reason 非空；falsified 默认必须带 linked_outcome_id
    （--skip-outcome-check 逃生门：人工/复盘路径无数值结果时用，lint 会列 WARN 待补）。
    """
    if new_status not in STATUSES:
        raise ValueError(f"非法状态: {new_status}（可选 {STATUSES}）")
    if not reason or not reason.strip():
        raise ValueError("transition 必须填写 reason")
    if new_status == "falsified" and not linked_outcome_id and not skip_outcome_check:
        raise ValueError("falsified 必须带 linked_outcome_id（证伪要挂结果），或 --skip-outcome-check 逃生")
    if new_status == "superseded" and not superseded_by_view_id:
        raise ValueError("superseded 必须带 superseded_by_view_id（被谁替代）")

    row = conn.execute("SELECT * FROM view_lifecycle WHERE view_id=?", (view_id,)).fetchone()
    if row is None:
        raise KeyError(f"view_id 不在 lifecycle 库（先跑 migrate）：{view_id}")
    old_status = row["status"]
    if old_status == new_status:
        raise ValueError(f"观点已是 {new_status}，无需转移")
    now = _now()
    with conn:
        conn.execute(
            """UPDATE view_lifecycle SET status=?, updated_at=?,
               linked_outcome_id=COALESCE(?, linked_outcome_id),
               superseded_by_view_id=COALESCE(?, superseded_by_view_id),
               transition_reason=?, transitioned_at=?, data_quality=? WHERE view_id=?""",
            (new_status, now, linked_outcome_id, superseded_by_view_id, reason, now,
             "suspect" if new_status in ("active_low_quality", "falsified") else row["data_quality"],
             view_id),
        )
        conn.execute(
            """INSERT INTO view_status_history
               (view_id, old_status, new_status, reason, linked_outcome_id, linked_view_id, changed_by, changed_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (view_id, old_status, new_status, reason, linked_outcome_id, superseded_by_view_id, changed_by, now),
        )
    return {"view_id": view_id, "old_status": old_status, "new_status": new_status, "changed_at": now}


def status_map(config: dict[str, Any] | None = None, db: str | Path | None = None) -> dict[str, str]:
    """view_id -> status 全量映射（读 facade 用）。db 缺失/异常 → 空 dict（日报不破）。"""
    try:
        path = Path(db) if db else db_path(config)
        if not path.exists():
            return {}
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT view_id, status FROM view_lifecycle").fetchall()
        conn.close()
        return {r["view_id"]: r["status"] for r in rows}
    except Exception:
        return {}


def history(conn: sqlite3.Connection, view_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM view_status_history WHERE view_id=? ORDER BY id DESC LIMIT ?", (view_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    by_status = {s: 0 for s in STATUSES}
    for r in conn.execute("SELECT status, COUNT(*) c FROM view_lifecycle GROUP BY status"):
        by_status[r["status"]] = r["c"]
    total = sum(by_status.values())
    by_dq = {r["data_quality"]: r["c"] for r in conn.execute(
        "SELECT data_quality, COUNT(*) c FROM view_lifecycle GROUP BY data_quality")}
    return {"total": total, "by_status": by_status, "by_data_quality": by_dq,
            "db_path": str(conn.execute("PRAGMA database_list").fetchone()["name"])}


def main() -> None:
    parser = argparse.ArgumentParser(description="观点生命周期（记忆体系 P0）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mig = sub.add_parser("migrate", help="存量迁移（幂等，可重跑）")
    p_mig.add_argument("--dry-run", action="store_true", help="只统计不落库")
    p_mig.add_argument("--db", help="覆盖 lifecycle 库路径")

    p_tr = sub.add_parser("transition", help="状态转移")
    p_tr.add_argument("view_id")
    p_tr.add_argument("status", choices=STATUSES)
    p_tr.add_argument("--reason", required=True)
    p_tr.add_argument("--by", default="cli")
    p_tr.add_argument("--linked-outcome")
    p_tr.add_argument("--superseded-by")
    p_tr.add_argument("--skip-outcome-check", action="store_true")
    p_tr.add_argument("--db")

    p_hist = sub.add_parser("history", help="观点状态历史")
    p_hist.add_argument("view_id")
    p_hist.add_argument("--db")

    sub.add_parser("stats", help="状态分布")

    args = parser.parse_args()
    conn = connect(db=args.db) if getattr(args, "db", None) else connect()

    if args.cmd == "migrate":
        cfg = load_config()
        result = migrate_from_jsonl(conn, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "transition":
        try:
            r = transition(conn, args.view_id, args.status, args.reason, changed_by=args.by,
                           linked_outcome_id=args.linked_outcome,
                           superseded_by_view_id=args.superseded_by,
                           skip_outcome_check=args.skip_outcome_check)
            print(json.dumps(r, ensure_ascii=False, indent=2))
        except (ValueError, KeyError) as e:
            print(f"[拒绝] {e}", file=sys.stderr)
            sys.exit(2)
    elif args.cmd == "history":
        for h in history(conn, args.view_id):
            print(f"{h['changed_at']} | {h['old_status']} -> {h['new_status']} | {h['changed_by']} | {h['reason']}")
    elif args.cmd == "stats":
        print(json.dumps(stats(conn), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
