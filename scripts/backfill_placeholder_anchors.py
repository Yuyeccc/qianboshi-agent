#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_placeholder_anchors.py — 修复 (0,0) 占位锚点（71号后检修：最初目的"观点可下钻原文"的最后一公里）

背景（2026-09-01 侦察确认）：
- view_provenance 有 1153 条 anchor_start_ms=0 AND anchor_end_ms=0 的"假锚定"，
  时间戳全部是占位 '00:00:00-00:00:00'（结构化提取时无时间信息），却标 anchor_confidence='high'。
- 但 raw_json.evidence 字段里藏着**原文片段**（ASR 繁体原句，按 '(00:00:00-00:00:00)' 标记分隔）——
  用片段做文本兜底匹配可恢复真实下钻（证据链保真），未命中的诚实降级 unanchored。

修复逻辑（确定性，零 LLM，不猜）：
1. 只处理 anchor_start_ms=0 AND anchor_end_ms=0 的占位 view（幂等，重跑不重复处理）
2. 从 evidence 提取括号标记后的原文片段（过滤逻辑概括段）
3. 繁→简归一（zhcn_map.json，本地 zhconv getdict('zh-cn') 导出）+ 去空白标点
4. 在 BV 的 transcript_segment（qianboshi_evidence.db）逐段子串匹配（长片段优先）
5. 命中 → 更新 anchor 为 segment 时间戳（confidence=medium, notes=text_fallback）
   + 写 view_evidence_link（match_method='text_fallback'）
6. 未命中 → 降级 unanchored + NULL + confidence=low（不再假锚定）

用法（在 Mac 上跑，库在 ~/qianboshi_task）：
  env -u PYTHONPATH python3 scripts/backfill_placeholder_anchors.py --dry-run   # 只统计
  env -u PYTHONPATH python3 scripts/backfill_placeholder_anchors.py --write     # 写库（先备份）

