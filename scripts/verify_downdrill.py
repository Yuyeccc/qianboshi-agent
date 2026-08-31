#!/usr/bin/env python3
"""
verify_downdrill.py — Phase 0 验收：观点库 timestamp 锚点 → transcript_segment 原文

检验"任一日报观点可下钻到 ASR 时间点"：
  对 structured_views 每条 view：
    source_bv + timestamp(MM:SS-MM:SS) → start_s/end_s
    → 查 transcript_segment 表中该 BV 的段，找与 [start,end] 区间重叠的段原文
  统计命中率与失败原因，暴露 Phase 0 数据缺口。

用法: env -u PYTHONPATH python scripts/verify_downdrill.py [--limit 5000]
"""
import re
import json
import argparse
import sqlite3
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
VIEWS_FILE = PROJ / "data" / "views" / "structured_views.jsonl"
DB_FILE = PROJ / "data" / "evidence" / "qianboshi_evidence.db"

# timestamp 可能是 (MM:SS-MM:SS) / MM:SS-MM:SS / 00:15:17-00:15:20
TSTAMP_RE = re.compile(r'(?:\(|^|\s)(\d{1,2}):(\d{1,2}):(\d{1,2})-(\d{1,2}):(\d{1,2}):(\d{1,2})\)?(?:\s|$)')


def parse_ts(ts):
    """解析 timestamp 字符串 → (start_ms, end_ms) 或 None。支持 MM:SS / HH:MM:SS。"""
    if not ts:
        return None
    ts = str(ts).strip()
    m = re.fullmatch(r'(\d{1,2}):(\d{1,2}):(\d{1,2})-(\d{1,2}):(\d{1,2}):(\d{1,2})', ts)
    if m:
        s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        e = int(m.group(4)) * 3600 + int(m.group(5)) * 60 + int(m.group(6))
        return s * 1000, e * 1000
    m = re.fullmatch(r'(\d{1,2}):(\d{1,2})-(\d{1,2}):(\d{1,2})', ts)
    if m:
        s = int(m.group(1)) * 60 + int(m.group(2))
        e = int(m.group(3)) * 60 + int(m.group(4))
        return s * 1000, e * 1000
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    # 预载所有 BV 的 segment 起止范围 + 段列表区间
    # 按 BV 拉取段(start_ms,end_ms,text)，构建区间索引
    bv_segs = {}
    for bv, s, e, text in cur.execute(
            "SELECT raw_asset_id, start_ms, end_ms, text FROM transcript_segment WHERE start_ms IS NOT NULL"):
        bv_segs.setdefault(bv, []).append((s, e, text))

    total = 0; bv_hit = 0; ts_hit = 0; seg_hit = 0
    need_bv = {}  # BV有transcript但ts没命中
    no_bv = {}    # BV无transcript
    no_ts = 0
    hit_samples = []
    with open(VIEWS_FILE, encoding="utf-8") as f:
        for i, ln in enumerate(f):
            if args.limit and i >= args.limit:
                break
            try:
                d = json.loads(ln)
            except Exception:
                continue
            total += 1
            bv = d.get("source_bv", "")
            ts = d.get("timestamp", "")
            parsed = parse_ts(ts)
            if parsed is None:
                no_ts += 1
                continue
            s_ms, e_ms = parsed
            segs = bv_segs.get(bv)
            if not segs:
                no_bv[bv] = no_bv.get(bv, 0) + 1
                continue
            bv_hit += 1
            # 找与该区间重叠的段（允许 ±2s 容差）
            overlap = [t for (ss, ee, t) in segs
                       if ss <= e_ms + 2000 and ee >= s_ms - 2000]
            if overlap:
                seg_hit += 1
                if len(hit_samples) < 8:
                    hit_samples.append({
                        "view_id": d.get("view_id"), "analyst": d.get("analyst"),
                        "claim": (d.get("claim") or "")[:30], "bv": bv, "ts": ts,
                        "seg": (overlap[0] or "")[:50],
                    })
            else:
                need_bv[bv] = need_bv.get(bv, 0) + 1

    conn.close()
    print(f"观点总数: {total}")
    print(f"  timestamp可解析: {total - no_ts}  ({no_ts} 条无timestamp)")
    print(f"  BV在transcript库: {bv_hit}  ({no_bv and sum(no_bv.values())} 条BV无transcript → 数据缺口)")
    print(f"  **timestamp命中原文段: {seg_hit}**  ({seg_hit/total*100:.1f}%)")
    print(f"  BV有但ts未命中: {sum(need_bv.values())}")
    print()
    print("=== 命中样例（观点→原文） ===")
    for h in hit_samples:
        print(f"  [{h['analyst']}] {h['claim']} | {h['bv']} {h['ts']} -> \"{h['seg']}\"")
    print()
    print("=== 无transcript的BV top5（数据缺口，需止损） ===")
    for bv, c in sorted(no_bv.items(), key=lambda x: -x[1])[:5]:
        print(f"  {bv}: {c} 条观点")
    print("=== BV有但ts超范围 top5 ===")
    for bv, c in sorted(need_bv.items(), key=lambda x: -x[1])[:5]:
        print(f"  {bv}: {c} 条观点")


if __name__ == "__main__":
    main()
