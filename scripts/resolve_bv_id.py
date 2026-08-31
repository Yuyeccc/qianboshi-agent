#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resolve_bv_id.py — Phase 0 数据质量闸门 第3步

确定性补齐观点库的 BV 身份（source_bv），写入 view_provenance.bv_id。
**绝不根据观点文本猜 BV**（gpt 红线）。优先级：
  1. source_bv 已是合法 BV 格式 → 直接用
  2. source_file / source_path 正则提取 BV[0-9A-Za-z]+（覆盖 10263 条）
  3. 均无 → unanchored，并记 view_quality_issue(MISSING_BV)

用法:
  env -u PYTHONPATH python scripts/resolve_bv_id.py
"""
import os, re, json, sqlite3
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DB_FILE = PROJ / "data" / "evidence" / "qianboshi_quality.db"

BV_RE = re.compile(r'(BV[0-9A-Za-z]{9,})')  # 标准 BV + 变体


def pick_bv(source_bv, source_file, source_path):
    """按优先级确定性选 BV，返回 (bv_id, source_of_bv) 或 (None, None)。"""
    for val, tag in ((source_bv, "source_bv"),
                     (source_file, "source_file"),
                     (source_path, "source_path")):
        if not val:
            continue
        m = BV_RE.search(str(val))
        if m:
            return m.group(1), tag
    return None, None


def main():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # 拉取所有原始观点（含 raw_json 里的 source_file/source_path）
    rows = cur.execute(
        "SELECT view_id, source_bv, raw_json FROM view_raw").fetchall()

    filled = bv_ok = miss = 0
    miss_samples = []
    for view_id, source_bv, raw_json in rows:
        try:
            d = json.loads(raw_json)
        except Exception:
            d = {}
        source_file = d.get("source_file", "")
        source_path = d.get("source_path", "")
        bv, src_tag = pick_bv(source_bv, source_file, source_path)
        if bv:
            # 写 provenance.bv_id
            cur.execute(
                """INSERT INTO view_provenance (view_id, bv_id)
                   VALUES (?,?)
                   ON CONFLICT(view_id) DO UPDATE SET bv_id=excluded.bv_id""",
                (view_id, bv))
            filled += 1
            if source_bv and source_bv.startswith("BV"):
                bv_ok += 1
        else:
            # 无 BV：标 unanchored + 记 issue
            miss += 1
            if len(miss_samples) < 8:
                miss_samples.append((view_id, d.get("analyst"), source_bv,
                                     source_file[:40]))
            cur.execute(
                """INSERT INTO view_provenance (view_id, bv_id, anchor_status)
                   VALUES (?, NULL, 'unanchored')
                   ON CONFLICT(view_id) DO UPDATE SET
                       anchor_status='unanchored'""", (view_id,))
            cur.execute(
                """INSERT OR IGNORE INTO view_quality_issue
                   (view_id, issue_code, field, raw_value, reason, suggested_status)
                   VALUES (?, 'MISSING_BV', 'source_bv', ?, '无BV可确定(不猜)', 'unanchored')""",
                (view_id, str(source_bv)[:120]))

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM view_provenance WHERE bv_id IS NOT NULL")
    n_bv = cur.fetchone()[0]
    cur.close()
    print(f"[resolve] 观点 {len(rows)} 条")
    print(f"  补出 bv_id: {filled}   (原 source_bv 即合法 BV: {bv_ok})")
    print(f"  无 BV(unanchored): {miss}")
    print(f"  库中已有 bv_id 的 provenance: {n_bv}")
    print("\n--- 无BV样例(前8) ---")
    for s in miss_samples:
        print(f"  {s[0]} | analyst={s[1]} | source_bv={s[2]!r} | file={s[3]!r}")


if __name__ == "__main__":
    main()
