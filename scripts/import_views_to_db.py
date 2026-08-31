#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_views_to_db.py — Phase 0 数据质量闸门 第1步

把 structured_views.jsonl 导入 SQLite 作为 immutable 原始层（view_raw），
并建齐派生表 schema（view_quality_issue / view_provenance / view_evidence_link）。
不改、不删原 jsonl，只读。

安全性：
- 记录原 jsonl 的 md5 到 manifest（immutable 校验基准，后续比对）
- 建表用 CREATE TABLE IF NOT EXISTS；重跑幂等（--overwrite 才删表重建）
- 全部用 /c/Python314/python.exe 运行（env -u PYTHONPATH）

用法:
  env -u PYTHONPATH python scripts/import_views_to_db.py [--overwrite]
"""
import os
import sys
import json
import time
import hashlib
import sqlite3
import argparse
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
VIEWS_FILE = PROJ / "data" / "views" / "structured_views.jsonl"
DB_FILE = PROJ / "data" / "evidence" / "qianboshi_quality.db"
BK_DIR = PROJ / "data" / "views" / "backup"

SCHEMA = """
-- immutable 原始层
CREATE TABLE IF NOT EXISTS view_raw (
  view_id TEXT PRIMARY KEY,
  raw_json TEXT NOT NULL,
  analyst TEXT, source_bv TEXT, timestamp_raw TEXT, stance TEXT,
  horizon TEXT, claim TEXT, evidence TEXT, view_type TEXT,
  load_ts TEXT DEFAULT (datetime('now'))
);
-- 质量问题清单
CREATE TABLE IF NOT EXISTS view_quality_issue (
  view_id TEXT, issue_code TEXT,
  field TEXT, raw_value TEXT, reason TEXT,
  suggested_status TEXT, detected_by TEXT DEFAULT 'validator',
  detected_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY(view_id, issue_code)
);
-- 溯源与锚点（标准化结果）
CREATE TABLE IF NOT EXISTS view_provenance (
  view_id TEXT PRIMARY KEY,
  bv_id TEXT, anchor_status TEXT,
  anchor_start_ms INTEGER, anchor_end_ms INTEGER,
  normalized_ts TEXT, anchor_confidence TEXT,
  duration_ms INTEGER, notes TEXT
);
-- 观点↔segment 下钻关联
CREATE TABLE IF NOT EXISTS view_evidence_link (
  view_id TEXT, segment_id TEXT,
  start_ms INTEGER, end_ms INTEGER,
  match_method TEXT, overlap_ms INTEGER,
  PRIMARY KEY(view_id, segment_id)
);
"""


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true", help="删表重建")
    args = ap.parse_args()

    if not VIEWS_FILE.exists():
        sys.exit(f"[err] 找不到 {VIEWS_FILE}")

    # 1) immutable 留底：备份 jsonl + 记 md5
    BK_DIR.mkdir(parents=True, exist_ok=True)
    bk_stamp = time.strftime("%Y%m%d_%H%M%S")
    bk_file = BK_DIR / f"structured_views_{bk_stamp}.jsonl"
    import shutil
    shutil.copy2(VIEWS_FILE, bk_file)
    src_md5 = md5_of(VIEWS_FILE)
    print(f"[backup] 原 jsonl 已备份 → {bk_file.name}")
    print(f"[md5]   源文件 md5 = {src_md5}")

    # 2) 建库
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    if args.overwrite:
        for t in ("view_evidence_link", "view_provenance", "view_quality_issue", "view_raw"):
            cur.execute(f"DROP TABLE IF EXISTS {t}")
    conn.executescript(SCHEMA)

    # 3) 导入 view_raw
    total = n_ok = n_bad = 0
    rows = []
    BATCH = 5000
    with open(VIEWS_FILE, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            total += 1
            try:
                d = json.loads(ln)
            except Exception as e:
                n_bad += 1
                continue
            rows.append((
                d.get("view_id") or f"missing_id_{total}:{n_bad}",
                ln,
                d.get("analyst"), d.get("source_bv"), d.get("timestamp"),
                d.get("stance"), d.get("horizon"), d.get("claim"),
                d.get("evidence"), d.get("view_type"),
            ))
            if len(rows) >= BATCH:
                cur.executemany(
                    """INSERT OR IGNORE INTO view_raw
                       (view_id, raw_json, analyst, source_bv, timestamp_raw,
                        stance, horizon, claim, evidence, view_type)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""", rows)
                conn.commit()
                rows = []
    if rows:
        cur.executemany(
            """INSERT OR IGNORE INTO view_raw
               (view_id, raw_json, analyst, source_bv, timestamp_raw,
                stance, horizon, claim, evidence, view_type)
               VALUES (?,?,?,?,?,?,?,?,?,?)""", rows)
        conn.commit()

    cur.execute("SELECT COUNT(*) FROM view_raw")
    n_in_db = cur.fetchone()[0]
    # 4) manifest：md5 + 计数，供 immutable 校验
    manifest = {
        "source_file": str(VIEWS_FILE),
        "source_md5": src_md5,
        "backup_file": bk_file.name,
        "lines_read": total,
        "json_parse_fail": n_bad,
        "view_raw_rows": n_in_db,
        "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    man_path = DB_FILE.parent / "import_manifest.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    conn.close()
    print(f"\n[import] 读取 {total} 行, JSON 失败 {n_bad}, 入 view_raw {n_in_db}")
    print(f"[db]     {DB_FILE}")
    print(f"[md5]   manifest 存 {man_path.name}（immutable 校验基准）")


if __name__ == "__main__":
    main()
