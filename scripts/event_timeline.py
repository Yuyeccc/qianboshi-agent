#!/usr/bin/env python3
"""统一事件时间轴 service（记忆体系 P1b，架构文档 v6 §5.1 / 03 融合终版 §6）。

职责：
- 建表：data/views/view_lifecycle.db 追加 event_timeline + event_links（P1b schema 独立管理）
- insert_event：幂等写事件（source_fingerprint UNIQUE，重跑零新增；event_id 由指纹派生，确定性）
- link_event：事件关系（决策链/复盘回放用）
- 事件类型 14 枚举（03 融合终版 §6.1）：market_snapshot/source_ingested/view_created/
  view_status_changed/user_view_changed/decision_created/trade_executed/outcome_observed/
  review_created/rule_proposed/rule_activated/asset_card_versioned/report_generated/lint_run

原则：主表（decision/review/asset/views/prediction）是事实源，事件表是派生物可重建；
同库幂等；reconcile 每日兜底；旧脚本不改造（补偿式）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import view_lifecycle  # noqa: E402  (复用 db_path/connect)

EVENT_TYPES = (
    "market_snapshot", "source_ingested", "view_created", "view_status_changed",
    "user_view_changed", "decision_created", "trade_executed", "outcome_observed",
    "review_created", "rule_proposed", "rule_activated", "asset_card_versioned",
    "report_generated", "lint_run",
)
P1_TYPES = {  # P1 实际落库的事件（有主表源的；其余枚举随主表就位 P2 补）
    "view_created", "view_status_changed", "user_view_changed",
    "decision_created", "outcome_observed", "review_created", "asset_card_versioned",
}

SCHEMA_EVT = """
CREATE TABLE IF NOT EXISTS event_timeline (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    actor TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    source_ref TEXT,
    snapshot_ref TEXT,
    payload_json TEXT NOT NULL,
    source_fingerprint TEXT UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_links (
    event_id TEXT NOT NULL,
    linked_type TEXT NOT NULL,
    linked_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    PRIMARY KEY (event_id, linked_type, linked_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_evt_type_time ON event_timeline(event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_evt_links_linked ON event_links(linked_type, linked_id);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_EVT)


def connect(db: str | Path | None = None) -> sqlite3.Connection:
    """连 lifecycle 库并确保 P1b schema 就位。"""
    conn = view_lifecycle.connect(db=db)
    ensure_schema(conn)
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fingerprint_for(source_ref: str, payload: dict[str, Any]) -> str:
    """source_fingerprint = sha256(source_ref + 归一化 payload)，幂等判重核心。"""
    norm = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(f"{source_ref}|{norm}".encode("utf-8")).hexdigest()


def insert_event(
    conn: sqlite3.Connection,
    event_type: str,
    occurred_at: str,
    actor: str | None,
    title: str,
    summary: str | None,
    source_ref: str,
    payload: dict[str, Any],
    snapshot_ref: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """幂等写一条事件（fingerprint 冲突 → 跳过返回 inserted=False）。

    返回 {"event_id","inserted"}。event_id = event_<type>_<fingerprint[:10]> 确定性派生。
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"event_type 必须 ∈ {EVENT_TYPES}")
    fp = fingerprint_for(source_ref, payload)
    eid = f"event_{event_type}_{fp[:10]}"
    now = recorded_at or _now()
    row = (eid, event_type, occurred_at, now, actor, title, summary,
           source_ref, snapshot_ref, json.dumps(payload, ensure_ascii=False), fp, now)
    cur = conn.execute(
        """INSERT OR IGNORE INTO event_timeline
           (event_id, event_type, occurred_at, recorded_at, actor, title, summary,
            source_ref, snapshot_ref, payload_json, source_fingerprint, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", row)
    return {"event_id": eid, "inserted": cur.rowcount > 0}


def link_event(
    conn: sqlite3.Connection,
    event_id: str,
    linked_type: str,
    linked_id: str,
    relation: str,
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO event_links (event_id, linked_type, linked_id, relation)
           VALUES (?,?,?,?)""", (event_id, linked_type, linked_id, relation))


def count_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT event_type, COUNT(*) FROM event_timeline GROUP BY event_type").fetchall()
    return {r["event_type"]: r[1] for r in rows}


def total(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM event_timeline").fetchone()[0]


def last_recorded_at(conn: sqlite3.Connection) -> str | None:
    """reconcile 水位：库内最新 recorded_at（跨类型粗略水位，配合指纹幂等双保险）。"""
    r = conn.execute("SELECT MAX(recorded_at) FROM event_timeline").fetchone()
    return r[0] if r else None


def query_timeline(
    conn: sqlite3.Connection,
    event_type: str = "",
    actor: str = "",
    since: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """时间轴查询（MCP/日报消费）：按类型/actor/起始时间过滤，occurred_at 倒序最近 limit 条。"""
    where, params = [], []
    if event_type:
        where.append("event_type=?")
        params.append(event_type)
    if actor:
        where.append("actor=?")
        params.append(actor)
    if since:
        where.append("occurred_at>=?")
        params.append(since)
    sql = "SELECT * FROM event_timeline"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY occurred_at DESC, event_id LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json"))
        except Exception:
            d["payload"] = None
        out.append(d)
    return out


def trace_decision(conn: sqlite3.Connection, decision_id: str) -> list[dict[str, Any]]:
    """决策链回放（两跳）：直达 decision 的事件 + 经 review/asset 对象中转的事件。

    - 直达：事件 links (decision, D)
    - 中转：事件 links (review, R)，而 R 被某 links (decision, D) 的 review_created 事件引用
      （asset_card_versioned links review → 经 review 入决策链）
    """
    events = conn.execute(
        """SELECT e.* FROM event_timeline e
           WHERE e.event_id IN (
             SELECT l.event_id FROM event_links l
             WHERE l.linked_type='decision' AND l.linked_id=?
             UNION
             SELECT l1.event_id FROM event_links l1
             WHERE l1.linked_type='review' AND l1.linked_id IN (
               SELECT l2.linked_id FROM event_links l2
               WHERE l2.event_id IN (
                 SELECT l3.event_id FROM event_links l3
                 WHERE l3.linked_type='decision' AND l3.linked_id=?
               ) AND l2.linked_type='review'
             )
           )
           ORDER BY occurred_at, event_id""", (decision_id, decision_id)).fetchall()
    out = []
    for r in events:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json"))
        except Exception:
            d["payload"] = None
        out.append(d)
    return out