安全：--write 前自动备份两个库（.bak_20260901_placeholder_fix）；不碰 view_raw/claim 表；
仅更新占位 view 的 provenance 行 + 新增 evidence_link 行。
"""
import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

# --- 路径（Mac 权威库；本地调试可 --quality-db/--evidence-db 覆盖） ---
QUALITY_DB = Path.home() / "qianboshi_task" / "data" / "evidence" / "qianboshi_quality.db"
EVIDENCE_DB = Path.home() / "qianboshi_task" / "data" / "evidence" / "qianboshi_evidence.db"
MAP_FILE = Path(__file__).resolve().parent / "zhcn_map.json"

MIN_FRAG = 5        # 原文片段最小长度（归一化后）
MAX_SUBSTR = 16     # 匹配子串最长尝试长度
MIN_SUBSTR = 6      # 匹配子串最短尝试长度


def load_zhcn_map() -> dict:
    if not MAP_FILE.exists():
        return {}
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))


def normalize(text: str, mapping: dict) -> str:
    """繁→简 + 去空白 + 去标点（保留中文/字母/数字），供子串匹配。"""
    s = "".join(mapping.get(ch, ch) for ch in str(text or ""))
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def extract_evidence_fragments(evidence: str) -> list:
    """从 evidence 提取括号标记后的原文片段。

    evidence 形如: '逻辑概括... (00:00:00-00:00:00) 原文片段1 (00:00:00-00:00:00) 原文片段2'
    只取括号后的文本段；过滤含 逻辑:/看多/看空 等概括标记的段。
    """
    parts = re.split(r"[（(]\s*[\d:\- ]+\s*[）)]", str(evidence or ""))
    frags = []
    for p in parts[1:]:  # 第一个括号前的段=逻辑概括，丢弃
        p = p.strip()
        if len(p) < 4:
            continue
        if re.search(r"逻辑[:：]|看多|看空|中性", p[:12]):
            continue
        frags.append(p)
    return frags


def match_segment(cur, bv: str, frag_norm: str, seg_norm_map: dict) -> tuple:
    """在 BV 的 segment 里找 frag_norm 的子串命中。

    seg_norm_map: {segment_id: (norm_text, start_ms, end_ms)}
    从长到短尝试子串；返回 (segment_id, start_ms, end_ms) 或 None。
    """
    n = len(frag_norm)
    for ln in range(min(MAX_SUBSTR, n), MIN_SUBSTR - 1, -1):
        sub = frag_norm[:ln]
        for seg_id, (seg_text, s_ms, e_ms) in seg_norm_map.items():
            if sub in seg_text:
                return seg_id, s_ms, e_ms
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    ap.add_argument("--write", action="store_true", help="写库（先备份）")
    ap.add_argument("--quality-db", default=str(QUALITY_DB))
    ap.add_argument("--evidence-db", default=str(EVIDENCE_DB))
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（调试）")
    args = ap.parse_args()

    if not args.dry_run and not args.write:
        print("[err] 需要 --dry-run 或 --write")
        sys.exit(1)

    mapping = load_zhcn_map()
    print(f"[map] 繁简映射 {len(mapping)} 条")

    q = sqlite3.connect(args.quality_db)
    e = sqlite3.connect(args.evidence_db)
    qc, ec = q.cursor(), e.cursor()

    # 1) 占位 view
    rows = qc.execute(
        "SELECT p.view_id, p.bv_id, r.source_bv, r.raw_json "
        "FROM view_provenance p JOIN view_raw r ON r.view_id=p.view_id "
        "WHERE p.anchor_start_ms=0 AND p.anchor_end_ms=0"
    ).fetchall()
    print(f"[scan] 占位锚点 {len(rows)} 条")
    if args.limit:
        rows = rows[: args.limit]

    # 2) 预载所有相关 BV 的 segment 归一化索引（只载涉及的 BV）
    bvs = sorted({(r[1] or r[2]) for r in rows if (r[1] or r[2])})
    print(f"[idx] 涉及 BV {len(bvs)} 个，构建 segment 索引...")
    seg_index = {}  # bv -> {segment_id: (norm, start_ms, end_ms)}
    for bv in bvs:
        segs = ec.execute(
            "SELECT id, start_ms, end_ms, text FROM transcript_segment WHERE raw_asset_id=?",
            (bv,),
        ).fetchall()
        seg_index[bv] = {
            s[0]: (normalize(s[3], mapping), s[1], s[2])
            for s in segs if s[3]
        }

    # 3) 逐条匹配
    stat = {"matched": 0, "unanchored": 0, "no_frag": 0, "no_bv": 0}
    updates = []      # (view_id, seg_id, s_ms, e_ms)
    downgrades = []   # view_id
    for view_id, p_bv, r_bv, raw_json in rows:
        bv = p_bv or r_bv
        if not bv:
            stat["no_bv"] += 1
            downgrades.append(view_id)
            continue
        try:
            d = json.loads(raw_json)
        except Exception:
            d = {}
        frags = extract_evidence_fragments(d.get("evidence") or "")
        norms = [normalize(f, mapping) for f in frags]
        norms = [f for f in norms if len(f) >= MIN_FRAG]
        if not norms:
            stat["no_frag"] += 1
            downgrades.append(view_id)
            continue
        hit = None
        for fn in norms:
            hit = match_segment(ec, bv, fn, seg_index.get(bv, {}))
            if hit:
                break
        if hit:
            updates.append((view_id, hit[0], hit[1], hit[2]))
            stat["matched"] += 1
        else:
            downgrades.append(view_id)
            stat["unanchored"] += 1

    print(f"[result] 命中锚定 {stat['matched']} / 降级 unanchored {stat['unanchored']} "
          f"/ 无片段 {stat['no_frag']} / 无BV {stat['no_bv']}")

    if args.dry_run:
        print("[dry-run] 不写库。示例命中:")
        for vid, sid, s, e2 in updates[:5]:
            print(f"  {vid[:12]} -> seg {sid[:20]} ({s}ms-{e2}ms)")
        q.close()
        e.close()
        return

    # 4) 写库（先备份）
    ts = time.strftime("%Y%m%d_%H%M%S")
    for db in (args.quality_db, args.evidence_db):
        shutil.copy2(db, f"{db}.bak_{ts}_placeholder_fix")
    print(f"[bak] 已备份 -> .bak_{ts}_placeholder_fix")

    n_link = 0
    for view_id, seg_id, s_ms, e_ms in updates:
        qc.execute(
            "UPDATE view_provenance SET anchor_status='anchored', "
            "anchor_start_ms=?, anchor_end_ms=?, anchor_confidence='medium', "
            "notes='text_fallback 文本兜底锚定(evidence片段匹配)' "
            "WHERE view_id=? AND anchor_start_ms=0 AND anchor_end_ms=0",
            (s_ms, e_ms, view_id),
        )
        # 写 evidence_link（幂等）
        qc.execute(
            "INSERT OR REPLACE INTO view_evidence_link "
            "(view_id, segment_id, start_ms, end_ms, match_method, overlap_ms) "
            "VALUES (?,?,?,?,?,NULL)",
            (view_id, seg_id, s_ms, e_ms, "text_fallback"),
        )
        n_link += 1
    for view_id in downgrades:
        qc.execute(
            "UPDATE view_provenance SET anchor_status='unanchored', "
            "anchor_start_ms=NULL, anchor_end_ms=NULL, anchor_confidence='low', "
            "notes='占位时间戳(00:00:00)降级，无原文可锚' "
            "WHERE view_id=? AND anchor_start_ms=0 AND anchor_end_ms=0",
            (view_id,),
        )
    q.commit()

    # 5) 终验
    remain = qc.execute(
        "SELECT COUNT(*) FROM view_provenance WHERE anchor_start_ms=0 AND anchor_end_ms=0"
    ).fetchone()[0]
    anchored = qc.execute(
        "SELECT COUNT(*) FROM view_provenance WHERE anchor_status='anchored'"
    ).fetchone()[0]
    print(f"[done] 写库完成：更新锚定 {len(updates)} / 降级 {len(downgrades)} / 写 link {n_link}")
    print(f"[verify] 剩余占位 {remain}（应为 0）| 总 anchored {anchored}")
    q.close()
    e.close()


if __name__ == "__main__":
    main()
