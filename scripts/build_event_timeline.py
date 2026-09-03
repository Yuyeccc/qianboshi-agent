#!/usr/bin/env python3
"""存量事件时间轴全量重建（记忆体系 P1b，一次性首跑 + 故障修复用）。

用法：
    C:/Python314/python.exe scripts/build_event_timeline.py --dry-run   # 预演统计
    C:/Python314/python.exe scripts/build_event_timeline.py             # 全量重建（幂等）

源（全部只读）：
    - qianboshi_decision.db: user_decision_logs(5)/decision_reviews(5)/asset_card_versions(8)
      prediction_events resolved(9935) + prediction_events_legacy resolved(2382)
    - view_lifecycle.db: view_status_history(251) → view_status_changed + 痕迹 view_created
    - data/views/structured_views.jsonl: 痕迹观点原文摘要（view_created payload）
P1 不建（无主表源，P2 随主表就位）：source_ingested/trade_executed/rule_*/report_generated/lint_run/market_snapshot(随 decision_created payload 走)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import event_timeline as evt  # noqa: E402
from decision_db import decision_db_path  # noqa: E402  (只取路径，源只读)
import view_store  # noqa: E402
import view_lifecycle  # noqa: E402  (db_path)


def _ro_connect(path: str | Path) -> sqlite3.Connection:
    """只读连接源库（不建表不写锁）。"""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _iso_or(src: str | None, fallback: str) -> str:
    return (src or fallback).strip() or fallback


def _build_decisions(conn: sqlite3.Connection, ev: sqlite3.Connection, dry_run: bool) -> dict:
    stats = {"decision_created": 0, "review_created": 0, "asset_card_versioned": 0}
    try:
        rows = conn.execute("SELECT * FROM user_decision_logs").fetchall()
    except sqlite3.Error as e:
        return {**stats, "error": str(e)}
    for r in rows:
        d = dict(r)
        occurred = _iso_or(d.get("decision_date"), d.get("created_at") or "")
        snap = d.get("market_snapshot")
        try:
            snap = json.loads(snap)[:500] if isinstance(snap, str) and snap else None
        except Exception:
            snap = None
        payload = {"decision_id": d.get("decision_id"), "asset_id": d.get("asset_id"),
                   "asset_name": d.get("asset_name"), "direction": d.get("direction"),
                   "horizon": d.get("horizon"), "conviction": d.get("conviction"),
                   "decision_date": d.get("decision_date"), "status": d.get("status"),
                   "user_view_version_ids": json.loads(d.get("user_view_version_ids"))
                   if d.get("user_view_version_ids") else None,
                   "market_snapshot_summary": snap}
        if not dry_run:
            res = evt.insert_event(ev, "decision_created", occurred, "user",
                                   f"决策 {d.get('asset_name')} {d.get('direction')}@{d.get('horizon')}",
                                   (d.get("thesis") or "")[:200],
                                   f"qianboshi_decision.db/user_decision_logs/{d.get('decision_id')}",
                                   payload)
            evt.link_event(ev, res["event_id"], "decision", d.get("decision_id"), "self")
        stats["decision_created"] += 1
    return stats


def _build_reviews(conn: sqlite3.Connection, ev: sqlite3.Connection, dry_run: bool) -> dict:
    stats = {"review_created": 0}
    try:
        rows = conn.execute("SELECT * FROM decision_reviews").fetchall()
    except sqlite3.Error as e:
        return {**stats, "error": str(e)}
    for r in rows:
        d = dict(r)
        occurred = _iso_or(d.get("review_date"), d.get("created_at") or "")
        payload = {"review_id": d.get("review_id"), "decision_id": d.get("decision_id"),
                   "review_date": d.get("review_date"), "result_label": d.get("result_label"),
                   "outcome_return": d.get("outcome_return"),
                   "benchmark_return": d.get("benchmark_return"),
                   "excess_return": d.get("excess_return"),
                   "new_rule_learned": (d.get("new_rule_learned") or "")[:300],
                   "linked_new_card_version": d.get("linked_new_card_version")}
        if not dry_run:
            res = evt.insert_event(ev, "review_created", occurred, "user",
                                   f"复盘 {d.get('decision_id')} -> {d.get('result_label')}",
                                   (d.get("what_went_wrong") or "")[:200],
                                   f"qianboshi_decision.db/decision_reviews/{d.get('review_id')}",
                                   payload)
            evt.link_event(ev, res["event_id"], "decision", d.get("decision_id"), "reviewed_by")
            evt.link_event(ev, res["event_id"], "review", d.get("review_id"), "self")
        stats["review_created"] += 1
    return stats


def _build_asset_versions(conn: sqlite3.Connection, ev: sqlite3.Connection, dry_run: bool) -> dict:
    stats = {"asset_card_versioned": 0}
    try:
        rows = conn.execute("SELECT * FROM asset_card_versions").fetchall()
    except sqlite3.Error as e:
        return {**stats, "error": str(e)}
    for r in rows:
        d = dict(r)
        occurred = _iso_or(d.get("created_at"), "")
        cfg = d.get("config_json")
        try:
            cfg_s = json.loads(cfg) if isinstance(cfg, str) and cfg else {}
            cfg_s = json.dumps(cfg_s, ensure_ascii=False)[:400]
        except Exception:
            cfg_s = str(cfg)[:400]
        payload = {"version_id": d.get("version_id"), "asset_id": d.get("asset_id"),
                   "version": d.get("version"), "change_reason": d.get("change_reason"),
                   "changed_by": d.get("changed_by"),
                   "linked_review_id": d.get("linked_review_id"), "config_summary": cfg_s}
        if not dry_run:
            res = evt.insert_event(ev, "asset_card_versioned", occurred,
                                   d.get("changed_by") or "system",
                                   f"资产卡 {d.get('asset_id')} v{d.get('version')}",
                                   (d.get("change_reason") or "")[:200],
                                   f"qianboshi_decision.db/asset_card_versions/{d.get('version_id')}",
                                   payload)
            evt.link_event(ev, res["event_id"], "asset", d.get("asset_id"), "versioned")
            if d.get("linked_review_id"):
                evt.link_event(ev, res["event_id"], "review",
                               d.get("linked_review_id"), "produced_version")
        stats["asset_card_versioned"] += 1
    return stats


def _build_outcomes(conn: sqlite3.Connection, ev: sqlite3.Connection, dry_run: bool) -> dict:
    """prediction_events + legacy：仅 status='resolved' → outcome_observed（error/skipped 不建）。"""
    stats = {"outcome_observed": 0, "outcome_skipped": 0}
    cols_sql = ("event_id, view_id, entity, stance, horizon, event_date, "
                "window_days, return_pct, status")
    for table in ("prediction_events", "prediction_events_legacy"):
        try:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not {"view_id", "entity", "status"}.issubset(cols):
                stats["outcome_skipped"] += 1
                continue
            rows = conn.execute(
                f"SELECT {cols_sql} FROM {table} WHERE status='resolved'").fetchall()
        except sqlite3.Error as e:
            return {**stats, "error": str(e)}
        for r in rows:
            d = dict(r)
            if d.get("status") != "resolved":
                continue
            payload = {"event_id": d.get("event_id"), "view_id": d.get("view_id"),
                       "entity": d.get("entity"), "stance": d.get("stance"),
                       "horizon": d.get("horizon"), "window_days": d.get("window_days"),
                       "return_pct": d.get("return_pct"), "status": d.get("status")}
            if not dry_run:
                res = evt.insert_event(ev, "outcome_observed",
                                       _iso_or(d.get("event_date"), ""),
                                       "market",
                                       f"结果 {d.get('entity')} {d.get('stance')} "
                                       f"{d.get('window_days')}d {d.get('return_pct')}%",
                                       None,
                                       f"qianboshi_decision.db/{table}/{d.get('event_id')}",
                                       payload)
                if d.get("view_id"):
                    evt.link_event(ev, res["event_id"], "view", d.get("view_id"), "outcome_of")
            stats["outcome_observed"] += 1
    return stats


def _build_view_events(ev: sqlite3.Connection, jsonl_path: str | Path, dry_run: bool) -> dict:
    """view 痕迹：view_status_history 全建 status_changed；涉及的 view_id 去重建 view_created。

    view_created 的 occurred_at/payload 取自 structured_views.jsonl 原文（date/claim/horizon）。
    """
    stats = {"view_status_changed": 0, "view_created": 0, "view_created_missing_src": 0}
    hist = ev.execute(
        "SELECT * FROM view_status_history ORDER BY changed_at, id").fetchall()
    trace_vids: set[str] = set()
    for h in hist:
        d = dict(h)
        trace_vids.add(d["view_id"])
        payload = {"view_id": d["view_id"], "old_status": d["old_status"],
                   "new_status": d["new_status"], "reason": d["reason"],
                   "linked_outcome_id": d["linked_outcome_id"],
                   "linked_view_id": d["linked_view_id"]}
        if not dry_run:
            res = evt.insert_event(ev, "view_status_changed", _iso_or(d["changed_at"], ""),
                                   d["changed_by"] or "system",
                                   f"观点 {d['view_id'][:12]} {d['old_status']}->{d['new_status']}",
                                   (d["reason"] or "")[:200],
                                   f"view_lifecycle.db/view_status_history/{d['id']}",
                                   payload)
            evt.link_event(ev, res["event_id"], "view", d["view_id"], "changed")
            if d.get("linked_outcome_id"):
                evt.link_event(ev, res["event_id"], "outcome",
                               d["linked_outcome_id"], "caused_status")
            if d.get("linked_view_id"):
                evt.link_event(ev, res["event_id"], "view",
                               d["linked_view_id"], "superseded_by")
        stats["view_status_changed"] += 1
    # view_created：痕迹观点原文摘要
    src_map: dict[str, dict] = {}
    jp = Path(jsonl_path)
    if jp.exists():
        with jp.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    v = json.loads(line)
                except Exception:
                    continue
                if v.get("view_id") in trace_vids:
                    src_map[v["view_id"]] = v
    for vid in sorted(trace_vids):
        v = src_map.get(vid)
        if v is None:
            stats["view_created_missing_src"] += 1
            continue
        payload = {"view_id": vid, "analyst": v.get("analyst"),
                   "date": v.get("date"), "claim": (v.get("claim") or "")[:300],
                   "horizon": v.get("horizon"), "authority": str(v.get("authority"))
                   if v.get("authority") else None}
        if not dry_run:
            res = evt.insert_event(ev, "view_created", _iso_or(v.get("date"), ""),
                                   v.get("analyst") or "unknown",
                                   f"观点入库 {vid[:12]}",
                                   (v.get("claim") or "")[:200],
                                   f"structured_views.jsonl/{vid}",
                                   payload)
            evt.link_event(ev, res["event_id"], "view", vid, "self")
        stats["view_created"] += 1
    return stats


def _build_user_view_changed(ev: sqlite3.Connection, dry_run: bool) -> dict:
    """user_view_changed：版本链 v2+（version_no>1）→ 信念变更事件（P1a append 产物）。

    存量 v1（legacy_import 初始化）非"用户变更"不建；reconcile 每日从版本表补缺。
    """
    stats = {"user_view_changed": 0}
    rows = ev.execute(
        "SELECT * FROM user_view_versions WHERE version_no > 1 ORDER BY created_at").fetchall()
    for r in rows:
        d = dict(r)
        try:
            content = json.loads(d["content_json"])
            content_s = json.dumps(content, ensure_ascii=False)[:300]
        except Exception:
            content_s = None
        payload = {"version_id": d["version_id"], "view_key": d["view_key"],
                   "version_no": d["version_no"], "change_type": d["change_type"],
                   "change_reason": d["change_reason"],
                   "parent_version_id": d["parent_version_id"],
                   "content_summary": content_s}
        if not dry_run:
            res = evt.insert_event(ev, "user_view_changed",
                                   _iso_or(d["created_at"], ""),
                                   d["created_by"] or "manual",
                                   f"信念变更 {d['view_key']} v{d['version_no']} "
                                   f"[{d['change_type']}]",
                                   (d["change_reason"] or "")[:200],
                                   f"view_lifecycle.db/user_view_versions/{d['version_id']}",
                                   payload)
            evt.link_event(ev, res["event_id"], "user_view", d["view_key"], "versioned")
        stats["user_view_changed"] += 1
    return stats


def _build_report_docs(ev: sqlite3.Connection, dry_run: bool) -> dict:
    """report_generated：report_docs 登记行 → 事件（P2 刀3，03 §7.3 好答案回填落事件层）。

    payload 只含稳定字段（doc_id/report_type/generated_at/file_sha256），内容寻址指纹稳定；
    entity_key/status 是治理字段不参与事件 payload（supersede 不重建事件）。
    """
    stats = {"report_generated": 0, "report_linked_views": 0}
    try:
        rows = ev.execute("SELECT * FROM report_docs ORDER BY created_at").fetchall()
    except sqlite3.Error:
        return stats  # 表未建（旧库）→ 0，不阻断
    for r in rows:
        d = dict(r)
        payload = {"doc_id": d["doc_id"], "report_type": d["report_type"],
                   "generated_at": d["generated_at"], "file_sha256": d["file_sha256"]}
        occurred = _iso_or(d["generated_at"], d["created_at"])
        title = f"报告生成 {d['doc_id']} ({d['report_type']})"
        if not dry_run:
            res = evt.insert_event(ev, "report_generated", occurred, "system", title,
                                   (d["entity_key"] or "entity 未标")[:200],
                                   f"report_docs/{d['doc_id']}", payload)
            evt.link_event(ev, res["event_id"], "report", d["doc_id"], "generated")
            # 报告→观点互链（opinions 强匹配回填）
            try:
                vids = json.loads(d["linked_view_ids"] or "[]")
            except Exception:
                vids = []
            for vid in vids:
                evt.link_event(ev, res["event_id"], "view", vid, "cited_in")
                stats["report_linked_views"] += 1
        stats["report_generated"] += 1
    return stats


def build_all(
    ev_db: str | Path,
    decision_db: str | Path,
    jsonl_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict:
    ev = evt.connect(db=ev_db)
    src = _ro_connect(decision_db)
    try:
        s1 = _build_decisions(src, ev, dry_run)
        s2 = _build_reviews(src, ev, dry_run)
        s3 = _build_asset_versions(src, ev, dry_run)
        s4 = _build_outcomes(src, ev, dry_run)
        jp = jsonl_path or view_store.views_path()
        s5 = _build_view_events(ev, jp, dry_run)
        s6 = _build_user_view_changed(ev, dry_run)
        s7 = _build_report_docs(ev, dry_run)
    finally:
        src.close()
    if not dry_run:
        ev.commit()
    result = {**s1, **s2, **s3, **s4, **s5, **s6, **s7,
              "dry_run": dry_run, "total_events": evt.total(ev)}
    ev.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="事件时间轴存量全量重建（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="预演：只统计不落库")
    parser.add_argument("--db", help="覆盖 lifecycle 库路径（事件落点）")
    parser.add_argument("--decision-db", help="覆盖决策源库路径")
    parser.add_argument("--jsonl", help="覆盖 structured_views.jsonl 路径")
    args = parser.parse_args()

    ev_db = args.db or view_lifecycle.db_path()
    dec_db = args.decision_db or decision_db_path()
    result = build_all(ev_db, dec_db, args.jsonl, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.dry_run:
        print(f"[事件库] {ev_db}")


if __name__ == "__main__":
    main()
